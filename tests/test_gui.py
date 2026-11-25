"""Desktop integration tests: run under xvfb-run on Linux, directly on Windows."""

import time
import tkinter as tk
from unittest.mock import Mock

import pandas as pd
import pytest

from investment.gui import InvestmentApp
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
