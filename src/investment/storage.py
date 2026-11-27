"""CSV snapshots with provenance and a deduplicated SQLite price history."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .market import PRICE_COLUMNS, PriceHistory


class Snapshot(Protocol):
    data: pd.DataFrame
    metadata: dict[str, Any]


def save_csv(history: Snapshot, path: str | Path, *, overwrite: bool = False) -> tuple[Path, Path]:
    """Write an Excel-friendly CSV and a JSON provenance sidecar.

    Each file is replaced atomically. The two-file pair is not one transaction.
    Existing data or sidecar files require explicit overwrite=True.
    """
    target = Path(path)
    if target.suffix.lower() != ".csv":
        raise ValueError("The output filename must end with .csv.")
    sidecar = target.with_suffix(target.suffix + ".metadata.json")
    for destination in (target, sidecar):
        if destination.exists() and not overwrite:
            raise FileExistsError(f"File exists: {destination}. Use --overwrite to replace it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    export = history.data.copy()
    if "timestamp" in export:
        export["timestamp"] = export["timestamp"].map(
            lambda value: value.isoformat() if not pd.isna(value) else ""
        )
    pending: list[tuple[Path, Path]] = []
    try:
        for destination, content, encoding in (
            (target, export.to_csv(index=False, lineterminator="\n"), "utf-8-sig"),
            (sidecar, json.dumps(history.metadata, ensure_ascii=False, indent=2) + "\n", "utf-8"),
        ):
            with tempfile.NamedTemporaryFile(
                mode="w", encoding=encoding, newline="", dir=target.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                pending.append((temporary, destination))
                handle.write(content)
        for temporary, destination in pending:
            if overwrite:
                os.replace(temporary, destination)
            else:
                # A concurrent writer must not silently overwrite another snapshot.
                try:
                    os.link(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
    finally:
        for temporary, _ in pending:
            temporary.unlink(missing_ok=True)
    return target, sidecar


def save_sqlite(history: PriceHistory, path: str | Path) -> int:
    """Upsert bars, preserving separate sources, intervals, and session policies."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    meta = history.metadata
    columns = [
        "source",
        "interval",
        "prepost",
        *PRICE_COLUMNS,
        "currency",
        "exchange_timezone",
        "retrieved_at",
    ]
    keys = {"source", "interval", "prepost", "symbol", "timestamp"}
    updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column not in keys)
    statement = (
        f"INSERT INTO prices ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        "ON CONFLICT(source, symbol, interval, prepost, timestamp) DO UPDATE SET " + updates
    )

    def sql_value(value):
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        return value.item() if hasattr(value, "item") else value

    rows = [
        (
            meta["source"],
            meta["interval"],
            int(meta["prepost"]),
            *(sql_value(value) for value in row),
            meta["currency"],
            meta["exchange_timezone"],
            meta["retrieved_at"],
        )
        for row in history.data[PRICE_COLUMNS].itertuples(index=False, name=None)
    ]
    with closing(sqlite3.connect(target, timeout=30)) as connection, connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS prices (
                source TEXT NOT NULL,
                interval TEXT NOT NULL,
                prepost INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                adj_close REAL,
                volume INTEGER,
                dividends REAL,
                stock_splits REAL,
                currency TEXT,
                exchange_timezone TEXT,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (source, symbol, interval, prepost, timestamp)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS fetch_runs (
                id INTEGER PRIMARY KEY,
                retrieved_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )"""
        )
        connection.executemany(statement, rows)
        connection.execute(
            "INSERT INTO fetch_runs (retrieved_at, metadata_json) VALUES (?, ?)",
            (meta["retrieved_at"], json.dumps(meta, ensure_ascii=False)),
        )
    return len(rows)
