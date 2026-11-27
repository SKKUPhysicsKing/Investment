"""Interest-rate observations from FRED and Bank of Korea ECOS.

Values stay in percent (3.5 means 3.5%), at the provider's native frequency.
Dates are observation dates, never invented publication timestamps.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .market import DataError, FetchError, NoDataError

RATE_COLUMNS = [
    "date",
    "series_id",
    "series_name",
    "country",
    "rate",
    "unit",
    "frequency",
    "source",
]
MAX_BYTES = 32 * 1024 * 1024
PAGE_SIZE = 1000


@dataclass(frozen=True)
class RateSeries:
    id: str
    name: str
    country: str
    source: str
    category: str
    frequency: str = "daily"
    table: str = ""
    item: str = ""
    policy: bool = False

    @property
    def url(self):
        if self.source == "FRED":
            return f"https://fred.stlouisfed.org/series/{self.id}"
        return "https://ecos.bok.or.kr/"


def _catalog():
    rows = [
        RateSeries("DFF", "미국 실효 연방기금금리", "US", "FRED", "정책·단기"),
        RateSeries("DFEDTARU", "미국 정책금리 목표 상단", "US", "FRED", "정책·단기", policy=True),
        RateSeries("DFEDTARL", "미국 정책금리 목표 하단", "US", "FRED", "정책·단기", policy=True),
        RateSeries(
            "DFEDTAR", "미국 과거 정책금리 단일 목표", "US", "FRED", "정책·단기", policy=True
        ),
    ]
    for code, label in (
        ("1MO", "1개월"),
        ("3MO", "3개월"),
        ("6MO", "6개월"),
        ("1", "1년"),
        ("2", "2년"),
        ("3", "3년"),
        ("5", "5년"),
        ("7", "7년"),
        ("10", "10년"),
        ("20", "20년"),
        ("30", "30년"),
    ):
        rows.append(RateSeries(f"DGS{code}", f"미국 국채 {label}", "US", "FRED", "국채"))
    for years in (5, 7, 10, 20, 30):
        rows.append(
            RateSeries(f"DFII{years}", f"미국 실질 국채 {years}년", "US", "FRED", "실질금리")
        )
    for code, label in (
        ("SOFR", "미국 SOFR 담보부 익일물"),
        ("OBFR", "미국 익일물 은행자금조달금리"),
        ("IORB", "미국 지급준비금 이자율"),
        ("DPRIME", "미국 은행 프라임 대출금리"),
        ("DCPF3M", "미국 금융기업 CP 3개월"),
        ("DCPN3M", "미국 비금융기업 CP 3개월"),
    ):
        rows.append(RateSeries(code, label, "US", "FRED", "정책·단기"))
    for years in (15, 30):
        rows.append(
            RateSeries(
                f"MORTGAGE{years}US",
                f"미국 주택담보대출 {years}년",
                "US",
                "FRED",
                "대출·예금",
                "weekly",
            )
        )
    rows.append(
        RateSeries(
            "BOK_BASE_RATE",
            "한국은행 기준금리",
            "KR",
            "ECOS",
            "정책·단기",
            table="722Y001",
            item="0101000",
            policy=True,
        )
    )
    for item, name, category in (
        ("010190000", "국고채 1년", "국채"),
        ("010200000", "국고채 3년", "국채"),
        ("010200001", "국고채 5년", "국채"),
        ("010210000", "국고채 10년", "국채"),
        ("010220000", "국고채 20년", "국채"),
        ("010101000", "콜금리 1일 전체거래", "정책·단기"),
        ("010102000", "콜금리 1일 중개회사거래", "정책·단기"),
        ("010150000", "KORIBOR 3개월", "정책·단기"),
        ("010151000", "KORIBOR 6개월", "정책·단기"),
        ("010152000", "KORIBOR 12개월", "정책·단기"),
    ):
        rows.append(
            RateSeries(
                f"ECOS_817Y002_{item}_D",
                f"한국 {name}",
                "KR",
                "ECOS",
                category,
                table="817Y002",
                item=item,
            )
        )
    for table, item, name in (
        ("121Y002", "BEABAA2", "한국 저축성수신 신규취급 평균"),
        ("121Y002", "BEABAA21", "한국 순수저축성예금 신규취급"),
        ("121Y002", "BEABAA211", "한국 정기예금 신규취급"),
        ("121Y006", "BECBLA01", "한국 대출 신규취급 평균"),
        ("121Y006", "BECBLA02", "한국 기업대출 신규취급"),
        ("121Y006", "BECBLA0201", "한국 대기업대출 신규취급"),
    ):
        rows.append(
            RateSeries(
                f"ECOS_{table}_{item}_M",
                name,
                "KR",
                "ECOS",
                "대출·예금",
                "monthly",
                table,
                item,
            )
        )
    return {series.id: series for series in rows}


RATE_SERIES = _catalog()
ECOS_TABLES = {
    "722Y001": ("한국은행", "정책·단기", "D"),
    "817Y002": ("한국 시장금리", "시장금리", "D"),
    "121Y002": ("한국 예금 신규취급", "대출·예금", "M"),
    "121Y006": ("한국 대출 신규취급", "대출·예금", "M"),
}


@dataclass(frozen=True)
class RateRequest:
    series: RateSeries
    start: str
    end: str

    def __post_init__(self):
        try:
            for value in (self.start, self.end):
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                date.fromisoformat(value)
            if self.start > self.end:
                raise ValueError
        except ValueError as exc:
            raise ValueError(
                "날짜를 YYYY-MM-DD로 입력하고 시작일 ≤ 종료일인지 확인하세요."
            ) from exc


@dataclass
class RateHistory:
    data: pd.DataFrame
    metadata: dict[str, Any]


def resolve_series(series: str | RateSeries) -> RateSeries:
    if isinstance(series, RateSeries):
        if series.source not in {"FRED", "ECOS"}:
            raise ValueError("지원하지 않는 금리 출처입니다.")
        return series
    try:
        return RATE_SERIES[series.strip().upper()]
    except (KeyError, AttributeError) as exc:
        raise ValueError(
            "금리 목록에서 지표를 선택하세요. CLI의 rates --list로 확인할 수 있습니다."
        ) from exc


def _download(url: str, source: str, timeout: float, attempts: int) -> bytes:
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "Investment/0.6 (interest-rate data)"})
            with urlopen(request, timeout=timeout) as response:
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise DataError(f"{source} 응답이 너무 큽니다. 기간을 나누어 조회하세요.")
            return body
        except HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise FetchError(
                    f"{source} 요청 실패 (HTTP {exc.code}). 출처와 설정을 확인하세요."
                ) from None
        except (URLError, TimeoutError, OSError):
            pass
        if attempt + 1 < attempts:
            time.sleep(min(0.5 * 2**attempt, 4))
    # ECOS URLs contain credentials. Never echo a URL or the underlying exception.
    raise FetchError(
        f"{source}에 연결하지 못했습니다. 네트워크와 출처 상태를 확인하세요."
    ) from None


def _ecos_key(value: str | None) -> str:
    key = (value or os.environ.get("ECOS_API_KEY", "")).strip()
    if not key:
        raise ValueError(
            "한국 금리는 ECOS API 인증키가 필요합니다. 금리 탭의 API 설정에서 입력하세요."
        )
    return key


def _ecos_rows(service, suffix, key, timeout, attempts):
    rows = []
    page_size = min(PAGE_SIZE, 10) if key == "sample" else PAGE_SIZE
    for start in range(1, 100001, page_size):
        url = (
            f"https://ecos.bok.or.kr/api/{service}/{quote(key, safe='')}/json/kr/"
            f"{start}/{start + page_size - 1}/{suffix}"
        )
        try:
            payload = json.loads(_download(url, "ECOS", timeout, attempts))
        except (ValueError, UnicodeError):
            raise DataError("ECOS가 예상한 JSON 자료를 반환하지 않았습니다.") from None
        if not isinstance(payload, dict):
            raise DataError("ECOS 응답 형식이 올바르지 않습니다.")
        if "RESULT" in payload:
            result = payload["RESULT"]
            code = result.get("CODE", "") if isinstance(result, dict) else ""
            if code == "INFO-200":
                if rows:
                    raise DataError(
                        "ECOS 자료가 중간에 누락됐습니다. 기간이나 인증키를 확인하세요."
                    )
                raise NoDataError("선택한 기간에 ECOS 관측값이 없습니다.")
            raise FetchError("ECOS 인증키·조회 권한·호출 한도를 확인하세요.")
        block = payload.get(service)
        if not isinstance(block, dict):
            raise DataError("ECOS 응답에 요청한 통계가 없습니다.")
        try:
            total = int(block["list_total_count"])
            page = block["row"]
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                raise ValueError
            if total < 0 or total > 100000 or len(page) > page_size:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise DataError("ECOS 응답의 건수 또는 행 형식이 올바르지 않습니다.") from None
        if not page:
            raise NoDataError("선택한 기간에 ECOS 관측값이 없습니다.")
        if start > 1 and page == rows[-len(page) :]:
            raise DataError("ECOS가 같은 페이지를 반복 반환했습니다.")
        rows.extend(page)
        if len(rows) >= total:
            if len(rows) != total:
                raise DataError("ECOS 전체 건수가 응답과 일치하지 않습니다.")
            return rows
        if key == "sample":
            raise DataError(
                "ECOS 예제키는 10건까지만 조회할 수 있습니다. 정식 인증키를 입력하세요."
            )
        if len(page) != page_size:
            raise DataError(
                "ECOS 전체 자료를 확보하지 못했습니다. 정식 인증키와 조회 범위를 확인하세요."
            )
    raise DataError("ECOS 자료가 너무 많습니다. 기간을 나누어 조회하세요.")


def discover_ecos_rates(*, api_key=None, timeout=20, attempts=2) -> list[RateSeries]:
    """List all native daily policy/market and monthly bank-rate items."""
    key = _ecos_key(api_key)
    series = {s.id: s for s in RATE_SERIES.values() if s.source == "ECOS"}
    identities = {(s.table, s.item, s.frequency) for s in series.values()}
    for table, (prefix, category, cycle) in ECOS_TABLES.items():
        rows = _ecos_rows("StatisticItemList", table, key, timeout, attempts)
        for row in rows:
            if row.get("GRP_CODE") != "Group1" or row.get("CYCLE") != cycle:
                continue
            if row.get("UNIT_NAME") not in {"연%", "연리%", "%"}:
                continue
            item = str(row.get("ITEM_CODE", ""))
            if not re.fullmatch(r"[A-Za-z0-9]+", item):
                continue
            frequency = "daily" if cycle == "D" else "monthly"
            if (table, item, frequency) in identities:
                continue
            identifier = f"ECOS_{table}_{item}_{cycle}"
            series[identifier] = RateSeries(
                identifier,
                f"{prefix} · {row['ITEM_NAME']}",
                "KR",
                "ECOS",
                category,
                frequency,
                table,
                item,
                table == "722Y001",
            )
            identities.add((table, item, frequency))
    return list(series.values())


def _fred_frame(body, series):
    if not body.strip():
        raise NoDataError("선택한 기간에 FRED 관측값이 없습니다. 조회 기간을 넓혀 보세요.")
    try:
        if body.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                files = [f for f in archive.infolist() if f.filename.lower().endswith(".csv")]
                if len(files) != 1 or files[0].file_size > MAX_BYTES:
                    raise ValueError
                body = archive.read(files[0])
        raw = pd.read_csv(io.StringIO(body.decode("utf-8-sig")), dtype=str, keep_default_na=False)
    except (ValueError, UnicodeError, zipfile.BadZipFile, pd.errors.ParserError):
        raise DataError("FRED가 예상한 CSV 자료를 반환하지 않았습니다.") from None
    date_column = "observation_date" if "observation_date" in raw else "DATE"
    if date_column not in raw or series.id not in raw:
        raise DataError("FRED CSV에 요청한 금리 코드와 날짜 열이 없습니다.")
    return raw[[date_column, series.id]].set_axis(["date", "rate"], axis=1)


def _normalise(raw, request):
    dates = raw["date"].astype(str).str.strip()
    parsed = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any() or not dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise DataError("금리 자료에 해석할 수 없는 관측일이 있습니다.")
    values = raw["rate"].astype(str).str.strip()
    missing = values.isin(["", ".", "NA", "N/A", "NaN", "nan", "None"])
    numeric = pd.to_numeric(values.mask(missing), errors="coerce")
    if (numeric.isna() & ~missing).any() or numeric.isin([float("inf"), float("-inf")]).any():
        raise DataError("금리 자료에 숫자가 아닌 값이나 무한대가 있습니다.")
    frame = pd.DataFrame({"date": dates, "rate": numeric})
    frame = frame.loc[frame["date"].between(request.start, request.end)].copy()
    duplicates = int(frame.duplicated("date", keep="last").sum())
    frame = frame.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    if frame.empty or not frame["rate"].notna().any():
        raise NoDataError("선택한 기간에 유효한 금리 관측값이 없습니다. 기간과 지표를 확인하세요.")
    s = request.series
    for key, value in (
        ("series_id", s.id),
        ("series_name", s.name),
        ("country", s.country),
        ("unit", "percent"),
        ("frequency", s.frequency),
        ("source", s.source),
    ):
        frame[key] = value
    return frame[RATE_COLUMNS].reset_index(drop=True), duplicates


def fetch_rates(
    series: str | RateSeries, *, start: str, end: str, ecos_api_key=None, timeout=15, attempts=3
) -> RateHistory:
    """Fetch native observations; both start and end are inclusive."""
    s = resolve_series(series)
    request = RateRequest(s, start, end)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive.")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise ValueError("attempts must be an integer between 1 and 5.")
    if s.source == "FRED":
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(
            {"id": s.id, "cosd": start, "coed": end}
        )
        raw = _fred_frame(_download(url, "FRED", timeout, attempts), s)
    else:
        cycle = "M" if s.frequency == "monthly" else "D"
        first, last = start.replace("-", ""), end.replace("-", "")
        if cycle == "M":
            first, last = first[:6], last[:6]
        rows = _ecos_rows(
            "StatisticSearch",
            f"{s.table}/{cycle}/{first}/{last}/{s.item}",
            _ecos_key(ecos_api_key),
            timeout,
            attempts,
        )
        records = []
        for row in rows:
            stamp = str(row.get("TIME", ""))
            if (
                row.get("STAT_CODE") != s.table
                or row.get("ITEM_CODE1") != s.item
                or row.get("UNIT_NAME") not in {"연%", "연리%", "%"}
            ):
                raise DataError("ECOS 응답의 통계 항목 또는 단위가 요청과 다릅니다.")
            if not re.fullmatch(r"\d{6}" if cycle == "M" else r"\d{8}", stamp):
                raise DataError("ECOS 관측일 형식이 올바르지 않습니다.")
            day = f"{stamp[:4]}-{stamp[4:6]}-" + ("01" if cycle == "M" else stamp[6:8])
            records.append({"date": day, "rate": row.get("DATA_VALUE", "")})
        raw = pd.DataFrame(records, columns=["date", "rate"])
    frame, duplicates = _normalise(raw, request)
    return RateHistory(
        frame,
        {
            "schema_version": 1,
            "dataset": "interest_rates",
            "source": s.source,
            "series_id": s.id,
            "series_name": s.name,
            "source_url": s.url,
            "country": s.country,
            "unit": "percent",
            "frequency": s.frequency,
            "provider_table": s.table,
            "provider_item": s.item,
            "policy": s.policy,
            "request": {"start": start, "end_inclusive": end},
            "date_convention": "observation_period_start"
            if s.frequency == "monthly"
            else "provider_observation_date",
            "publication_time_known": False,
            "vintage": "latest_available_at_retrieval",
            "missing_values_filled": False,
            "missing_values": int(frame["rate"].isna().sum()),
            "duplicate_rows_removed": duplicates,
            "row_count": len(frame),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def collect_rates(series, *, start, end, ecos_api_key=None, cancel=None, progress=None):
    """Keep successful series when another provider fails; never truncate history."""
    chosen = list({s.id: s for s in map(resolve_series, series)}.values())
    if not chosen:
        raise ValueError("조회할 금리를 하나 이상 선택하세요.")
    RateRequest(chosen[0], start, end)
    cancel = cancel or threading.Event()
    histories, errors = {}, {}

    def work(s):
        if cancel.is_set():
            raise FetchError("취소됨")
        return fetch_rates(s, start=start, end=end, ecos_api_key=ecos_api_key)

    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(work, s): s for s in chosen}
        for count, future in enumerate(as_completed(pending), 1):
            s = pending[future]
            try:
                histories[s.id] = future.result()
            except (FetchError, ValueError) as exc:
                errors[s.id] = str(exc)
            if progress:
                progress(f"금리 {count}/{len(chosen)} 확인 · {s.name}")
    if not histories:
        if len(chosen) == 1:
            raise FetchError(next(iter(errors.values())))
        raise FetchError("금리 조회에 실패했습니다. 네트워크·기간·ECOS 인증키를 확인하세요.")
    ordered = [histories[s.id] for s in chosen if s.id in histories]
    frame = (
        pd.concat([h.data for h in ordered], ignore_index=True)
        .sort_values(["date", "series_id"], kind="stable")
        .reset_index(drop=True)
    )
    return RateHistory(
        frame,
        {
            "schema_version": 1,
            "dataset": "interest_rates",
            "unit": "percent",
            "request": {"start": start, "end_inclusive": end, "series_ids": [s.id for s in chosen]},
            "series": [h.metadata for h in ordered],
            "errors": errors,
            "cancelled": cancel.is_set(),
            "row_count": len(frame),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    )
