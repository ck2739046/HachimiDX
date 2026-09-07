@echo off
cd /d "%~dp0"

:: 启动 python 脚本
"..\python\python.exe" -u -m script.tee

pause
