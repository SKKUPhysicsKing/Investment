"""Desktop integration tests: run under xvfb-run on Linux, directly on Windows."""

import time
import tkinter as tk
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from investment.gui import InvestmentApp
from investment.news import NewsResult, SourceReport, make_item
from investment.search import Company, SearchResults


@pytest.fixture
def app(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No desktop display: {exc}")
    view = InvestmentApp(root, tmp_path / "data")
    monkeypatch.setattr("investment.gui.messagebox.showerror", Mock())
    root.update()
    yield view
    if not view.closed:
        view.close()


def finish(app):
    deadline = time.monotonic() + 10
    while app.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    app.root.update()
    assert not app.busy


def test_search_plot_and_export_the_loaded_snapshot(app, monkeypatch, history):
    company = Company("AAPL", "Apple Inc.", "NASDAQ", "Yahoo")
    monkeypatch.setattr("investment.gui.search_companies", lambda *args: SearchResults([company]))
    fetch = Mock(return_value=history)
    monkeypatch.setattr("investment.gui.load_company", fetch)
    app.search_button.invoke()
    finish(app)
    assert app.results.selection() == ("0",)
    app.start.set("2024-01-02")
    app.end.set("2024-01-03")
    app.load_button.invoke()
    finish(app)
    assert app.history is history
    assert len(app.price_ax.lines[0].get_xdata()) == 2
    assert len(app.table.get_children()) == 2
    app.query.set("MSFT")  # Editing the next query must not relabel/export old data as MSFT.
    app.start.set("2020-01-01")
    app.export_button.invoke()
    finish(app)
    files = list(app.data_dir.glob("*.csv"))
    assert len(files) == 1
    assert pd.read_csv(files[0])["symbol"].tolist() == ["AAPL", "AAPL"]
    assert "AAPL" in app.loaded_title.get()


def test_network_error_restores_buttons_and_existing_plot(app, monkeypatch, history):
    app.show_results(SearchResults([Company("AAPL", "Apple", "NASDAQ", "Yahoo")]))
    app.show_history(history)
    monkeypatch.setattr("investment.gui.load_company", Mock(side_effect=TimeoutError("offline")))
    app.load_button.invoke()
    finish(app)
    assert app.history is history
    assert app.export_button.instate(["!disabled"])
    assert app.search_button.instate(["!disabled"])
    assert "offline" in app.status.get()


def test_main_controls_fit_minimum_window(app, history):
    app.show_history(history)
    app.root.update()
    assert app.figure.bbox.width <= app.canvas.get_tk_widget().winfo_width() + 1
    app.root.geometry("980x660")
    app.root.update()
    for control in (
        app.search_button,
        app.load_button,
        app.export_button,
        app.metric,
        app.notebook,
        app.progress,
    ):
        left = control.winfo_rootx() - app.root.winfo_rootx()
        top = control.winfo_rooty() - app.root.winfo_rooty()
        assert left >= 0 and top >= 0
        assert left + control.winfo_width() <= app.root.winfo_width()
        assert top + control.winfo_height() <= app.root.winfo_height()


def test_invalid_dates_do_not_start_network(app, monkeypatch):
    app.show_results(SearchResults([Company("AAPL", "Apple", "NASDAQ", "Yahoo")]))
    fetch = Mock()
    monkeypatch.setattr("investment.gui.load_company", fetch)
    app.start.set("bad date")
    app.load_button.invoke()
    fetch.assert_not_called()
    assert not app.busy


def test_news_collect_chart_click_and_full_export(app, monkeypatch, history):
    company = Company("AAPL", "Apple Inc.", "NASDAQ", "Yahoo")
    app.show_results(SearchResults([company]))
    app.start.set("2024-01-01")
    app.end.set("2024-01-31")
    app.show_history(history)
    news = make_item(
        company, "test", "Apple beats estimates", "2024-01-02", "https://example.com/a"
    )
    result = NewsResult(
        "AAPL",
        "Apple Inc.",
        "2024-01-01",
        "2024-01-31",
        [news],
        [SourceReport("test", "sampled", 1)],
    )

    def collect(*args):
        args[-1]("intermediate progress")
        return result

    monkeypatch.setattr("investment.news_ui.collect_news", collect)
    panel = app.news_panel
    panel.collect_button.invoke()
    finish(app)
    timeline = app.timeline
    assert len(panel.tree.get_children()) == 1 and timeline.artists
    assert "규칙" in panel.detail.get("1.0", "end")
    from types import SimpleNamespace

    app.notebook.select(app.chart_frame)
    timeline.on_pick(SimpleNamespace(artist=next(iter(timeline.artists)), ind=[0]))
    assert timeline.focus_key and len(timeline.tree.get_children()) == 1
    assert app.notebook.select() == str(app.chart_frame)
    assert news.title in timeline.preview.get()
    app.query.set("MSFT")
    app.start.set("2020-01-01")
    panel.export_button.invoke()
    finish(app)
    files = list(app.data_dir.glob("*news*.csv"))
    assert pd.read_csv(files[0])["symbol"].tolist() == ["AAPL"]


def test_news_controls_fit_small_window(app):
    app.root.geometry("980x660")
    app.notebook.select(app.news_panel.frame)
    app.root.update()
    panel = app.news_panel
    for widget in (
        panel.collect_button,
        panel.settings_button,
        panel.export_button,
        panel.import_button,
        panel.split,
    ):
        x = widget.winfo_rootx() - app.root.winfo_rootx()
        y = widget.winfo_rooty() - app.root.winfo_rooty()
        assert x >= 0 and y >= 0
        assert x + widget.winfo_width() <= app.root.winfo_width()
        assert y + widget.winfo_height() <= app.root.winfo_height()


def test_chart_collect_uses_loaded_company_and_stays_with_stock_plot(app, monkeypatch, history):
    from investment.news import NewsStore

    app.show_history(history)
    app.show_results(SearchResults([Company("MSFT", "Microsoft", "NASDAQ", "Yahoo")]))
    app.start.set("2020-01-01")
    row = make_item(
        Company("AAPL", "Apple", "NASDAQ", "Yahoo"),
        "test",
        "Apple earnings",
        "2024-01-02",
        "https://example.com/a",
    )
    result = NewsResult("AAPL", "Apple", "2024-01-02", "2024-01-03", [row], [])

    def collect(query, *args):
        assert query.company.symbol == "AAPL" and query.start == "2024-01-02"
        return result

    monkeypatch.setattr("investment.news_ui.collect_news", collect)
    app.timeline.collect_button.invoke()
    finish(app)
    assert app.notebook.select() == str(app.chart_frame)
    assert row.id in app.timeline.rows
    NewsStore(app.data_dir / "news.sqlite").save(result)
    app.show_results(SearchResults([Company("AAPL", "Apple", "NASDAQ", "Yahoo")]))
    app.start.set("2024-01-02")
    app.end.set("2024-01-03")
    app.timeline.items = []
    monkeypatch.setattr("investment.gui.load_company", lambda *args: history)
    app.load_button.invoke()
    finish(app)
    assert row.id in app.timeline.rows


def test_timeline_hover_and_other_company_collection_preserve_chart(app, history):
    from matplotlib.backend_bases import MouseEvent

    from investment.timeline import LANES

    app.show_history(history)
    row = make_item(
        Company("AAPL", "Apple", "NASDAQ", "Yahoo"),
        "test",
        r"Apple earnings $5 \unknown$",
        "2024-01-02",
        "https://example.com/apple",
    )
    app.news_panel.show_result(
        NewsResult("AAPL", "Apple", "2024-01-02", "2024-01-03", [row], []), select_tab=False
    )
    app.root.update()
    group = app.timeline.groups[0]
    x, y = app.event_ax.transData.transform((group.number, LANES[group.kind][0]))
    app.timeline.on_motion(MouseEvent("motion_notify_event", app.canvas, x, y))
    assert app.timeline.hover.get_visible()
    assert row.title in app.timeline.hover.get_text()
    app.canvas.draw()  # Finance headlines containing dollars must stay literal text.
    app.timeline.detail_button.invoke()
    app.root.update()
    windows = [child for child in app.root.winfo_children() if isinstance(child, tk.Toplevel)]
    assert windows and not app.root.grab_current()
    assert app.notebook.select() == str(app.chart_frame)
    for window in windows:
        window.destroy()
    other = make_item(
        Company("MSFT", "Microsoft", "NASDAQ", "Yahoo"),
        "test",
        "Microsoft results",
        "2024-01-02",
        "https://example.com/microsoft",
    )
    app.news_panel.show_result(
        NewsResult("MSFT", "Microsoft", "2024-01-02", "2024-01-03", [other], []), select_tab=False
    )
    app.root.update()
    assert row.id in app.timeline.rows and other.id not in app.timeline.rows


def test_corrupt_news_cache_keeps_stock_plot_and_explains_cache_failure(app, monkeypatch, history):
    app.data_dir.mkdir(parents=True)
    (app.data_dir / "news.sqlite").write_bytes(b"not a SQLite database")
    app.show_results(SearchResults([Company("AAPL", "Apple", "NASDAQ", "Yahoo")]))
    monkeypatch.setattr("investment.gui.load_company", lambda *args: history)
    app.load_button.invoke()
    finish(app)
    assert app.history is history
    assert "뉴스를 불러오지 못" in app.status.get()


def test_chart_tracks_share_x_axis_and_keep_weekend_events(app, history):
    import matplotlib.dates as mdates

    history.metadata["ui_requested_dates"] = {"start": "2024-01-01", "end_inclusive": "2024-01-07"}
    app.show_history(history)
    row = make_item(
        Company("AAPL", "Apple", "NASDAQ", "Yahoo"),
        "test",
        "Apple Sunday news",
        "2024-01-07",
        "https://example.com/sunday",
    )
    app.news_panel.show_result(
        NewsResult("AAPL", "Apple", "2024-01-01", "2024-01-07", [row], []), select_tab=False
    )
    app.root.update()
    assert app.price_ax.get_xlim() == app.volume_ax.get_xlim() == app.event_ax.get_xlim()
    assert app.event_ax.get_xlim()[1] >= mdates.date2num(pd.Timestamp("2024-01-07"))
    assert row.id in app.timeline.rows
    app.price_ax.set_xlim(
        mdates.date2num(pd.Timestamp("2024-01-02")), mdates.date2num(pd.Timestamp("2024-01-04"))
    )
    app.canvas.draw()
    app.root.update()
    assert not app.timeline.rows


def test_chart_news_controls_fit_minimum_window(app, history):
    app.show_history(history)
    app.root.geometry("980x660")
    app.root.update()
    assert app.price_ax.bbox.height >= 55
    assert app.event_ax.bbox.height >= 25
    assert app.timeline.tree.winfo_height() >= 45
    for widget in (
        app.timeline.collect_button,
        app.timeline.filter,
        app.timeline.tree,
        app.timeline.detail_button,
        app.timeline.link_button,
        app.timeline.cancel_button,
        *app.timeline.navigation_buttons,
    ):
        x = widget.winfo_rootx() - app.root.winfo_rootx()
        y = widget.winfo_rooty() - app.root.winfo_rooty()
        assert 0 <= x and x + widget.winfo_width() <= app.root.winfo_width()
        assert 0 <= y and y + widget.winfo_height() <= app.root.winfo_height()
    assert app.compact_toolbar
    app.timeline.navigate("zoom")
    assert app.toolbar.mode
    app.timeline.navigate("home")
    assert not app.toolbar.mode


def test_shared_timeline_remains_readable_at_high_dpi(app, history):
    app.show_history(history)
    app.root.geometry("980x660")
    app.root.update()
    app.figure.set_dpi(144)
    app._fit_canvas()
    app.draw_plot(preserve_view=True)
    app.root.update()
    assert app.price_ax.bbox.height >= 55
    assert app.event_ax.bbox.height >= 25
    assert not app.show_volume.get()


def test_native_desktop_entry_preserves_data_and_opens_news_tab(tmp_path, monkeypatch):
    import json

    from investment.desktop import main

    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as exc:
        pytest.skip(f"No desktop display: {exc}")
    home = tmp_path / "Investment"
    data = home / "data" / "existing.csv"
    data.parent.mkdir(parents=True)
    data.write_text("keep", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    report = tmp_path / "desktop.json"
    assert main(["--app-home", str(home), "--smoke-result", str(report)]) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["news_tab"] and Path(result["data_dir"]) == data.parent
    assert data.read_text(encoding="utf-8") == "keep"
