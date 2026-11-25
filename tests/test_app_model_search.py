import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from investment.app_model import export_history, inclusive_request, load_company, plot_times
from investment.search import (
    Company,
    SearchError,
    korean_companies,
    parse_kind_table,
    search_companies,
)

KIND_HTML = """<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th></tr>
<tr><td>삼성전자</td><td>유가</td><td>005930</td></tr>
<tr><td>삼성전기</td><td>유가</td><td>009150</td></tr>
<tr><td>에코프로비엠</td><td>코스닥</td><td>247540</td></tr>
<tr><td>코넥스기업</td><td>코넥스</td><td>123456</td></tr></table>""".encode("euc-kr")


def test_inclusive_end_and_single_trading_day():
    result = inclusive_request("AAPL", "2024-02-29", "2024-02-29", "1d")
    assert (result.start, result.end) == ("2024-02-29", "2024-03-01")


@pytest.mark.parametrize(
    "first,last",
    [("20240101", "2024-01-02"), ("2024-02-30", "2024-03-01"), ("2024-01-03", "2024-01-02")],
)
def test_invalid_date_ranges(first, last):
    with pytest.raises(ValueError):
        inclusive_request("AAPL", first, last, "1d")


def test_load_captures_company_and_inclusive_dates(monkeypatch, history):
    fetch = Mock(return_value=history)
    monkeypatch.setattr("investment.app_model.fetch_prices", fetch)
    result = load_company(
        Company("AAPL", "Apple Inc.", "NASDAQ", "Yahoo"), "2024-01-02", "2024-01-03", "1d"
    )
    assert fetch.call_args.kwargs["end"] == "2024-01-04"
    assert result.metadata["company_name"] == "Apple Inc."
    assert result.metadata["ui_requested_dates"]["end_inclusive"] == "2024-01-03"


def test_plot_day_labels_and_intraday_exchange_clock(history):
    history.data["timestamp"] = pd.to_datetime(["2024-01-01T15:00Z", "2024-01-02T15:00Z"])
    history.metadata["exchange_timezone"] = "Asia/Seoul"
    assert plot_times(history).iloc[0] == pd.Timestamp("2024-01-02")
    history.metadata["interval"] = "5m"
    assert plot_times(history).iloc[0] == pd.Timestamp("2024-01-02")


def test_export_uses_loaded_data_and_never_overwrites(history, tmp_path):
    data_dir = tmp_path / "data"
    first, sidecar = export_history(history, data_dir)
    second, _ = export_history(history, data_dir)
    assert first.parent == second.parent == data_dir
    assert first != second
    assert sidecar.exists()
    assert pd.read_csv(first)["close"].tolist() == history.data["close"].tolist()


def test_kind_exchange_suffixes_and_leading_zeros():
    companies = parse_kind_table(KIND_HTML)
    assert [(c.name, c.symbol) for c in companies] == [
        ("삼성전자", "005930.KS"),
        ("삼성전기", "009150.KS"),
        ("에코프로비엠", "247540.KQ"),
    ]


def test_korean_search_matches_names_without_yahoo(monkeypatch, tmp_path):
    response = SimpleNamespace(content=KIND_HTML, raise_for_status=lambda: None)
    request = Mock(return_value=response)
    yahoo = Mock(side_effect=AssertionError("Korean search should use KRX"))
    monkeypatch.setattr("investment.search.requests.get", request)
    monkeypatch.setattr("investment.search.yf.Search", yahoo)
    result = search_companies("삼성 전자", tmp_path)
    assert result.companies[0].symbol == "005930.KS"
    assert search_companies("005930", tmp_path).companies[0].symbol == "005930.KS"
    assert request.call_count == 1  # Subsequent searches use the disk cache.


def test_stale_cache_survives_krx_outage(monkeypatch, tmp_path):
    saved_at = datetime.now(timezone.utc) - timedelta(days=10)
    (tmp_path / "companies.json").write_text(
        json.dumps(
            {
                "saved_at": saved_at.isoformat(),
                "companies": [
                    {"symbol": "005930.KS", "name": "삼성전자", "exchange": "유가", "source": "KRX"}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("investment.search.requests.get", Mock(side_effect=TimeoutError("offline")))
    companies, notice = korean_companies(tmp_path)
    assert companies[0].symbol == "005930.KS"
    assert "이전" in notice


def test_no_cache_and_network_failure_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr("investment.search.requests.get", Mock(side_effect=TimeoutError("offline")))
    with pytest.raises(SearchError, match="목록"):
        search_companies("삼성전자", tmp_path)


def test_foreign_name_alias_and_derivative_filtering(monkeypatch, tmp_path):
    search = Mock(
        return_value=SimpleNamespace(
            quotes=[
                {
                    "symbol": "AAPL",
                    "longname": "Apple Inc.",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                },
                {"symbol": "AAPL", "shortname": "Apple", "quoteType": "EQUITY"},
                {"symbol": "SAAPL=F", "shortname": "Apple futures", "quoteType": "FUTURE"},
            ]
        )
    )
    monkeypatch.setattr("investment.search.yf.Search", search)
    result = search_companies("애플", tmp_path)
    assert search.call_args.args == ("Apple",)
    assert [c.symbol for c in result.companies] == ["AAPL"]
    assert result.companies[0].name == "Apple Inc."
