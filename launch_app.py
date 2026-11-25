"""Double-click bootstrap: stdlib only, no git or PowerShell activation required.

Each GitHub revision gets its own installed environment. A new revision becomes
active only after installation and an import smoke check complete successfully.
The previous revision and all exported data are preserved on an update failure.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY = "SKKUPhysicsKing/Investment"
HEAD_URL = f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main"
MAX_ARCHIVE = 20 * 1024 * 1024
RUNTIME_TAG = (
    f"py{sys.version_info.major}{sys.version_info.minor}-{sys.platform}-{platform.machine()}"
)
WINDOWS = sys.platform == "win32"


def cache_root(home: Path) -> Path:
    """Keep Windows dependency paths independent of the ZIP extraction depth."""
    if WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        identity = str(home.resolve()).casefold() + "\0" + RUNTIME_TAG
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        return local / "Investment" / key
    return home / ".investment-app" / RUNTIME_TAG


def versions_dir(cache: Path) -> Path:
    return cache / ("v" if WINDOWS else "versions")


def installed_runtime(cache: Path, versions: Path) -> tuple[Path, str] | None:
    state = read_json(cache / "state.json")
    for key in ("active", "previous"):
        revision = state.get(key)
        if valid_revision(revision) and ready(versions / revision, revision):
            return versions / revision, revision
    return None


def valid_revision(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value))


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remote_revision() -> str:
    request = urllib.request.Request(
        HEAD_URL,
        headers={
            "User-Agent": "Investment-App-Updater",
            "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read(1024 * 1024))
    revision = payload.get("object", {}).get("sha")
    if not valid_revision(revision):
        raise RuntimeError("GitHub returned an invalid revision.")
    return revision


def download_archive(revision: str, target: Path):
    if not valid_revision(revision):
        raise ValueError("Invalid revision.")
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{revision}"
    request = urllib.request.Request(url, headers={"User-Agent": "Investment-App-Updater"})
    size = 0
    with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as handle:
        while chunk := response.read(128 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE:
                raise RuntimeError("Update archive exceeds the size limit.")
            handle.write(chunk)


def extract_archive(archive_path: Path, destination: Path, revision: str):
    """Extract only regular files below GitHub's expected repository root."""
    root_name = f"Investment-{revision}"
    with zipfile.ZipFile(archive_path) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_ARCHIVE * 5:
            raise RuntimeError("Expanded update archive exceeds the size limit.")
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (
                not path.parts
                or path.parts[0] != root_name
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or ":" in info.filename
            ):
                raise RuntimeError("Invalid update archive path.")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError("Symlinks are not allowed in update archives.")
            if len(path.parts) == 1:
                continue
            target = destination.joinpath(*path.parts[1:])
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    if not (destination / "pyproject.toml").is_file():
        raise RuntimeError("Update does not contain a Python project.")


def python_path(runtime: Path) -> Path:
    return runtime / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ready(runtime: Path, revision: str) -> bool:
    return (
        valid_revision(revision)
        and python_path(runtime).is_file()
        and read_json(runtime / "ready.json").get("revision") == revision
    )


def install_revision(runtime: Path, revision: str):
    if ready(runtime, revision):
        return
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    try:
        archive = runtime / "source.zip"
        print(f"Downloading {revision[:8]}…", flush=True)
        download_archive(revision, archive)
        source = runtime / "app"
        extract_archive(archive, source, revision)
        archive.unlink()
        print("Installing app dependencies. First launch can take several minutes…", flush=True)
        # Create the venv at its final path: installed virtual environments are not portable.
        venv.EnvBuilder(with_pip=True).create(runtime / "venv")
        executable = python_path(runtime)
        subprocess.run(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--timeout",
                "30",
                "--retries",
                "1",
                str(source) + "[gui]",
            ],
            check=True,
        )
        subprocess.run(
            [
                str(executable),
                "-c",
                "import tkinter; from investment.gui import InvestmentApp; "
                "from investment.search import search_companies",
            ],
            check=True,
            timeout=90,
        )
        atomic_json(runtime / "ready.json", {"revision": revision})
    except BaseException:
        # Removing only this incomplete managed slot cannot affect the active app or data.
        shutil.rmtree(runtime, ignore_errors=True)
        raise


def choose_runtime(home: Path, *, offline: bool = False) -> tuple[Path, str]:
    cache = cache_root(home)
    versions = versions_dir(cache)
    state_path = cache / "state.json"
    fallback = installed_runtime(cache, versions)
    active = fallback[1] if fallback else None
    if fallback is None and WINDOWS:
        # Virtual environments cannot be moved. Keep an already working legacy
        # installation as a fallback, and install updates at the new short path.
        legacy = home / ".investment-app" / RUNTIME_TAG
        fallback = installed_runtime(legacy, legacy / "versions")
    try:
        if offline:
            if not fallback:
                raise RuntimeError("No installed app is available for offline startup.")
            return fallback
        print("Checking GitHub for updates…", flush=True)
        latest = remote_revision()
        if latest != active:
            install_revision(versions / latest, latest)
            atomic_json(state_path, {"active": latest, "previous": active})
            # Keep active and previous environments; do not accumulate one venv per commit.
            for slot in versions.iterdir():
                if (
                    slot.is_dir()
                    and valid_revision(slot.name)
                    and slot.name not in (active, latest)
                ):
                    shutil.rmtree(slot, ignore_errors=True)
            active = latest
        else:
            print("Already up to date.", flush=True)
        return versions / active, active
    except Exception as exc:
        if fallback:
            print(
                f"Update unavailable: {exc}\nStarting installed version {fallback[1][:8]}.",
                flush=True,
            )
            return fallback
        raise RuntimeError(
            f"App setup did not complete and no installed version is available: {exc}"
        ) from exc


@contextlib.contextmanager
def launcher_lock(home: Path):
    path = home / ".investment-app" / "launcher.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Investment is already running in this folder.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start Investment with automatic GitHub updates")
    parser.add_argument(
        "--no-update", action="store_true", help="Start the installed version directly"
    )
    parser.add_argument(
        "--prepare-only", action="store_true", help="Install/check the app without opening a window"
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="App folder; exports go into its data subfolder",
    )
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):  # noqa: UP036 - bootstrap also runs before package installation
        print("Python 3.10 or later is required.", file=sys.stderr)
        return 2
    home = args.app_dir.resolve()
    try:
        with launcher_lock(home):
            runtime, revision = choose_runtime(home, offline=args.no_update)
            if args.prepare_only:
                print(f"Ready: {revision} -> {runtime}")
                return 0
            environment = os.environ.copy()
            environment["INVESTMENT_REVISION"] = revision
            environment["PYTHONUTF8"] = "1"
            print("Opening Investment…", flush=True)
            return subprocess.run(
                [
                    str(python_path(runtime)),
                    "-m",
                    "investment.gui",
                    "--data-dir",
                    str(home / "data"),
                ],
                cwd=home,
                env=environment,
            ).returncode
    except Exception as exc:
        print(f"Investment startup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
