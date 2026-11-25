"""Yahoo Finance adapter and a stable, ascending time-series schema."""

from __future__ import annotations

import math
import re
import time
import warnings
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFInvalidPeriodError, YFPricesMissingError, YFTzMissingError

INTERVALS = ("1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo")
PERIODS = ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max")
PRICE_COLUMNS = [
    "timestamp",
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
]
OHLC = ["open", "high", "low", "close"]


class FetchError(RuntimeError):
    """The provider could not deliver usable prices."""


class NoDataError(FetchError):
    """There are no usable bars for the requested symbol and range."""


class DataError(FetchError):
    """The provider returned an unexpected or ambiguous data shape."""


def _date_string(value: str | date | None, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date, not a datetime; use YYYY-MM-DD.")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value}.") from exc


@dataclass(frozen=True)
class HistoryRequest:
    symbol: str
    start: str | date | None = None
    end: str | date | None = None
    period: str | None = None
    interval: str = "1d"
    prepost: bool = False

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper() if isinstance(self.symbol, str) else ""
        if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=_-]{0,63}", symbol):
            raise ValueError("Use a Yahoo ticker such as AAPL, 005930.KS, or 247540.KQ.")
        start = _date_string(self.start, "start")
        end = _date_string(self.end, "end")
        if end and not start:
            raise ValueError("end requires start.")
        if start and end and start >= end:
            raise ValueError("end must be later than start (end is exclusive).")
        if self.period is not None and (start or end):
            raise ValueError("Choose period OR start/end, not both.")
        period = self.period if self.period is not None else (None if start else "1y")
        if period is not None and period not in PERIODS:
            raise ValueError(f"Unsupported period: {period}. Choose from {', '.join(PERIODS)}.")
        if self.interval not in INTERVALS:
            raise ValueError(f"Unsupported interval: {self.interval}.")
        if not isinstance(self.prepost, bool):
            raise ValueError("prepost must be True or False.")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "period", period)
        object.__setattr__(self, "interval", "1h" if self.interval == "60m" else self.interval)


@dataclass
class PriceHistory:
    data: pd.DataFrame
    metadata: dict[str, Any]


def normalize_history(
    raw: pd.DataFrame, request: HistoryRequest, exchange_timezone: str | None = None
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Keep exchange calendar dates while converting bar timestamps to UTC."""
    if raw.empty:
        raise NoDataError(f"No data for {request.symbol}. Check the ticker and trading dates.")
    required = {"Open", "High", "Low", "Close", "Volume"}
    if isinstance(raw.columns, pd.MultiIndex) or not required.issubset(raw.columns):
        raise DataError("Yahoo response is missing the expected OHLCV columns.")
    if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.hasnans:
        raise DataError("Yahoo response must have valid datetime timestamps.")
    index = raw.index
    if index.tz is None and not exchange_timezone:
        raise DataError("Missing exchange timezone; refusing to guess UTC.")
    try:
        if index.tz is None:
            index = index.tz_localize(exchange_timezone, ambiguous="raise", nonexistent="raise")
        elif exchange_timezone:
            index = index.tz_convert(exchange_timezone)
    except Exception as exc:
        raise DataError(f"Cannot interpret the exchange timezone: {exchange_timezone}.") from exc

    frame = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
            "Dividends": "dividends",
            "Stock Splits": "stock_splits",
        }
    ).copy()
    frame["timestamp"] = index.tz_convert("UTC")
    frame["date"] = index.strftime("%Y-%m-%d")
    frame["symbol"] = request.symbol
    for column in [*OHLC, "adj_close", "volume", "dividends", "stock_splits"]:
        default = 0.0 if column in ("dividends", "stock_splits") else float("nan")
        values = frame[column] if column in frame else pd.Series(default, index=frame.index)
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.isin([float("inf"), float("-inf")]).any():
            raise DataError(f"Non-finite values in {column}.")
        frame[column] = numeric

    missing_prices = frame[OHLC].isna().any(axis=1)
    missing_count = int(missing_prices.sum())
    frame = frame.loc[~missing_prices].copy()
    try:
        frame["volume"] = frame["volume"].astype("Int64")
    except (ValueError, TypeError, OverflowError) as exc:
        raise DataError("Volume must contain integers or missing values.") from exc
    if (frame["volume"].dropna() < 0).any():
        raise DataError("Volume cannot be negative.")
    outside_range = pd.Series(False, index=frame.index)
    if request.start:
        outside_range |= frame["date"] < request.start
    if request.end:
        outside_range |= frame["date"] >= request.end
    outside_count = int(outside_range.sum())
    frame = frame.loc[~outside_range].sort_values("timestamp", kind="stable")
    duplicate_count = int(frame.duplicated("timestamp", keep="last").sum())
    frame = frame.drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise NoDataError(f"No usable prices for {request.symbol} in the requested range.")
    return frame[PRICE_COLUMNS].reset_index(drop=True), {
        "missing_price_rows_removed": missing_count,
        "out_of_range_rows_removed": outside_count,
        "duplicate_rows_removed": duplicate_count,
    }


def fetch_prices(
    symbol: str,
    *,
    start: str | date | None = None,
    end: str | date | None = None,
    period: str | None = None,
    interval: str = "1d",
    prepost: bool = False,
    timeout: float = 15,
    attempts: int = 3,
) -> PriceHistory:
    """Fetch one symbol; start is inclusive, end exclusive in exchange local time.

    OHLC is returned with yfinance auto_adjust=False. Yahoo may still apply its
    own split normalization; adj_close is kept separately as supplied by Yahoo.
    """
    request = HistoryRequest(symbol, start, end, period, interval, prepost)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number.")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise ValueError("attempts must be an integer between 1 and 5.")
    kwargs: dict[str, Any] = {
        "interval": request.interval,
        "prepost": request.prepost,
        "auto_adjust": False,
        "back_adjust": False,
        "actions": True,
        "repair": False,
        "keepna": True,
        "rounding": False,
        "timeout": timeout,
        "raise_errors": True,
    }
    if request.start:
        kwargs["start"] = request.start
        if request.end:
            kwargs["end"] = request.end
    else:
        kwargs["period"] = request.period

    for attempt in range(attempts):
        try:
            ticker = yf.Ticker(request.symbol)
            # The per-call switch avoids changing yfinance's process-wide error policy.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message="'raise_errors' deprecated.*", category=DeprecationWarning
                )
                raw = ticker.history(**kwargs)
            provider_metadata = ticker.history_metadata or {}
            break
        except (YFInvalidPeriodError, YFPricesMissingError, YFTzMissingError) as exc:
            raise NoDataError(
                f"No data for {request.symbol}: {exc}. Check the ticker and dates; "
                "for intraday bars, try a shorter recent period."
            ) from exc
        except Exception as exc:
            if attempt == attempts - 1:
                raise FetchError(
                    f"Yahoo request for {request.symbol} failed after {attempts} attempt(s): "
                    f"{exc}. Check the network or try again later."
                ) from exc
            time.sleep(min(0.5 * 2**attempt, 4))

    timezone_name = provider_metadata.get("exchangeTimezoneName")
    if not timezone_name and isinstance(raw.index, pd.DatetimeIndex) and raw.index.tz is not None:
        timezone_name = str(raw.index.tz)
    frame, cleaning = normalize_history(raw, request, timezone_name)
    metadata = {
        "schema_version": 1,
        "source": "yahoo",
        "client": "yfinance",
        "client_version": yf.__version__,
        "symbol": request.symbol,
        "currency": provider_metadata.get("currency"),
        "exchange_timezone": timezone_name,
        "interval": request.interval,
        "prepost": request.prepost,
        "auto_adjust": False,
        "repair": False,
        "timestamp_timezone": "UTC",
        "date_convention": "exchange_local_bar_date",
        "end_exclusive": True,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "request": asdict(request),
        "row_count": len(frame),
        "first_timestamp": frame["timestamp"].iloc[0].isoformat(),
        "last_timestamp": frame["timestamp"].iloc[-1].isoformat(),
        "cleaning": cleaning,
    }
    return PriceHistory(frame, metadata)
