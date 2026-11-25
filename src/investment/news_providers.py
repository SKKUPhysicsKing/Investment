"""Independent news adapters. Missing keys or one failed source never hide other results."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
import yfinance as yf
from defusedxml import ElementTree as ET

from .news import NewsItem, SourceReport, make_item, safe_url, text
from .search import Company

PROVIDERS = {
    "google": "Google News RSS",
    "yahoo": "Yahoo 뉴스/보도자료",
    "gdelt": "GDELT",
    "dart": "OpenDART",
    "naver": "네이버 뉴스",
    "sec": "SEC EDGAR",
    "finnhub": "Finnhub",
    "alpha": "Alpha Vantage",
    "rss": "추가 RSS/IR",
}
COMMON_NAMES = {
    "005930.KS": ["삼성전자", "Samsung Electronics"],
    "000660.KS": ["SK하이닉스", "SK hynix"],
    "035420.KS": ["네이버", "NAVER"],
    "035720.KS": ["카카오", "Kakao"],
    "005380.KS": ["현대자동차", "현대차", "Hyundai Motor"],
    "AAPL": ["Apple", "애플"],
    "MSFT": ["Microsoft", "마이크로소프트"],
    "NVDA": ["NVIDIA", "엔비디아"],
    "TSLA": ["Tesla", "테슬라"],
    "GOOG": ["Alphabet", "Google", "구글"],
    "GOOGL": ["Alphabet", "Google", "구글"],
    "AMZN": ["Amazon", "아마존"],
    "META": ["Meta Platforms", "메타"],
}
OFFICIAL_FEEDS = {
    "005930.KS": ("https://news.samsung.com/kr/feed/", "https://news.samsung.com/global/feed/"),
    "AAPL": ("https://www.apple.com/newsroom/rss-feed.rss",),
    "NVDA": ("https://nvidianews.nvidia.com/releases.xml",),
}


@dataclass
class NewsSettings:
    sources: tuple[str, ...] = tuple(PROVIDERS)
    aliases: str = ""
    max_requests: int = 60
    max_items: int = 10000
    body_limit: int = 10
    rss_urls: tuple[str, ...] = ()
    dart_key: str = field(default="", repr=False)
    naver_id: str = field(default="", repr=False)
    naver_secret: str = field(default="", repr=False)
    finnhub_key: str = field(default="", repr=False)
    alpha_key: str = field(default="", repr=False)
    sec_contact: str = field(default="", repr=False)

    @classmethod
    def from_environment(cls):
        return cls(
            dart_key=os.getenv("DART_API_KEY", ""),
            naver_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
            finnhub_key=os.getenv("FINNHUB_API_KEY", ""),
            alpha_key=os.getenv("ALPHAVANTAGE_API_KEY", ""),
            sec_contact=os.getenv("SEC_CONTACT", ""),
        )


@dataclass(frozen=True)
class NewsQuery:
    company: Company
    start: str
    end: str
    timezone: str = "UTC"

    def __post_init__(self):
        first, last = date.fromisoformat(self.start), date.fromisoformat(self.end)
        if first > last:
            raise ValueError("시작일이 종료일보다 늦습니다.")
        if last == date.max:
            raise ValueError("종료일을 줄이세요.")

    @property
    def korean(self):
        return self.company.symbol.endswith((".KS", ".KQ"))

    def aliases(self, settings):
        names = [self.company.name, *COMMON_NAMES.get(self.company.symbol, [])]
        names.extend(value.strip() for value in settings.aliases.split(",") if value.strip())
        if not self.korean:
            names.append(self.company.symbol)
        return list(dict.fromkeys(re.sub(r'["\n\r]', " ", name).strip() for name in names if name))[
            :10
        ]


class StopSource(Exception):
    pass


class SourceContext:
    def __init__(self, key, query, settings, cache_dir, cancel, progress):
        self.key, self.query, self.settings = key, query, settings
        self.cache_dir, self.cancel, self.progress = cache_dir, cancel, progress
        self.items: list[NewsItem] = []
        self.report = SourceReport(
            PROVIDERS[key], requested_start=query.start, requested_end=query.end
        )
        self.last_request = 0.0

    def check(self):
        if self.cancel.is_set():
            self.report.status = "cancelled"
            self.report.message = "사용자 취소. 완료한 요청의 결과를 보존했습니다."
            raise StopSource

    def get(
        self,
        url,
        *,
        params=None,
        headers=None,
        json_result=True,
        limit=12 * 1024 * 1024,
        retry=True,
    ):
        self.check()
        if self.report.requests >= self.settings.max_requests:
            self.report.status = "partial"
            self.report.message += " 요청 수 상한 도달. 기간을 줄이거나 수집 한도를 늘리세요."
            raise StopSource
        self.cancel.wait(max(0, 0.3 - (time.monotonic() - self.last_request)))
        self.check()
        self.report.requests += 1
        self.last_request = time.monotonic()
        self.progress(
            f"{self.report.source}: 요청 {self.report.requests} · 확보 {len(self.items):,}건"
        )
        try:
            with requests.get(
                url,
                params=params,
                headers=headers or {"User-Agent": "Investment/0.3 news collector"},
                timeout=(5, 18),
                stream=True,
            ) as response:
                if not response.ok:
                    if response.status_code == 429:
                        self.report.status = "partial"
                        self.report.message += (
                            " 요청 한도(HTTP 429)에 도달해 추가 요청을 중단했습니다."
                        )
                        raise StopSource
                    if response.status_code >= 500 and retry:
                        response.close()
                        self.cancel.wait(1)
                        return self.get(
                            url,
                            params=params,
                            headers=headers,
                            json_result=json_result,
                            limit=limit,
                            retry=False,
                        )
                    raise RuntimeError(f"HTTP {response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    self.check()
                    size += len(chunk)
                    if size > limit:
                        raise RuntimeError("응답 크기 제한 초과")
                    chunks.append(chunk)
            payload = b"".join(chunks)
            return json.loads(payload) if json_result else payload
        except requests.RequestException as exc:
            if retry:
                self.cancel.wait(1)
                return self.get(
                    url,
                    params=params,
                    headers=headers,
                    json_result=json_result,
                    limit=limit,
                    retry=False,
                )
            # Never expose request URLs, which may contain API keys.
            raise RuntimeError(f"네트워크 오류 ({type(exc).__name__})") from None

    def add(self, item):
        if item and self.query.start <= item.event_date <= self.query.end:
            if len(self.items) >= self.settings.max_items:
                self.report.status = "partial"
                self.report.message += " 기사 수 상한 도달."
                raise StopSource
            self.items.append(item)

    def skip(self, reason):
        self.report.status, self.report.message = "not_configured", reason
        raise StopSource

    def cached_json(self, name, fetch):
        path = self.cache_dir / name
        try:
            if time.time() - path.stat().st_mtime < 86400:
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        value = fetch()
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass
        return value


def windows(start: str, end: str, days=30):
    """Newest slices first, inclusive calendar dates."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    while last >= first:
        left = max(first, last - timedelta(days=days - 1))
        yield left, last
        last = left - timedelta(days=1)


def mentions_company(content, names):
    content = text(content).casefold()
    for name in names:
        name = name.casefold()
        if re.search(r"[가-힣]", name):
            if name in content:
                return True
        elif re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", content):
            return True
    return False


def feed_entries(payload):
    root = ET.fromstring(payload)
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        values = {}
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "link" and child.attrib.get("href"):
                if child.attrib.get("rel", "alternate") == "alternate":
                    values["link"] = child.attrib["href"]
            else:
                values.setdefault(tag, "".join(child.itertext()))
        yield values


def google(ctx):
    names = ctx.query.aliases(ctx.settings)
    expression = "(" + " OR ".join(f'"{name}"' for name in names) + ")"
    plan = deque(
        (a, b, language)
        for a, b in windows(ctx.query.start, ctx.query.end)
        for language in ("ko", "en")
    )
    ctx.report.message = "공개 검색 RSS 표본. 전체 기사·과거 검색 완전성은 보장되지 않습니다."
    consecutive_failures = 0
    while plan:
        a, b, language = plan.popleft()
        query = (
            f"{expression} after:{(a - timedelta(days=1)).isoformat()} "
            f"before:{(b + timedelta(days=2)).isoformat()}"
        )
        params = {
            "q": query,
            "hl": "ko" if language == "ko" else "en-US",
            "gl": "KR" if language == "ko" else "US",
            "ceid": "KR:ko" if language == "ko" else "US:en",
        }
        try:
            entries = list(
                feed_entries(
                    ctx.get("https://news.google.com/rss/search", params=params, json_result=False)
                )
            )
        except StopSource:
            raise
        except Exception:
            consecutive_failures += 1
            ctx.report.status = "partial"
            ctx.report.message += f" {language}:{a}~{b} 조회 실패."
            if consecutive_failures >= 4:
                ctx.report.message += " 연속 실패로 추가 요청을 중단했습니다."
                break
            continue
        consecutive_failures = 0
        for entry in entries:
            ctx.add(
                make_item(
                    ctx.query.company,
                    "Google News RSS",
                    entry.get("title"),
                    entry.get("pubDate"),
                    entry.get("link", ""),
                    publisher=entry.get("source", ""),
                    tz=ctx.query.timezone,
                    summary="",
                    time_basis="feed_published",
                )
            )
        if len(entries) >= 100:
            if a < b:
                midpoint = a + (b - a) // 2
                plan.extend([(a, midpoint, language), (midpoint + timedelta(days=1), b, language)])
            else:
                ctx.report.status = "partial"
                ctx.report.message += f" {a}: 하루 검색도 결과 상한에 도달했습니다."


def yahoo(ctx):
    ctx.report.status = "latest_only"
    ctx.report.message = "최신 뉴스/보도자료만 제공. 과거 전체 기간을 조회하는 API가 아닙니다."
    for tab in ("all", "press releases"):
        ctx.check()
        if ctx.report.requests >= ctx.settings.max_requests:
            ctx.report.status = "partial"
            ctx.report.message += " 요청 수 상한 도달."
            raise StopSource
        ctx.report.requests += 1
        raw = yf.Ticker(ctx.query.company.symbol).get_news(count=80, tab=tab)
        for row in raw:
            content = row.get("content") or row
            if content.get("contentType") == "VIDEO":
                continue
            provider = content.get("provider") or {}
            link = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
            link = link.get("url", "") if isinstance(link, dict) else link
            item = make_item(
                ctx.query.company,
                "Yahoo",
                content.get("title"),
                content.get("pubDate") or content.get("providerPublishTime"),
                link or content.get("link", ""),
                publisher=provider.get("displayName", content.get("publisher", "")),
                summary=content.get("summary") or content.get("description"),
                tz=ctx.query.timezone,
                time_basis="provider_published",
            )
            if item and ((content.get("finance") or {}).get("premiumFinance") or {}).get(
                "isPremiumNews"
            ):
                item.body_status = "restricted"
            ctx.add(item)


def gdelt(ctx):
    # GDELT's public DOC interface documents a rolling three-month search window.
    now = datetime.now(timezone.utc)
    cutoff = now.date() - timedelta(days=89)
    first = max(date.fromisoformat(ctx.query.start), cutoff)
    last = min(date.fromisoformat(ctx.query.end), now.date())
    if first > last:
        ctx.report.status, ctx.report.message = (
            "unsupported_range",
            "공개 DOC API의 최근 약 3개월 범위를 벗어났습니다.",
        )
        return
    ctx.report.message = (
        "최근 약 3개월 검색 표본; 시각은 최초 관측 시각이며 원문 발행 시각과 다를 수 있습니다."
    )
    if ctx.query.start < first.isoformat():
        ctx.report.status = "partial"
    english = [name for name in ctx.query.aliases(ctx.settings) if re.search(r"[A-Za-z]", name)]
    if not english:
        ctx.skip("영문 회사 별칭을 설정하면 GDELT 검색을 추가할 수 있습니다.")
    expression = "(" + " OR ".join(f'"{n}"' for n in english) + ")"
    plan = deque(windows(first.isoformat(), last.isoformat(), 7))
    while plan:
        a, b = plan.popleft()
        end_utc = min(
            datetime.combine(b + timedelta(days=1), datetime.max.time(), timezone.utc), now
        )
        data = ctx.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": expression,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 250,
                "startdatetime": max(cutoff, a - timedelta(days=1)).strftime("%Y%m%d") + "000000",
                "enddatetime": end_utc.strftime("%Y%m%d%H%M%S"),
                "sort": "DateDesc",
            },
        )
        articles = data.get("articles", [])
        if len(articles) >= 250:
            if a < b:
                midpoint = a + (b - a) // 2
                plan.extend([(a, midpoint), (midpoint + timedelta(days=1), b)])
            else:
                ctx.report.status = "partial"
                ctx.report.message += f" {a}: 하루 검색도 결과 상한에 도달했습니다."
        for row in articles:
            ctx.add(
                make_item(
                    ctx.query.company,
                    "GDELT",
                    row.get("title"),
                    row.get("seendate"),
                    row.get("url", ""),
                    publisher=row.get("domain", ""),
                    tz=ctx.query.timezone,
                    time_basis="first_seen",
                    naive_timezone="UTC",
                )
            )


def dart(ctx):
    if not ctx.query.korean:
        ctx.skip("국내 종목 전용입니다.")
    if not ctx.settings.dart_key:
        ctx.skip("설정에서 DART API 키를 입력하세요.")

    def corporations():
        payload = ctx.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": ctx.settings.dart_key},
            json_result=False,
        )
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            info = archive.getinfo("CORPCODE.xml")
            if info.file_size > 100 * 1024 * 1024:
                raise RuntimeError("기업 코드 파일 크기 제한 초과")
            root = ET.fromstring(archive.read(info))
        return {
            node.findtext("stock_code", "").strip(): node.findtext("corp_code")
            for node in root.findall("list")
            if node.findtext("stock_code", "").strip()
        }

    codes = ctx.cached_json("dart-companies.json", corporations)
    code = codes.get(ctx.query.company.symbol.split(".")[0])
    if not code:
        raise RuntimeError("DART 기업 고유번호를 찾지 못했습니다.")
    page, pages = 1, 1
    ctx.report.message = (
        "회사별 접수일 기준 전체 공시. 날짜만 제공되는 공시의 발표 시각은 미상입니다."
    )
    while page <= pages:
        data = ctx.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": ctx.settings.dart_key,
                "corp_code": code,
                "bgn_de": ctx.query.start.replace("-", ""),
                "end_de": ctx.query.end.replace("-", ""),
                "page_no": page,
                "page_count": 100,
                "sort": "date",
                "sort_mth": "desc",
                "last_reprt_at": "N",
            },
        )
        status = data.get("status")
        if status == "013":
            break
        if status != "000":
            raise RuntimeError(f"DART 응답 코드 {status}; 키/이용 한도를 확인하세요.")
        pages = int(data.get("total_page", 1))
        for row in data.get("list", []):
            number = row.get("rcept_no", "")
            ctx.add(
                make_item(
                    ctx.query.company,
                    "DART",
                    row.get("report_nm"),
                    row.get("rcept_dt"),
                    "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + number,
                    publisher="금융감독원 DART",
                    tz=ctx.query.timezone,
                    record_id=number,
                    filing=True,
                    time_basis="filing_date",
                    relevance="공시 대상 회사 고유번호 일치",
                )
            )
        page += 1
    ctx.report.status = "completed"
    ctx.report.message += " 제공된 페이지 조회 완료(비공개·미제공 자료 제외)."


def naver(ctx):
    if not ctx.settings.naver_id or not ctx.settings.naver_secret:
        ctx.skip("설정에서 네이버 Client ID/Secret을 입력하세요.")
    ctx.report.status = "latest_only"
    ctx.report.message = (
        "검색 위치 1,000 제한·날짜 구간 인자 없음. 시각은 네이버 제공 시각일 수 있습니다."
    )
    for query in ctx.query.aliases(ctx.settings)[:4]:
        for start in range(1, 1000, 100):
            data = ctx.get(
                "https://openapi.naver.com/v1/search/news.json",
                params={"query": query, "sort": "date", "display": 100, "start": start},
                headers={
                    "X-Naver-Client-Id": ctx.settings.naver_id,
                    "X-Naver-Client-Secret": ctx.settings.naver_secret,
                },
            )
            rows = data.get("items", [])
            old = False
            for row in rows:
                item = make_item(
                    ctx.query.company,
                    "Naver",
                    row.get("title"),
                    row.get("pubDate"),
                    row.get("originallink") or row.get("link", ""),
                    summary=row.get("description"),
                    tz=ctx.query.timezone,
                    time_basis="portal_provided",
                )
                if item and item.event_date < ctx.query.start:
                    old = True
                ctx.add(item)
            if len(rows) < 100 or old:
                break


def sec(ctx):
    if ctx.query.korean:
        ctx.skip("미국 SEC 등록 회사용입니다.")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", ctx.settings.sec_contact):
        ctx.skip("SEC 요청 식별용 실제 연락 이메일을 설정하세요(API 키는 불필요).")
    headers = {"User-Agent": "Investment research app " + ctx.settings.sec_contact}
    companies = ctx.cached_json(
        "sec-companies.json",
        lambda: ctx.get("https://www.sec.gov/files/company_tickers.json", headers=headers),
    )
    target = ctx.query.company.symbol.upper().replace("-", ".")
    match = next(
        (v for v in companies.values() if v.get("ticker", "").upper().replace("-", ".") == target),
        None,
    )
    if not match:
        raise RuntimeError("SEC 기업 CIK를 찾지 못했습니다.")
    cik = str(match["cik_str"]).zfill(10)
    base = "https://data.sec.gov/submissions/"
    data = ctx.get(base + f"CIK{cik}.json", headers=headers)

    def sections():
        yield data.get("filings", {}).get("recent", {})
        for entry in data.get("filings", {}).get("files", []):
            if (
                entry.get("filingTo", "") < ctx.query.start
                or entry.get("filingFrom", "9999") > ctx.query.end
            ):
                continue
            yield ctx.get(base + quote(entry["name"], safe=""), headers=headers)

    ctx.report.message = "공식 제출 이력. 실적 발표일과 정기보고서 제출일은 서로 다를 수 있습니다."
    for section in sections():
        count = len(section.get("accessionNumber", []))
        for index in range(count):
            row = {
                key: values[index]
                for key, values in section.items()
                if isinstance(values, list) and len(values) > index
            }
            form = row.get("form", "")
            accession = row["accessionNumber"]
            document = row.get("primaryDocument", "")
            link = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession.replace('-', '')}/{quote(document, safe='/')}"
            )
            item = make_item(
                ctx.query.company,
                "SEC",
                f"{ctx.query.company.name} · {form} · {row.get('primaryDocDescription', '')}",
                row.get("acceptanceDateTime") or row.get("filingDate"),
                link,
                publisher="SEC EDGAR",
                summary=f"Form {form}; report period {row.get('reportDate', '')}; "
                f"items {row.get('items', '')}",
                tz=ctx.query.timezone,
                record_id=accession,
                filing=True,
                time_basis="filing_acceptance" if row.get("acceptanceDateTime") else "filing_date",
                naive_timezone="America/New_York",
                relevance="SEC CIK와 종목 일치",
            )
            if item and (
                form in ("10-K", "10-Q", "20-F", "40-F") or "2.02" in row.get("items", "")
            ):
                item.event_type = "earnings"
            ctx.add(item)
    ctx.report.status = "completed"
    ctx.report.message += " 제공된 이력 파일 조회 완료."


def finnhub(ctx):
    if not ctx.settings.finnhub_key:
        ctx.skip("설정에서 Finnhub 키를 입력하세요.")
    if ctx.query.korean:
        ctx.skip("Company News API는 북미 기업 중심입니다.")
    ctx.report.message = "계정별 과거 제공 범위와 검색 표본 한도가 적용됩니다."
    for a, b in windows(ctx.query.start, ctx.query.end, 7):
        data = ctx.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ctx.query.company.symbol,
                "from": (a - timedelta(days=1)).isoformat(),
                "to": (b + timedelta(days=1)).isoformat(),
            },
            headers={"X-Finnhub-Token": ctx.settings.finnhub_key},
        )
        if not isinstance(data, list):
            raise RuntimeError("Finnhub 응답/계정 권한을 확인하세요.")
        if len(data) >= 1000:
            ctx.report.status = "partial"
        for row in data:
            ctx.add(
                make_item(
                    ctx.query.company,
                    "Finnhub",
                    row.get("headline"),
                    row.get("datetime"),
                    row.get("url", ""),
                    publisher=row.get("source", ""),
                    summary=row.get("summary"),
                    tz=ctx.query.timezone,
                    record_id=str(row.get("id", "")),
                    time_basis="provider_published",
                )
            )


def alpha(ctx):
    if ctx.query.korean:
        ctx.skip("국내 상장 티커는 Alpha Vantage 뉴스 티커와 직접 호환되지 않습니다.")
    if not ctx.settings.alpha_key:
        ctx.skip("Alpha Vantage 키/뉴스 API 이용 권한이 필요합니다.")
    ctx.report.message = "기간별 뉴스 표본. 뉴스 API 이용 권한(유료 기능)을 확인하세요."
    plan = deque(windows(ctx.query.start, ctx.query.end, 30))
    while plan:
        a, b = plan.popleft()
        data = ctx.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ctx.query.company.symbol,
                "time_from": (a - timedelta(days=1)).strftime("%Y%m%d") + "T0000",
                "time_to": (b + timedelta(days=2)).strftime("%Y%m%d") + "T0000",
                "limit": 1000,
                "sort": "LATEST",
                "apikey": ctx.settings.alpha_key,
            },
        )
        if "feed" not in data:
            raise RuntimeError("Alpha Vantage 권한/호출 한도를 확인하세요.")
        rows = data["feed"]
        if len(rows) >= 1000:
            if a < b:
                midpoint = a + (b - a) // 2
                plan.extend([(a, midpoint), (midpoint + timedelta(days=1), b)])
            else:
                ctx.report.status = "partial"
        for row in rows:
            specific = next(
                (
                    v
                    for v in row.get("ticker_sentiment", [])
                    if v.get("ticker") == ctx.query.company.symbol
                ),
                {},
            )
            ctx.add(
                make_item(
                    ctx.query.company,
                    "Alpha Vantage",
                    row.get("title"),
                    row.get("time_published"),
                    row.get("url", ""),
                    publisher=row.get("source", ""),
                    summary=row.get("summary"),
                    tz=ctx.query.timezone,
                    naive_timezone="UTC",
                    time_basis="provider_published",
                    provider_sentiment=json.dumps(
                        specific or {"overall": row.get("overall_sentiment_label")},
                        ensure_ascii=False,
                    ),
                )
            )


def rss(ctx):
    official = OFFICIAL_FEEDS.get(ctx.query.company.symbol, ())
    urls = tuple(dict.fromkeys((*official, *ctx.settings.rss_urls)))
    if not urls:
        ctx.skip("설정에 회사 IR/뉴스룸 등의 공개 RSS/Atom URL을 추가할 수 있습니다.")
    names = ctx.query.aliases(ctx.settings)
    ctx.report.status = "latest_only"
    ctx.report.message = (
        "공식 회사/추가 RSS의 제공 범위. 과거 전체가 아닙니다. 추가 RSS는 회사명으로 필터링합니다."
    )
    failures = 0
    for url in urls:
        if not safe_url(url):
            continue
        try:
            entries = list(feed_entries(ctx.get(url, json_result=False)))
        except StopSource:
            raise
        except Exception:
            failures += 1
            continue
        for row in entries:
            title, summary = (
                row.get("title", ""),
                row.get("description") or row.get("summary") or row.get("content", ""),
            )
            if url not in official and not mentions_company(title + " " + summary, names):
                continue
            item = make_item(
                ctx.query.company,
                "RSS/IR",
                title,
                row.get("pubDate") or row.get("published") or row.get("updated") or row.get("date"),
                row.get("link", ""),
                publisher=ctx.query.company.name + " 공식 뉴스룸"
                if url in official
                else row.get("author", ""),
                summary=summary,
                tz=ctx.query.timezone,
                time_basis="feed_published",
            )
            if item and (row.get("encoded") or row.get("content")):
                item.body = text(row.get("encoded") or row.get("content"), 40000)
                item.body_status = "feed_excerpt"
            ctx.add(item)
    if failures:
        ctx.report.status = "partial" if ctx.items else "error"
        ctx.report.message += f" RSS {failures}개 연결 실패."


ADAPTERS = {
    "google": google,
    "yahoo": yahoo,
    "gdelt": gdelt,
    "dart": dart,
    "naver": naver,
    "sec": sec,
    "finnhub": finnhub,
    "alpha": alpha,
    "rss": rss,
}


def run_source(key, query, settings, cache_dir: Path, cancel: threading.Event, progress):
    ctx = SourceContext(key, query, settings, cache_dir, cancel, progress)
    try:
        ADAPTERS[key](ctx)
    except StopSource:
        pass
    except Exception as exc:
        ctx.report.status = "partial" if ctx.items else "error"
        # Third-party clients may put credentials in errors; redact all configured secrets.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        for secret in (
            settings.dart_key,
            settings.naver_id,
            settings.naver_secret,
            settings.finnhub_key,
            settings.alpha_key,
            settings.sec_contact,
        ):
            if secret:
                message = message.replace(secret, "[redacted]")
        ctx.report.message = f"수집 중단: {message}. 확보한 자료는 보존했습니다."
    ctx.report.fetched = len(ctx.items)
    return ctx.items, ctx.report
