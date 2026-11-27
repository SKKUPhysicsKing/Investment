"""Shared stock/event time axis with uncertainty-aware groups and inline articles."""

from __future__ import annotations

import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from tkinter import ttk

import matplotlib.dates as mdates
import pandas as pd

from .news import EVENT_TYPES, SENTIMENTS, NewsItem, safe_url
from .news_collect import timezone_for
from .news_providers import NewsQuery
from .search import Company

LANES = {
    "earnings": (2, "실적", "#a36312", "D"),
    "filing": (1, "공시", "#7545a0", "s"),
    "news": (0, "뉴스", "#23799c", "o"),
}
DAILY = {"1d", "5d", "1wk", "1mo", "3mo"}


def query_for_history(history):
    meta, frame = history.metadata, history.data
    company = Company(meta["symbol"], meta.get("company_name", meta["symbol"]), "", "Loaded chart")
    requested = meta.get("ui_requested_dates", {})
    return NewsQuery(
        company,
        requested.get("start", frame["date"].iloc[0]),
        requested.get("end_inclusive", frame["date"].iloc[-1]),
        meta.get("exchange_timezone") or timezone_for(company),
    )


def category(item):
    if item.event_type == "earnings":
        return "earnings"
    if item.event_type == "filing" or set(item.sources) & {"DART", "SEC"}:
        return "filing"
    return "news"


def local_time(item, timezone):
    if not item.published_at or item.time_precision == "day":
        return None
    try:
        stamp = pd.Timestamp(item.published_at)
        return stamp.tz_convert(timezone).tz_localize(None) if stamp.tzinfo else None
    except (TypeError, ValueError):
        return None


def chronological(items):
    return sorted(items, key=lambda i: (i.event_date, i.published_at, i.id))


@dataclass
class EventGroup:
    key: str
    kind: str
    x: pd.Timestamp
    end: pd.Timestamp | None = None
    items: list[NewsItem] = field(default_factory=list)

    @property
    def number(self):
        return float(mdates.date2num(self.x.to_pydatetime()))

    @property
    def last_number(self):
        return (
            float(mdates.date2num(self.end.to_pydatetime()))
            if self.end is not None
            else self.number
        )


def group_events(items, history, kind="전체"):
    query = query_for_history(history)
    daily = history.metadata["interval"] in DAILY
    groups = {}
    for item in chronological(items):
        if item.symbol != query.company.symbol:
            continue
        stamp = local_time(item, query.timezone)
        day = stamp.date().isoformat() if stamp is not None else item.event_date
        if not query.start <= day <= query.end:
            continue
        lane = category(item)
        if kind != "전체" and LANES[lane][1] != kind:
            continue
        # Date-only records get a full-day band on intraday plots, never a fake time.
        x = pd.Timestamp(day) if daily or stamp is None else stamp
        end = x + pd.Timedelta(days=1) if not daily and stamp is None else None
        key = f"{lane}/{x.isoformat()}/{'day' if end is not None else 'point'}"
        if key not in groups:
            groups[key] = EventGroup(key, lane, x, end)
        groups[key].items.append(item)
    return sorted(groups.values(), key=lambda group: (group.x, -LANES[group.kind][0], group.key))


class NewsTimeline:
    def __init__(self, app, parent):
        self.app = app
        self.symbol = ""
        self.items = []
        self.groups = []
        self.artists = {}
        self.annotations = []
        self.cursors = []
        self.rows = {}
        self.focus_key = None
        self.selected_id = None
        self.viewport = None
        self.hover = None
        self.hover_key = None
        self.last_motion = 0
        self.kind = tk.StringVar(value="전체")
        self.caption = tk.StringVar(value="뉴스/공시를 수집하면 같은 날짜 축에 표시합니다.")
        self.preview = tk.StringVar(
            value="마커 또는 목록을 선택하면 주가의 해당 날짜를 표시합니다."
        )
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(2, 3))
        self.collect_button = ttk.Button(controls, text="그래프 뉴스 수집", command=self.collect)
        self.collect_button.grid(row=0, column=0, padx=(0, 4))
        self.filter = ttk.Combobox(
            controls,
            textvariable=self.kind,
            values=("전체", "실적", "공시", "뉴스"),
            state="readonly",
            width=6,
        )
        self.filter.grid(row=0, column=1, padx=3)
        self.filter.bind("<<ComboboxSelected>>", lambda _: self.filter_changed())
        self.reset_button = ttk.Button(controls, text="전체 목록", command=self.reset, width=8)
        self.reset_button.grid(row=0, column=2, padx=3)
        self.detail_button = ttk.Button(controls, text="기사 상세", command=self.details, width=8)
        self.detail_button.grid(row=0, column=3, padx=3)
        self.link_button = ttk.Button(controls, text="원문", command=self.open_original, width=5)
        self.link_button.grid(row=0, column=4, padx=3)
        self.cancel_button = ttk.Button(
            controls, text="취소", command=lambda: app.news_panel.stop(), width=5
        )
        self.cancel_button.grid(row=0, column=5, padx=3)
        self.zoom_mode = tk.BooleanVar(value=False)
        self.pan_mode = tk.BooleanVar(value=False)
        self.navigation_buttons = []
        for column, (label, action, variable) in enumerate(
            (
                ("홈", "home", None),
                ("확대", "zoom", self.zoom_mode),
                ("이동", "pan", self.pan_mode),
                ("그림", "save_figure", None),
            ),
            6,
        ):
            options = {
                "text": label,
                "command": lambda action=action: self.navigate(action),
                "width": 4,
            }
            button = (
                ttk.Checkbutton(controls, variable=variable, **options)
                if variable is not None
                else ttk.Button(controls, **options)
            )
            button.grid(row=0, column=column, padx=2)
            button.grid_remove()
            self.navigation_buttons.append(button)
        listing = ttk.Frame(parent)
        listing.grid(row=1, column=0, sticky="nsew")
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            listing,
            columns=("time", "kind", "title", "publisher"),
            show="headings",
            selectmode="browse",
            height=3,
        )
        for key, title, width in (
            ("time", "거래소 현지 날짜/시각", 165),
            ("kind", "구분", 55),
            ("title", "기사 · 공시 제목", 490),
            ("publisher", "출처", 115),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=45, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(listing, orient="horizontal", command=self.tree.xview)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select_row())
        self.tree.bind("<Double-1>", lambda _: self.details())
        self.caption_label = ttk.Label(parent, textvariable=self.caption, width=1)
        self.caption_label.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        ttk.Label(parent, textvariable=self.preview, width=1).grid(row=3, column=0, sticky="ew")
        parent.bind(
            "<Configure>",
            lambda event: (
                self.caption_label.grid_remove()
                if event.height < 155
                else self.caption_label.grid()
            ),
            add="+",
        )
        app.canvas.mpl_connect("pick_event", self.on_pick)
        app.canvas.mpl_connect("motion_notify_event", self.on_motion)
        app.canvas.mpl_connect("figure_leave_event", lambda _: self.hide_hover())
        app.canvas.mpl_connect("draw_event", lambda _: self.refresh_view())
        self.update_controls()

    def update_controls(self):
        self.collect_button.state(
            ["!disabled"] if self.app.history is not None and not self.app.busy else ["disabled"]
        )
        panel = getattr(self.app, "news_panel", None)
        self.cancel_button.state(
            ["!disabled"] if panel and self.app.busy and not panel.cancel.is_set() else ["disabled"]
        )
        for button in (self.detail_button, self.link_button):
            button.state(["!disabled"] if self.selected() else ["disabled"])

    def set_compact_navigation(self, visible):
        for button in self.navigation_buttons:
            button.grid() if visible else button.grid_remove()
        self.sync_navigation()

    def sync_navigation(self):
        mode = str(self.app.toolbar.mode).lower()
        self.zoom_mode.set(mode.startswith("zoom"))
        self.pan_mode.set(mode.startswith("pan"))

    def navigate(self, action):
        if action == "home":
            if self.zoom_mode.get():
                self.app.toolbar.zoom()
            elif self.pan_mode.get():
                self.app.toolbar.pan()
        getattr(self.app.toolbar, action)()
        self.sync_navigation()

    def set_history(self, history, cached=None):
        symbol = history.metadata["symbol"]
        if symbol != self.symbol:
            self.symbol, self.items = symbol, []
            self.focus_key = self.selected_id = None
            self.kind.set("전체")
        if cached:
            self.remember(cached)

    def remember(self, result):
        if result.symbol != self.symbol:
            return
        self.items = [
            item for item in self.items if not result.start <= item.event_date <= result.end
        ] + list(result.items)

    def collect(self):
        if self.app.history is not None:
            self.app.news_panel.collect(query=query_for_history(self.app.history), select_tab=False)

    def filter_changed(self):
        self.focus_key = None
        self.app.draw_plot(preserve_view=True)

    def reset(self):
        self.focus_key = None
        self.viewport = None
        self.refresh_view()

    def render(self, history):
        ax = self.app.event_ax
        self.artists, self.annotations, self.cursors = {}, [], []
        self.groups = group_events(self.items, history, self.kind.get())
        self.viewport = self.hover_key = None
        ax.set_ylim(-0.55, 2.85)
        ax.set_yticks(
            [0, 1, 2],
            labels=["뉴스", "공시", "실적"],
            fontfamily=self.app.chart_font,
            fontsize=self.app.chart_font_size(8),
        )
        ax.grid(axis="x", alpha=0.22)
        for kind, (y, _, color, marker) in LANES.items():
            points = [group for group in self.groups if group.kind == kind and group.end is None]
            if points:
                artist = ax.scatter(
                    [group.x for group in points],
                    [y] * len(points),
                    color=color,
                    marker=marker,
                    s=[32 + min(len(group.items), 30) * 2 for group in points],
                    picker=5,
                    zorder=4,
                )
                self.artists[artist] = points
        for group in self.groups:
            if group.end is not None:
                y, _, color, _ = LANES[group.kind]
                band = ax.axvspan(
                    group.number,
                    group.last_number,
                    ymin=(y + 0.38) / 3.4,
                    ymax=(y + 0.72) / 3.4,
                    facecolor=color,
                    alpha=0.3,
                    hatch="//",
                    picker=True,
                )
                self.artists[band] = [group]
        if not self.groups:
            ax.text(
                0.5,
                0.5,
                "표시 조건의 자료가 없습니다 · 그래프 뉴스 수집",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontfamily=self.app.chart_font,
                fontsize=self.app.chart_font_size(8),
                color="#666666",
            )
        self.hover = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(8, 14),
            textcoords="offset points",
            fontsize=self.app.chart_font_size(8),
            parse_math=False,
            fontfamily=self.app.chart_font,
            bbox={"boxstyle": "round", "fc": "#ffffff", "ec": "#888888", "alpha": 0.97},
            zorder=20,
        )
        self.hover.set_visible(False)
        self.hover.set_in_layout(False)
        self.refresh_view()

    def visible_groups(self):
        left, right = sorted(self.app.event_ax.get_xlim())
        return [
            group
            for group in self.groups
            if (group.last_number >= left if group.end is None else group.last_number > left)
            and group.number <= right
        ]

    def refresh_view(self):
        if not self.app.history or not self.hover:
            return
        limits = tuple(self.app.event_ax.get_xlim())
        signature = limits + (
            round(self.app.event_ax.bbox.width),
            round(self.app.event_ax.bbox.height),
        )
        if signature == self.viewport:
            return
        self.viewport = signature
        visible = self.visible_groups()
        if self.focus_key and self.focus_key not in {group.key for group in visible}:
            self.focus_key = None
        for annotation in self.annotations:
            annotation.remove()
        self.annotations = []
        # Keep the axis readable; all points and articles remain available on zoom/click.
        labelled = [
            group
            for group in visible
            if len(group.items) > 1 or group.end is not None or len(visible) <= 8
        ]
        if self.app.event_ax.bbox.height < 45:
            labelled = []
        if len(labelled) > 24:
            labelled = labelled[:: max(1, (len(labelled) + 23) // 24)][:24]
        label_edges = {}
        for group in labelled:
            label = f"{len(group.items)}건" if len(group.items) > 1 else group.items[0].title[:13]
            if group.end is not None:
                label = "시각 미상 · " + str(len(group.items))
            x = (
                (max(group.number, min(limits)) + min(group.last_number, max(limits))) / 2
                if group.end is not None
                else group.number
            )
            pixel = (
                (x - limits[0])
                / max(abs(limits[1] - limits[0]), 1e-10)
                * self.app.event_ax.bbox.width
            )
            width = sum(7 if ord(char) > 127 else 4 for char in label)
            if pixel - width / 2 < label_edges.get(group.kind, float("-inf")) + 7:
                continue
            label_edges[group.kind] = pixel + width / 2
            self.annotations.append(
                self.app.event_ax.annotate(
                    label,
                    (x, LANES[group.kind][0]),
                    xytext=(0, 8),
                    textcoords="offset points",
                    ha="center",
                    fontsize=self.app.chart_font_size(6.7),
                    parse_math=False,
                    fontfamily=self.app.chart_font,
                    clip_on=True,
                )
            )
        visible_items = chronological(
            [
                item
                for group in visible
                if self.focus_key is None or group.key == self.focus_key
                for item in group.items
            ]
        )
        self.tree.delete(*self.tree.get_children())
        self.rows = {item.id: item for item in visible_items[:1000]}
        timezone = query_for_history(self.app.history).timezone
        for item in self.rows.values():
            stamp = local_time(item, timezone)
            when = (
                stamp.strftime("%Y-%m-%d %H:%M:%S")
                if stamp is not None
                else item.event_date + " (시각 미상)"
            )
            self.tree.insert(
                "",
                "end",
                iid=item.id,
                values=(
                    when,
                    LANES[category(item)][1],
                    item.title,
                    item.publisher or ", ".join(item.sources),
                ),
            )
        count = sum(len(group.items) for group in self.groups)
        unit = (
            "날짜별 묶음"
            if self.app.history.metadata["interval"] in DAILY
            else "현지 시각 · 시각 미상은 하루 구간"
        )
        self.caption.set(
            f"{self.symbol} · 전체 {count:,}건 / 현재 목록 {len(visible_items):,}건 "
            f"(표 {len(self.rows):,}건) · {unit}"
        )
        if self.selected_id in self.rows:
            self.tree.selection_set(self.selected_id)
        elif self.rows:
            self.tree.selection_set(next(iter(self.rows)))
        else:
            self.selected_id = None
            self.preview.set("표시 범위의 수집 자료가 없습니다. 기간·필터·출처 상태를 확인하세요.")
        self.update_controls()
        self.app.canvas.draw_idle()

    def selected(self):
        keys = self.tree.selection()
        return self.rows.get(keys[0]) if keys else None

    def select_row(self):
        item = self.selected()
        if not item:
            return
        self.selected_id = item.id
        self.preview.set(f"{item.event_date} · {EVENT_TYPES[item.event_type]} · {item.title}")
        for cursor in self.cursors:
            cursor.remove()
        self.cursors = []
        group = next(
            (group for group in self.groups if any(row.id == item.id for row in group.items)), None
        )
        if group:
            for ax in (self.app.price_ax, self.app.volume_ax, self.app.event_ax):
                cursor = (
                    ax.axvspan(
                        group.number, group.last_number, color="#555555", alpha=0.12, zorder=1
                    )
                    if group.end is not None
                    else ax.axvline(
                        group.number, color="#555555", linewidth=0.85, alpha=0.65, zorder=3
                    )
                )
                self.cursors.append(cursor)
        self.update_controls()
        self.app.canvas.draw_idle()

    def on_pick(self, event):
        groups = self.artists.get(event.artist)
        if not groups or self.app.toolbar.mode:
            return
        indices = getattr(event, "ind", [0])
        if len(indices):
            if hasattr(self.app, "reveal_articles"):
                self.app.reveal_articles()
            self.focus_key = groups[int(indices[0])].key
            self.selected_id = groups[int(indices[0])].items[0].id
            self.viewport = None
            self.refresh_view()
            self.select_row()

    def hide_hover(self):
        if self.hover and self.hover.get_visible():
            self.hover.set_visible(False)
            self.hover_key = None
            self.app.canvas.draw_idle()

    def on_motion(self, event):
        if event.inaxes is not self.app.event_ax or self.app.toolbar.mode:
            self.hide_hover()
            return
        if time.monotonic() - self.last_motion < 0.05:
            return
        self.last_motion = time.monotonic()
        for artist, groups in self.artists.items():
            contains, info = artist.contains(event)
            if not contains:
                continue
            indices = info.get("ind", [0])
            group = groups[int(indices[0])]
            if group.key == self.hover_key:
                return
            self.hover_key = group.key
            self.hover.xy = (event.xdata, LANES[group.kind][0])
            text = f"{group.x:%Y-%m-%d} · {LANES[group.kind][1]} · {len(group.items)}건"
            text += "\n" + "\n".join("• " + item.title[:52] for item in group.items[:3])
            if group.end is not None:
                text += "\n발표 시각 미상: 날짜만 제공된 자료"
            self.hover.set_text(text)
            right = event.x > self.app.event_ax.bbox.x0 + self.app.event_ax.bbox.width * 0.55
            self.hover.set_ha("right" if right else "left")
            self.hover.set_position((-8 if right else 8, 14))
            self.hover.set_visible(True)
            self.app.canvas.draw_idle()
            return
        self.hide_hover()

    def open_original(self):
        item = self.selected()
        if item and safe_url(item.url):
            webbrowser.open(item.url)

    def details(self):
        item = self.selected()
        if not item:
            return
        window = tk.Toplevel(self.app.root)
        window.title("뉴스 · 공시 상세")
        window.geometry("720x440")
        window.transient(self.app.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        detail = tk.Text(window, wrap="word", width=1)
        detail.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scroll = ttk.Scrollbar(window, orient="vertical", command=detail.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=10)
        detail.configure(yscrollcommand=scroll.set)
        detail.insert(
            "1.0",
            f"{item.title}\n\n{item.company} · {item.symbol}\n날짜: {item.event_date}\n"
            f"제공 시각(UTC): {item.published_at or '시각 미상'}\n"
            f"시각 기준: {item.time_basis} / {item.time_precision}\n"
            f"분류: {EVENT_TYPES[item.event_type]}\n"
            f"논조 추정: {SENTIMENTS[item.sentiment]}\n근거: {item.rationale}\n"
            f"출처: {item.publisher} / {', '.join(item.sources)}\n\n"
            f"{item.summary or '제공 요약 없음'}\n\n"
            f"{item.body or '공개 본문 발췌 없음'}\n\n{item.url}",
        )
        detail.configure(state="disabled")
        ttk.Button(
            window,
            text="원문 열기",
            command=lambda: webbrowser.open(item.url) if safe_url(item.url) else None,
        ).grid(row=1, column=0, sticky="e", padx=10, pady=(0, 10))
