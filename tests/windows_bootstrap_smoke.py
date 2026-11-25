"""Install the actual GUI dependencies from a deeply nested Windows app folder.

CI only: GitHub network responses are replaced with the checked-out source, while
venv creation, pip installation, import checks, and warm startup are real.
"""

import importlib.util
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch


def main():
    if sys.platform != "win32":
        raise SystemExit("This smoke test requires Windows.")
    project = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("bootstrap_smoke", project / "launch_app.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    revision = "d" * 40
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary) / "Investment" / "Investment-main" / "Investment-main"
        # Keep the app folder itself below MAX_PATH, while the old dependency
        # install layout would exceed it. The new layout must remain short.
        while len(str(home)) < 155:
            home /= "nested-app-folder"
        home.mkdir(parents=True)
        data = home / "data" / "existing.csv"
        data.parent.mkdir()
        data.write_text("keep existing data", encoding="utf-8")
        cache = launcher.cache_root(home)

        def source_archive(commit, target):
            assert commit == revision
            with zipfile.ZipFile(target, "w") as archive:
                for source in [
                    project / "pyproject.toml",
                    project / "README.md",
                    *sorted((project / "src" / "investment").glob("*.py")),
                ]:
                    archive.write(
                        source, f"Investment-{revision}/{source.relative_to(project).as_posix()}"
                    )

        try:
            with (
                patch.object(launcher, "remote_revision", return_value=revision),
                patch.object(launcher, "download_archive", side_effect=source_archive) as download,
            ):
                arguments = ["--prepare-only", "--app-dir", str(home)]
                assert launcher.main(arguments) == 0
                slot = launcher.versions_dir(cache) / revision
                resource = slot / (
                    "venv/Lib/site-packages/lxml/isoschematron/resources/xsl/"
                    "iso-schematron-xslt1/iso_schematron_skeleton_for_xslt1.xsl"
                )
                assert resource.is_file(), resource
                assert len(str(resource)) < 240, resource
                assert not slot.is_relative_to(home)
                assert data.read_text(encoding="utf-8") == "keep existing data"
                assert launcher.main(arguments) == 0
                assert launcher.main(arguments + ["--no-update"]) == 0
                download.assert_called_once()
                print(
                    f"Windows bootstrap OK: Python {sys.version.split()[0]}; "
                    f"app folder {len(str(home))} chars; "
                    f"dependency path {len(str(resource))} chars."
                )
        finally:
            shutil.rmtree(cache, ignore_errors=True)


if __name__ == "__main__":
    main()
