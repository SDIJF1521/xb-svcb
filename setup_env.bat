@echo off
rem ============================================================
rem  XB-SVCB - build/repair the runtime environment (no PowerShell)
rem  Installed CUDA packages remember XB_RUNTIME_LAYOUT=shared and continue
rem  using the two-layer shared runtime on later repairs. CPU/DirectML and old
rem  installations retain the isolated compatibility path.
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
if defined XB_WHEELHOUSE if not exist "%XB_WHEELHOUSE%\wheelhouse.json" (
  echo [XB-SVCB] Offline wheel cache is absent; repair will use configured online indexes.
  set "XB_WHEELHOUSE="
  set "XB_WHEELHOUSE_STRICT=0"
)
if not defined XB_WHEELHOUSE if exist "%~dp0assets\wheels\wheelhouse.json" set "XB_WHEELHOUSE=%~dp0assets\wheels"
if defined XB_WHEELHOUSE if not defined XB_WHEELHOUSE_STRICT set "XB_WHEELHOUSE_STRICT=1"
if not defined UV_LINK_MODE set "UV_LINK_MODE=copy"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"
echo [XB-SVCB] HuggingFace mirror: %HF_ENDPOINT%
echo [XB-SVCB] PyPI mirror       : %PIP_INDEX_URL%
if defined XB_WHEELHOUSE echo [XB-SVCB] Wheelhouse        : %XB_WHEELHOUSE%

rem The selected installer emits the authoritative 0-100 progress stream.
rem These wrapper messages deliberately stay at the local start position so
rem they cannot jump ahead and then move backwards when install.py starts.
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 0 正在查找 Python 运行时
set "PYTHON_DETECTOR=%~dp0install\detect_python.bat"
if not exist "%PYTHON_DETECTOR%" (
  echo [XB-SVCB] Python detector not found: %PYTHON_DETECTOR%
  exit /b 1
)
call "%PYTHON_DETECTOR%"
if errorlevel 1 goto PYTHON_MISSING
set "XB_PYTHON_310_EXE=%XB_PYTHON_EXE%"
set "PATH=%XB_PYTHON_DIR%;%XB_PYTHON_DIR%\Scripts;%PATH%"
rem Prefer the current per-user uv installation over an older uv.exe that
rem may be left in the detected Python Scripts directory.
if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if defined XB_FFMPEG_DIR if exist "%XB_FFMPEG_DIR%\bin\ffmpeg.exe" if exist "%XB_FFMPEG_DIR%\bin\ffprobe.exe" set "XB_FFMPEG_BIN=%XB_FFMPEG_DIR%\bin"
if defined XB_FFMPEG_DIR if not defined XB_FFMPEG_BIN if exist "%XB_FFMPEG_DIR%\ffmpeg.exe" if exist "%XB_FFMPEG_DIR%\ffprobe.exe" set "XB_FFMPEG_BIN=%XB_FFMPEG_DIR%"
if defined XB_GIT_BIN set "PATH=%XB_GIT_BIN%;%PATH%"
if defined XB_FFMPEG_BIN set "PATH=%XB_FFMPEG_BIN%;%PATH%"
if defined XB_CUDA_BIN set "PATH=%XB_CUDA_BIN%;%PATH%"

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 0 已找到 Python，准备创建运行环境
echo [XB-SVCB] Using locked Python 3.10.x: %XB_PYTHON_EXE%
echo [XB-SVCB] Building runtime environment, this may take a while...
echo.
rem App UI ships as XB-SVCB.exe, so the app/web build steps are not needed here;
rem only the plugin runtime, AI envs, and models are set up.
rem --root pins all deps to THIS install folder.
set "XB_RUNTIME_INSTALLER=install\install.py"
set "XB_RUNTIME_STACK_ARG="
if /I "%XB_RUNTIME_LAYOUT%"=="shared" set "XB_RUNTIME_INSTALLER=install\install_shared.py"
if /I "%XB_GPU_STACK%"=="cu126" set "XB_RUNTIME_STACK_ARG=--cu126"
if /I "%XB_GPU_STACK%"=="cu128" set "XB_RUNTIME_STACK_ARG=--cu128"
for %%A in (%*) do (
  if /I "%%~A"=="--cpu" (
    set "XB_RUNTIME_INSTALLER=install\install.py"
    set "XB_RUNTIME_STACK_ARG="
  )
  if /I "%%~A"=="--directml" (
    set "XB_RUNTIME_INSTALLER=install\install.py"
    set "XB_RUNTIME_STACK_ARG="
  )
  if /I "%%~A"=="--cu126" (
    set "XB_RUNTIME_INSTALLER=install\install_shared.py"
    set "XB_RUNTIME_STACK_ARG=--cu126"
  )
  if /I "%%~A"=="--cu128" (
    set "XB_RUNTIME_INSTALLER=install\install_shared.py"
    set "XB_RUNTIME_STACK_ARG=--cu128"
  )
  if /I "%%~A"=="--consolidated" set "XB_RUNTIME_INSTALLER=install\install_shared.py"
)
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 0 正在执行运行环境安装脚本：%XB_RUNTIME_INSTALLER%
"%XB_PYTHON_EXE%" "%XB_RUNTIME_INSTALLER%" --root "%CD%" --skip-app --skip-web %XB_RUNTIME_STACK_ARG% %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 运行环境搭建完成
  echo [XB-SVCB] Done. You can now launch the app from the Start Menu.
) else (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 运行环境搭建失败
  echo [XB-SVCB] Finished with errors ^(exit code %RC%^). See log above.
  echo           CUDA core repair: setup_env.bat --only uvr seedvc ddsp
)
echo.
if not "%XB_FROM_INSTALLER%"=="1" pause
endlocal & exit /b %RC%

:PYTHON_MISSING
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 未找到可用的 Python，运行环境搭建失败
echo [XB-SVCB] A runnable CPython 3.10.x was not found.
echo           Get it from https://www.python.org/downloads/ then retry.
echo.
if not "%XB_FROM_INSTALLER%"=="1" pause
endlocal
exit /b 1
