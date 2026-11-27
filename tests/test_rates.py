import io
import json
import zipfile
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from investment import DataError, FetchError, NoDataError
from investment.app_model import export_rates
from investment.cli import main
from investment.rates import (
    RATE_COLUMNS,
    RATE_SERIES,
    collect_rates,
    discover_ecos_rates,
    fetch_rates,
)


def csv_response(monkeypatch, body):
    monkeypatch.setattr("investment.rates._download", lambda *args: body)


def test_native_percent_inclusive_dates_missing_and_negative_yields(monkeypatch):
    csv_response(
        monkeypatch,
        b"observation_date,DFII10\n2024-01-05,0\n2024-01-03,.\n"
        b"2024-01-02,-0.25\n2024-01-01,8\n2024-01-04,3.5\n2024-01-06,9\n",
    )
    history = fetch_rates("DFII10", start="2024-01-02", end="2024-01-05")
    assert history.data.columns.tolist() == RATE_COLUMNS
    assert history.data.date.tolist() == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    assert history.data.rate.iloc[0] == -0.25 and history.data.rate.iloc[-1] == 0
    assert history.data.rate.iloc[2] == 3.5
    assert pd.isna(history.data.rate.iloc[1])
    assert history.metadata["missing_values"] == 1
    assert not history.metadata["publication_time_known"]
    assert not history.metadata["missing_values_filled"]


@pytest.mark.parametrize("header", ["DATE", "observation_date"])
@pytest.mark.parametrize("zipped", [False, True])
def test_fred_download_formats_and_single_day(monkeypatch, header, zipped):
    body = f"{header},DGS10\n2024-01-02,3.95\n".encode()
    if zipped:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("DGS10.csv", body)
        body = stream.getvalue()
    csv_response(monkeypatch, body)
    assert fetch_rates("DGS10", start="2024-01-02", end="2024-01-02").data.rate.tolist() == [3.95]


@pytest.mark.parametrize("value", ["inf", "-inf", "broken"])
def test_corrupt_values_are_not_silently_turned_into_missing(monkeypatch, value):
    csv_response(monkeypatch, f"DATE,DFF\n2024-01-02,{value}\n".encode())
    with pytest.raises(DataError):
        fetch_rates("DFF", start="2024-01-02", end="2024-01-02")


@pytest.mark.parametrize("body", [b"<html>error</html>", b"DATE,OTHER\n2024-01-02,3.5\n"])
def test_wrong_series_or_provider_error_page_is_rejected(monkeypatch, body):
    csv_response(monkeypatch, body)
    with pytest.raises(DataError):
        fetch_rates("DFF", start="2024-01-02", end="2024-01-02")


def test_no_data_and_bad_dates_do_not_manufacture_observations(monkeypatch):
    csv_response(monkeypatch, b"DATE,DFF\n2024-01-02,.\n")
    with pytest.raises(NoDataError):
        fetch_rates("DFF", start="2024-01-02", end="2024-01-02")
    csv_response(monkeypatch, b"\n")
    with pytest.raises(NoDataError):
        fetch_rates("DCPN3M", start="2024-01-02", end="2024-01-02")
    monkeypatch.setattr("investment.rates._download", lambda *args: pytest.fail("network used"))
    for first, last in [
        ("bad", "2024-01-02"),
        ("2024-02-30", "2024-03-01"),
        ("2024-02-01", "2024-01-01"),
    ]:
        with pytest.raises(ValueError):
            fetch_rates("DFF", start=first, end=last)


def ecos_row(stamp, value, table="722Y001", item="0101000"):
    return {
        "TIME": stamp,
        "DATA_VALUE": value,
        "STAT_CODE": table,
        "ITEM_CODE1": item,
        "UNIT_NAME": "연%",
    }


def test_ecos_follows_all_pages_and_never_exports_key(monkeypatch, tmp_path):
    monkeypatch.setattr("investment.rates.PAGE_SIZE", 2)
    urls = []

    def download(url, *args):
        urls.append(url)
        rows = [ecos_row("20240102", "3.5"), ecos_row("20240103", "3.5")]
        if "/3/4/" in url:
            rows = [ecos_row("20240104", "3.25")]
        return json.dumps({"StatisticSearch": {"list_total_count": 3, "row": rows}}).encode()

    monkeypatch.setattr("investment.rates._download", download)
    history = fetch_rates(
        "BOK_BASE_RATE", start="2024-01-02", end="2024-01-04", ecos_api_key="private-key"
    )
    assert len(urls) == 2 and "/3/4/" in urls[-1]
    assert history.data.rate.tolist() == [3.5, 3.5, 3.25]
    csv, metadata = export_rates(history, tmp_path)
    assert "private-key" not in metadata.read_text(encoding="utf-8")
    assert "timestamp" not in pd.read_csv(csv)
    assert len(pd.read_csv(csv)) == 3


def test_monthly_rates_keep_period_label_and_frequency(monkeypatch):
    body = {
        "StatisticSearch": {
            "list_total_count": 1,
            "row": [ecos_row("202401", "3.5", "121Y002", "BEABAA2")],
        }
    }
    csv_response(monkeypatch, json.dumps(body).encode())
    history = fetch_rates(
        "ECOS_121Y002_BEABAA2_M", start="2024-01-01", end="2024-01-31", ecos_api_key="private"
    )
    assert history.data.date.tolist() == ["2024-01-01"]
    assert history.metadata["frequency"] == "monthly"
    assert history.metadata["date_convention"] == "observation_period_start"


@pytest.mark.parametrize("code,kind", [("INFO-200", NoDataError), ("INFO-100", FetchError)])
def test_ecos_error_does_not_look_like_success_or_reveal_message(monkeypatch, code, kind):
    csv_response(
        monkeypatch, json.dumps({"RESULT": {"CODE": code, "MESSAGE": "private-key"}}).encode()
    )
    with pytest.raises(kind) as caught:
        fetch_rates(
            "BOK_BASE_RATE", start="2024-01-02", end="2024-01-04", ecos_api_key="private-key"
        )
    assert "private-key" not in str(caught.value)


def test_ecos_transport_exception_redacts_credentials(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("https://ecos.bok.or.kr/api/StatisticSearch/private-key/")

    monkeypatch.setattr("investment.rates.urlopen", fail)
    with pytest.raises(FetchError) as caught:
        fetch_rates(
            "BOK_BASE_RATE",
            start="2024-01-02",
            end="2024-01-04",
            ecos_api_key="private-key",
            attempts=1,
        )
    assert "private-key" not in str(caught.value)


def test_partial_ecos_page_is_not_reported_as_full_history(monkeypatch):
    body = {"StatisticSearch": {"list_total_count": 1001, "row": [ecos_row("20240102", "3.5")]}}
    csv_response(monkeypatch, json.dumps(body).encode())
    with pytest.raises(DataError, match="전체 자료"):
        fetch_rates("BOK_BASE_RATE", start="2024-01-01", end="2024-12-31", ecos_api_key="private")


def test_partial_batch_retains_success_and_provenance(monkeypatch, tmp_path):
    def download(url, *args):
        if "ecos.bok.or.kr" in url:
            raise FetchError("ECOS unavailable")
        code = parse_qs(urlsplit(url).query)["id"][0]
        return f"DATE,{code}\n2024-01-02,3.5\n2024-01-03,3.75\n".encode()

    monkeypatch.setattr("investment.rates._download", download)
    result = collect_rates(
        ["DFF", "DGS10", "BOK_BASE_RATE"],
        start="2024-01-02",
        end="2024-01-03",
        ecos_api_key="private",
    )
    assert len(result.data) == 4
    assert len(result.metadata["series"]) == 2
    assert result.metadata["errors"] == {"BOK_BASE_RATE": "ECOS unavailable"}
    first, _ = export_rates(result, tmp_path)
    second, _ = export_rates(result, tmp_path)
    assert first != second and first.exists()
    assert pd.read_csv(first).rate.tolist() == [3.5, 3.5, 3.75, 3.75]


def test_discovery_uses_rate_tables_native_cycle_and_percent_units(monkeypatch):
    def rows(service, table, *args):
        cycle = "M" if table.startswith("121") else "D"
        return [
            {
                "GRP_CODE": "Group1",
                "CYCLE": cycle,
                "UNIT_NAME": "연%",
                "ITEM_CODE": "NEW",
                "ITEM_NAME": "New rate",
            },
            {
                "GRP_CODE": "Group1",
                "CYCLE": "A",
                "UNIT_NAME": "연%",
                "ITEM_CODE": "ANNUAL",
                "ITEM_NAME": "Annual",
            },
            {
                "GRP_CODE": "Group2",
                "CYCLE": cycle,
                "UNIT_NAME": "연%",
                "ITEM_CODE": "OTHER",
                "ITEM_NAME": "Other",
            },
        ]

    monkeypatch.setattr("investment.rates._ecos_rows", rows)
    found = [s for s in discover_ecos_rates(api_key="private") if s.item == "NEW"]
    assert len(found) == 4
    assert {s.frequency for s in found} == {"daily", "monthly"}


def test_rates_cli_is_usable_without_gui_and_preserves_csv_schema(monkeypatch, tmp_path, capsys):
    csv_response(monkeypatch, b"DATE,DFF\n2024-01-02,3.5\n")
    target = tmp_path / "rates.csv"
    assert (
        main(["rates", "DFF", "--start", "2024-01-02", "--end", "2024-01-02", "-o", str(target)])
        == 0
    )
    assert pd.read_csv(target).columns.tolist() == RATE_COLUMNS
    assert main(["rates", "--list"]) == 0
    assert "BOK_BASE_RATE" in capsys.readouterr().out
    assert "MORTGAGE30US" in RATE_SERIES
