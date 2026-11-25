import importlib.util
import json
import stat
import zipfile
from pathlib import Path, PureWindowsPath
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "investment_bootstrap", Path(__file__).parents[1] / "launch_app.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
OLD, NEW, OLDER = "1" * 40, "2" * 40, "3" * 40


@pytest.fixture(autouse=True)
def isolated_local_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))


def runtime(home, revision):
    return launcher.versions_dir(launcher.cache_root(home)) / revision


def state_path(home):
    return launcher.cache_root(home) / "state.json"


def mark_ready(path, revision):
    launcher.python_path(path).parent.mkdir(parents=True, exist_ok=True)
    launcher.python_path(path).touch()
    launcher.atomic_json(path / "ready.json", {"revision": revision})


def existing(home):
    mark_ready(runtime(home, OLD), OLD)
    launcher.atomic_json(state_path(home), {"active": OLD})


def test_update_installs_then_switches_and_preserves_data(monkeypatch, tmp_path):
    existing(tmp_path)
    mark_ready(runtime(tmp_path, OLDER), OLDER)
    data = tmp_path / "data" / "important.csv"
    data.parent.mkdir()
    data.write_text("keep")
    monkeypatch.setattr(launcher, "remote_revision", lambda: NEW)
    monkeypatch.setattr(launcher, "install_revision", mark_ready)
    path, revision = launcher.choose_runtime(tmp_path)
    assert path == runtime(tmp_path, NEW) and revision == NEW
    assert json.loads(state_path(tmp_path).read_text()) == {"active": NEW, "previous": OLD}
    assert launcher.ready(runtime(tmp_path, OLD), OLD)
    assert not runtime(tmp_path, OLDER).exists()
    assert data.read_text() == "keep"


@pytest.mark.parametrize("failure", ["network", "install"])
def test_failed_update_runs_previous_version(monkeypatch, tmp_path, failure):
    existing(tmp_path)
    monkeypatch.setattr(
        launcher,
        "remote_revision",
        Mock(side_effect=OSError("offline")) if failure == "network" else lambda: NEW,
    )
    monkeypatch.setattr(launcher, "install_revision", Mock(side_effect=RuntimeError("pip failed")))
    assert launcher.choose_runtime(tmp_path) == (runtime(tmp_path, OLD), OLD)
    assert json.loads(state_path(tmp_path).read_text())["active"] == OLD


def test_same_revision_and_offline_start_do_not_reinstall(monkeypatch, tmp_path):
    existing(tmp_path)
    network = Mock(return_value=OLD)
    install = Mock(side_effect=AssertionError("must not reinstall"))
    monkeypatch.setattr(launcher, "remote_revision", network)
    monkeypatch.setattr(launcher, "install_revision", install)
    launcher.choose_runtime(tmp_path)
    launcher.choose_runtime(tmp_path, offline=True)
    network.assert_called_once()
    install.assert_not_called()


def test_first_launch_failure_has_no_active_state(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "remote_revision", Mock(side_effect=OSError("offline")))
    with pytest.raises(RuntimeError, match="App setup did not complete"):
        launcher.choose_runtime(tmp_path)
    assert not state_path(tmp_path).exists()


def test_invalid_or_incomplete_active_slot_falls_back_to_previous(monkeypatch, tmp_path):
    existing(tmp_path)
    launcher.atomic_json(state_path(tmp_path), {"active": "../data", "previous": OLD})
    assert launcher.choose_runtime(tmp_path, offline=True)[1] == OLD


def test_second_instance_is_blocked_and_lock_released(tmp_path):
    with launcher.launcher_lock(tmp_path), pytest.raises(RuntimeError, match="already running"):
        with launcher.launcher_lock(tmp_path):
            pass
    with launcher.launcher_lock(tmp_path):
        pass


def test_valid_archive_and_rejected_traversal(tmp_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(f"Investment-{NEW}/pyproject.toml", "[project]")
        handle.writestr(f"Investment-{NEW}/src/investment/gui.py", "print('app')")
    launcher.extract_archive(archive, tmp_path / "app", NEW)
    assert (tmp_path / "app/src/investment/gui.py").is_file()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(f"Investment-{NEW}/../../data/stolen.csv", "bad")
    with pytest.raises(RuntimeError, match="path"):
        launcher.extract_archive(archive, tmp_path / "bad", NEW)
    assert not (tmp_path / "data/stolen.csv").exists()


def test_archive_symlink_is_rejected(tmp_path):
    path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo(f"Investment-{NEW}/link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr(info, "../../data")
    with pytest.raises(RuntimeError, match="Symlinks"):
        launcher.extract_archive(path, tmp_path / "app", NEW)


def test_failed_install_cleans_only_incomplete_slot(monkeypatch, tmp_path):
    existing(tmp_path)
    monkeypatch.setattr(launcher, "download_archive", Mock(side_effect=OSError("download failed")))
    with pytest.raises(OSError):
        launcher.install_revision(runtime(tmp_path, NEW), NEW)
    assert not runtime(tmp_path, NEW).exists()
    assert launcher.ready(runtime(tmp_path, OLD), OLD)


def test_windows_cache_avoids_reported_long_lxml_path(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WINDOWS", True)
    home = tmp_path / "Investment" / "Investment-main" / "Investment-main"
    cache = launcher.cache_root(home)
    assert cache.parent == tmp_path / "local" / "Investment"
    assert len(cache.name) == 12
    assert not cache.is_relative_to(home)
    resource = PureWindowsPath(
        "venv/Lib/site-packages/lxml/isoschematron/resources/xsl/"
        "iso-schematron-xslt1/iso_schematron_skeleton_for_xslt1.xsl"
    )
    reported_home = PureWindowsPath(
        "C:/Users/user/Desktop/Investment/Investment-main/Investment-main"
    )
    old = reported_home / ".investment-app" / "py310-win32-AMD64" / "versions" / NEW / resource
    new = (
        PureWindowsPath("C:/Users/user/AppData/Local/Investment")
        / cache.name
        / "v"
        / NEW
        / resource
    )
    assert len(str(old)) >= 260
    assert len(str(new)) < 240


def test_windows_cache_distinguishes_app_folders_and_python_versions(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WINDOWS", True)
    home = tmp_path / "first app"
    first = launcher.cache_root(home)
    assert first == launcher.cache_root(home)
    assert first != launcher.cache_root(tmp_path / "second app")
    monkeypatch.setattr(launcher, "RUNTIME_TAG", launcher.RUNTIME_TAG + "-other-python")
    assert first != launcher.cache_root(home)


def test_legacy_windows_environment_remains_available_on_update_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WINDOWS", True)
    legacy_cache = tmp_path / ".investment-app" / launcher.RUNTIME_TAG
    legacy = legacy_cache / "versions" / OLD
    mark_ready(legacy, OLD)
    launcher.atomic_json(legacy_cache / "state.json", {"active": OLD})
    monkeypatch.setattr(launcher, "remote_revision", Mock(side_effect=OSError("offline")))
    assert launcher.choose_runtime(tmp_path) == (legacy, OLD)
    assert launcher.choose_runtime(tmp_path, offline=True) == (legacy, OLD)


def test_legacy_windows_upgrade_reinstalls_without_moving_venv_or_data(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WINDOWS", True)
    legacy_cache = tmp_path / ".investment-app" / launcher.RUNTIME_TAG
    legacy = legacy_cache / "versions" / OLD
    mark_ready(legacy, OLD)
    launcher.atomic_json(legacy_cache / "state.json", {"active": OLD})
    data = tmp_path / "data" / "samsung.csv"
    data.parent.mkdir()
    data.write_text("preserve export")
    monkeypatch.setattr(launcher, "remote_revision", lambda: NEW)
    monkeypatch.setattr(launcher, "install_revision", mark_ready)
    assert launcher.choose_runtime(tmp_path) == (runtime(tmp_path, NEW), NEW)
    assert launcher.ready(legacy, OLD)
    assert data.read_text() == "preserve export"
