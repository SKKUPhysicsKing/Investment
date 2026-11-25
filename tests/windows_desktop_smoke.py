"""Verify the real windowed bundle, native shortcuts and preserved user data."""

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from investment.desktop import create_shortcuts
from investment.desktop_update import BuildInfo, activate, installed


def main():
    if sys.platform != "win32":
        raise SystemExit("This smoke test requires Windows.")
    binary = Path(sys.argv[1]).resolve()
    with binary.open("rb") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe)
        assert f.read(4) == b"PE\x00\x00"
        machine = struct.unpack("<H", f.read(2))[0]
        f.seek(pe + 24 + 68)
        subsystem = struct.unpack("<H", f.read(2))[0]
        assert machine == 0x8664, "Expected a native x64 app"
        assert subsystem == 2, "Must be WINDOWS_GUI, not WINDOWS_CUI"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        home = root / "Investment" / "Investment-main" / "Investment-main"
        home.mkdir(parents=True)
        sentinel = home / "data" / "existing.csv"
        sentinel.parent.mkdir()
        sentinel.write_text("keep existing data", encoding="utf-8")
        report = root / "smoke.json"
        environment = os.environ.copy()
        # The bundle must use its embedded runtime and dependencies.
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        for source in (binary,):
            subprocess.run(
                [
                    str(source),
                    "--no-update",
                    "--no-shortcuts",
                    "--app-home",
                    str(home),
                    "--smoke-result",
                    str(report),
                ],
                env=environment,
                cwd=home,
                check=True,
                timeout=120,
            )
        result = json.loads(report.read_text(encoding="utf-8"))
        assert result["frozen"] and not result["console_window"], result
        assert result["news_tab"] and result["icon"], result
        # Windows TEMP can use RUNNER~1 while the app resolves its long path.
        assert Path(result["data_dir"]).samefile(sentinel.parent), result
        assert sentinel.read_text(encoding="utf-8") == "keep existing data"
        info = BuildInfo(result["version"], result["revision"], "2026-11-25T00:00:00Z")
        cache = root / "cache"
        target = activate(cache, binary, info)
        assert installed(cache, info.revision).executable == target
        paths = create_shortcuts(
            target, home, directories=(root / "Desktop", root / "Programs" / "Investment")
        )
        import pythoncom
        from win32com.client.dynamic import Dispatch

        pythoncom.CoInitialize()
        try:
            shell = Dispatch("WScript.Shell")
            for path in paths:
                assert path.is_file()
                link = shell.CreateShortcut(str(path))
                assert Path(link.TargetPath).samefile(target)
                assert Path(link.WorkingDirectory).samefile(home)
                assert "--app-home" in link.Arguments
                assert "cmd" not in link.TargetPath.lower()
        finally:
            pythoncom.CoUninitialize()
        subprocess.run(
            [
                str(target),
                "--no-update",
                "--no-shortcuts",
                "--app-home",
                str(home),
                "--smoke-result",
                str(report),
            ],
            env=environment,
            cwd=home,
            check=True,
            timeout=120,
        )
        assert not json.loads(report.read_text(encoding="utf-8"))["console_window"]
        assert sentinel.read_text(encoding="utf-8") == "keep existing data"
        print(
            "Desktop bundle OK: x64 GUI subsystem, no console, embedded Python/Tk, "
            "native shortcuts, cached launch, existing data preserved."
        )


if __name__ == "__main__":
    main()
