import importlib.util
import json
import stat
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "investment_bootstrap", Path(__file__).parents[1] / "launch_app.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
OLD, NEW, OLDER = "1" * 40, "2" * 40, "3" * 40


def runtime(home, revision):
    return home / ".investment-app" / launcher.RUNTIME_TAG / "versions" / revision


def state_path(home):
    return home / ".investment-app" / launcher.RUNTIME_TAG / "state.json"


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
    with pytest.raises(RuntimeError, match="First launch"):
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
