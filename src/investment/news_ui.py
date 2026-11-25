"""News timeline, source diagnostics, settings and chart integration."""

from __future__ import annotations

import copy
import json
import threading
import tkinter as tk
import webbrowser
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from .app_model import inclusive_request
from .news import EVENT_TYPES, SENTIMENTS, NewsStore, export_news, safe_url
from .news_collect import collect_news, import_archive, load_cached, timezone_for
from .news_content import PublicContent
from .news_providers import PROVIDERS, NewsQuery, NewsSettings

STATUS_LABELS = {
    "sampled": "검색 표본",
    "latest_only": "최신 중심",
    "partial": "일부 수집",
    "completed": "API 조회 완료",
    "not_configured": "설정 필요",
    "error": "오류",
    "cancelled": "취소",
    "unsupported_range": "기간 미지원",
    "cached": "저장 자료",
    "imported": "파일 가져옴",
}


class NewsPanel:
    def __init__(self, app):
        self.app = app
        self.result = None
        self.settings = NewsSettings.from_environment()
        self.company_aliases = {}
        self.cancel = threading.Event()
        self.cancel.set()
        self.rows = {}
        self.markers = None
        self.marker_dates = []
        self.date_filter = ""
        self.caption = tk.StringVar(value="회사와 기간을 선택한 뒤 뉴스/공시 수집을 누르세요.")
        self.notice = tk.StringVar(value="제공 범위·호출 한도에 따라 자료가 빠질 수 있습니다.")
        self.filter_text = tk.StringVar()
        self.filter_tone = tk.StringVar(value="전체")
        self.filter_type = tk.StringVar(value="전체")
        self.frame = ttk.Frame(app.notebook, padding=6)
        app.notebook.add(self.frame, text="뉴스 · 공시")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(3, weight=1)
        self._build()
        app.canvas.mpl_connect("pick_event", self.on_pick)

    def _build(self):
        toolbar = ttk.Frame(self.frame)
        toolbar.grid(row=0, column=0, sticky="ew")
        self.collect_button = ttk.Button(toolbar, text="뉴스/공시 수집", command=self.collect)
        self.collect_button.grid(row=0, column=0, padx=(0, 4))
        self.cancel_button = ttk.Button(toolbar, text="취소", command=self.stop, width=5)
        self.cancel_button.grid(row=0, column=1, padx=2)
        self.settings_button = ttk.Button(toolbar, text="출처 · API 설정", command=self.configure)
        self.settings_button.grid(row=0, column=2, padx=2)
        self.cache_button = ttk.Button(toolbar, text="저장 자료", command=self.cached)
        self.cache_button.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=(0, 4))
        self.import_button = ttk.Button(
            toolbar, text="BIGKinds/파일 가져오기", command=self.import_file
        )
        self.import_button.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(5, 0))
        self.export_button = ttk.Button(toolbar, text="뉴스 CSV", command=self.export)
        self.export_button.grid(row=0, column=3, rowspan=2, sticky="ns", padx=(6, 0))
        ttk.Label(self.frame, textvariable=self.caption, wraplength=620).grid(
            row=1, column=0, sticky="w", pady=5
        )
        filters = ttk.Frame(self.frame)
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        filters.columnconfigure(0, weight=1)
        ttk.Entry(filters, textvariable=self.filter_text, width=16).grid(
            row=0, column=0, sticky="ew"
        )
        for column, variable, values in (
            (1, self.filter_tone, ["전체", *SENTIMENTS.values()]),
            (2, self.filter_type, ["전체", *EVENT_TYPES.values()]),
        ):
            combo = ttk.Combobox(
                filters, textvariable=variable, values=values, state="readonly", width=10
            )
            combo.grid(row=0, column=column, padx=3)
            combo.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Button(filters, text="적용", width=5, command=self.refresh).grid(row=0, column=3)
        ttk.Button(filters, text="초기화", width=6, command=self.reset_filters).grid(
            row=0, column=4, padx=3
        )
        self.split = ttk.Notebook(self.frame)
        self.split.grid(row=3, column=0, sticky="nsew")
        listing = ttk.Frame(self.split)
        detail = ttk.Frame(self.split)
        coverage = ttk.Frame(self.split)
        self.split.add(listing, text="기사 목록")
        self.split.add(detail, text="선택 기사 · 내용")
        self.split.add(coverage, text="출처별 수집 상태")
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        columns = ("date", "type", "tone", "publisher", "title")
        self.tree = ttk.Treeview(
            listing, columns=columns, show="headings", selectmode="browse", height=7
        )
        for key, label, width in (
            ("date", "현지 날짜", 95),
            ("type", "분류", 85),
            ("tone", "논조 추정", 90),
            ("publisher", "출처", 120),
            ("title", "기사/공시 제목", 550),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=60, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self._scrollbars(listing, self.tree)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.details())
        self.tree.bind("<Double-1>", lambda _: self.open_original())
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(1, weight=1)
        actions = ttk.Frame(detail)
        actions.grid(row=0, column=0, sticky="ew", pady=3)
        for column, (label, command) in enumerate(
            (
                ("원문 열기", self.open_original),
                ("공개 본문 추가", self.enrich_selected),
                ("분류 수정", self.edit_label),
            )
        ):
            ttk.Button(actions, text=label, command=command).grid(row=0, column=column, padx=3)
        self.detail = tk.Text(detail, wrap="word", height=6, width=1, state="disabled")
        self.detail.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(detail, orient="vertical", command=self.detail.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=scrollbar.set)
        coverage.columnconfigure(0, weight=1)
        coverage.rowconfigure(0, weight=1)
        columns = ("source", "status", "count", "requests", "message")
        self.coverage = ttk.Treeview(coverage, columns=columns, show="headings", height=6)
        for key, label, width in (
            ("source", "출처", 140),
            ("status", "상태", 100),
            ("count", "확보", 60),
            ("requests", "요청", 60),
            ("message", "범위/제한/오류", 800),
        ):
            self.coverage.heading(key, text=label)
            self.coverage.column(key, width=width, minwidth=40, stretch=False)
        self.coverage.grid(row=0, column=0, sticky="nsew")
        self._scrollbars(coverage, self.coverage)
        ttk.Label(self.frame, textvariable=self.notice, wraplength=620).grid(
            row=4, column=0, sticky="w", pady=3
        )
        self.update_controls()

    @staticmethod
    def _scrollbars(parent, tree):
        ys = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)

    def query(self):
        selected = self.app.results.selection()
        if not selected or selected[0] not in self.app.companies:
            raise ValueError("검색 결과에서 회사를 먼저 선택하세요.")
        company = self.app.companies[selected[0]]
        start, end = self.app.start.get().strip(), self.app.end.get().strip()
        inclusive_request(company.symbol, start, end, "1d")
        timezone_name = timezone_for(company)
        if self.app.history and self.app.history.metadata["symbol"] == company.symbol:
            timezone_name = self.app.history.metadata.get("exchange_timezone") or timezone_name
        return NewsQuery(company, start, end, timezone_name)

    def effective_settings(self, query):
        return replace(self.settings, aliases=self.company_aliases.get(query.company.symbol, ""))

    def update_controls(self):
        enabled = bool(self.app.results.selection()) and not self.app.busy
        for button in (self.collect_button, self.cache_button, self.import_button):
            button.state(["!disabled"] if enabled else ["disabled"])
        self.settings_button.state(["disabled"] if self.app.busy else ["!disabled"])
        self.export_button.state(
            ["!disabled"] if self.result and not self.app.busy else ["disabled"]
        )
        self.cancel_button.state(
            ["!disabled"] if self.app.busy and not self.cancel.is_set() else ["disabled"]
        )

    def collect(self):
        if self.app.busy:
            return
        try:
            query = self.query()
        except ValueError as exc:
            messagebox.showerror("조회 조건", str(exc), parent=self.app.root)
            return
        self.cancel.clear()
        settings = self.effective_settings(query)
        self.app._run(
            lambda: collect_news(
                query,
                settings,
                self.app.data_dir,
                self.cancel,
                lambda message: self.app.events.put((None, message, None)),
            ),
            self.show_result,
            "뉴스/공시 수집 중…",
        )

    def stop(self):
        self.cancel.set()
        self.app.status.set(
            "취소 요청됨. 진행 중인 네트워크 요청이 끝나면 확보한 자료를 표시합니다."
        )
        self.cancel_button.state(["disabled"])

    def cached(self):
        try:
            query = self.query()
        except ValueError as exc:
            messagebox.showerror("조회 조건", str(exc), parent=self.app.root)
            return
        self.app._run(
            lambda: load_cached(query, self.app.data_dir), self.show_result, "저장 자료 조회 중…"
        )

    def import_file(self):
        if self.app.busy:
            return
        try:
            query = self.query()
        except ValueError as exc:
            messagebox.showerror("조회 조건", str(exc), parent=self.app.root)
            return
        filename = filedialog.askopenfilename(
            parent=self.app.root,
            title="선택 회사의 BIGKinds/기사 자료 가져오기",
            filetypes=[("Excel / CSV", "*.xlsx *.csv")],
        )
        if filename:
            self.app._run(
                lambda: import_archive(
                    Path(filename), query, self.effective_settings(query), self.app.data_dir
                ),
                self.show_result,
                "기사 파일을 읽고 회사/기간 조건을 확인하는 중…",
            )

    def show_result(self, result):
        self.cancel.set()
        self.result = result
        self.split.select(0)
        self.date_filter = ""
        self.caption.set(
            f"뉴스 표시 중: {result.company} ({result.symbol}) · {result.start} ~ {result.end} · "
            f"전체 {len(result.items):,}건"
        )
        self.coverage.delete(*self.coverage.get_children())
        for report in result.reports:
            self.coverage.insert(
                "",
                "end",
                values=(
                    report.source,
                    STATUS_LABELS.get(report.status, report.status),
                    report.fetched,
                    report.requests,
                    report.message,
                ),
            )
        self.notice.set(
            " ".join(result.notices)
            or "검색/제공 범위 내 자료입니다. 긍정·부정은 실제 주가 영향이 아닌 추정입니다."
        )
        self.refresh()
        self.app.draw_plot()
        self.app.notebook.select(self.frame)
        self.app.status.set(
            f"뉴스/공시 {len(result.items):,}건 표시. "
            "출처별 수집 상태 탭에서 제한·오류를 확인하세요."
        )
        self.update_controls()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        if not self.result:
            return
        search, tone, kind = (
            self.filter_text.get().casefold(),
            self.filter_tone.get(),
            self.filter_type.get(),
        )
        filtered = [
            item
            for item in reversed(self.result.items)
            if (not self.date_filter or item.event_date == self.date_filter)
            and (not search or search in (item.title + " " + item.summary).casefold())
            and (tone == "전체" or SENTIMENTS[item.sentiment] == tone)
            and (kind == "전체" or EVENT_TYPES[item.event_type] == kind)
        ]
        for item in filtered[:1000]:
            self.rows[item.id] = item
            self.tree.insert(
                "",
                "end",
                iid=item.id,
                values=(
                    item.event_date,
                    EVENT_TYPES[item.event_type],
                    SENTIMENTS[item.sentiment],
                    item.publisher or ", ".join(item.sources),
                    item.title,
                ),
            )
        self.caption.set(
            f"뉴스 표시 중: {self.result.company} ({self.result.symbol}) · "
            f"전체 {len(self.result.items):,}건 / 필터 {len(filtered):,}건 / "
            f"표 최근 {min(len(filtered), 1000):,}건"
        )
        if self.rows:
            self.tree.selection_set(next(iter(self.rows)))
        self.details()

    def reset_filters(self):
        self.date_filter = ""
        self.filter_text.set("")
        self.filter_tone.set("전체")
        self.filter_type.set("전체")
        self.refresh()

    def selected(self):
        keys = self.tree.selection()
        return self.rows.get(keys[0]) if keys else None

    def details(self):
        item = self.selected()
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if item:
            self.detail.insert(
                "end",
                f"{item.title}\n{item.company} · {item.symbol}\n"
                f"현지 날짜: {item.event_date} / UTC 시각: {item.published_at or '시각 미상'}\n"
                f"시각 기준: {item.time_basis} / 정밀도: {item.time_precision}\n"
                f"출처: {', '.join(item.sources)} / 언론사: {item.publisher}\n"
                f"분류: {EVENT_TYPES[item.event_type]} / 논조: {SENTIMENTS[item.sentiment]}\n"
                f"방법: {item.label_method} / 규칙 점수(정확도 아님): {item.confidence:.2f}\n"
                f"근거: {item.rationale}\n"
                f"제공자 감성: {item.provider_sentiment or '없음'}\n관련성: {item.relevance}\n"
                f"수집: {item.collected_at} / 최근 확인: {item.last_seen_at}\n"
                f"원문 발행: {item.original_published_at or '미확인'}\n"
                f"원문 수정: {item.original_updated_at or '미확인'}\n"
                f"URL: {item.url}\n추가 URL: {'; '.join(item.alternate_urls)}\n\n"
                "[출처별 시각/관측 기록]\n"
                f"{json.dumps(item.observations, ensure_ascii=False, indent=2)}\n\n"
                f"[제공된 요약]\n{item.summary or '요약 미제공'}\n\n"
                f"[공개 본문 발췌 — {item.body_status}]\n"
                f"{item.body or '본문이 없거나 아직 수집하지 않았습니다.'}",
            )
        self.detail.configure(state="disabled")

    def open_original(self):
        item = self.selected()
        if item and safe_url(item.url):
            webbrowser.open(item.url)

    def enrich_selected(self):
        item = self.selected()
        if item and not self.app.busy:
            self.cancel.clear()
            snapshot = copy.deepcopy(item)

            def work():
                enriched = PublicContent(self.cancel, self.settings.sec_contact).enrich(snapshot)
                NewsStore(self.app.data_dir / "news.sqlite").update_item(enriched)
                return enriched

            def done(enriched):
                self.cancel.set()
                for index, old in enumerate(self.result.items):
                    if old.id == enriched.id:
                        self.result.items[index] = enriched
                self.refresh()
                if enriched.id in self.rows:
                    self.tree.selection_set(enriched.id)
                    self.details()
                self.app.status.set(f"본문 수집 결과: {enriched.body_status}")

            self.app._run(work, done, "선택 기사의 공개 본문 확인 중…")

    def edit_label(self):
        item = self.selected()
        if not item or self.app.busy:
            return
        window = tk.Toplevel(self.app.root)
        window.title("논조 분류 수정")
        window.transient(self.app.root)
        window.grab_set()
        tone = tk.StringVar(value=SENTIMENTS[item.sentiment])
        reason = tk.StringVar(value=item.rationale)
        ttk.Label(window, text="실제 주가 영향과 구분해서 기록하세요.").pack(padx=12, pady=8)
        ttk.Combobox(
            window, textvariable=tone, values=list(SENTIMENTS.values()), state="readonly"
        ).pack(padx=12, fill="x")
        ttk.Entry(window, textvariable=reason, width=55).pack(padx=12, pady=8, fill="x")

        def apply():
            item.sentiment = next(key for key, value in SENTIMENTS.items() if value == tone.get())
            item.label_method, item.confidence, item.rationale = "manual", 1.0, reason.get()
            NewsStore(self.app.data_dir / "news.sqlite").update_item(item)
            self.refresh()
            self.app.draw_plot()
            window.destroy()

        ttk.Button(window, text="저장", command=apply).pack(pady=(0, 10))

    def export(self):
        if self.result and not self.app.busy:
            snapshot = self.result
            self.app._run(
                lambda: export_news(snapshot, self.app.data_dir),
                lambda paths: self.app.status.set(f"뉴스 CSV 저장: {paths[0]}"),
                "뉴스 전체 자료 내보내는 중…",
            )

    def draw_overlay(self):
        self.markers = None
        history = self.app.history
        if not self.result or not history or self.result.symbol != history.metadata["symbol"]:
            return
        first, last = history.data["date"].iloc[[0, -1]]
        days = {}
        for item in self.result.items:
            if first <= item.event_date <= last:
                days.setdefault(item.event_date, []).append(item.sentiment)
        self.marker_dates = sorted(days)
        if not self.marker_dates:
            return
        colors = []
        for day in self.marker_dates:
            counts = Counter(days[day])
            colors.append(
                "#b63232"
                if counts["negative"] > counts["positive"]
                else "#23854b"
                if counts["positive"] > counts["negative"]
                else "#866b24"
            )
        self.markers = self.app.price_ax.scatter(
            pd.to_datetime(self.marker_dates),
            [0.98] * len(days),
            c=colors,
            marker="v",
            s=28,
            transform=self.app.price_ax.get_xaxis_transform(),
            picker=5,
            zorder=6,
            label="News/events (click)",
        )
        self.app.price_ax.legend(loc="lower left", fontsize=8)

    def on_pick(self, event):
        if event.artist is self.markers and len(event.ind):
            self.date_filter = self.marker_dates[int(event.ind[0])]
            self.refresh()
            self.split.select(0)
            self.app.notebook.select(self.frame)

    def configure(self):
        window = tk.Toplevel(self.app.root)
        window.title("뉴스 출처 · API 설정")
        window.transient(self.app.root)
        window.grab_set()
        window.columnconfigure(1, weight=1)
        ttk.Label(
            window,
            text="키는 이번 실행에서만 사용합니다. 환경변수에서도 읽습니다.\n"
            "무료 공개 출처는 키 없이 동작합니다. SEC에는 실제 연락 이메일을 입력하세요.",
            wraplength=600,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=8)
        sources = {}
        checks = ttk.Frame(window)
        checks.grid(row=1, column=0, columnspan=2, padx=12, sticky="ew")
        for index, (key, name) in enumerate(PROVIDERS.items()):
            sources[key] = tk.BooleanVar(value=key in self.settings.sources)
            ttk.Checkbutton(checks, text=name, variable=sources[key]).grid(
                row=index // 3, column=index % 3, sticky="w", padx=6
            )
        fields = {}
        entries = (
            ("dart_key", "DART API 키"),
            ("naver_id", "Naver Client ID"),
            ("naver_secret", "Naver Client Secret"),
            ("finnhub_key", "Finnhub 키"),
            ("alpha_key", "Alpha Vantage 키(유료 권한)"),
            ("sec_contact", "SEC 연락 이메일"),
            ("max_requests", "출처별 최대 요청 수 (1~300)"),
            ("max_items", "출처별 최대 자료 수 (1~50,000)"),
            ("body_limit", "공개 본문 추가 수집 (0~50건)"),
        )
        for row, (key, title) in enumerate(entries, 2):
            fields[key] = tk.StringVar(value=str(getattr(self.settings, key)))
            ttk.Label(window, text=title).grid(row=row, column=0, sticky="w", padx=12, pady=2)
            ttk.Entry(
                window,
                textvariable=fields[key],
                width=42,
                show="*" if key.endswith(("key", "secret")) else "",
            ).grid(row=row, column=1, sticky="ew", padx=12, pady=2)
        try:
            symbol = self.query().company.symbol
        except ValueError:
            symbol = ""
        aliases = tk.StringVar(value=self.company_aliases.get(symbol, ""))
        ttk.Label(window, text="선택 회사 추가 별칭 (쉼표 구분)").grid(
            row=11, column=0, padx=12, sticky="w"
        )
        ttk.Entry(window, textvariable=aliases).grid(row=11, column=1, padx=12, sticky="ew", pady=3)
        ttk.Label(window, text="추가 공개 RSS/Atom URL\n(회사명으로 필터링)").grid(
            row=12, column=0, padx=12, sticky="nw"
        )
        feeds = tk.Text(window, width=42, height=3)
        feeds.grid(row=12, column=1, padx=12, sticky="ew", pady=3)
        feeds.insert("1.0", "\n".join(self.settings.rss_urls))

        def apply():
            try:
                values = {key: variable.get().strip() for key, variable in fields.items()}
                for key, maximum in (
                    ("max_requests", 300),
                    ("max_items", 50000),
                    ("body_limit", 50),
                ):
                    values[key] = int(values[key])
                    if not (0 if key == "body_limit" else 1) <= values[key] <= maximum:
                        raise ValueError
                self.settings = NewsSettings(
                    **values,
                    sources=tuple(key for key, var in sources.items() if var.get()),
                    rss_urls=tuple(
                        value.strip()
                        for value in feeds.get("1.0", "end").splitlines()
                        if safe_url(value)
                    ),
                )
                if symbol:
                    self.company_aliases[symbol] = aliases.get().strip()
            except ValueError:
                messagebox.showerror(
                    "설정 확인", "요청 수·자료 수·본문 수의 숫자 범위를 확인하세요.", parent=window
                )
                return
            window.destroy()

        ttk.Button(window, text="이번 실행에 적용", command=apply).grid(
            row=13, column=0, columnspan=2, pady=10
        )
