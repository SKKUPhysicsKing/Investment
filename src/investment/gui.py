"""Native desktop UI. All Tk access stays on the main thread."""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import matplotlib.dates as mdates
import pandas as pd
from matplotlib import font_manager
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from .app_model import export_history, inclusive_request, load_company, plot_times
from .market import PriceHistory
from .news_collect import load_cached
from .news_ui import NewsPanel
from .rates_ui import RatePanel
from .search import Company, SearchResults, search_companies
from .timeline import NewsTimeline, query_for_history

INTERVAL_LABELS = {
    "일봉": "1d",
    "주봉": "1wk",
    "월봉": "1mo",
    "1분": "1m",
    "5분": "5m",
    "15분": "15m",
    "30분": "30m",
    "1시간": "1h",
}


class InvestmentApp:
    def __init__(self, root: tk.Tk, data_dir: Path | None = None):
        self.root = root
        self.data_dir = (data_dir or Path.cwd() / "data").resolve()
        self.cache_dir = self.data_dir.parent / ".investment-app" / "search"
        self.history: PriceHistory | None = None
        self.companies: dict[str, Company] = {}
        self.busy = False
        self.closed = False
        self.events: queue.Queue = queue.Queue()
        self.query = tk.StringVar(value="삼성전자")
        today = date.today()
        self.start = tk.StringVar(value=(today - timedelta(days=365)).isoformat())
        self.end = tk.StringVar(value=today.isoformat())
        self.interval = tk.StringVar(value="일봉")
        self.price_column = tk.StringVar(value="종가")
        self.show_volume = tk.BooleanVar(value=True)
        self.volume_auto_hidden = False
        self.compact_toolbar = False
        self.chart_resize_timer = None
        self.last_chart_height = None
        self.last_pane_height = None
        self.status = tk.StringVar(value="회사명을 검색한 뒤 결과에서 종목을 선택하세요.")
        self.loaded_title = tk.StringVar(value="아직 조회한 데이터가 없습니다.")
        self.table_notice = tk.StringVar(value="조회 후 데이터를 확인할 수 있습니다.")
        self.focus_view = tk.BooleanVar(value=False)
        self.show_articles = tk.BooleanVar(value=True)
        self._configure_window()
        self._build()
        self.news_panel = NewsPanel(self)
        self.rate_panel = RatePanel(self)
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.timer = self.root.after(100, self._poll)

    def _configure_window(self):
        self.root.title("Investment — 주가·금리·뉴스")
        width = min(1360, self.root.winfo_screenwidth() - 60)
        height = min(880, self.root.winfo_screenheight() - 80)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(980, 660)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        # Set only the chart font; ttk follows the operating system's UI font.
        available = {font.name for font in font_manager.fontManager.ttflist}
        self.chart_font = next(
            (
                name
                for name in ("Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "Noto Sans CJK JP")
                if name in available
            ),
            "DejaVu Sans",
        )
        families = set(tkfont.families(self.root))
        self.ui_font = next(
            (
                name
                for name in ("Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "Noto Sans CJK JP")
                if name in families
            ),
            tkfont.nametofont("TkDefaultFont").actual("family"),
        )
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=self.ui_font, size=9)
        ttk.Style(self.root).configure("Treeview", rowheight=25)
        style = ttk.Style(self.root)
        style.configure("Treeview.Heading", font=(self.ui_font, 9, "bold"))
        style.configure("TNotebook.Tab", padding=(12, 6))
        style.configure("TButton", padding=(7, 4))
        style.configure("Chart.TButton", padding=(3, 2))
        style.configure("Chart.TCheckbutton", padding=(2, 2))

    def _build(self):
        header = ttk.Frame(self.root, padding=(12, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Investment · 주가·금리·뉴스", font=(self.ui_font, 13, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.focus_button = ttk.Checkbutton(
            header, text="차트 집중", variable=self.focus_view, command=self._apply_layout
        )
        self.focus_button.grid(row=0, column=1, padx=16)
        revision = os.environ.get("INVESTMENT_REVISION", "")
        label = f"v{version('investment-stock-data')}" + (f" · {revision[:8]}" if revision else "")
        ttk.Label(header, text=label).grid(row=0, column=2, sticky="e")

        self.panes = ttk.Panedwindow(self.root, orient="horizontal")
        self.panes.grid(row=1, column=0, sticky="nsew", padx=12)
        left = ttk.Frame(self.panes, padding=(0, 0, 10, 0), width=290)
        self.search_panel = left
        right = ttk.Frame(self.panes)
        self.panes.add(left, weight=0)
        self.panes.add(right, weight=1)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        self.root.after_idle(lambda: self.panes.sashpos(0, 290))

        ttk.Label(left, text="1. 회사 검색", font=(self.ui_font, 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        search = ttk.Frame(left)
        search.grid(row=1, column=0, sticky="ew")
        search.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(search, textvariable=self.query, width=18)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _: self.search())
        self.search_button = ttk.Button(search, text="검색", command=self.search, width=6)
        self.search_button.grid(row=0, column=1, padx=(5, 0))
        ttk.Label(left, text="예: 삼성전자, Apple, 애플, AAPL", wraplength=270).grid(
            row=2, column=0, sticky="w", pady=6
        )
        results = ttk.Frame(left)
        results.grid(row=3, column=0, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.results = ttk.Treeview(
            results, columns=("name", "symbol"), show="headings", selectmode="browse", height=12
        )
        self.results.heading("name", text="회사명")
        self.results.heading("symbol", text="티커")
        self.results.column("name", width=155, minwidth=80)
        self.results.column("symbol", width=95, minwidth=75)
        self.results.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.results.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(results, orient="horizontal", command=self.results.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.results.configure(xscrollcommand=horizontal.set)
        self.results.bind("<<TreeviewSelect>>", lambda _: self._button_states())
        self.results.bind("<Double-1>", lambda _: self.load())
        self.selection_text = tk.StringVar(value="검색 결과에서 회사를 선택하세요.")
        ttk.Label(left, textvariable=self.selection_text, wraplength=270).grid(
            row=4, column=0, sticky="ew", pady=8
        )

        form = ttk.LabelFrame(right, text="2. 조회 기간 (시작일·종료일 모두 포함)", padding=10)
        self.price_form = form
        form.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        form.columnconfigure(4, weight=1)
        ttk.Label(form, text="시작일").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.start, width=12).grid(row=0, column=1, padx=(6, 16))
        ttk.Label(form, text="종료일").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.end, width=12).grid(row=0, column=3, padx=6)
        ttk.Label(form, text="YYYY-MM-DD").grid(row=0, column=4, sticky="e")
        options = ttk.Frame(form)
        options.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        options.columnconfigure(5, weight=1)
        ttk.Label(options, text="봉 간격").grid(row=0, column=0)
        ttk.Combobox(
            options,
            textvariable=self.interval,
            values=list(INTERVAL_LABELS),
            state="readonly",
            width=7,
        ).grid(row=0, column=1, padx=6)
        for column, (label, days) in enumerate((("1개월", 30), ("3개월", 90), ("1년", 365)), 2):
            ttk.Button(
                options, text=label, width=6, command=lambda days=days: self._set_range(days)
            ).grid(row=0, column=column, padx=2)
        self.load_button = ttk.Button(options, text="조회 · PLOT", command=self.load)
        self.load_button.grid(row=0, column=6, sticky="e", padx=(8, 0))
        self.load_button.state(["disabled"])

        summary = ttk.Frame(right)
        self.price_summary = summary
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        summary.columnconfigure(0, weight=1)
        self.loaded_label = ttk.Label(summary, textvariable=self.loaded_title, wraplength=500)
        self.loaded_label.grid(row=0, column=0, sticky="w")
        summary.bind(
            "<Configure>",
            lambda event: self.loaded_label.configure(wraplength=max(160, event.width - 260)),
        )
        self.volume_toggle = ttk.Checkbutton(
            summary, text="거래량", variable=self.show_volume, command=self._toggle_volume
        )
        self.volume_toggle.grid(row=0, column=1, padx=(6, 0))
        self.article_toggle = ttk.Checkbutton(
            summary, text="기사 목록", variable=self.show_articles, command=self._apply_layout
        )
        self.article_toggle.grid(row=0, column=2, padx=(6, 0))
        self.metric = ttk.Combobox(
            summary,
            textvariable=self.price_column,
            values=["종가", "수정종가"],
            state="readonly",
            width=8,
        )
        self.metric.grid(row=0, column=3, padx=(8, 0))
        self.metric.bind("<<ComboboxSelected>>", lambda _: self.draw_plot())

        self.notebook = ttk.Notebook(right)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.chart_frame = chart = ttk.Frame(self.notebook)
        table = ttk.Frame(self.notebook)
        self.notebook.add(chart, text="주가 그래프")
        self.notebook.add(table, text="데이터 표")
        chart.rowconfigure(0, weight=1)
        chart.columnconfigure(0, weight=1)
        self.chart_panes = ttk.Panedwindow(chart, orient="vertical")
        self.chart_panes.grid(row=0, column=0, sticky="nsew")
        plot = ttk.Frame(self.chart_panes)
        articles = ttk.Frame(self.chart_panes)
        self.article_frame = articles
        self.chart_panes.add(plot, weight=4)
        self.chart_panes.add(articles, weight=1)
        plot.rowconfigure(0, weight=1)
        plot.columnconfigure(0, weight=1)
        self.chart_panes.bind(
            "<Map>", lambda _: self.root.after_idle(self._fit_chart_panes), add="+"
        )
        self.chart_panes.bind("<Configure>", lambda _: self._fit_chart_panes(), add="+")
        self.figure = Figure(figsize=(7, 4), dpi=100, layout="constrained")
        self.price_ax, self.volume_ax, self.event_ax = self.figure.subplots(
            3, 1, sharex=True, gridspec_kw={"height_ratios": [3.2, 0.8, 1.4]}
        )
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        # A DPI change on first mapping can update Figure's size without a Tk
        # resize event when grid keeps the canvas dimensions unchanged.
        self.canvas.get_tk_widget().bind(
            "<Map>", lambda _: self.root.after_idle(self._fit_canvas), add="+"
        )
        self.canvas.get_tk_widget().bind("<Configure>", self._schedule_chart_layout, add="+")
        self.toolbar_frame = toolbar_frame = ttk.Frame(plot)
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()
        self.timeline = NewsTimeline(self, articles)
        self.price_ax.text(
            0.5,
            0.5,
            "Select a company, then load prices.",
            ha="center",
            va="center",
            transform=self.price_ax.transAxes,
        )
        self.canvas.draw_idle()

        table.rowconfigure(1, weight=1)
        table.columnconfigure(0, weight=1)
        ttk.Label(table, textvariable=self.table_notice).grid(row=0, column=0, sticky="w", pady=5)
        columns = ("time", "open", "high", "low", "close", "adj_close", "volume")
        self.table = ttk.Treeview(table, columns=columns, show="headings")
        for key, label in zip(
            columns,
            ("현지 날짜/시각", "시가", "고가", "저가", "종가", "수정종가", "거래량"),
            strict=True,
        ):
            self.table.heading(key, text=label)
            self.table.column(
                key,
                width=145 if key == "time" else 100,
                minwidth=90,
                stretch=False,
                anchor="w" if key == "time" else "e",
            )
        self.table.grid(row=1, column=0, sticky="nsew")
        ys = ttk.Scrollbar(table, orient="vertical", command=self.table.yview)
        xs = ttk.Scrollbar(table, orient="horizontal", command=self.table.xview)
        ys.grid(row=1, column=1, sticky="ns")
        xs.grid(row=2, column=0, sticky="ew")
        self.table.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)

        bottom = ttk.Frame(right, padding=(0, 8))
        self.price_bottom = bottom
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, text="주가: 주말·휴장일 제외 · 마지막 봉은 장중 갱신 가능").grid(
            row=0, column=0, sticky="w"
        )
        self.export_button = ttk.Button(bottom, text="주가 CSV", command=self.export)
        self.export_button.grid(row=0, column=1, padx=5)
        self.export_button.state(["disabled"])
        ttk.Button(bottom, text="data 폴더 열기", command=self.open_data).grid(row=0, column=2)

        footer = ttk.Frame(self.root, padding=(12, 7))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, wraplength=820).grid(
            row=0, column=0, sticky="w"
        )
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, padx=(8, 0))
        self.search_entry.focus_set()

    def _fit_canvas(self):
        if not self.closed:
            widget = self.canvas.get_tk_widget()
            widget.event_generate(
                "<Configure>", width=widget.winfo_width(), height=widget.winfo_height()
            )

    def _fit_chart_panes(self):
        height = self.chart_panes.winfo_height()
        if len(self.chart_panes.panes()) > 1 and height > 200 and height != self.last_pane_height:
            self.last_pane_height = height
            self.chart_panes.sashpos(0, max(170, height - max(128, min(165, int(height * 0.28)))))

    def _tab_changed(self, _event=None):
        if hasattr(self, "rate_panel"):
            self._apply_layout()

    def reveal_articles(self):
        self.focus_view.set(False)
        self.show_articles.set(True)
        self._apply_layout()

    def _apply_layout(self):
        if not hasattr(self, "rate_panel"):
            return
        rates = self.notebook.select() == str(self.rate_panel.frame)
        focus = self.focus_view.get()
        has_search = str(self.search_panel) in tuple(map(str, self.panes.panes()))
        if (rates or focus) and has_search:
            self.panes.forget(self.search_panel)
        elif not rates and not focus and not has_search:
            self.panes.insert(0, self.search_panel, weight=0)
            self.root.after_idle(lambda: self.panes.sashpos(0, 290))
        for widget in (self.price_form, self.price_bottom):
            widget.grid_remove() if rates or focus else widget.grid()
        self.price_summary.grid_remove() if rates else self.price_summary.grid()
        self.rate_panel.set_focus(focus)
        show = self.show_articles.get() and not focus
        has_articles = str(self.article_frame) in tuple(map(str, self.chart_panes.panes()))
        if not show and has_articles:
            self.chart_panes.forget(self.article_frame)
        elif show and not has_articles:
            self.chart_panes.add(self.article_frame, weight=1)
            self.last_pane_height = None
            self.root.after_idle(self._fit_chart_panes)
        self.root.after_idle(self._fit_canvas)

    def _toggle_volume(self):
        self.volume_auto_hidden = False
        self.draw_plot(preserve_view=True)

    def chart_font_size(self, size):
        compact = self.canvas.get_tk_widget().winfo_height() < 240
        return size * min(1.0, 100 / self.figure.dpi) if compact else size

    def _schedule_chart_layout(self, event):
        if self.closed:
            return
        if self.chart_resize_timer:
            self.root.after_cancel(self.chart_resize_timer)
        height = event.height

        def apply():
            self.chart_resize_timer = None
            changed = False
            if height != self.last_chart_height:
                if height < 240 and not self.compact_toolbar:
                    self.compact_toolbar = True
                    self.toolbar_frame.grid_remove()
                    self.timeline.set_compact_navigation(True)
                elif height >= 320 and self.compact_toolbar:
                    self.compact_toolbar = False
                    self.toolbar_frame.grid()
                    self.timeline.set_compact_navigation(False)
                if height < 240 and self.show_volume.get():
                    self.show_volume.set(False)
                    self.volume_auto_hidden = changed = True
                elif height >= 280 and self.volume_auto_hidden:
                    self.show_volume.set(True)
                    self.volume_auto_hidden = False
                    changed = True
                self.last_chart_height = height
            if changed and self.history is not None:
                self.draw_plot(preserve_view=True)

        self.chart_resize_timer = self.root.after_idle(apply)

    def _set_range(self, days: int):
        today = date.today()
        self.start.set((today - timedelta(days=days)).isoformat())
        self.end.set(today.isoformat())

    def _button_states(self):
        selected = self.results.selection()
        if selected and selected[0] in self.companies:
            company = self.companies[selected[0]]
            self.selection_text.set(f"{company.name}\n{company.symbol} · {company.exchange}")
        self.search_button.state(["disabled"] if self.busy else ["!disabled"])
        self.load_button.state(["!disabled"] if selected and not self.busy else ["disabled"])
        self.export_button.state(
            ["!disabled"] if self.history is not None and not self.busy else ["disabled"]
        )
        if hasattr(self, "news_panel"):
            self.news_panel.update_controls()
        if hasattr(self, "rate_panel"):
            self.rate_panel.update_controls()
        self.timeline.update_controls()

    def _run(self, work, done, status: str):
        if self.busy:
            return
        self.busy = True
        self.status.set(status)
        self.progress.start(12)
        self._button_states()

        def worker():
            try:
                self.events.put((done, work(), None))
            except Exception as exc:
                self.events.put((done, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                done, result, error = self.events.get_nowait()
                if done is None:
                    self.status.set(result)
                    continue
                self.busy = False
                self.progress.stop()
                if error:
                    self.news_panel.cancel.set()
                    self.status.set(f"실패: {error}")
                    messagebox.showerror("작업 실패", str(error), parent=self.root)
                else:
                    try:
                        done(result)
                    except Exception as exc:
                        self.status.set(f"표시 오류: {exc}")
                        messagebox.showerror("표시 오류", str(exc), parent=self.root)
                self._button_states()
        except queue.Empty:
            pass
        self.timer = self.root.after(100, self._poll)

    def search(self):
        if self.busy:
            return
        query = self.query.get().strip()
        if not query:
            self.status.set("회사명 또는 티커를 입력하세요.")
            return
        self._run(
            lambda: search_companies(query, self.cache_dir), self.show_results, "회사 검색 중…"
        )

    def show_results(self, result: SearchResults):
        self.results.delete(*self.results.get_children())
        self.companies.clear()
        for index, company in enumerate(result.companies):
            key = str(index)
            self.companies[key] = company
            self.results.insert("", "end", iid=key, values=(company.name, company.symbol))
        if result.companies:
            self.results.selection_set("0")
            self.results.focus("0")
            self.status.set(
                f"검색 결과 {len(result.companies)}개. 종목과 기간을 확인하고 조회하세요. "
                f"{result.notice}"
            )
        else:
            self.selection_text.set("검색 결과가 없습니다.")
            self.status.set("검색 결과가 없습니다. 해외 기업은 영문 회사명 또는 티커로 검색하세요.")
        self._button_states()

    def load(self):
        selected = self.results.selection()
        if self.busy or not selected or selected[0] not in self.companies:
            return
        company = self.companies[selected[0]]
        start, end, interval = (
            self.start.get().strip(),
            self.end.get().strip(),
            INTERVAL_LABELS[self.interval.get()],
        )
        try:
            inclusive_request(company.symbol, start, end, interval)
        except ValueError as exc:
            messagebox.showerror("입력 확인", str(exc), parent=self.root)
            return

        def work():
            history = load_company(company, start, end, interval)
            cached = None
            cache_notice = ""
            if (self.data_dir / "news.sqlite").is_file():
                try:
                    cached = load_cached(query_for_history(history), self.data_dir)
                except Exception:
                    # A broken optional news cache must not prevent a stock plot.
                    cache_notice = (
                        "주가는 조회했지만 저장된 뉴스를 불러오지 못했습니다. "
                        "그래프 뉴스 수집으로 자료를 조회하세요."
                    )
            return history, cached, cache_notice

        self._run(
            work,
            lambda result: self.show_history(*result),
            f"{company.name} · {start} ~ {end} 조회 중…",
        )

    def show_history(self, history: PriceHistory, cached_news=None, cache_notice=""):
        self.history = history
        self.timeline.set_history(history, cached_news)
        if self.news_panel.result:
            self.timeline.remember(self.news_panel.result)
        meta, frame = history.metadata, history.data
        name = meta.get("company_name", meta["symbol"])
        self.loaded_title.set(
            f"표시 중: {name} ({meta['symbol']}) · {meta['interval']}\n"
            f"{frame['date'].iloc[0]} ~ {frame['date'].iloc[-1]} · {len(frame):,}개 봉 · "
            f"{meta.get('currency') or '통화 미상'}"
        )
        self.draw_plot()
        self.table.delete(*self.table.get_children())
        times = plot_times(history)
        daily = meta["interval"] in ("1d", "5d", "1wk", "1mo", "3mo")
        for index, row in frame.tail(500).iterrows():
            timestamp = times.loc[index].strftime("%Y-%m-%d" if daily else "%Y-%m-%d %H:%M")
            values = [timestamp]
            for key in ("open", "high", "low", "close", "adj_close", "volume"):
                value = row[key]
                values.append(
                    ""
                    if pd.isna(value)
                    else (
                        f"{int(value):,}"
                        if key == "volume"
                        else f"{value:,.4f}".rstrip("0").rstrip(".")
                    )
                )
            self.table.insert("", "end", values=values)
        self.table_notice.set(
            f"전체 {len(frame):,}행 중 최근 {min(len(frame), 500):,}행 표시 · "
            "CSV에는 전체 데이터 저장"
        )
        self.toolbar.update()
        self.status.set(
            cache_notice or "조회 완료. 그래프와 데이터 표를 확인하거나 CSV로 내보내세요."
        )
        self.notebook.select(self.chart_frame)
        self._button_states()

    def draw_plot(self, *, preserve_view=False):
        if self.history is None:
            return
        frame, meta = self.history.data, self.history.metadata
        times = plot_times(self.history)
        limits = (
            (self.price_ax.get_xlim(), self.price_ax.get_ylim(), self.volume_ax.get_ylim())
            if preserve_view
            else None
        )
        column = "adj_close" if self.price_column.get() == "수정종가" else "close"
        self.price_ax.clear()
        self.volume_ax.clear()
        self.event_ax.clear()
        compact = self.canvas.get_tk_widget().winfo_height() < 240
        self.figure.get_layout_engine().set(
            h_pad=0.01 if compact else 0.035, w_pad=0.035, hspace=0.01, wspace=0.02
        )
        self.volume_ax.set_visible(self.show_volume.get())
        self.price_ax.get_subplotspec().get_gridspec().set_height_ratios(
            [4.0, 0.8 if self.show_volume.get() else 0.01, 1.0]
        )
        if frame[column].notna().any():
            self.price_ax.plot(times, frame[column], linewidth=1.7, color="#2563b4")
        else:
            self.price_ax.text(
                0.5,
                0.5,
                "Adjusted close unavailable",
                ha="center",
                va="center",
                transform=self.price_ax.transAxes,
            )
        self.price_ax.text(
            0.01,
            0.98,
            f"{meta.get('company_name', meta['symbol'])} ({meta['symbol']})",
            transform=self.price_ax.transAxes,
            va="top",
            fontfamily=self.chart_font,
            fontsize=self.chart_font_size(9),
            parse_math=False,
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none", "pad": 1},
        )
        self.price_ax.set_ylabel(
            f"Price ({meta.get('currency') or '?'})", fontsize=self.chart_font_size(9)
        )
        self.price_ax.tick_params(axis="y", labelsize=self.chart_font_size(8))
        self.price_ax.grid(True, alpha=0.25)
        span = (times.iloc[-1] - times.iloc[0]).total_seconds() / 86400
        width = min(0.8, span / max(len(times), 1) * 0.75) if span else 0.5
        self.volume_ax.bar(times, frame["volume"].astype(float), width=width, color="#9daab5")
        self.volume_ax.set_ylabel("Volume", fontsize=self.chart_font_size(8))
        self.volume_ax.tick_params(axis="y", labelsize=self.chart_font_size(7))
        self.volume_ax.grid(True, alpha=0.2)
        locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
        self.timeline.render(self.history)
        self.event_ax.xaxis.set_major_locator(locator)
        self.event_ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        self.event_ax.set_xlabel(
            f"Exchange local time · {meta.get('exchange_timezone') or 'UTC'}",
            fontsize=self.chart_font_size(8),
        )
        self.price_ax.tick_params(labelbottom=False)
        self.volume_ax.tick_params(labelbottom=False)
        self.event_ax.tick_params(axis="x", labelsize=self.chart_font_size(8))
        self.event_ax.xaxis.get_offset_text().set_fontsize(self.chart_font_size(7.5))
        for axis in (self.price_ax, self.volume_ax, self.event_ax):
            axis.set_facecolor("#f8fafc")
            axis.spines[["top", "right"]].set_visible(False)
            axis.spines[["left", "bottom"]].set_color("#bccbda")
            axis.tick_params(colors="#4b6075")
        self.price_ax.grid(axis="y", color="#dfe7ef", linewidth=0.7, alpha=1)
        self.price_ax.grid(axis="x", visible=False)
        if limits:
            self.price_ax.set_xlim(limits[0])
            self.price_ax.set_ylim(limits[1])
            self.volume_ax.set_ylim(limits[2])
        self.canvas.draw_idle()

    def export(self):
        if self.history is None or self.busy:
            return
        snapshot = self.history
        self._run(
            lambda: export_history(snapshot, self.data_dir),
            lambda paths: self.status.set(f"CSV 저장 완료: {paths[0]}"),
            "CSV 저장 중…",
        )

    def open_data(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(self.data_dir))
            else:
                subprocess.Popen(
                    ["open" if sys.platform == "darwin" else "xdg-open", str(self.data_dir)]
                )
        except OSError as exc:
            messagebox.showerror("폴더 열기 실패", str(exc), parent=self.root)

    def close(self):
        self.closed = True
        self.news_panel.cancel.set()
        self.rate_panel.cancel.set()
        self.root.after_cancel(self.timer)
        if self.chart_resize_timer:
            self.root.after_cancel(self.chart_resize_timer)
        self.root.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Investment desktop app")
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / "data")
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Cannot open a desktop window: {exc}", file=sys.stderr)
        return 2
    InvestmentApp(root, args.data_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
