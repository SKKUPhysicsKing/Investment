"""Command-line entry point for downloading one company's price history."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from .market import INTERVALS, PERIODS, FetchError, fetch_prices
from .storage import save_csv, save_sqlite


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download stock price time series from Yahoo Finance."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser("fetch", help="Download one ticker's price history")
    fetch.add_argument("symbol", help="Yahoo ticker, e.g. AAPL, MSFT, 005930.KS, 247540.KQ")
    fetch.add_argument("--start", help="First exchange-local date, inclusive (YYYY-MM-DD)")
    fetch.add_argument("--end", help="End exchange-local date, exclusive (YYYY-MM-DD)")
    fetch.add_argument("--period", choices=PERIODS, help="Lookback; default 1y without --start")
    fetch.add_argument("--interval", choices=INTERVALS, default="1d", help="Bar size; default 1d")
    fetch.add_argument("--prepost", action="store_true", help="Include pre/post-market bars")
    fetch.add_argument(
        "-o", "--output", type=Path, help="CSV path; default data/SYMBOL_INTERVAL.csv"
    )
    fetch.add_argument("--db", type=Path, help="Also upsert bars into a SQLite database")
    fetch.add_argument(
        "--overwrite", action="store_true", help="Replace existing CSV/metadata files"
    )
    fetch.add_argument("--timeout", type=float, default=15, help="Per-request timeout in seconds")
    fetch.add_argument("--attempts", type=int, default=3, help="Provider attempts, 1-5; default 3")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        history = fetch_prices(
            args.symbol,
            start=args.start,
            end=args.end,
            period=args.period,
            interval=args.interval,
            prepost=args.prepost,
            timeout=args.timeout,
            attempts=args.attempts,
        )
        symbol = history.metadata["symbol"]
        interval = history.metadata["interval"]
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", symbol)
        target = args.output or Path("data") / f"{safe_name}_{interval}.csv"
        csv_path, metadata_path = save_csv(history, target, overwrite=args.overwrite)
        print(f"Saved {len(history.data)} bars for {symbol} ({interval}) -> {csv_path}")
        print(f"Metadata -> {metadata_path}")
        if args.db:
            rows = save_sqlite(history, args.db)
            print(f"Upserted {rows} bars -> {args.db}")
        return 0
    except (FetchError, ValueError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
