@echo off
cd /d "%~dp0"
set OUT_DIR=bin\Release\net472

:: 通过编译期常量 LITE 区分版本
:: 两次构建的 MSBuild 属性不同，必须清掉中间产物，否则增量编译会跳过

rmdir /s /q obj 2>nul
rmdir /s /q bin 2>nul
dotnet build -c Release
if not exist "%OUT_DIR%\HachimiDX.exe" goto fail
copy /y "%OUT_DIR%\HachimiDX.exe" "." >nul

rmdir /s /q obj 2>nul
rmdir /s /q bin 2>nul
dotnet build -c Release -p:IsLite=true
if not exist "%OUT_DIR%\HachimiDX-Lite.exe" goto fail
copy /y "%OUT_DIR%\HachimiDX-Lite.exe" "." >nul

:: build success
exit /b 0

:fail
echo.
echo Build failed: %OUT_DIR% exe not found.
pause
exit /b 1
