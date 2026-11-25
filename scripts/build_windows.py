"""Build the self-contained, windowed Investment.exe on a Windows runner."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows binaries must be built on Windows.")
    project = Path(__file__).resolve().parents[1]
    build = project / "build" / "desktop"
    build.mkdir(parents=True, exist_ok=True)
    revision = (
        os.getenv("GITHUB_SHA")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
    )
    app_version = version("investment-stock-data")
    (build / "desktop-build.json").write_text(
        json.dumps(
            {
                "version": app_version,
                "revision": revision,
                "built_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    icon = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((6, 6, 250, 250), radius=48, fill="#18354d")
    draw.line([(48, 192), (48, 58)], fill="#adc4d6", width=9)
    draw.line([(48, 192), (210, 192)], fill="#adc4d6", width=9)
    draw.line([(59, 166), (100, 127), (131, 147), (198, 76)], fill="#59d4aa", width=15)
    draw.polygon([(174, 76), (208, 65), (198, 100)], fill="#59d4aa")
    icon.save(
        build / "investment.ico", sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)]
    )
    numeric_version = tuple(int(part) for part in app_version.split(".")) + (0,)
    version_file = build / "version.txt"
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers="
        + repr(numeric_version)
        + ", prodvers="
        + repr(numeric_version)
        + ", mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('CompanyName','Investment'),"
        "StringStruct('FileDescription','Investment Desktop'),"
        f"StringStruct('FileVersion','{app_version}'),"
        "StringStruct('InternalName','Investment'),"
        "StringStruct('OriginalFilename','Investment.exe'),"
        "StringStruct('ProductName','Investment'),"
        f"StringStruct('ProductVersion','{app_version}')"
        "])]), VarFileInfo([VarStruct('Translation',[1033,1200])])])",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--noupx",
        "--name",
        "Investment",
        "--distpath",
        str(project / "dist"),
        "--workpath",
        str(build / "work"),
        "--specpath",
        str(build),
        "--icon",
        str(build / "investment.ico"),
        "--version-file",
        str(version_file),
        "--paths",
        str(project / "src"),
        "--add-data",
        str(build / "desktop-build.json") + ";.",
        "--add-data",
        str(build / "investment.ico") + ";assets",
        "--copy-metadata",
        "investment-stock-data",
        "--recursive-copy-metadata",
        "yfinance",
        "--collect-all",
        "curl_cffi",
        "--collect-data",
        "certifi",
        "--hidden-import",
        "matplotlib.backends.backend_tkagg",
    ]
    for module in ("pytest", "IPython", "scipy", "pandas.tests", "numpy.tests", "matplotlib.tests"):
        command.extend(["--exclude-module", module])
    command.append(str(project / "Investment.pyw"))
    subprocess.run(command, cwd=project, check=True)
    binary = project / "dist" / "Investment.exe"
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    binary.with_suffix(".exe.sha256").write_text(digest + "  Investment.exe\n", encoding="ascii")
    (project / "dist" / "release-notes.md").write_text(
        f"Investment {app_version} — Windows 10/11 x64\n\n"
        "Investment.exe를 기존 Investment 폴더에 저장한 뒤 더블클릭하세요.\n"
        "Python 설치나 CMD 실행이 필요하지 않습니다. 첫 실행 후 바탕화면과 시작 메뉴의 "
        "Investment 아이콘으로 열 수 있습니다. 기존 폴더의 data를 계속 사용합니다.\n\n"
        "실행할 때 검증된 최신 Windows 앱을 자동으로 확인합니다. 업데이트에 실패하면 "
        "설치된 버전을 실행하며, 실행 중에는 강제로 재시작하지 않습니다.\n\n"
        f"소스 커밋: {revision}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
