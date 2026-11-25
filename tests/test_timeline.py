from copy import deepcopy

import pandas as pd

from investment.news import make_item
from investment.search import Company
from investment.timeline import category, group_events, query_for_history

COMPANY = Company("AAPL", "Apple", "NASDAQ", "Yahoo")


def news(title, day, *, source="Yahoo", precision=None):
    item = make_item(
        COMPANY, source, title, day, "https://example.com/" + title, tz="America/New_York"
    )
    if precision:
        item.time_precision = precision
    return item


def test_daily_track_groups_by_date_and_type_without_dropping_articles(history):
    items = [
        news("Apple product launch", "2024-01-02T15:00:00Z"),
        news("Apple research update", "2024-01-02T12:00:00Z"),
        news("Apple earnings", "2024-01-02", source="SEC"),
        news("Apple filing", "2024-01-02", source="SEC"),
    ]
    groups = group_events(items, history)
    assert [group.kind for group in groups] == ["earnings", "filing", "news"]
    assert len(groups[-1].items) == 2
    assert groups[-1].items[0].title == "Apple research update"
    assert all(group.x == pd.Timestamp("2024-01-02") for group in groups)
    assert sum(len(group.items) for group in groups) == len(items)


def test_requested_weekend_news_is_not_lost_after_last_stock_bar(history):
    history.metadata["ui_requested_dates"] = {"start": "2024-01-01", "end_inclusive": "2024-01-07"}
    item = news("Apple Sunday announcement", "2024-01-07")
    groups = group_events([item], history)
    assert len(groups) == 1 and groups[0].x == pd.Timestamp("2024-01-07")
    assert history.data["date"].iloc[-1] == "2024-01-03"


def test_unrelated_company_and_outside_requested_range_are_excluded(history):
    other = news("Other company", "2024-01-02")
    other.symbol = "MSFT"
    assert not group_events([other, news("Apple later", "2024-01-04")], history)


def test_intraday_preserves_exchange_clock_and_date_only_uncertainty(history):
    history.metadata["interval"] = "5m"
    known = news("Apple earnings release", "2024-01-03T01:30:00Z")
    unknown = news("Apple filing", "2024-01-02", source="SEC")
    groups = group_events([known, unknown], history)
    assert groups[0].x == pd.Timestamp("2024-01-02")
    assert groups[0].end == pd.Timestamp("2024-01-03")
    assert groups[1].x == pd.Timestamp("2024-01-02 20:30:00")
    assert groups[1].end is None
    assert unknown.published_at == "" and unknown.time_precision == "day"


def test_filter_and_query_come_from_the_loaded_chart_snapshot(history):
    groups = group_events(
        [news("Apple earnings", "2024-01-02"), news("Apple product", "2024-01-02")], history, "실적"
    )
    assert len(groups) == 1 and groups[0].kind == "earnings"
    query = query_for_history(history)
    assert (query.company.symbol, query.start, query.end, query.timezone) == (
        "AAPL",
        "2024-01-02",
        "2024-01-03",
        "America/New_York",
    )


def test_sec_and_dart_are_filings_even_if_their_specific_type_is_legal():
    item = news("Apple legal report", "2024-01-02", source="SEC")
    item.event_type = "legal"
    assert category(item) == "filing"
    item.event_type = "earnings"
    assert category(item) == "earnings"


def test_track_rendering_does_not_mutate_collected_timestamps(history):
    item = news("Apple announcement", "2024-01-03T01:30:00Z")
    before = deepcopy(item)
    group_events([item], history)
    assert item == before
