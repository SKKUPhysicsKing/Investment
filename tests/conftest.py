import pandas as pd
import pytest

from investment import PriceHistory


@pytest.fixture
def raw_history():
    index = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], tz="America/New_York")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [103.0, 104.0],
            "Low": [99.0, 100.0],
            "Close": [102.0, 103.0],
            "Adj Close": [98.0, 99.0],
            "Volume": [1234, 5678],
            "Dividends": [0.0, 0.25],
            "Stock Splits": [0.0, 0.0],
        },
        index=index,
    )


@pytest.fixture
def history(raw_history):
    from investment.market import HistoryRequest, normalize_history

    data, _ = normalize_history(raw_history, HistoryRequest("AAPL"))
    return PriceHistory(
        data,
        {
            "source": "yahoo",
            "symbol": "AAPL",
            "interval": "1d",
            "prepost": False,
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "retrieved_at": "2024-01-04T00:00:00+00:00",
            "row_count": 2,
        },
    )


@pytest.fixture
def rate_history():
    from investment.rates import RATE_COLUMNS, RateHistory

    rows, series = [], []
    for identifier, name, values in (
        ("DFF", "미국 실효 연방기금금리", [5.33, 5.33]),
        ("DGS10", "미국 국채 10년", [3.95, 3.91]),
    ):
        for day, value in zip(("2024-01-02", "2024-01-03"), values, strict=True):
            rows.append([day, identifier, name, "US", value, "percent", "daily", "FRED"])
        series.append(
            {
                "series_id": identifier,
                "series_name": name,
                "frequency": "daily",
                "source_url": f"https://fred.stlouisfed.org/series/{identifier}",
                "row_count": 2,
            }
        )
    return RateHistory(
        pd.DataFrame(rows, columns=RATE_COLUMNS).sort_values(["date", "series_id"]),
        {
            "series": series,
            "errors": {},
            "request": {"start": "2024-01-02", "end_inclusive": "2024-01-03"},
        },
    )
