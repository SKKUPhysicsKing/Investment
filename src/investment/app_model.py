"""GUI-facing date semantics and exports, independent of the desktop toolkit."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .market import HistoryRequest, PriceHistory, fetch_prices
from .search import Company
from .storage import save_csv


def inclusive_request(symbol: str, start: str, end: str, interval: str) -> HistoryRequest:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", end
        ):
            raise ValueError
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if last < first:
            raise ValueError("종료일은 시작일과 같거나 이후여야 합니다.")
        exclusive_end = last + timedelta(days=1)
    except (ValueError, OverflowError) as exc:
        raise ValueError("날짜를 YYYY-MM-DD로 입력하고 시작일 ≤ 종료일인지 확인하세요.") from exc
    return HistoryRequest(symbol, first, exclusive_end, interval=interval)


def load_company(company: Company, start: str, end: str, interval: str) -> PriceHistory:
    request = inclusive_request(company.symbol, start, end, interval)
    history = fetch_prices(
        company.symbol, start=request.start, end=request.end, interval=request.interval
    )
    history.metadata["company_name"] = company.name
    history.metadata["ui_requested_dates"] = {"start": start, "end_inclusive": end}
    return history


def plot_times(history: PriceHistory) -> pd.Series:
    if history.metadata["interval"] in ("1d", "5d", "1wk", "1mo", "3mo"):
        return pd.to_datetime(history.data["date"])
    # Display intraday bars on their exchange clock, keeping the CSV in UTC.
    timezone_name = history.metadata.get("exchange_timezone") or "UTC"
    return history.data["timestamp"].dt.tz_convert(timezone_name).dt.tz_localize(None)


def export_history(history: PriceHistory, data_dir: Path) -> tuple[Path, Path]:
    symbol = re.sub(r"[^A-Za-z0-9._-]", "_", history.metadata["symbol"])
    first, last = history.data["date"].iloc[[0, -1]]
    stem = f"{symbol}_{first}_{last}_{history.metadata['interval']}"
    # Export exactly the loaded history. Never silently overwrite an earlier export.
    for number in range(1, 10000):
        suffix = "" if number == 1 else f"_{number}"
        target = data_dir / f"{stem}{suffix}.csv"
        try:
            return save_csv(history, target)
        except FileExistsError:
            continue
    raise OSError("같은 이름의 내보내기 파일이 너무 많습니다.")
