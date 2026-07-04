@echo off
rem ============================================================
rem  XB-SVCB - build/repair the runtime environment (no PowerShell)
rem  Runs install/install.py with the system Python. Web is prebuilt.
rem  Extra args are forwarded, e.g.:  setup_env.bat --only svc
rem ============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if exist "%~dp0installer_env.cmd" call "%~dp0installer_env.cmd"

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 3 正在查找 Python 运行时
set "PYEXE="
if defined XB_PYTHON_EXE if exist "%XB_PYTHON_EXE%" set "PYEXE="%XB_PYTHON_EXE%""
if defined XB_PYTHON_DIR (
  if exist "%XB_PYTHON_DIR%\python.exe" set "PATH=%XB_PYTHON_DIR%;%XB_PYTHON_DIR%\Scripts;%PATH%"
)
if defined XB_GIT_BIN set "PATH=%XB_GIT_BIN%;%PATH%"
if defined XB_FFMPEG_BIN set "PATH=%XB_FFMPEG_BIN%;%PATH%"
if defined XB_CUDA_BIN set "PATH=%XB_CUDA_BIN%;%PATH%"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 未找到 Python，运行环境搭建失败
  echo [XB-SVCB] Python 3.10+ not found in PATH.
  echo           Get it from https://www.python.org/downloads/ then retry.
  echo.
  if not "%XB_FROM_INSTALLER%"=="1" pause
  exit /b 1
)

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 10 已找到 Python，准备创建隔离环境
echo [XB-SVCB] Using %PYEXE%
echo [XB-SVCB] Building runtime environment, this may take a while...
echo.
rem App UI ships as XB-SVCB.exe, so the app/web build steps are not needed here;
rem only the heavy AI envs (uvr/svc) and models are set up.
rem --root pins all deps (engines/.venv-svc/.venv-uvr/models) to THIS install folder.
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 18 正在执行运行环境安装脚本
%PYEXE% "install\install.py" --root "%CD%" --skip-app --skip-web %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 运行环境搭建完成
  echo [XB-SVCB] Done. You can now launch the app from the Start Menu.
) else (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 运行环境搭建失败
  echo [XB-SVCB] Finished with errors ^(exit code %RC%^). See log above.
  echo           You can retry a single step, e.g.:  setup_env.bat --only svc
)
echo.
if not "%XB_FROM_INSTALLER%"=="1" pause
endlocal
exit /b %RC%
