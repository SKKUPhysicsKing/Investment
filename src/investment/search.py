"""Resolve Korean company names with KRX KIND, and overseas names with Yahoo."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
ALIASES = {
    "애플": "Apple",
    "엔비디아": "NVIDIA",
    "마이크로소프트": "Microsoft",
    "테슬라": "Tesla",
    "아마존": "Amazon",
    "구글": "Alphabet",
    "메타": "Meta",
    "브로드컴": "Broadcom",
}


class SearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Company:
    symbol: str
    name: str
    exchange: str
    source: str


@dataclass
class SearchResults:
    companies: list[Company]
    notice: str = ""


def _key(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def parse_kind_table(content: bytes) -> list[Company]:
    # KIND's Excel download is an EUC-KR HTML table. Preserve leading zeros.
    tables = pd.read_html(StringIO(content.decode("euc-kr")), converters={"종목코드": str})
    table = next(
        (t for t in tables if {"회사명", "시장구분", "종목코드"}.issubset(t.columns)), None
    )
    if table is None:
        raise SearchError("KRX 회사 목록의 형식이 변경되었습니다.")
    suffixes = {
        "유가": ".KS",
        "유가증권": ".KS",
        "코스피": ".KS",
        "KOSPI": ".KS",
        "코스닥": ".KQ",
        "KOSDAQ": ".KQ",
    }
    companies = []
    for _, row in table.iterrows():
        market = str(row["시장구분"]).strip()
        code = str(row["종목코드"]).strip().zfill(6)
        name = str(row["회사명"]).strip()
        if market in suffixes and re.fullmatch(r"[0-9A-Za-z]{6}", code) and name != "nan":
            companies.append(Company(code + suffixes[market], name, market, "KRX KIND"))
    if not companies:
        raise SearchError("KRX 회사 목록을 읽지 못했습니다.")
    return companies


def korean_companies(cache_dir: Path) -> tuple[list[Company], str]:
    cache = cache_dir / "companies.json"
    old = []
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
        old = [Company(**item) for item in payload["companies"]]
        saved = datetime.fromisoformat(payload["saved_at"])
        if saved.tzinfo and datetime.now(timezone.utc) - saved < timedelta(days=7) and old:
            return old, ""
    except (OSError, ValueError, KeyError, TypeError):
        old = []
    try:
        response = requests.get(
            KIND_URL,
            params={"method": "download", "searchType": "13"},
            timeout=15,
            headers={"User-Agent": "Investment/0.2 company lookup"},
        )
        response.raise_for_status()
        companies = parse_kind_table(response.content)
    except Exception as exc:
        if old:
            return old, "KRX 연결 실패: 이전에 저장한 회사 목록을 사용합니다."
        raise SearchError(f"국내 회사 목록을 불러오지 못했습니다: {exc}") from exc
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "companies": [asdict(company) for company in companies],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(cache)
    except OSError:
        pass  # Search should still work in a read-only directory.
    return companies, ""


def search_companies(query: str, cache_dir: Path, limit: int = 50) -> SearchResults:
    query = query.strip()
    if not query:
        raise ValueError("회사명 또는 티커를 입력하세요.")
    if len(query) > 100:
        raise ValueError("검색어는 100자 이하로 입력하세요.")
    candidates: list[Company] = []
    notice = ""
    korean_query = bool(re.search(r"[가-힣]", query)) and query not in ALIASES
    if korean_query or re.fullmatch(r"\d{6}(?:\.(?:KS|KQ))?", query, re.I):
        companies, notice = korean_companies(cache_dir)
        candidates = [
            c for c in companies if _key(query) in _key(c.name) or _key(query) in _key(c.symbol)
        ]
    if not korean_query and not candidates:
        try:
            quotes = yf.Search(
                ALIASES.get(query, query), max_results=20, news_count=0, lists_count=0, timeout=15
            ).quotes
            for quote in quotes:
                if quote.get("quoteType") not in ("EQUITY", "ETF") or not quote.get("symbol"):
                    continue
                candidates.append(
                    Company(
                        quote["symbol"],
                        quote.get("longname") or quote.get("shortname") or quote["symbol"],
                        quote.get("exchDisp") or quote.get("exchange") or "",
                        "Yahoo Finance",
                    )
                )
        except Exception as exc:
            if not candidates:
                raise SearchError(f"회사 검색에 실패했습니다: {exc}") from exc
            notice = (notice + " Yahoo 검색 연결 실패: 국내 목록 결과를 표시합니다.").strip()
    unique = {company.symbol: company for company in reversed(candidates)}
    effective_query = _key(ALIASES.get(query, query))
    result = sorted(
        unique.values(),
        key=lambda c: (
            _key(c.name) != effective_query and _key(c.symbol) != effective_query,
            not _key(c.name).startswith(effective_query),
        ),
    )
    return SearchResults(result[:limit], notice)
