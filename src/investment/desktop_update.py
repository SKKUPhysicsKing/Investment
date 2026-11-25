"""Verified, per-user updates for the self-contained Windows desktop executable."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

REPOSITORY = "SKKUPhysicsKing/Investment"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_EXE = 384 * 1024 * 1024


def valid_revision(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value))


def read_json(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, ensure_ascii=False)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


@dataclass(frozen=True)
class BuildInfo:
    version: str
    revision: str
    built_at: str

    @property
    def order(self):
        try:
            return datetime.fromisoformat(self.built_at.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return 0


@dataclass
class Candidate:
    executable: Path
    info: BuildInfo
    notice: str = ""


def cache_root(home):
    local = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    key = hashlib.sha256(str(home.resolve()).casefold().encode()).hexdigest()[:12]
    return local / "Investment" / "desktop" / key


def slot(cache, revision):
    if not valid_revision(revision):
        raise ValueError("잘못된 앱 버전 식별자입니다.")
    return cache / "v" / revision


def installed(cache, revision):
    if not valid_revision(revision):
        return None
    directory = slot(cache, revision)
    metadata = read_json(directory / "ready.json")
    executable = directory / "Investment.exe"
    try:
        if (
            metadata.get("revision") != revision
            or executable.stat().st_size != metadata.get("size")
            or digest(executable) != metadata.get("sha256")
        ):
            return None
        info = BuildInfo(**metadata["build"])
        return Candidate(executable, info) if info.revision == revision else None
    except (OSError, TypeError, KeyError):
        return None


def fallback(cache, current, *, exclude_revision=None):
    candidates = [current]
    state = read_json(cache / "state.json")
    for key in ("active", "previous"):
        candidate = installed(cache, state.get(key))
        if candidate:
            candidates.append(candidate)
    return max(
        (candidate for candidate in candidates if candidate.info.revision != exclude_revision),
        key=lambda candidate: candidate.info.order,
        default=None,
    )


def trusted_asset(url):
    parts = urlsplit(str(url))
    return (
        parts.scheme == "https"
        and parts.netloc == "github.com"
        and not parts.username
        and parts.path.startswith(f"/{REPOSITORY}/releases/download/")
        and not parts.query
        and not parts.fragment
    )


def release_info(payload):
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("공개 정식 버전이 아닙니다.")
    revision = str(payload.get("tag_name", "")).removeprefix("desktop-")
    if not valid_revision(revision):
        raise ValueError("앱 배포 태그를 확인할 수 없습니다.")
    assets = {asset["name"]: asset for asset in payload.get("assets", [])}
    binary, checksum = assets["Investment.exe"], assets["Investment.exe.sha256"]
    if not all(trusted_asset(asset.get("browser_download_url")) for asset in (binary, checksum)):
        raise ValueError("저장소의 앱 다운로드 주소가 아닙니다.")
    if not 0 < int(binary["size"]) <= MAX_EXE:
        raise ValueError("앱 파일 크기 제한을 초과했습니다.")
    info = BuildInfo(payload.get("name", "Investment"), revision, payload["published_at"])
    return info, binary, checksum


def request_bytes(url, limit, cancel, progress=lambda value: None):
    if cancel.is_set():
        raise RuntimeError("업데이트를 건너뛰었습니다.")
    with requests.get(
        url,
        headers={"User-Agent": "Investment-Desktop-Updater", "Cache-Control": "no-cache"},
        timeout=(5, 12),
        stream=True,
    ) as response:
        response.raise_for_status()
        size = 0
        for chunk in response.iter_content(256 * 1024):
            if cancel.is_set():
                raise RuntimeError("업데이트를 건너뛰었습니다.")
            size += len(chunk)
            if size > limit:
                raise ValueError("다운로드 크기 제한을 초과했습니다.")
            progress(size)
            yield chunk


def download_release(cache, info, binary, checksum, cancel, progress):
    checksum_text = b"".join(request_bytes(checksum["browser_download_url"], 4096, cancel)).decode(
        "ascii"
    )
    expected = checksum_text.split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("올바른 SHA-256 체크섬이 아닙니다.")
    cached = installed(cache, info.revision)
    if cached and digest(cached.executable) == expected:
        return cached
    directory = slot(cache, info.revision)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=directory, suffix=".part", delete=False) as f:
        temporary = Path(f.name)
        try:
            for chunk in request_bytes(
                binary["browser_download_url"],
                min(int(binary["size"]), MAX_EXE),
                cancel,
                lambda size: progress(f"새 버전 다운로드: {size / 1024 / 1024:.1f} MB"),
            ):
                f.write(chunk)
        except BaseException:
            f.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if temporary.stat().st_size != int(binary["size"]) or digest(temporary) != expected:
            raise ValueError("앱 파일 무결성 검사에 실패했습니다.")
        with temporary.open("rb") as f:
            if f.read(2) != b"MZ":
                raise ValueError("Windows 앱 파일이 아닙니다.")
        temporary.replace(directory / "Investment.exe")
        atomic_json(
            directory / "ready.json",
            {
                "revision": info.revision,
                "sha256": expected,
                "size": int(binary["size"]),
                "build": asdict(info),
            },
        )
        # The child activates this build only after its GUI initializes successfully.
        return Candidate(directory / "Investment.exe", info)
    finally:
        temporary.unlink(missing_ok=True)


def choose_build(cache, current, cancel, progress, *, offline=False):
    selected = fallback(cache, current)
    if offline:
        return selected
    try:
        progress("GitHub에서 앱 업데이트를 확인하는 중…")
        payload = json.loads(b"".join(request_bytes(LATEST_URL, 1024 * 1024, cancel)))
        info, binary, checksum = release_info(payload)
        if info.revision == selected.info.revision or info.order < selected.info.order:
            return selected
        failure = read_json(cache / "failed.json")
        if failure.get("revision") == info.revision and time.time() - failure.get("time", 0) < 3600:
            selected.notice = (
                "새 버전을 시작하지 못해 이전 앱으로 실행합니다. 다음 실행에 재확인합니다."
            )
            return selected
        return download_release(cache, info, binary, checksum, cancel, progress)
    except Exception:
        selected.notice = (
            "업데이트를 건너뛰고 설치된 앱을 실행했습니다."
            if cancel.is_set()
            else "업데이트를 확인/설치하지 못해 설치된 앱을 실행했습니다."
        )
        return selected


def activate(cache, executable, info):
    """Install the running executable and keep the last successfully opened build."""
    directory = slot(cache, info.revision)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "Investment.exe"
    if executable.resolve() != target.resolve():
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as f:
            temporary = Path(f.name)
        try:
            shutil.copyfile(executable, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    atomic_json(
        directory / "ready.json",
        {
            "revision": info.revision,
            "sha256": digest(target),
            "size": target.stat().st_size,
            "build": asdict(info),
        },
    )
    state = read_json(cache / "state.json")
    previous = (
        state.get("active") if state.get("active") != info.revision else state.get("previous")
    )
    atomic_json(cache / "state.json", {"active": info.revision, "previous": previous})
    for child in directory.parent.iterdir():
        if (
            child.is_dir()
            and valid_revision(child.name)
            and child.name not in (info.revision, previous)
        ):
            shutil.rmtree(child, ignore_errors=True)
    return target


def mark_failed(cache, revision):
    if valid_revision(revision):
        atomic_json(cache / "failed.json", {"revision": revision, "time": time.time()})


@contextlib.contextmanager
def application_lock(home, *, wait=0):
    path = home / ".investment-app" / "launcher.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + wait
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Investment가 이미 실행 중입니다.") from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def restart(candidate, home):
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    command = [str(candidate.executable), "--run-app", "--app-home", str(home)]
    if candidate.notice:
        command.extend(["--startup-notice", candidate.notice])
    subprocess.Popen(
        command,
        cwd=home,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        close_fds=True,
    )
