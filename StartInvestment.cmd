@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 (
    py -3 "%~dp0launch_app.py"
) else (
    python "%~dp0launch_app.py"
)
if errorlevel 1 (
    echo.
    echo Investment could not start. See the message above.
    echo Python 3.10+ with Tcl/Tk must be installed.
    pause
)
endlocal
