import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pandas as pd
import pytest
import requests
from defusedxml.common import EntitiesForbidden

from investment.news import (
    NewsResult,
    NewsStore,
    SourceReport,
    deduplicate,
    export_news,
    make_item,
    parse_time,
)
from investment.news_collect import collect_news, import_archive
from investment.news_content import PublicContent, public_url
from investment.news_providers import (
    NewsQuery,
    NewsSettings,
    SourceContext,
    feed_entries,
    run_source,
)
from investment.search import Company

COMPANY = Company("AAPL", "Apple Inc.", "NASDAQ", "Yahoo")
KOREAN = Company("005930.KS", "삼성전자", "유가", "KRX")


@pytest.fixture
def query():
    return NewsQuery(COMPANY, "2024-01-01", "2024-01-31", "America/New_York")


def item(
    title="Apple beats estimates", day="2024-01-02", source="test", url="https://example.com/a"
):
    return make_item(COMPANY, source, title, day, url, publisher="Example")


def rss_data(count=1, day="Tue, 02 Jan 2024 12:00:00 GMT"):
    return (
        "<rss><channel>"
        + "".join(
            f"<item><title>Apple earnings {i}</title><link>https://example.com/{i}</link>"
            f"<pubDate>{day}</pubDate><source>Example</source></item>"
            for i in range(count)
        )
        + "</channel></rss>"
    ).encode()


def test_date_only_never_gets_a_midnight_timestamp():
    assert parse_time("20240102") == ("", "2024-01-02", "day")
    assert parse_time("2024-01-02") == ("", "2024-01-02", "day")
    assert parse_time("2024-01-02 10:00") == ("", "2024-01-02", "day")
    assert parse_time("not a date") == ("", "", "unknown")


def test_timezones_and_provider_epoch():
    utc, day, precision = parse_time("2024-01-01T23:30Z", "Asia/Seoul")
    assert (utc, day, precision) == ("2024-01-01T23:30:00+00:00", "2024-01-02", "second")
    assert parse_time(1704196800)[0].startswith("2024-01-02T12:00")


def test_keyword_labels_are_conservative_and_keep_mixed_stories():
    assert item().sentiment == "positive"
    assert item("Apple cuts guidance after data breach").sentiment == "negative"
    assert item("Apple beats estimates but cuts guidance").sentiment == "neutral"
    assert item("Apple announces quarterly results").sentiment == "unknown"
    assert item().confidence < 1


def test_dedup_retains_sources_links_and_manual_label():
    first = item(source="Google", url="https://news.google.com/rss/articles/123")
    first.label_method, first.sentiment = "manual", "negative"
    second = item(source="Naver", url="https://example.com/article?utm_source=feed")
    second.summary = "A richer summary"
    result = deduplicate([first, second])
    assert len(result) == 1
    assert result[0].sources == ["Google", "Naver"]
    assert result[0].url == "https://example.com/article"
    assert result[0].sentiment == "negative"
    assert len(result[0].alternate_urls) == 2


def test_filings_and_amendments_have_distinct_ids():
    a = make_item(
        COMPANY, "SEC", "Apple 8-K", "2024-01-02", "https://sec.gov/a", filing=True, record_id="1"
    )
    b = make_item(
        COMPANY, "SEC", "Apple 8-K", "2024-01-02", "https://sec.gov/b", filing=True, record_id="2"
    )
    assert len(deduplicate([a, b])) == 2


def test_store_upsert_cache_union_and_manual_labels_survive(tmp_path):
    store = NewsStore(tmp_path / "news.sqlite")
    original = item()
    store.save(NewsResult("AAPL", "Apple", "2024-01-01", "2024-01-31", [original], []))
    original.sentiment, original.label_method = "negative", "manual"
    store.update_item(original)
    result = NewsResult(
        "AAPL",
        "Apple",
        "2024-01-01",
        "2024-01-31",
        [item(), item("Apple other event", url="https://example.com/b")],
        [],
    )
    store.save(result)
    assert len(result.items) == 2
    assert next(i for i in result.items if i.id == original.id).sentiment == "negative"
    assert len(store.load("MSFT", "2024-01-01", "2024-01-31")) == 0


def test_export_keeps_date_only_blank_and_no_overwrite(tmp_path):
    result = NewsResult(
        "AAPL", "Apple", "2024-01-01", "2024-01-31", [item()], [SourceReport("test")]
    )
    path, meta = export_news(result, tmp_path)
    exported = pd.read_csv(path, keep_default_na=False)
    assert exported["timestamp"].iloc[0] == exported["published_at"].iloc[0] == ""
    assert exported["event_date"].iloc[0] == "2024-01-02"
    assert json.loads(meta.read_text())["sources"][0]["status"] == "sampled"
    assert export_news(result, tmp_path)[0] != path


def test_empty_export_has_headers(tmp_path):
    path, _ = export_news(NewsResult("AAPL", "Apple", "2024-01-01", "2024-01-31", [], []), tmp_path)
    assert "event_date" in pd.read_csv(path).columns


def test_atom_feed_and_entity_expansion_is_rejected():
    raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Apple</title><link href="https://apple.com/a"/><published>2024-01-02T12:00Z</published></entry></feed>'
    assert list(feed_entries(raw))[0]["link"] == "https://apple.com/a"
    with pytest.raises(EntitiesForbidden):
        list(feed_entries(b'<!DOCTYPE x [<!ENTITY evil "oops">]><rss>&evil;</rss>'))


def test_google_adaptive_splitting_and_budget_keeps_partial(monkeypatch, query, tmp_path):
    calls = []

    def response(self, url, **kwargs):
        self.check()
        if self.report.requests == 3:
            from investment.news_providers import StopSource

            self.report.status = "partial"
            raise StopSource
        self.report.requests += 1
        calls.append(kwargs["params"]["q"])
        return rss_data(100)

    monkeypatch.setattr(SourceContext, "get", response)
    items, report = run_source(
        "google", query, NewsSettings(body_limit=0), tmp_path, threading.Event(), lambda _: None
    )
    assert report.status == "partial" and len(items) > 0
    assert len(set(calls)) > 1


def test_provider_limits_filter_out_of_range_data(monkeypatch, query, tmp_path):
    monkeypatch.setattr(
        SourceContext, "get", lambda *args, **kwargs: rss_data(1, "Tue, 02 Jan 2035 12:00:00 GMT")
    )
    items, _ = run_source(
        "google", query, NewsSettings(), tmp_path, threading.Event(), lambda _: None
    )
    assert not items


def test_dart_pagination_retains_data_on_later_failure(monkeypatch, tmp_path):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "CORPCODE.xml",
            "<result><list><stock_code>005930</stock_code><corp_code>00126380</corp_code></list></result>",
        )

    def response(self, url, **kwargs):
        if url.endswith("corpCode.xml"):
            return buffer.getvalue()
        if kwargs["params"]["page_no"] == 2:
            raise RuntimeError("HTTP 429")
        return {
            "status": "000",
            "total_page": 2,
            "list": [
                {
                    "rcept_no": "123",
                    "rcept_dt": "20240102",
                    "report_nm": "삼성전자 영업실적 공정공시",
                }
            ],
        }

    monkeypatch.setattr(SourceContext, "get", response)
    query = NewsQuery(KOREAN, "2024-01-01", "2024-01-31", "Asia/Seoul")
    items, report = run_source(
        "dart", query, NewsSettings(dart_key="secret"), tmp_path, threading.Event(), lambda _: None
    )
    assert len(items) == 1 and report.status == "partial"
    assert items[0].published_at == "" and items[0].event_type == "earnings"


def test_sec_recent_filings_survive_archive_failure(monkeypatch, query, tmp_path):
    def response(self, url, **kwargs):
        if "company_tickers" in url:
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}
        if "CIK0000320193.json" in url:
            return {
                "filings": {
                    "recent": {
                        "accessionNumber": ["0001-24-01"],
                        "form": ["8-K"],
                        "items": ["2.02"],
                        "filingDate": ["2024-01-02"],
                        "primaryDocument": ["earnings.htm"],
                    },
                    "files": [
                        {"name": "older.json", "filingFrom": "2024-01-01", "filingTo": "2024-01-31"}
                    ],
                }
            }
        raise RuntimeError("HTTP 403")

    monkeypatch.setattr(SourceContext, "get", response)
    items, report = run_source(
        "sec",
        query,
        NewsSettings(sec_contact="person@example.org"),
        tmp_path,
        threading.Event(),
        lambda _: None,
    )
    assert len(items) == 1 and items[0].event_type == "earnings" and report.status == "partial"


@pytest.mark.parametrize("key", ["dart", "naver", "sec", "finnhub", "alpha"])
def test_missing_credentials_reported_without_network(monkeypatch, query, tmp_path, key):
    request = Mock(side_effect=AssertionError("must not request"))
    monkeypatch.setattr(SourceContext, "get", request)
    _, report = run_source(key, query, NewsSettings(), tmp_path, threading.Event(), lambda _: None)
    assert report.status == "not_configured"
    request.assert_not_called()


def test_sensitive_errors_are_redacted(monkeypatch, query, tmp_path):
    monkeypatch.setattr(SourceContext, "get", Mock(side_effect=RuntimeError("bad key VERYSECRET")))
    _, report = run_source(
        "finnhub",
        query,
        NewsSettings(finnhub_key="VERYSECRET"),
        tmp_path,
        threading.Event(),
        lambda _: None,
    )
    assert "VERYSECRET" not in report.message


def test_official_rss_accepts_company_products_without_company_in_title(
    monkeypatch, query, tmp_path
):
    monkeypatch.setattr(
        SourceContext,
        "get",
        lambda *a, **k: rss_data().replace(b"Apple earnings 0", b"New product released"),
    )
    items, report = run_source(
        "rss", query, NewsSettings(), tmp_path, threading.Event(), lambda _: None
    )
    assert len(items) == 1 and report.status == "latest_only"


def test_collector_isolates_failures_and_retains_cached_data(monkeypatch, query, tmp_path):
    def provider(key, *args):
        return (
            [item()] if key == "google" else [],
            SourceReport(
                "Google News RSS" if key == "google" else "Yahoo 뉴스/보도자료",
                "sampled" if key == "google" else "error",
            ),
        )

    monkeypatch.setattr("investment.news_collect.run_source", provider)
    result = collect_news(query, NewsSettings(sources=("google", "yahoo"), body_limit=0), tmp_path)
    assert len(result.items) == 1 and any(r.status == "error" for r in result.reports)
    result.items[0].label_method, result.items[0].sentiment = "manual", "negative"
    NewsStore(tmp_path / "news.sqlite").update_item(result.items[0])
    again = collect_news(query, NewsSettings(sources=("google",), body_limit=0), tmp_path)
    assert again.items[0].sentiment == "negative"


def test_cancel_preserves_existing_cache(query, tmp_path):
    store = NewsStore(tmp_path / "news.sqlite")
    store.save(NewsResult("AAPL", "Apple", query.start, query.end, [item()], []))
    cancel = threading.Event()
    cancel.set()
    result = collect_news(query, NewsSettings(sources=("google",), body_limit=0), tmp_path, cancel)
    assert len(result.items) == 1 and result.reports[0].status == "cancelled"


def test_bigkinds_import_filters_company_dates_and_keeps_summary(query, tmp_path):
    path = tmp_path / "archive.xlsx"
    pd.DataFrame(
        {
            "일자": ["20240102", "20240103", "20250101"],
            "제목": ["Apple earnings", "Other company news", "Apple old date"],
            "언론사": ["Daily"] * 3,
            "본문": ["요약"] * 3,
            "URL": ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
        }
    ).to_excel(path, index=False)
    result = import_archive(path, query, NewsSettings(), tmp_path / "data")
    assert len(result.items) == 1 and result.items[0].summary == "요약"
    assert result.items[0].time_precision == "day"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost/a",
        "http://127.0.0.1/a",
        "http://[::1]/a",
    ],
)
def test_article_fetch_rejects_nonpublic_urls(url):
    assert not public_url(url)


def test_public_article_metadata_and_excerpt_preserve_provider_time(monkeypatch):
    article = item()
    client = PublicContent(threading.Event())
    monkeypatch.setattr(client, "allowed", lambda _: True)
    payload = (
        '<html><script type="application/ld+json">'
        '{"@type":"NewsArticle","datePublished":"2024-01-02T12:00:00Z"}</script>'
        "<article><p>" + "A public company announcement. " * 20 + "</p></article></html>"
    ).encode()
    monkeypatch.setattr(
        client, "request", lambda *args, **kwargs: (200, "text/html", payload, article.url)
    )
    enriched = client.enrich(article)
    assert enriched.body_status == "public_excerpt"
    assert enriched.original_published_at.startswith("2024-01-02T12:00")
    assert enriched.published_at == "" and enriched.time_precision == "day"


def test_paywall_not_extracted(monkeypatch):
    client = PublicContent(threading.Event())
    monkeypatch.setattr(client, "allowed", lambda _: True)
    payload = (
        b'<script type="application/ld+json">'
        b'{"@type":"NewsArticle","isAccessibleForFree":false}</script>'
        b"<article>private</article>"
    )
    monkeypatch.setattr(
        client, "request", lambda *a, **k: (200, "text/html", payload, "https://example.com/a")
    )
    result = client.enrich(item())
    assert result.body_status == "restricted" and not result.body


def test_naver_keeps_provided_time_basis_and_uses_headers(monkeypatch, query, tmp_path):
    calls = []

    def response(self, url, **kwargs):
        calls.append(kwargs)
        return {
            "items": [
                {
                    "title": "Apple 실적",
                    "pubDate": "Tue, 02 Jan 2024 12:00:00 GMT",
                    "originallink": "https://example.com/news",
                    "description": "제공된 요약",
                }
            ]
        }

    monkeypatch.setattr(SourceContext, "get", response)
    rows, report = run_source(
        "naver",
        query,
        NewsSettings(naver_id="id", naver_secret="secret"),
        tmp_path,
        threading.Event(),
        lambda _: None,
    )
    assert rows[0].time_basis == "portal_provided" and report.status == "latest_only"
    assert calls[0]["headers"]["X-Naver-Client-Secret"] == "secret"


def test_yahoo_recent_and_press_releases_parse(monkeypatch, query, tmp_path):
    news = Mock(
        return_value=[
            {
                "content": {
                    "title": "Apple earnings",
                    "pubDate": "2024-01-02T12:00Z",
                    "canonicalUrl": {"url": "https://example.com/a"},
                    "summary": "summary",
                    "provider": {"displayName": "Publisher"},
                }
            }
        ]
    )
    monkeypatch.setattr(
        "investment.news_providers.yf.Ticker", lambda _: SimpleNamespace(get_news=news)
    )
    rows, report = run_source(
        "yahoo", query, NewsSettings(), tmp_path, threading.Event(), lambda _: None
    )
    assert len(deduplicate(rows)) == 1
    assert {call.kwargs["tab"] for call in news.call_args_list} == {"all", "press releases"}
    assert report.status == "latest_only"
    news.reset_mock()
    rows, report = run_source(
        "yahoo", query, NewsSettings(max_requests=1), tmp_path, threading.Event(), lambda _: None
    )
    assert len(rows) == 1 and report.status == "partial"
    assert news.call_count == report.requests == 1


def test_temporary_network_failure_retries_and_retains_feed(monkeypatch, query, tmp_path):
    monkeypatch.setattr("investment.news_providers.OFFICIAL_FEEDS", {})
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.ok = True
    response.iter_content.return_value = [rss_data()]
    request = Mock(side_effect=[requests.ReadTimeout("temporary"), response])
    monkeypatch.setattr("investment.news_providers.requests.get", request)
    rows, report = run_source(
        "rss",
        query,
        NewsSettings(rss_urls=("https://example.com/feed",)),
        tmp_path,
        threading.Event(),
        lambda _: None,
    )
    assert len(rows) == 1 and report.status == "latest_only"
    assert report.requests == request.call_count == 2


def test_provider_rate_limit_stops_without_repeating_requests(monkeypatch, query, tmp_path):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.ok = False
    response.status_code = 429
    request = Mock(return_value=response)
    monkeypatch.setattr("investment.news_providers.requests.get", request)
    rows, report = run_source(
        "google", query, NewsSettings(), tmp_path, threading.Event(), lambda _: None
    )
    assert not rows and report.status == "partial"
    assert report.requests == request.call_count == 1 and "429" in report.message


def test_alpha_preserves_provider_sentiment_and_utc_boundary_padding(monkeypatch, query, tmp_path):
    calls = []

    def response(self, url, **kwargs):
        calls.append(kwargs["params"])
        return {
            "feed": [
                {
                    "title": "Apple earnings",
                    "time_published": "20240103T040000",
                    "url": "https://example.com/a",
                    "ticker_sentiment": [{"ticker": "AAPL", "ticker_sentiment_label": "Bullish"}],
                }
            ]
        }

    monkeypatch.setattr(SourceContext, "get", response)
    target = replace(query, start="2024-01-02", end="2024-01-02")
    rows, _ = run_source(
        "alpha", target, NewsSettings(alpha_key="key"), tmp_path, threading.Event(), lambda _: None
    )
    assert rows[0].event_date == "2024-01-02"
    assert "Bullish" in rows[0].provider_sentiment
    assert rows[0].sentiment == "unknown"
    assert calls[0]["time_from"] == "20240101T0000" and calls[0]["time_to"] == "20240104T0000"


def test_finnhub_epoch_times_and_token_header(monkeypatch, query, tmp_path):
    calls = []

    def response(self, url, **kwargs):
        calls.append(kwargs)
        return [
            {"headline": "Apple earnings", "datetime": 1704196800, "url": "https://example.com/a"}
        ]

    monkeypatch.setattr(SourceContext, "get", response)
    rows, _ = run_source(
        "finnhub",
        query,
        NewsSettings(finnhub_key="key"),
        tmp_path,
        threading.Event(),
        lambda _: None,
    )
    assert rows[0].time_precision == "second"
    assert calls[0]["headers"]["X-Finnhub-Token"] == "key"


def test_gdelt_keeps_first_seen_basis_and_local_date_boundary(monkeypatch, query, tmp_path):
    day = datetime.now(timezone.utc).date() - timedelta(days=3)
    calls = []

    def response(self, url, **kwargs):
        calls.append(kwargs["params"])
        return {
            "articles": [
                {
                    "title": "Apple earnings",
                    "seendate": (day + timedelta(days=1)).strftime("%Y%m%dT030000Z"),
                    "url": "https://example.com/a",
                    "domain": "example.com",
                }
            ]
        }

    monkeypatch.setattr(SourceContext, "get", response)
    target = replace(query, start=day.isoformat(), end=day.isoformat())
    rows, _ = run_source(
        "gdelt", target, NewsSettings(), tmp_path, threading.Event(), lambda _: None
    )
    assert rows[0].time_basis == "first_seen" and rows[0].event_date == day.isoformat()
    assert calls[0]["enddatetime"] > (day + timedelta(days=1)).strftime("%Y%m%d030000")


def test_cross_source_time_observations_retained():
    a, b = item(source="Naver"), item(source="RSS")
    b.observations[0]["time_basis"] = "feed_published"
    merged = deduplicate([a, b])[0]
    assert {o["source"] for o in merged.observations} == {"Naver", "RSS"}


def test_import_does_not_match_apple_inside_pineapple(query, tmp_path):
    path = tmp_path / "news.csv"
    pd.DataFrame(
        {"date": ["2024-01-02"], "title": ["Pineapple farming"], "summary": ["fruit"]}
    ).to_csv(path, index=False)
    assert not import_archive(path, query, NewsSettings(), tmp_path / "data").items


def test_http_redirect_to_private_host_not_followed(monkeypatch):
    client = PublicContent(threading.Event())
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = 302
    response.headers = {"Location": "http://127.0.0.1/private"}
    request = Mock(return_value=response)
    monkeypatch.setattr(
        "investment.news_content.public_url", lambda url: url.startswith("https://public.example/")
    )
    monkeypatch.setattr("investment.news_content.requests.get", request)
    with pytest.raises(RuntimeError, match="공개 URL"):
        client.request("https://public.example/article")
    request.assert_called_once()
