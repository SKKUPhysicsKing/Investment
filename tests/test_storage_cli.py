import json
import sqlite3

import pandas as pd
import pytest

from investment import NoDataError, PriceHistory, save_csv, save_sqlite
from investment.cli import main


def test_csv_round_trip_and_metadata(history, tmp_path):
    target, sidecar = save_csv(history, tmp_path / "nested" / "aapl.csv")
    frame = pd.read_csv(target)
    assert len(frame) == 2
    assert frame["timestamp"].iloc[0] == "2024-01-02T05:00:00+00:00"
    assert frame["close"].tolist() == [102.0, 103.0]
    assert frame["adj_close"].tolist() == [98.0, 99.0]
    assert json.loads(sidecar.read_text())["currency"] == "USD"
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_existing_snapshot_or_sidecar_requires_overwrite(history, tmp_path):
    target, sidecar = save_csv(history, tmp_path / "aapl.csv")
    original = target.read_bytes()
    history.data.loc[0, "close"] = 999.0
    with pytest.raises(FileExistsError):
        save_csv(history, target)
    assert target.read_bytes() == original
    save_csv(history, target, overwrite=True)
    assert pd.read_csv(target)["close"].iloc[0] == 999.0
    target.unlink()
    with pytest.raises(FileExistsError):
        save_csv(history, target)
    assert sidecar.exists()
    assert not target.exists()


def test_csv_missing_values_round_trip(history, tmp_path):
    history.data["adj_close"] = float("nan")
    history.data["volume"] = pd.Series([pd.NA, 5678], dtype="Int64")
    path, _ = save_csv(history, tmp_path / "missing.csv")
    data = pd.read_csv(path)
    assert data["adj_close"].isna().all()
    assert pd.isna(data["volume"].iloc[0])


def test_sqlite_repeated_fetch_updates_without_duplicates(history, tmp_path):
    path = tmp_path / "prices.sqlite"
    assert save_sqlite(history, path) == 2
    history.data.loc[0, "close"] = 102.5
    history.data.loc[0, "adj_close"] = float("nan")
    history.data.loc[0, "volume"] = pd.NA
    save_sqlite(history, path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM prices").fetchone()[0] == 2
        row = db.execute(
            "SELECT close, adj_close, volume FROM prices ORDER BY timestamp"
        ).fetchone()
        assert row == (102.5, None, None)
        assert db.execute("SELECT count(*) FROM fetch_runs").fetchone()[0] == 2


def test_sqlite_separates_intervals_symbols_and_sessions(history, tmp_path):
    path = tmp_path / "prices.sqlite"
    save_sqlite(history, path)
    hourly = PriceHistory(history.data.copy(), history.metadata | {"interval": "1h"})
    save_sqlite(hourly, path)
    extended = PriceHistory(history.data.copy(), history.metadata | {"prepost": True})
    save_sqlite(extended, path)
    other = PriceHistory(history.data.assign(symbol="MSFT"), history.metadata | {"symbol": "MSFT"})
    save_sqlite(other, path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM prices").fetchone()[0] == 8


def test_cli_success_writes_csv_and_db(monkeypatch, history, tmp_path, capsys):
    monkeypatch.setattr("investment.cli.fetch_prices", lambda *args, **kwargs: history)
    output, database = tmp_path / "aapl.csv", tmp_path / "prices.sqlite"
    assert main(["fetch", "AAPL", "--output", str(output), "--db", str(database)]) == 0
    assert output.exists() and database.exists()
    assert "Saved 2 bars" in capsys.readouterr().out


def test_cli_error_creates_no_files(monkeypatch, tmp_path, capsys):
    def fail(*args, **kwargs):
        raise NoDataError("No prices for the requested ticker.")

    monkeypatch.setattr("investment.cli.fetch_prices", fail)
    output = tmp_path / "aapl.csv"
    assert main(["fetch", "UNKNOWN", "-o", str(output)]) == 2
    assert not output.exists()
    assert "Error:" in capsys.readouterr().err


def test_cli_refuses_existing_csv(monkeypatch, history, tmp_path, capsys):
    monkeypatch.setattr("investment.cli.fetch_prices", lambda *args, **kwargs: history)
    path = tmp_path / "aapl.csv"
    path.write_text("keep this")
    assert main(["fetch", "AAPL", "-o", str(path)]) == 2
    assert path.read_text() == "keep this"
    assert "--overwrite" in capsys.readouterr().err
