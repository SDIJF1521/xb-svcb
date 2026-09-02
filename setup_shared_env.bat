@echo off
rem ============================================================
rem  XB-SVCB - explicitly build/repair the NVIDIA shared runtime
rem  setup_env.bat is the user-facing dispatcher; this file is the direct
rem  shared-layout entry point for development and diagnosis.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

if exist "%~dp0installer_env.cmd" call "%~dp0installer_env.cmd"
if not defined XB_HF_MIRROR set "XB_HF_MIRROR=https://hf-mirror.com"
if not defined HF_ENDPOINT set "HF_ENDPOINT=%XB_HF_MIRROR%"
if not defined HUGGINGFACE_HUB_ENDPOINT set "HUGGINGFACE_HUB_ENDPOINT=%XB_HF_MIRROR%"
if not defined XB_PYPI_MIRROR set "XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=%XB_PYPI_MIRROR%"
if not defined UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=%XB_PYPI_MIRROR%"
if defined XB_WHEELHOUSE if not exist "%XB_WHEELHOUSE%\wheelhouse.json" (
  echo [XB-SVCB] Offline wheel cache is absent; repair will use configured online indexes.
  set "XB_WHEELHOUSE="
  set "XB_WHEELHOUSE_STRICT=0"
)
if not defined XB_WHEELHOUSE if exist "%~dp0assets\wheels\wheelhouse.json" set "XB_WHEELHOUSE=%~dp0assets\wheels"
if defined XB_WHEELHOUSE if not defined XB_WHEELHOUSE_STRICT set "XB_WHEELHOUSE_STRICT=1"
if not defined UV_LINK_MODE set "UV_LINK_MODE=copy"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"

set "PYTHON_DETECTOR=%~dp0install\detect_python.bat"
if not exist "%PYTHON_DETECTOR%" (
  echo [XB-SVCB] Python detector not found: %PYTHON_DETECTOR%
  exit /b 1
)
call "%PYTHON_DETECTOR%"
if errorlevel 1 (
  echo [XB-SVCB] A runnable CPython 3.10.x was not found.
  exit /b 1
)
set "XB_PYTHON_310_EXE=%XB_PYTHON_EXE%"
set "UV_PYTHON=%XB_PYTHON_EXE%"
set "UV_NO_MANAGED_PYTHON=1"
set "UV_PYTHON_DOWNLOADS=never"
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 0 正在执行共享运行环境安装脚本
"%XB_PYTHON_EXE%" "install\install_shared.py" --root "%CD%" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 共享运行环境搭建完成
  echo [XB-SVCB] Shared runtime is ready.
) else (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 共享运行环境搭建失败
  echo [XB-SVCB] Shared runtime setup failed ^(exit code %RC%^).
)
if not "%XB_FROM_INSTALLER%"=="1" pause
endlocal & exit /b %RC%
