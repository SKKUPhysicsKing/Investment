"""Independent interest-rate browser, comparison plot and snapshot exports."""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
import webbrowser
from datetime import date, timedelta
from tkinter import messagebox, ttk

import matplotlib.dates as mdates
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from .app_model import export_rates
from .rates import RATE_SERIES, RateRequest, collect_rates, discover_ecos_rates

COLORS = ("#2563b4", "#cb613b", "#13816d", "#8858ad", "#b78214", "#218ea6", "#ba4c80", "#5a7091")
FREQUENCIES = {"daily": "일별", "weekly": "주별", "monthly": "월별"}


class RatePanel:
    def __init__(self, app):
        self.app = app
        self.catalog = dict(RATE_SERIES)
        self.selected = {"DFF", "DGS2", "DGS10"}
        self.visible = set()
        self.history = None
        self.last_hover = 0
        self.cancel = threading.Event()
        self.api_key = os.environ.get("ECOS_API_KEY", "")
        self.country = tk.StringVar(value="전체 국가")
        self.search_text = tk.StringVar()
        today = date.today()
        self.start = tk.StringVar(value=(today - timedelta(days=365 * 5)).isoformat())
        self.end = tk.StringVar(value=today.isoformat())
        self.caption = tk.StringVar(
            value="미국·한국 금리를 선택해 함께 비교하세요. 회사 선택은 필요하지 않습니다."
        )
        self.selection_label = tk.StringVar()
        self.cursor_label = tk.StringVar(
            value="그래프 위에서 마우스를 움직이면 가까운 관측값을 표시합니다."
        )
        self.data_notice = tk.StringVar(value="조회 후 관측값을 확인할 수 있습니다.")
        self.frame = ttk.Frame(app.notebook, padding=8)
        app.notebook.add(self.frame, text="금리 · 비교")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        self._build()
        self.refresh_catalog()

    def _build(self):
        period = ttk.Frame(self.frame)
        period.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for col, (label, variable) in enumerate((("시작일", self.start), ("종료일", self.end))):
            ttk.Label(period, text=label).grid(row=0, column=col * 2, padx=(0, 5))
            ttk.Entry(period, textvariable=variable, width=12).grid(
                row=0, column=col * 2 + 1, padx=(0, 10)
            )
        for col, (label, years) in enumerate(
            (("1년", 1), ("5년", 5), ("10년", 10), ("최대", 0)), 4
        ):
            ttk.Button(
                period, text=label, width=5, command=lambda years=years: self.set_range(years)
            ).grid(row=0, column=col, padx=2)
        period.columnconfigure(8, weight=1)
        self.load_button = ttk.Button(period, text="선택 금리 조회", command=self.load)
        self.load_button.grid(row=0, column=9, padx=(8, 0))
        self.cancel_button = ttk.Button(period, text="취소", command=self.cancel.set, width=5)
        self.cancel_button.grid(row=0, column=10, padx=(5, 0))
        ttk.Label(self.frame, textvariable=self.caption, wraplength=1050).grid(
            row=1, column=0, sticky="w", pady=(0, 7)
        )
        self.panes = ttk.Panedwindow(self.frame, orient="horizontal")
        self.panes.grid(row=2, column=0, sticky="nsew")
        self.picker = picker = ttk.Frame(self.panes, width=300)
        detail = ttk.Frame(self.panes)
        self.panes.add(picker, weight=0)
        self.panes.add(detail, weight=1)
        self.app.root.after_idle(lambda: self.panes.sashpos(0, 300))
        picker.columnconfigure(0, weight=1)
        picker.rowconfigure(3, weight=1)
        filters = ttk.Frame(picker)
        filters.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        filters.columnconfigure(1, weight=1)
        country = ttk.Combobox(
            filters,
            textvariable=self.country,
            values=("전체 국가", "미국", "한국"),
            width=9,
            state="readonly",
        )
        country.grid(row=0, column=0, padx=(0, 5))
        country.bind("<<ComboboxSelected>>", lambda _: self.refresh_catalog())
        ttk.Entry(filters, textvariable=self.search_text, width=16).grid(
            row=0, column=1, sticky="ew"
        )
        self.search_text.trace_add("write", lambda *_: self.refresh_catalog())
        tools = ttk.Frame(picker)
        tools.grid(row=1, column=0, sticky="w", pady=6)
        ttk.Button(tools, text="검색 결과 선택", command=self.select_filtered).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(tools, text="선택 해제", command=self.clear_selection).pack(side="left")
        ttk.Label(picker, textvariable=self.selection_label).grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        listing = ttk.Frame(picker)
        listing.grid(row=3, column=0, sticky="nsew", padx=(0, 8))
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            listing, columns=("check", "name"), show="headings", selectmode="browse"
        )
        self.tree.heading("check", text="선택")
        self.tree.heading("name", text="금리 / 만기 / 원자료 주기")
        self.tree.column("check", width=42, minwidth=40, stretch=False, anchor="center")
        self.tree.column("name", width=228, minwidth=160)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(listing, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<ButtonRelease-1>", self.toggle_selected)
        self.tree.bind("<space>", self.toggle_selected)
        self.settings_button = ttk.Button(
            picker, text="한국 금리 API 설정 · 목록 확장", command=self.settings
        )
        self.settings_button.grid(row=4, column=0, sticky="ew", padx=(0, 8), pady=(7, 0))

        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        self.tabs = ttk.Notebook(detail)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.chart = chart = ttk.Frame(self.tabs)
        table = ttk.Frame(self.tabs)
        status = ttk.Frame(self.tabs)
        self.tabs.add(chart, text="비교 그래프")
        self.tabs.add(table, text="관측값 표")
        self.tabs.add(status, text="수집 상태")
        chart.columnconfigure(0, weight=1)
        chart.rowconfigure(0, weight=1)
        self.figure = Figure(figsize=(8, 5), dpi=100, layout="constrained", facecolor="white")
        self.ax = self.figure.subplots()
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.canvas.get_tk_widget().bind(
            "<Map>", lambda _: self.app.root.after_idle(self.fit_canvas), add="+"
        )
        toolbar = ttk.Frame(chart)
        toolbar.grid(row=1, column=0, sticky="ew")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar, pack_toolbar=False)
        self.toolbar.pack(side="left", fill="x", expand=True)
        ttk.Label(chart, textvariable=self.cursor_label).grid(row=2, column=0, sticky="w", pady=3)
        self.legend = ttk.Treeview(
            chart,
            columns=("show", "name", "latest", "date"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        for key, label, width in (
            ("show", "표시", 40),
            ("name", "금리 (클릭해 선 켜기·끄기)", 280),
            ("latest", "최신 금리 (%)", 105),
            ("date", "관측일", 100),
        ):
            self.legend.heading(key, text=label)
            self.legend.column(key, width=width, minwidth=40, stretch=key == "name")
        self.legend.grid(row=3, column=0, sticky="ew")
        legend_scroll = ttk.Scrollbar(chart, command=self.legend.yview)
        legend_scroll.grid(row=3, column=1, sticky="ns")
        self.legend.configure(yscrollcommand=legend_scroll.set)
        self.legend.bind("<ButtonRelease-1>", self.toggle_line)
        self.legend.bind("<space>", self.toggle_line)
        self.canvas.mpl_connect("motion_notify_event", self.hover)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(1, weight=1)
        ttk.Label(table, textvariable=self.data_notice).grid(row=0, column=0, sticky="w", pady=5)
        self.data_table = ttk.Treeview(
            table, columns=("date", "name", "rate", "frequency", "source"), show="headings"
        )
        for key, label, width in (
            ("date", "관측일", 100),
            ("name", "금리", 280),
            ("rate", "금리 (%)", 90),
            ("frequency", "원자료 주기", 85),
            ("source", "출처", 80),
        ):
            self.data_table.heading(key, text=label)
            self.data_table.column(key, width=width, minwidth=65, stretch=key == "name")
        self.data_table.grid(row=1, column=0, sticky="nsew")
        ys = ttk.Scrollbar(table, command=self.data_table.yview)
        ys.grid(row=1, column=1, sticky="ns")
        xs = ttk.Scrollbar(table, orient="horizontal", command=self.data_table.xview)
        xs.grid(row=2, column=0, sticky="ew")
        self.data_table.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        status.columnconfigure(0, weight=1)
        status.rowconfigure(0, weight=1)
        self.status_text = tk.Text(
            status, wrap="word", font=(self.app.ui_font, 10), state="disabled"
        )
        self.status_text.grid(row=0, column=0, sticky="nsew")
        sy = ttk.Scrollbar(status, command=self.status_text.yview)
        sy.grid(row=0, column=1, sticky="ns")
        self.status_text.configure(yscrollcommand=sy.set)
        bottom = ttk.Frame(self.frame)
        bottom.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(
            bottom, text="단위: % · 결측값 보간 없음 · 날짜는 관측일/월자료는 해당 월 1일"
        ).grid(row=0, column=0, sticky="w")
        self.export_button = ttk.Button(bottom, text="전체 금리 CSV", command=self.export)
        self.export_button.grid(row=0, column=1, padx=5)
        ttk.Button(bottom, text="data 폴더", command=self.app.open_data).grid(row=0, column=2)
        self.draw()
        self.update_controls()

    def set_focus(self, focused):
        has_picker = str(self.picker) in tuple(map(str, self.panes.panes()))
        if focused and has_picker:
            self.panes.forget(self.picker)
        elif not focused and not has_picker:
            self.panes.insert(0, self.picker, weight=0)
            self.app.root.after_idle(lambda: self.panes.sashpos(0, 300))

    def fit_canvas(self):
        if not self.app.closed:
            widget = self.canvas.get_tk_widget()
            widget.event_generate(
                "<Configure>", width=widget.winfo_width(), height=widget.winfo_height()
            )

    def set_range(self, years):
        today = date.today()
        self.start.set((today - timedelta(days=365 * years)).isoformat() if years else "1950-01-01")
        self.end.set(today.isoformat())

    def refresh_catalog(self):
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        text, country = self.search_text.get().strip().lower(), self.country.get()
        for s in self.catalog.values():
            if country != "전체 국가" and s.country != ("US" if country == "미국" else "KR"):
                continue
            if text and text not in f"{s.id} {s.name} {s.category}".lower():
                continue
            self.tree.insert(
                "",
                "end",
                iid=s.id,
                values=(
                    "✓" if s.id in self.selected else "",
                    f"{s.name} · {FREQUENCIES[s.frequency]}",
                ),
            )
        self.selection_label.set(f"목록 {len(self.catalog)}개 · 선택 {len(self.selected)}개")

    def toggle_selected(self, event):
        key = (
            self.tree.identify_row(event.y)
            if getattr(event, "num", None) == 1
            else next(iter(self.tree.selection()), "")
        )
        if key:
            self.selected.symmetric_difference_update({key})
            self.tree.set(key, "check", "✓" if key in self.selected else "")
            self.selection_label.set(f"목록 {len(self.catalog)}개 · 선택 {len(self.selected)}개")
        return "break"

    def select_filtered(self):
        self.selected.update(self.tree.get_children())
        self.refresh_catalog()

    def clear_selection(self):
        self.selected.clear()
        self.refresh_catalog()

    def update_controls(self):
        busy = self.app.busy
        self.load_button.state(["disabled"] if busy else ["!disabled"])
        self.settings_button.state(["disabled"] if busy else ["!disabled"])
        self.cancel_button.state(["!disabled"] if busy else ["disabled"])
        self.export_button.state(
            ["!disabled"] if self.history is not None and not busy else ["disabled"]
        )

    def load(self):
        if self.app.busy:
            return
        chosen = [s for s in self.catalog.values() if s.id in self.selected]
        first, last, key = self.start.get().strip(), self.end.get().strip(), self.api_key
        try:
            if not chosen:
                raise ValueError("목록에서 금리를 하나 이상 선택하세요.")
            RateRequest(chosen[0], first, last)
            if not key and any(s.source == "ECOS" for s in chosen):
                raise ValueError(
                    "한국 금리도 선택했습니다. '한국 금리 API 설정'에서 ECOS 인증키를 입력하세요."
                )
        except ValueError as exc:
            messagebox.showerror("금리 조회", str(exc), parent=self.app.root)
            return
        self.cancel.clear()
        self.app._run(
            lambda: collect_rates(
                chosen,
                start=first,
                end=last,
                ecos_api_key=key,
                cancel=self.cancel,
                progress=lambda text: self.app.events.put((None, text, None)),
            ),
            self.show_history,
            f"금리 {len(chosen)}개 조회 중…",
        )

    def show_history(self, history):
        self.history = history
        series = history.metadata["series"]
        self.visible = {s["series_id"] for s in series[:8]}
        self.legend.delete(*self.legend.get_children())
        for index, s in enumerate(series):
            identifier = s["series_id"]
            rows = history.data.loc[history.data.series_id == identifier].dropna(subset=["rate"])
            row = rows.iloc[-1]
            tag = f"series_{index}"
            self.legend.tag_configure(tag, foreground=COLORS[index % len(COLORS)])
            self.legend.insert(
                "",
                "end",
                iid=identifier,
                values=(
                    "✓" if identifier in self.visible else "",
                    s["series_name"],
                    f"{row['rate']:.3f}",
                    row["date"],
                ),
                tags=(tag,),
            )
        self.data_table.delete(*self.data_table.get_children())
        for row in history.data.tail(1000).itertuples(index=False):
            self.data_table.insert(
                "",
                "end",
                values=(
                    row.date,
                    row.series_name,
                    "" if pd.isna(row.rate) else f"{row.rate:.4f}",
                    FREQUENCIES[row.frequency],
                    row.source,
                ),
            )
        self.data_notice.set(
            f"전체 {len(history.data):,}행 중 최근 {min(len(history.data), 1000):,}행 · "
            "CSV는 모든 지표·행 저장"
        )
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        for s in series:
            self.status_text.insert(
                "end",
                f"완료 · {s['series_name']} ({s['series_id']}) · "
                f"{s['row_count']:,}행\n{s['source_url']}\n\n",
            )
        for identifier, error in history.metadata["errors"].items():
            self.status_text.insert("end", f"확보 실패 · {identifier}\n{error}\n\n")
        self.status_text.configure(state="disabled")
        self.caption.set(
            f"{history.metadata['request']['start']} ~ "
            f"{history.metadata['request']['end_inclusive']} · "
            f"{len(series)}개 지표 확보 · {len(history.metadata['errors'])}개 실패 · "
            "처음 8개까지 표시, 아래 목록으로 변경"
        )
        self.draw()
        self.toolbar.update()
        self.tabs.select(self.chart)
        self.app.status.set(
            ("수집 취소. 확보된 금리를 표시합니다. " if history.metadata.get("cancelled") else "")
            + "금리 조회 완료. 수집 상태에서 출처별 결과를 확인할 수 있습니다."
        )
        self.update_controls()

    def toggle_line(self, event):
        identifier = (
            self.legend.identify_row(event.y)
            if getattr(event, "num", None) == 1
            else next(iter(self.legend.selection()), "")
        )
        if identifier:
            self.visible.symmetric_difference_update({identifier})
            self.legend.set(identifier, "show", "✓" if identifier in self.visible else "")
            self.draw()
        return "break"

    def draw(self):
        self.ax.clear()
        self.ax.set_facecolor("#f8fafc")
        self.ax.grid(axis="y", color="#dfe7ef", linewidth=0.7)
        self.ax.spines[["top", "right"]].set_visible(False)
        self.ax.spines[["left", "bottom"]].set_color("#bccbda")
        self.ax.tick_params(colors="#4b6075", labelsize=9)
        self.ax.set_ylabel("Interest rate (%)", fontsize=10, color="#304960")
        locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
        self.ax.xaxis.set_major_locator(locator)
        self.ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        self.ax.margins(x=0.02, y=0.12)
        self.lines = []
        if self.history is not None:
            for index, s in enumerate(self.history.metadata["series"]):
                if s["series_id"] not in self.visible:
                    continue
                rows = self.history.data.loc[self.history.data.series_id == s["series_id"]]
                (line,) = self.ax.plot(
                    pd.to_datetime(rows.date),
                    rows.rate,
                    color=COLORS[index % len(COLORS)],
                    linewidth=1.7,
                    linestyle=("-", "--", "-.")[index // len(COLORS) % 3],
                    drawstyle="steps-post" if s.get("policy") else "default",
                    label=s["series_name"],
                    marker="o" if rows.rate.notna().sum() < 35 else None,
                    markersize=3,
                )
                values = rows.dropna(subset=["rate"])
                x = mdates.date2num(pd.to_datetime(values.date).to_numpy())
                self.lines.append((line, values, s, x))
            if len(self.lines) <= 5 and self.lines:
                self.ax.legend(
                    loc="best", framealpha=0.93, prop={"family": self.app.chart_font, "size": 9}
                )
        else:
            self.ax.text(
                0.5,
                0.5,
                "Select rates, then load observations.",
                transform=self.ax.transAxes,
                ha="center",
                color="#60758a",
            )
        self.canvas.draw_idle()

    def hover(self, event):
        if event.inaxes is not self.ax or event.xdata is None or not self.lines:
            return
        now = time.monotonic()
        if now - self.last_hover < 0.05:
            return
        self.last_hover = now
        best = None
        for _line, values, s, x in self.lines:
            index = abs(x - event.xdata).argmin()
            row = values.iloc[index]
            display = self.ax.transData.transform((x[index], row.rate))
            distance = abs(display[0] - event.x) + abs(display[1] - event.y)
            if best is None or distance < best[0]:
                best = (
                    distance,
                    f"{s['series_name']} · {row.date} · {row.rate:.4f}% "
                    f"({FREQUENCIES[s['frequency']]})",
                )
        self.cursor_label.set(best[1])

    def export(self):
        if self.history is not None and not self.app.busy:
            snapshot = self.history
            self.app._run(
                lambda: export_rates(snapshot, self.app.data_dir),
                lambda paths: self.app.status.set(f"금리 CSV 저장 완료: {paths[0]}"),
                "금리 CSV 저장 중…",
            )

    def settings(self):
        dialog = tk.Toplevel(self.app.root)
        dialog.title("한국은행 ECOS 금리 설정")
        dialog.transient(self.app.root)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="ECOS API 인증키", font=(self.app.ui_font, 11, "bold")).pack(
            anchor="w"
        )
        variable = tk.StringVar(value=self.api_key)
        ttk.Entry(frame, textvariable=variable, show="*", width=48).pack(fill="x", pady=8)
        ttk.Label(
            frame,
            text=(
                "인증키는 현재 실행에서만 사용하며 파일에 저장하지 않습니다.\n"
                "목록 확장으로 시장금리·은행 예금·대출의 세부 항목을 추가합니다."
            ),
            wraplength=430,
        ).pack(anchor="w")
        ttk.Button(
            frame,
            text="ECOS 인증키 발급 안내",
            command=lambda: webbrowser.open("https://ecos.bok.or.kr/api/#/AuthKey"),
        ).pack(anchor="w", pady=8)

        def apply(expand=False):
            self.api_key = variable.get().strip()
            if expand and not self.api_key:
                messagebox.showerror("인증키 확인", "ECOS 인증키를 입력하세요.", parent=dialog)
                return
            dialog.destroy()
            if expand:
                key = self.api_key
                self.app._run(
                    lambda: discover_ecos_rates(api_key=key),
                    self.add_catalog,
                    "한국 금리 세부 목록 불러오는 중…",
                )

        ttk.Button(frame, text="목록 확장하고 적용", command=lambda: apply(True)).pack(
            side="right", padx=(8, 0), pady=(10, 0)
        )
        ttk.Button(frame, text="적용", command=apply).pack(side="right", pady=(10, 0))

    def add_catalog(self, series):
        self.catalog.update({s.id: s for s in series})
        self.refresh_catalog()
        self.app.status.set(
            f"금리 목록 {len(self.catalog)}개. 검색·전체 선택으로 여러 지표를 조회하세요."
        )
