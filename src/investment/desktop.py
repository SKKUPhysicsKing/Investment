"""Console-free desktop entry, GUI startup feedback and native Windows shortcuts."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from importlib.metadata import version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk

from .desktop_update import (
    BuildInfo,
    Candidate,
    activate,
    application_lock,
    atomic_json,
    cache_root,
    choose_build,
    fallback,
    mark_failed,
    read_json,
    restart,
    valid_revision,
)


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2] / "build"))


def build_info():
    payload = read_json(resource_root() / "desktop-build.json")
    try:
        return BuildInfo(**payload)
    except TypeError:
        return BuildInfo(version("investment-stock-data"), "source", "")


def windows_identity():
    if sys.platform == "win32":
        with_optional = (
            lambda: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Investment.App"),
            lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
        )
        for action in with_optional:
            try:
                action()
            except (AttributeError, OSError):
                pass


def set_icon(root):
    icon = resource_root() / "assets" / "investment.ico"
    if sys.platform == "win32" and icon.is_file():
        root.iconbitmap(str(icon))


def create_shortcuts(executable, home, *, directories=None):
    """Use Windows COM directly; do not start cmd.exe, PowerShell or a script host."""
    if sys.platform != "win32":
        return []
    import pythoncom
    from win32com.client.dynamic import Dispatch

    pythoncom.CoInitialize()
    paths = []
    try:
        shell = Dispatch("WScript.Shell")
        if directories is None:
            directories = (
                Path(shell.SpecialFolders("Desktop")),
                Path(shell.SpecialFolders("Programs")) / "Investment",
            )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "Investment.lnk"
            shortcut = shell.CreateShortcut(str(path))
            shortcut.TargetPath = str(executable)
            shortcut.Arguments = subprocess.list2cmdline(["--app-home", str(home)])
            shortcut.WorkingDirectory = str(home)
            shortcut.IconLocation = str(executable) + ",0"
            shortcut.Description = "Investment — 주가·뉴스 시계열"
            shortcut.Save()
            paths.append(path)
    finally:
        pythoncom.CoUninitialize()
    return paths


class Startup:
    def __init__(self, root):
        self.root = root
        self.closed = False
        self.result = None
        self.cancel = threading.Event()
        self.events = queue.Queue()
        root.title("Investment")
        root.geometry("470x155")
        root.resizable(False, False)
        set_icon(root)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Investment", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.status = tk.StringVar(value="앱을 준비하는 중…")
        ttk.Label(frame, textvariable=self.status, wraplength=425).pack(anchor="w", pady=7)
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x")
        self.progress.start(15)
        self.skip_button = ttk.Button(frame, text="업데이트 건너뛰고 실행", command=self.skip)
        self.skip_button.pack(anchor="e", pady=(7, 0))
        root.update_idletasks()
        root.geometry(f"{max(470, frame.winfo_reqwidth())}x{max(155, frame.winfo_reqheight())}")
        root.protocol("WM_DELETE_WINDOW", self.close)

    def skip(self):
        self.cancel.set()
        self.skip_button.state(["disabled"])
        self.status.set("설치된 앱을 여는 중…")

    def close(self):
        self.closed = True
        self.cancel.set()
        self.root.quit()

    def run(self, work):
        def worker():
            try:
                self.events.put(
                    (True, work(self.cancel, lambda text: self.events.put((False, text))))
                )
            except Exception as exc:
                self.events.put((True, exc))

        def poll():
            try:
                while True:
                    done, value = self.events.get_nowait()
                    if done:
                        self.result = value
                        self.root.quit()
                        return
                    self.status.set(value)
            except queue.Empty:
                pass
            if not self.closed:
                self.root.after(80, poll)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, poll)
        self.root.mainloop()
        self.progress.stop()
        for child in self.root.winfo_children():
            child.destroy()
        self.root.resizable(True, True)
        if isinstance(self.result, Exception):
            raise self.result
        return None if self.closed else self.result


def configure_logging(cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "startup.log"
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("investment.desktop")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    return logger, path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Investment Windows app")
    default_home = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--app-home", type=Path, default=default_home)
    parser.add_argument("--no-update", action="store_true")
    parser.add_argument("--run-app", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup-notice", default="", help=argparse.SUPPRESS)
    parser.add_argument("--no-shortcuts", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = args.app_home.resolve()
    info = build_info()
    cache = cache_root(home)
    root = None
    logger = logging.getLogger("investment.desktop")
    handoff = None
    try:
        home.mkdir(parents=True, exist_ok=True)
        logger, log_path = configure_logging(cache)
        windows_identity()
        with application_lock(home, wait=5 if args.run_app else 0):
            root = tk.Tk()
            set_icon(root)
            current = Candidate(Path(sys.executable).resolve(), info)
            selected = current
            if getattr(sys, "frozen", False) and not args.run_app and not args.smoke_result:
                startup = Startup(root)
                selected = startup.run(
                    lambda cancel, progress: choose_build(
                        cache, current, cancel, progress, offline=args.no_update
                    )
                )
                if selected is None:
                    root.destroy()
                    return 0
            if selected.executable.resolve() != current.executable:
                handoff = selected
                root.destroy()
            else:
                from .gui import InvestmentApp

                os.environ["INVESTMENT_REVISION"] = info.revision
                app = InvestmentApp(root, home / "data")
                set_icon(root)

                def callback_error(kind, value, trace):
                    logger.error("GUI callback failed", exc_info=(kind, value, trace))
                    messagebox.showerror("Investment", f"{value}\n\n기록: {log_path}", parent=root)

                root.report_callback_exception = callback_error
                if selected.notice or args.startup_notice:
                    app.status.set(selected.notice or args.startup_notice)
                if args.smoke_result:
                    root.update()
                    console = (
                        bool(ctypes.windll.kernel32.GetConsoleWindow())
                        if sys.platform == "win32"
                        else False
                    )
                    atomic_json(
                        args.smoke_result,
                        {
                            "frozen": bool(getattr(sys, "frozen", False)),
                            "console_window": console,
                            "version": info.version,
                            "revision": info.revision,
                            "news_tab": bool(app.news_panel.frame.winfo_exists()),
                            "data_dir": str(app.data_dir),
                            "icon": (resource_root() / "assets" / "investment.ico").is_file(),
                        },
                    )
                    app.close()
                    return 0
                if getattr(sys, "frozen", False) and valid_revision(info.revision):
                    try:
                        target = activate(cache, current.executable, info)
                        if not args.no_shortcuts:
                            create_shortcuts(target, home)
                    except Exception:
                        logger.exception("Could not register installed app or shortcuts")
                        app.status.set("앱을 열었습니다. 아이콘 등록 기록: " + str(log_path))
                logger.info("Opened %s %s; home=%s", info.version, info.revision, home)
                root.mainloop()
        # Release the shared launcher lock before the independent updated app opens.
        if handoff:
            restart(handoff, home)
        return 0
    except Exception as exc:
        logger.exception("Desktop startup failed")
        if args.run_app:
            mark_failed(cache, info.revision)
            previous = fallback(
                cache,
                Candidate(Path(sys.executable).resolve(), info),
                exclude_revision=info.revision,
            )
            if previous:
                previous.notice = "새 버전 시작에 실패해 이전 앱을 열었습니다."
                try:
                    if root:
                        root.destroy()
                    root = None
                    restart(previous, home)
                    return 0
                except Exception:
                    logger.exception("Could not start the previous app")
        elif handoff:
            mark_failed(cache, handoff.info.revision)
            return main(
                [
                    "--run-app",
                    "--app-home",
                    str(home),
                    "--startup-notice",
                    "새 버전을 실행하지 못해 설치된 앱을 열었습니다.",
                ]
            )
        if args.smoke_result:
            atomic_json(args.smoke_result, {"error": str(exc)})
        else:
            messagebox.showerror("Investment 시작 실패", str(exc))
        return 2
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
