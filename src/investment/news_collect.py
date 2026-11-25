"""Concurrent collection, partial-result retention, cache union and archive import."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from .news import NewsResult, NewsStore, SourceReport, deduplicate, make_item
from .news_content import PublicContent
from .news_providers import PROVIDERS, NewsQuery, NewsSettings, mentions_company, run_source


def collect_news(
    query: NewsQuery,
    settings: NewsSettings,
    data_dir: Path,
    cancel: threading.Event | None = None,
    progress=lambda message: None,
) -> NewsResult:
    if not 1 <= settings.max_requests <= 300 or not 1 <= settings.max_items <= 50000:
        raise ValueError("요청 수는 1~300, 자료 수는 1~50,000 범위여야 합니다.")
    if not 0 <= settings.body_limit <= 50:
        raise ValueError("원문 추가 수집 한도는 0~50건입니다.")
    cancel = cancel or threading.Event()
    result = NewsResult(query.company.symbol, query.company.name, query.start, query.end, [], [])
    result.exchange_timezone = query.timezone
    keys = list(dict.fromkeys(key for key in settings.sources if key in PROVIDERS))
    cache_dir = data_dir.parent / ".investment-app" / "news-cache"
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(run_source, key, query, settings, cache_dir, cancel, progress): key
            for key in keys
        }
        for future in as_completed(futures):
            items, report = future.result()
            result.items.extend(items)
            result.reports.append(report)
            progress(f"{report.source}: {report.fetched:,}건 · {report.status}")
    result.reports.sort(key=lambda report: list(PROVIDERS.values()).index(report.source))
    result.items = deduplicate(result.items)
    if settings.body_limit and not cancel.is_set():
        client = PublicContent(cancel, settings.sec_contact)
        candidates = [
            item
            for item in reversed(result.items)
            if item.url
            and not item.body
            and "news.google.com" not in item.url
            and item.body_status != "restricted"
        ]
        for index, item in enumerate(candidates[: settings.body_limit]):
            if cancel.is_set():
                break
            progress(f"공개 원문 추가 수집 {index + 1}/{min(len(candidates), settings.body_limit)}")
            client.enrich(item)
    if cancel.is_set():
        result.notices.append("취소 전 확보한 결과와 기존 캐시를 표시합니다.")
    result.notices.append(
        "기사 없음과 수집 불가/한도 도달은 다릅니다. 출처별 수집 상태를 확인하세요."
    )
    try:
        fresh = len(result.items)
        store = NewsStore(data_dir / "news.sqlite")
        store.save(result)
        result.notices.append(
            f"이번 수집 {fresh:,}건, 이전 캐시와 병합 후 {len(result.items):,}건입니다."
        )
    except (OSError, ValueError, sqlite3.Error):
        result.notices.append("SQLite 저장 실패. 현재 결과를 CSV로 내보내 보존하세요.")
    return result


def load_cached(query: NewsQuery, data_dir: Path) -> NewsResult:
    store = NewsStore(data_dir / "news.sqlite")
    items = store.load(query.company.symbol, query.start, query.end)
    return NewsResult(
        query.company.symbol,
        query.company.name,
        query.start,
        query.end,
        items,
        [
            SourceReport(
                "SQLite cache",
                "cached",
                len(items),
                message="이전에 수집한 자료입니다. 새 네트워크 조회를 하지 않았습니다.",
            )
        ],
        exchange_timezone=query.timezone,
    )


def import_archive(
    path: Path, query: NewsQuery, settings: NewsSettings, data_dir: Path
) -> NewsResult:
    if path.suffix.lower() == ".xlsx":
        frame = pd.read_excel(path, dtype=str)
    elif path.suffix.lower() == ".csv":
        try:
            frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(path, dtype=str, encoding="cp949")
    else:
        raise ValueError("BIGKinds 등의 .xlsx 또는 .csv 파일을 선택하세요.")
    frame.columns = [str(column).strip() for column in frame.columns]
    date_key = next((key for key in ("일자", "날짜", "date", "event_date") if key in frame), None)
    title_key = next((key for key in ("제목", "title", "headline") if key in frame), None)
    if not date_key or not title_key:
        raise ValueError("파일에 일자/날짜/date와 제목/title 열이 필요합니다.")
    names = query.aliases(settings)
    items = []
    for _, row in frame.fillna("").iterrows():
        summary = row.get("본문") or row.get("summary") or row.get("description") or ""
        title = row[title_key]
        haystack = (title + " " + summary + " " + row.get("키워드", "")).casefold()
        if not mentions_company(haystack, names):
            continue
        item = make_item(
            query.company,
            "Archive import",
            title,
            row[date_key],
            row.get("URL") or row.get("url", ""),
            summary=summary,
            publisher=row.get("언론사") or row.get("publisher", ""),
            tz=query.timezone,
            time_basis="archive_date",
            relevance="회사명/별칭이 제목·요약·키워드에 포함됨",
        )
        if item and query.start <= item.event_date <= query.end:
            items.append(item)
    result = NewsResult(
        query.company.symbol,
        query.company.name,
        query.start,
        query.end,
        deduplicate(items),
        [
            SourceReport(
                "Archive import",
                "imported",
                len(items),
                message=f"파일 {len(frame):,}행 중 회사명/기간 일치 {len(items):,}건. "
                "본문 열은 원문 전문이 아닐 수 있습니다.",
            )
        ],
    )
    result.exchange_timezone = query.timezone
    NewsStore(data_dir / "news.sqlite").save(result)
    return result


def timezone_for(company):
    if company.symbol.endswith((".KS", ".KQ")):
        return "Asia/Seoul"
    for suffix, timezone_name in (
        (".T", "Asia/Tokyo"),
        (".HK", "Asia/Hong_Kong"),
        (".L", "Europe/London"),
        (".DE", "Europe/Berlin"),
        (".PA", "Europe/Paris"),
    ):
        if company.symbol.endswith(suffix):
            return timezone_name
    return "America/New_York" if "." not in company.symbol else "UTC"
