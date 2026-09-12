@echo off
cd /d "%~dp0"

:: 日志位置
set "LOG_PATH=..\data\logs\install_log.txt"
for %%I in ("%~dp0%LOG_PATH%") do set "LOG_PATH=%%~fI"

:: 启动 python 脚本
"..\python\python.exe" -u -m script.main "%LOG_PATH%"
set "EXIT_CODE=%errorlevel%"

:: 若用户选择立即打开 HachimiDX（特殊返回码 273），安装窗口自动关闭
if "%EXIT_CODE%"=="273" exit /b

:: 异常退出时告知日志位置
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Installation failed ^(exit code %EXIT_CODE%^). Log has been saved to: %LOG_PATH%
)

pause
