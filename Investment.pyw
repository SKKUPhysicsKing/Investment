"""Windowed entry point used to build Investment.exe."""

import os
import sys

# Windowed Python intentionally has no stdout/stderr handles. Keep libraries that
# write progress or warnings compatible without opening a console window.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from investment.desktop import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
