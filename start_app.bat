@echo off
setlocal
if "%~dp0"=="" (
  set ROOT=%CD%
) else (
  set ROOT=%~dp0
)
cd /d %ROOT%

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python，可前往 https://www.python.org/downloads/ 下载并安装。
  pause
  exit /b 1
)

python start_app.py
if errorlevel 1 (
  echo 程序运行出错，请检查上方日志。
) else (
  echo 服务器已停止。
)
pause
