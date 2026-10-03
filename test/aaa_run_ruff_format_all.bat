@echo off
rem Full ruff pass over the repository: format, autofix, format again.
rem Applies to src/, install/, test/ and any other .py outside the directories
rem excluded by .ruff.toml (archive, python, data, install/dml_support, .venv).
rem   aaa_run_ruff_format_all.bat           format + autofix
rem   aaa_run_ruff_format_all.bat --check   check only, for CI
setlocal enabledelayedexpansion
pushd "%~dp0.." || (echo [ERROR] cannot enter repo root & pause & exit /b 1)
chcp 65001 >nul

rem --- locate ruff: interpreter module, then ruff.exe on disk, then VS Code extension ---
set "RUFF="
if exist "python\python.exe" (
    python\python.exe -c "import ruff" >nul 2>nul && set "RUFF=python\python.exe -m ruff"
)
if not defined RUFF if exist "python\Scripts\ruff.exe" set "RUFF=python\Scripts\ruff.exe"
if not defined RUFF (
    where ruff >nul 2>nul && set "RUFF=ruff"
)
if not defined RUFF (
    for /d %%D in ("%USERPROFILE%\.vscode\extensions\charliermarsh.ruff-*") do (
        if exist "%%~fD\bundled\libs\bin\ruff.exe" set "RUFF=%%~fD\bundled\libs\bin\ruff.exe"
    )
)
if not defined RUFF (
    echo [ERROR] ruff not found. Either: python\python.exe -m pip install ruff
    echo         or install the Ruff VS Code extension, then re-run.
    pause & popd & exit /b 1
)

echo repo: %CD%
echo ruff: !RUFF!
echo scope: whole repo (.ruff.toml excludes archive / python / data / install\dml_support / .venv)
echo.

if /i "%~1"=="--check" goto :check

echo [1/3] ruff format .
!RUFF! format . || goto :fail
echo [2/3] ruff check --fix .
!RUFF! check --fix .
echo [3/3] ruff format .  (check --fix can leave files unformatted)
!RUFF! format . || goto :fail

echo.
echo --- remaining issues ---
!RUFF! check . --statistics
echo.
echo done.
pause & popd & exit /b 0

:check
echo [1/2] ruff format --check .
!RUFF! format . --check
if errorlevel 1 (set "FAILED=1") else (echo [OK] formatting clean)
echo [2/2] ruff check .
!RUFF! check .
if errorlevel 1 (set "FAILED=1") else (echo [OK] lint clean)
echo.
if defined FAILED (
    echo [FAIL] run %~nx0 to fix
    pause & popd & exit /b 1
)
popd & exit /b 0

:fail
echo.
echo [ERROR] ruff format failed
pause & popd & exit /b 1
