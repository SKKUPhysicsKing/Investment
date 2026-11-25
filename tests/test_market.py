from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from investment import DataError, FetchError, HistoryRequest, NoDataError, fetch_prices
from investment.market import PRICE_COLUMNS, normalize_history


def test_request_defaults_and_canonicalization():
    request = HistoryRequest(" aapl ", interval="60m")
    assert (request.symbol, request.interval, request.period) == ("AAPL", "1h", "1y")
    dates = HistoryRequest("005930.KS", start=date(2024, 1, 1))
    assert dates.start == "2024-01-01"
    assert dates.period is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"symbol": ""},
        {"symbol": "../../AAPL"},
        {"symbol": "삼성전자"},
        {"start": "2024-02-30"},
        {"start": "20240101"},
        {"start": datetime(2024, 1, 1)},
        {"end": "2025-01-01"},
        {"start": "2025-01-01", "end": "2025-01-01"},
        {"start": "2025-01-01", "end": "2024-01-01"},
        {"start": "2024-01-01", "period": "1y"},
        {"period": "forever"},
        {"interval": "3h"},
        {"prepost": "false"},
    ],
)
def test_invalid_requests_fail_before_network(kwargs):
    with pytest.raises(ValueError):
        HistoryRequest(**({"symbol": "AAPL"} | kwargs))


def test_korean_date_is_not_shifted_to_utc_date(raw_history):
    raw_history.index = raw_history.index.tz_localize(None).tz_localize("Asia/Seoul")
    data, _ = normalize_history(raw_history, HistoryRequest("005930.KS"), "Asia/Seoul")
    assert data["date"].iloc[0] == "2024-01-02"
    assert data["timestamp"].iloc[0].isoformat() == "2024-01-01T15:00:00+00:00"
    assert data.columns.tolist() == PRICE_COLUMNS
    assert str(data["volume"].dtype) == "Int64"


def test_dst_and_naive_index_localization(raw_history):
    raw_history.index = pd.DatetimeIndex(["2024-03-08", "2024-03-11"])
    data, _ = normalize_history(raw_history, HistoryRequest("AAPL"), "America/New_York")
    assert data["timestamp"].dt.hour.tolist() == [5, 4]
    assert data["date"].tolist() == ["2024-03-08", "2024-03-11"]


def test_unsorted_duplicates_keep_last_revision(raw_history):
    revised = raw_history.iloc[[0]].copy()
    revised["Close"] = 102.5
    raw = pd.concat([raw_history.iloc[[1]], raw_history.iloc[[0]], revised])
    data, cleaning = normalize_history(raw, HistoryRequest("AAPL"))
    assert data["timestamp"].is_monotonic_increasing
    assert data["close"].tolist() == [102.5, 103.0]
    assert cleaning["duplicate_rows_removed"] == 1


def test_exclusive_end_date_filters_provider_overrun(raw_history):
    request = HistoryRequest("AAPL", start="2024-01-02", end="2024-01-03")
    data, cleaning = normalize_history(raw_history, request)
    assert data["date"].tolist() == ["2024-01-02"]
    assert cleaning["out_of_range_rows_removed"] == 1


def test_missing_ohlc_dropped_and_optional_values_not_fabricated(raw_history):
    raw = raw_history.drop(columns=["Adj Close", "Dividends", "Stock Splits"]).copy()
    raw.loc[raw.index[1], "Close"] = float("nan")
    raw.loc[raw.index[0], "Volume"] = float("nan")
    data, cleaning = normalize_history(raw, HistoryRequest("AAPL"))
    assert len(data) == 1
    assert cleaning["missing_price_rows_removed"] == 1
    assert pd.isna(data["adj_close"].iloc[0])
    assert pd.isna(data["volume"].iloc[0])
    assert data["dividends"].iloc[0] == data["stock_splits"].iloc[0] == 0


@pytest.mark.parametrize("volume", [-1, 1.5, float("inf")])
def test_invalid_volume_rejected(raw_history, volume):
    raw_history["Volume"] = raw_history["Volume"].astype(float)
    raw_history.loc[raw_history.index[0], "Volume"] = volume
    with pytest.raises(DataError):
        normalize_history(raw_history, HistoryRequest("AAPL"))


def test_missing_timezone_is_not_assumed_utc(raw_history):
    raw_history.index = raw_history.index.tz_localize(None)
    with pytest.raises(DataError, match="timezone"):
        normalize_history(raw_history, HistoryRequest("AAPL"))


@pytest.mark.parametrize("timestamp", ["2024-11-03 01:30", "2024-03-10 02:30"])
def test_ambiguous_or_nonexistent_local_time_is_rejected(raw_history, timestamp):
    raw_history.index = pd.DatetimeIndex([timestamp, "2024-11-04 09:30"])
    with pytest.raises(DataError, match="timezone"):
        normalize_history(raw_history, HistoryRequest("AAPL"), "America/New_York")


def test_empty_or_missing_columns_fail(raw_history):
    with pytest.raises(NoDataError):
        normalize_history(raw_history.iloc[:0], HistoryRequest("AAPL"))
    with pytest.raises(DataError, match="OHLCV"):
        normalize_history(raw_history.drop(columns=["Close"]), HistoryRequest("AAPL"))


def mock_yahoo(monkeypatch, raw_history):
    ticker = SimpleNamespace(
        history=Mock(return_value=raw_history),
        history_metadata={"currency": "USD", "exchangeTimezoneName": "America/New_York"},
    )
    factory = Mock(return_value=ticker)
    monkeypatch.setattr("investment.market.yf.Ticker", factory)
    return ticker, factory


def test_fetch_explicit_adjustment_and_request_metadata(monkeypatch, raw_history):
    ticker, factory = mock_yahoo(monkeypatch, raw_history)
    history = fetch_prices(" aapl ", start="2024-01-01", end="2024-02-01")
    factory.assert_called_once_with("AAPL")
    kwargs = ticker.history.call_args.kwargs
    assert kwargs["auto_adjust"] is False
    assert kwargs["repair"] is False
    assert kwargs["actions"] is True
    assert kwargs["raise_errors"] is True
    assert "period" not in kwargs
    assert history.metadata["currency"] == "USD"
    assert history.metadata["request"]["end"] == "2024-02-01"
    assert history.metadata["row_count"] == 2


def test_transient_failure_retries_with_backoff(monkeypatch, raw_history):
    ticker, _ = mock_yahoo(monkeypatch, raw_history)
    ticker.history.side_effect = [TimeoutError("timed out"), raw_history]
    sleep = Mock()
    monkeypatch.setattr("investment.market.time.sleep", sleep)
    result = fetch_prices("AAPL", attempts=2)
    assert len(result.data) == 2
    assert ticker.history.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_exhausted_retries_raise_actionable_error(monkeypatch, raw_history):
    ticker, _ = mock_yahoo(monkeypatch, raw_history)
    ticker.history.side_effect = TimeoutError("offline")
    monkeypatch.setattr("investment.market.time.sleep", Mock())
    with pytest.raises(FetchError, match=r"AAPL.*2 attempt.*offline"):
        fetch_prices("AAPL", attempts=2)
    assert ticker.history.call_count == 2


def test_empty_response_is_not_written_or_retried(monkeypatch, raw_history):
    ticker, _ = mock_yahoo(monkeypatch, raw_history.iloc[:0])
    with pytest.raises(NoDataError):
        fetch_prices("AAPL")
    ticker.history.assert_called_once()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempts": 0},
        {"attempts": True},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
    ],
)
def test_invalid_network_settings(kwargs):
    with pytest.raises(ValueError):
        fetch_prices("AAPL", **kwargs)
