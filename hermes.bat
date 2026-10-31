@echo off
rem ============================================================================
rem HERMES Canonical Windows Launcher
rem Resolves strictly to the repository-local Python 3.12 virtual environment.
rem Prevents accidental invocation of system Python 3.10, 3.13, or other runtimes.
rem ============================================================================

setlocal
set SCRIPT_DIR=%~dp0
set CANONICAL_PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe

if not exist "%CANONICAL_PYTHON%" (
    echo [HERMES LAUNCHER ERROR] Canonical Python 3.12 environment not found at:
    echo   %CANONICAL_PYTHON%
    echo.
    echo Please create the canonical virtual environment using Python 3.12:
    echo   py -3.12 -m venv venv
    echo   venv\Scripts\python.exe -m pip install -r requirements.lock
    echo.
    exit /b 1
)

set PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%

if "%~1"=="" (
    rem Default to interactive TUI mode if invoked without arguments
    "%CANONICAL_PYTHON%" "%SCRIPT_DIR%main.py" ui
) else (
    "%CANONICAL_PYTHON%" "%SCRIPT_DIR%main.py" %*
)

exit /b %ERRORLEVEL%
