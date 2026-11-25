import hashlib
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from investment import desktop_update as update

OLD = update.BuildInfo("0.3.0", "a" * 40, "2026-11-24T12:00:00Z")
NEW = update.BuildInfo("0.4.0", "b" * 40, "2026-11-25T12:00:00Z")
BINARY = b"MZ" + b"a simulated Windows bundle" * 10
BASE = "https://github.com/SKKUPhysicsKing/Investment/releases/download/desktop-" + NEW.revision


def manifest():
    return {
        "tag_name": "desktop-" + NEW.revision,
        "name": NEW.version,
        "published_at": NEW.built_at,
        "assets": [
            {
                "name": "Investment.exe",
                "browser_download_url": BASE + "/Investment.exe",
                "size": len(BINARY),
            },
            {
                "name": "Investment.exe.sha256",
                "browser_download_url": BASE + "/Investment.exe.sha256",
            },
        ],
    }


def source(tmp_path, name="original.exe"):
    path = tmp_path / name
    path.write_bytes(BINARY)
    return path


def fake_download(monkeypatch, *, corrupt=False):
    def get(url, limit, cancel, progress=lambda size: None):
        if url.endswith(".sha256"):
            yield (hashlib.sha256(BINARY).hexdigest() + "  Investment.exe\n").encode()
        elif url == update.LATEST_URL:
            yield json.dumps(manifest()).encode()
        else:
            yield b"broken" if corrupt else BINARY

    monkeypatch.setattr(update, "request_bytes", get)


def test_download_validates_checksum_and_does_not_activate_before_gui(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    old = source(tmp_path)
    update.activate(cache, old, OLD)
    fake_download(monkeypatch)
    info, binary, checksum = update.release_info(manifest())
    candidate = update.download_release(
        cache, info, binary, checksum, threading.Event(), lambda _: None
    )
    assert update.installed(cache, NEW.revision).executable == candidate.executable
    assert update.read_json(cache / "state.json")["active"] == OLD.revision
    update.activate(cache, candidate.executable, NEW)
    assert update.read_json(cache / "state.json") == {
        "active": NEW.revision,
        "previous": OLD.revision,
    }


def test_bad_download_preserves_working_build_and_removes_partial(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    update.activate(cache, source(tmp_path), OLD)
    fake_download(monkeypatch, corrupt=True)
    info, binary, checksum = update.release_info(manifest())
    with pytest.raises(ValueError, match="무결성"):
        update.download_release(cache, info, binary, checksum, threading.Event(), lambda _: None)
    assert update.installed(cache, OLD.revision)
    assert update.installed(cache, NEW.revision) is None
    assert not list(cache.rglob("*.part"))


@pytest.mark.parametrize(
    "mutation", ["draft", "prerelease", "wrong_tag", "foreign_url", "oversize"]
)
def test_release_rejects_unexpected_assets(mutation):
    payload = manifest()
    if mutation in ("draft", "prerelease"):
        payload[mutation] = True
    elif mutation == "wrong_tag":
        payload["tag_name"] = "desktop-../../bad"
    elif mutation == "foreign_url":
        payload["assets"][0]["browser_download_url"] = "https://example.com/Investment.exe"
    else:
        payload["assets"][0]["size"] = update.MAX_EXE + 1
    with pytest.raises(ValueError):
        update.release_info(payload)


def test_offline_uses_newest_healthy_cached_build(tmp_path):
    cache = tmp_path / "cache"
    original = source(tmp_path)
    update.activate(cache, original, NEW)
    selected = update.choose_build(
        cache, update.Candidate(original, OLD), threading.Event(), lambda _: None, offline=True
    )
    assert selected.info == NEW


def test_current_newer_bundle_is_not_downgraded(tmp_path):
    cache = tmp_path / "cache"
    original = source(tmp_path)
    update.activate(cache, original, OLD)
    assert update.fallback(cache, update.Candidate(original, NEW)).info == NEW


def test_network_failure_starts_existing_app(monkeypatch, tmp_path):
    monkeypatch.setattr(
        update, "request_bytes", Mock(side_effect=requests.ConnectionError("offline"))
    )
    current = update.Candidate(source(tmp_path), NEW)
    result = update.choose_build(tmp_path, current, threading.Event(), lambda _: None)
    assert result.executable == current.executable and "설치된 앱" in result.notice


def test_failed_startup_cools_down_that_revision(monkeypatch, tmp_path):
    fake_download(monkeypatch)
    update.mark_failed(tmp_path, NEW.revision)
    result = update.choose_build(
        tmp_path, update.Candidate(source(tmp_path), OLD), threading.Event(), lambda _: None
    )
    assert result.info == OLD and "이전 앱" in result.notice


def test_corrupt_cached_binary_is_not_launched(tmp_path):
    target = update.activate(tmp_path / "cache", source(tmp_path), NEW)
    target.write_bytes(b"not the original")
    assert update.installed(tmp_path / "cache", NEW.revision) is None


def test_failed_gui_can_return_to_previous_healthy_build(tmp_path):
    cache = tmp_path / "cache"
    original = source(tmp_path)
    update.activate(cache, original, OLD)
    update.activate(cache, original, NEW)
    candidate = update.fallback(
        cache, update.Candidate(original, NEW), exclude_revision=NEW.revision
    )
    assert candidate.info == OLD


def test_running_build_install_keeps_two_versions_and_user_data(tmp_path):
    cache = tmp_path / "cache"
    data = tmp_path / "data" / "existing.csv"
    data.parent.mkdir()
    data.write_text("keep", encoding="utf-8")
    executable = source(tmp_path)
    oldest = update.BuildInfo("0.2.0", "c" * 40, "2026-11-23T12:00:00Z")
    update.activate(cache, executable, oldest)
    update.activate(cache, executable, OLD)
    update.activate(cache, executable, NEW)
    assert {p.name for p in (cache / "v").iterdir()} == {OLD.revision, NEW.revision}
    assert data.read_text(encoding="utf-8") == "keep"


def test_stream_download_honors_cancel_and_size_limit(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b"123", b"456"]
    request = Mock(return_value=response)
    monkeypatch.setattr(update.requests, "get", request)
    with pytest.raises(ValueError, match="크기"):
        list(update.request_bytes(BASE, 5, threading.Event()))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RuntimeError, match="건너"):
        list(update.request_bytes(BASE, 10, cancel))
    assert request.call_count == 1


def test_relaunch_is_direct_and_uses_independent_pyinstaller_environment(monkeypatch, tmp_path):
    process = Mock()
    monkeypatch.setattr(update.subprocess, "Popen", process)
    target = update.Candidate(Path("Investment.exe"), NEW)
    update.restart(target, tmp_path)
    command = process.call_args.args[0]
    assert command[0] == "Investment.exe" and "--run-app" in command
    assert process.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not process.call_args.kwargs.get("shell")


def test_native_and_legacy_launch_share_the_folder_lock(tmp_path):
    with update.application_lock(tmp_path):
        with pytest.raises(RuntimeError, match="이미 실행"):
            with update.application_lock(tmp_path):
                pass
    with update.application_lock(tmp_path):
        assert (tmp_path / ".investment-app" / "launcher.lock").is_file()
