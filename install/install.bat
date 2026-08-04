@echo off
cd /d "%~dp0"

@echo on

:: 更新 pip
"..\python\python.exe" -m pip install --upgrade pip --no-warn-script-location

:: 更新 wheel
"..\python\python.exe" -m pip install wheel --no-warn-script-location

:: 运行安装脚本
"..\python\python.exe" -u -m script.main

@echo off
pause
