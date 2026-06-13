@echo off
cd /d "%~dp0"

set "PYW=app\.venv\Scripts\pythonw.exe"
set "PY=app\.venv\Scripts\python.exe"

if exist "%PYW%" (
  start "" "%PYW%" "app\main.py"
  goto :eof
)
if exist "%PY%" (
  start "" "%PY%" "app\main.py"
  goto :eof
)

echo [XB-SVCB] Runtime not ready (app\.venv missing).
echo Please run install.ps1 to build the environment first.
pause
