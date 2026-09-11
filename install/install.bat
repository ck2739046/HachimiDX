@echo off
cd /d "%~dp0"

:: 启动 python 脚本
"..\python\python.exe" -u -m script.main
set "EXIT_CODE=%errorlevel%"

:: 若用户选择立即打开 HachimiDX（特殊返回码 273），安装窗口自动关闭
if "%EXIT_CODE%"=="273" exit /b

pause
