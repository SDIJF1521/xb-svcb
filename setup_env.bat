@echo off
rem ============================================================
rem  XB-SVCB - build/repair the runtime environment (no PowerShell)
rem  Runs install/install.py with the system Python. Web is prebuilt.
rem  Extra args are forwarded, e.g.:  setup_env.bat --only svc
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
if not defined UV_LINK_MODE set "UV_LINK_MODE=copy"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"
echo [XB-SVCB] HuggingFace mirror: %HF_ENDPOINT%
echo [XB-SVCB] PyPI mirror       : %PIP_INDEX_URL%

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 3 正在查找 Python 运行时
set "PYTHON_DETECTOR=%~dp0install\detect_python.bat"
if not exist "%PYTHON_DETECTOR%" (
  echo [XB-SVCB] Python detector not found: %PYTHON_DETECTOR%
  exit /b 1
)
call "%PYTHON_DETECTOR%"
if errorlevel 1 goto PYTHON_MISSING
set "PATH=%XB_PYTHON_DIR%;%XB_PYTHON_DIR%\Scripts;%PATH%"
if defined XB_FFMPEG_DIR if exist "%XB_FFMPEG_DIR%\bin\ffmpeg.exe" if exist "%XB_FFMPEG_DIR%\bin\ffprobe.exe" set "XB_FFMPEG_BIN=%XB_FFMPEG_DIR%\bin"
if defined XB_FFMPEG_DIR if not defined XB_FFMPEG_BIN if exist "%XB_FFMPEG_DIR%\ffmpeg.exe" if exist "%XB_FFMPEG_DIR%\ffprobe.exe" set "XB_FFMPEG_BIN=%XB_FFMPEG_DIR%"
if defined XB_GIT_BIN set "PATH=%XB_GIT_BIN%;%PATH%"
if defined XB_FFMPEG_BIN set "PATH=%XB_FFMPEG_BIN%;%PATH%"
if defined XB_CUDA_BIN set "PATH=%XB_CUDA_BIN%;%PATH%"

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 10 已找到 Python，准备创建隔离环境
echo [XB-SVCB] Using verified Python 3.10+: %XB_PYTHON_EXE%
echo [XB-SVCB] Building runtime environment, this may take a while...
echo.
rem App UI ships as XB-SVCB.exe, so the app/web build steps are not needed here;
rem only the heavy AI envs (uvr/svc/rvc/seedvc/ddsp) and models are set up.
rem --root pins all deps (engines/.venv-svc/.venv-uvr/models) to THIS install folder.
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 18 正在执行运行环境安装脚本
"%XB_PYTHON_EXE%" "install\install.py" --root "%CD%" --skip-app --skip-web %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 运行环境搭建完成
  echo [XB-SVCB] Done. You can now launch the app from the Start Menu.
) else (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 运行环境搭建失败
  echo [XB-SVCB] Finished with errors ^(exit code %RC%^). See log above.
  echo           You can retry a single step, e.g.:  setup_env.bat --only seedvc
)
echo.
if not "%XB_FROM_INSTALLER%"=="1" pause
endlocal & exit /b %RC%

:PYTHON_MISSING
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 未找到可用的 Python，运行环境搭建失败
echo [XB-SVCB] A runnable Python 3.10 or newer was not found.
echo           Get it from https://www.python.org/downloads/ then retry.
echo.
if not "%XB_FROM_INSTALLER%"=="1" pause
endlocal
exit /b 1
