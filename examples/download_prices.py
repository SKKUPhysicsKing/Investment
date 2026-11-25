"""Run after installation: python examples/download_prices.py."""

from investment import fetch_prices, save_csv, save_sqlite

history = fetch_prices("AAPL", start="2024-01-01", end="2025-01-01")
save_csv(history, "data/AAPL_2024.csv")
save_sqlite(history, "data/prices.sqlite")

# A pandas time series, indexed by timezone-aware UTC timestamps.
close = history.data.set_index("timestamp")["close"]
print(close.head())
print(history.metadata)
