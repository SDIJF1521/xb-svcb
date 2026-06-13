@echo off
rem ============================================================
rem  XB-SVCB - build/repair the runtime environment (no PowerShell)
rem  Runs install/install.py with the system Python. Web is prebuilt.
rem  Extra args are forwarded, e.g.:  setup_env.bat --only svc
rem ============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
  echo [XB-SVCB] Python 3.10+ not found in PATH.
  echo           Get it from https://www.python.org/downloads/ then retry.
  echo.
  pause
  exit /b 1
)

echo [XB-SVCB] Using %PYEXE%
echo [XB-SVCB] Building runtime environment, this may take a while...
echo.
rem App UI ships as XB-SVCB.exe, so the app/web build steps are not needed here;
rem only the heavy AI envs (uvr/svc) and models are set up.
rem --root pins all deps (engines/.venv-svc/.venv-uvr/models) to THIS install folder.
%PYEXE% "install\install.py" --root "%CD%" --skip-app --skip-web %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [XB-SVCB] Done. You can now launch the app from the Start Menu.
) else (
  echo [XB-SVCB] Finished with errors ^(exit code %RC%^). See log above.
  echo           You can retry a single step, e.g.:  setup_env.bat --only svc
)
echo.
pause
endlocal
exit /b %RC%
