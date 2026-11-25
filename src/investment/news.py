"""Auditable company news/events, conservative labels, and persistent history."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from bs4 import BeautifulSoup

SENTIMENTS = {
    "positive": "긍정 추정",
    "negative": "부정 추정",
    "neutral": "혼재/중립",
    "unknown": "판단 유보",
}
EVENT_TYPES = {
    "earnings": "실적",
    "contract": "수주/계약",
    "product": "제품/기술",
    "investment": "투자/M&A",
    "capital_return": "배당/자사주",
    "financing": "자금조달",
    "legal": "소송/규제",
    "incident": "사고/보안",
    "management": "경영/인사",
    "filing": "공시",
    "other": "기타",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value, limit=20000) -> str:
    return " ".join(BeautifulSoup(str(value or "")[:limit], "html.parser").get_text(" ").split())


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value).strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            return ""
        return urlunsplit(parsed)
    except ValueError:
        return ""


def canonical_url(value: str) -> str:
    value = safe_url(value)
    if not value:
        return ""
    parts = urlsplit(value)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def parse_time(value, exchange_timezone="UTC", naive_timezone=None) -> tuple[str, str, str]:
    """Return UTC timestamp, exchange date and precision; never invent a filing time."""
    if value is None or value == "" or pd.isna(value):
        return "", "", "unknown"
    string = str(value).strip()
    try:
        if re.fullmatch(r"\d{8}", string):
            return "", datetime.strptime(string, "%Y%m%d").date().isoformat(), "day"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", string):
            return "", date.fromisoformat(string).isoformat(), "day"
        if isinstance(value, (float, int)):
            stamp = pd.Timestamp(value, unit="s", tz="UTC")
        elif re.fullmatch(r"\d{8}T\d{6}", string):
            stamp = pd.Timestamp(datetime.strptime(string, "%Y%m%dT%H%M%S"))
        elif "," in string:
            stamp = pd.Timestamp(parsedate_to_datetime(string))
        else:
            stamp = pd.Timestamp(string)
        if stamp.tzinfo is None:
            if not naive_timezone:
                return "", stamp.date().isoformat(), "day"
            stamp = stamp.tz_localize(naive_timezone)
        return (
            stamp.tz_convert("UTC").isoformat(),
            stamp.tz_convert(exchange_timezone).date().isoformat(),
            "second",
        )
    except (ValueError, TypeError, OverflowError):
        return "", "", "unknown"


@dataclass
class NewsItem:
    id: str
    symbol: str
    company: str
    title: str
    event_date: str
    published_at: str = ""
    time_precision: str = "unknown"
    time_basis: str = "unknown"
    publisher: str = ""
    url: str = ""
    summary: str = ""
    sources: list[str] = field(default_factory=list)
    alternate_urls: list[str] = field(default_factory=list)
    alternate_titles: list[str] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    source_record_id: str = ""
    event_type: str = "other"
    sentiment: str = "unknown"
    confidence: float = 0.0
    rationale: str = "문맥과 시장 기대를 확인하지 않은 키워드 추정입니다."
    label_method: str = "keyword_rules_v1"
    provider_sentiment: str = ""
    relevance: str = "검색/종목 연결 결과; 원문에서 회사 관련성 확인 필요"
    body: str = ""
    body_status: str = "not_fetched"
    original_published_at: str = ""
    original_updated_at: str = ""
    collected_at: str = field(default_factory=now_utc)
    last_seen_at: str = field(default_factory=now_utc)


def classify(item: NewsItem):
    if item.label_method == "manual":
        return
    content = (item.title + " " + item.summary).casefold()
    categories = [
        (
            "earnings",
            r"실적|영업이익|매출|분기보고서|사업보고서|earnings|quarterly results|revenue|10-[kq]",
        ),
        ("incident", r"화재|폭발|해킹|유출|리콜|recall|data breach|cyberattack|outage"),
        ("legal", r"소송|제재|과징금|규제|반독점|lawsuit|antitrust|sanction|regulator"),
        ("contract", r"수주|공급계약|계약체결|contract|supply agreement"),
        ("capital_return", r"배당|자사주|dividend|buyback|repurchase"),
        ("financing", r"유상증자|전환사채|자금조달|stock offering|convertible|capital raise"),
        ("investment", r"인수|합병|투자|acquisition|merger|investment"),
        ("product", r"신제품|신약|승인|특허|출시|launch|patent|new product|approval"),
        ("management", r"대표이사|경영진|사임|ceo|resign|executive"),
    ]
    for category, pattern in categories:
        if re.search(pattern, content):
            item.event_type = category
            break
    positive = re.findall(
        r"흑자전환|사상\s?최대|수주\s?성공|실적\s?개선|어닝\s?서프라이즈|"
        r"beats? (?:estimates|expectations)|raises? (?:guidance|outlook)|record revenue",
        content,
    )
    negative = re.findall(
        r"적자전환|실적\s?쇼크|어닝\s?쇼크|영업\s?정지|대규모\s?해고|"
        r"misses? (?:estimates|expectations)|cuts? (?:guidance|outlook)|data breach|recall",
        content,
    )
    item.sentiment = (
        "neutral"
        if positive and negative
        else "positive"
        if positive
        else "negative"
        if negative
        else "unknown"
    )
    item.confidence = 0.55 if positive or negative else 0.0
    matched = positive + negative
    item.rationale = ("키워드: " + ", ".join(dict.fromkeys(matched)) + ". " if matched else "") + (
        "기사의 표현에 대한 규칙 추정이며 실제 주가 영향·시장 기대 대비 평가는 아닙니다."
    )


def make_item(
    company,
    source: str,
    title: str,
    published,
    url: str,
    *,
    publisher="",
    summary="",
    tz="UTC",
    time_basis="publisher",
    record_id="",
    filing=False,
    naive_timezone=None,
    **extra,
) -> NewsItem | None:
    title = text(title, 2000)
    publisher = text(publisher, 500)
    if publisher and title.endswith(" - " + publisher):
        title = title[: -len(" - " + publisher)]
    timestamp, day, precision = parse_time(published, tz, naive_timezone)
    if not title or not day:
        return None
    normalized = re.sub(r"[^\w가-힣]", "", title.casefold())
    key = (
        f"{company.symbol}|{source}|{record_id or url}"
        if filing
        else f"{company.symbol}|{day}|{normalized}"
    )
    item = NewsItem(
        id=hashlib.sha256(key.encode()).hexdigest(),
        symbol=company.symbol,
        company=company.name,
        title=title,
        event_date=day,
        published_at=timestamp,
        time_precision=precision,
        time_basis=time_basis,
        publisher=publisher,
        url=canonical_url(url),
        summary=text(summary),
        sources=[source],
        source_record_id=str(record_id),
        event_type="filing" if filing else "other",
        **extra,
    )
    classify(item)
    item.observations = [
        {
            "source": source,
            "published_at": timestamp,
            "event_date": day,
            "time_precision": precision,
            "time_basis": time_basis,
            "url": item.url,
            "collected_at": item.collected_at,
        }
    ]
    return item


def merge_item(first: NewsItem, second: NewsItem) -> NewsItem:
    """Merge duplicate discovery while retaining links, provenance and manual labels."""
    first.sources = list(dict.fromkeys(first.sources + second.sources))
    first.alternate_urls = list(
        dict.fromkeys(
            [u for u in first.alternate_urls + second.alternate_urls + [first.url, second.url] if u]
        )
    )
    first.alternate_titles = list(
        dict.fromkeys(
            first.alternate_titles + second.alternate_titles + [first.title, second.title]
        )
    )
    if len(second.summary) > len(first.summary):
        first.summary = second.summary
    if len(second.body) > len(first.body):
        first.body, first.body_status = second.body, second.body_status
        first.original_published_at = second.original_published_at
        first.original_updated_at = second.original_updated_at
    if "news.google.com" in first.url and "news.google.com" not in second.url and second.url:
        first.url = second.url
    if first.label_method != "manual" and second.label_method == "manual":
        for key in ("sentiment", "confidence", "rationale", "label_method"):
            setattr(first, key, getattr(second, key))
    if not first.provider_sentiment:
        first.provider_sentiment = second.provider_sentiment
    first.last_seen_at = max(first.last_seen_at, second.last_seen_at)
    first.collected_at = min(first.collected_at, second.collected_at)
    seen = set()
    observations = []
    for observation in first.observations + second.observations:
        key = tuple(
            observation.get(field, "") for field in ("source", "url", "published_at", "time_basis")
        )
        if key not in seen:
            seen.add(key)
            observations.append(observation)
    first.observations = observations
    classify(first)
    return first


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    result: dict[str, NewsItem] = {}
    urls: dict[tuple[str, str], str] = {}
    for item in items:
        identity = urls.get((item.symbol, item.url), item.id) if item.url else item.id
        if identity in result:
            merge_item(result[identity], item)
        else:
            item.id = identity
            result[identity] = item
        if item.url:
            urls[item.symbol, item.url] = identity
    return sorted(result.values(), key=lambda item: (item.event_date, item.published_at, item.id))


@dataclass
class SourceReport:
    source: str
    status: str = "sampled"
    fetched: int = 0
    requests: int = 0
    message: str = "검색에 포함된 모든 기사의 수집을 보장하지 않습니다."
    requested_start: str = ""
    requested_end: str = ""


@dataclass
class NewsResult:
    symbol: str
    company: str
    start: str
    end: str
    items: list[NewsItem]
    reports: list[SourceReport]
    collected_at: str = field(default_factory=now_utc)
    notices: list[str] = field(default_factory=list)
    exchange_timezone: str = "UTC"

    def metadata(self):
        return {
            "schema_version": 1,
            "symbol": self.symbol,
            "company": self.company,
            "start_inclusive": self.start,
            "end_inclusive": self.end,
            "collected_at": self.collected_at,
            "row_count": len(self.items),
            "exchange_timezone": self.exchange_timezone,
            "sources": [asdict(report) for report in self.reports],
            "notices": self.notices,
            "labels": "keyword/manual estimates; not market impact; "
            "scores are not calibrated probabilities",
        }


class NewsStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS news_items (id TEXT PRIMARY KEY, "
                "symbol TEXT NOT NULL, event_date TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS news_symbol_date ON news_items(symbol, event_date)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS news_runs (id INTEGER PRIMARY KEY, "
                "symbol TEXT NOT NULL, collected_at TEXT NOT NULL, metadata TEXT NOT NULL)"
            )

    def load(self, symbol: str, start: str, end: str) -> list[NewsItem]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT payload FROM news_items WHERE symbol=? "
                "AND event_date>=? AND event_date<=? ORDER BY event_date",
                (symbol, start, end),
            ).fetchall()
        return [NewsItem(**json.loads(row[0])) for row in rows]

    def save(self, result: NewsResult):
        existing = self.load(result.symbol, result.start, result.end)
        result.items = deduplicate(existing + result.items)
        with closing(sqlite3.connect(self.path)) as db, db:
            # Replace this range so canonical-URL merges remove redundant old IDs.
            db.execute(
                "DELETE FROM news_items WHERE symbol=? AND event_date>=? AND event_date<=?",
                (result.symbol, result.start, result.end),
            )
            db.executemany(
                "INSERT INTO news_items(id, symbol, event_date, payload) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "event_date=excluded.event_date,payload=excluded.payload",
                [
                    (i.id, i.symbol, i.event_date, json.dumps(asdict(i), ensure_ascii=False))
                    for i in result.items
                ],
            )
            db.execute(
                "INSERT INTO news_runs(symbol,collected_at,metadata) VALUES (?,?,?)",
                (
                    result.symbol,
                    result.collected_at,
                    json.dumps(result.metadata(), ensure_ascii=False),
                ),
            )

    def update_item(self, item: NewsItem):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE news_items SET payload=? WHERE id=? AND symbol=?",
                (json.dumps(asdict(item), ensure_ascii=False), item.id, item.symbol),
            )


def export_news(result: NewsResult, data_dir: Path) -> tuple[Path, Path]:
    from .market import PriceHistory
    from .storage import save_csv

    rows = []
    for item in result.items:
        row = asdict(item)
        for key in ("sources", "alternate_urls", "alternate_titles", "observations"):
            row[key] = json.dumps(row[key], ensure_ascii=False)
        rows.append(row)
    frame = pd.DataFrame(rows, columns=NewsItem.__dataclass_fields__)
    # Reuse the atomic/no-overwrite snapshot writer; its only typed column is timestamp.
    frame.insert(0, "timestamp", pd.to_datetime(frame["published_at"], utc=True, errors="coerce"))
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", result.symbol) + f"_news_{result.start}_{result.end}"
    for number in range(1, 10000):
        path = data_dir / f"{stem}{'' if number == 1 else f'_{number}'}.csv"
        try:
            return save_csv(PriceHistory(frame, result.metadata()), path)
        except FileExistsError:
            continue
    raise OSError("내보내기 파일 이름이 너무 많습니다.")
