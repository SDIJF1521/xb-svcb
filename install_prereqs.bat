@echo off
rem ============================================================
rem  XB-SVCB - prerequisite bootstrapper used by the Inno setup.
rem
rem  It is intentionally plain batch: no PowerShell dependency.
rem  The installer writes installer_env.cmd before calling this file.
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul

if exist "%~dp0installer_env.cmd" call "%~dp0installer_env.cmd"

if not defined XB_PREREQ_AUTO set "XB_PREREQ_AUTO=0"
if not defined XB_ENV_CONFIGURE set "XB_ENV_CONFIGURE=1"
if not defined XB_GPU_STACK set "XB_GPU_STACK=auto"
if not defined XB_GPU_STACK_REQUESTED set "XB_GPU_STACK_REQUESTED=%XB_GPU_STACK%"
if not defined XB_HF_MIRROR set "XB_HF_MIRROR=https://hf-mirror.com"
if not defined HF_ENDPOINT set "HF_ENDPOINT=%XB_HF_MIRROR%"
if not defined HUGGINGFACE_HUB_ENDPOINT set "HUGGINGFACE_HUB_ENDPOINT=%XB_HF_MIRROR%"
if not defined XB_PYPI_MIRROR set "XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=%XB_PYPI_MIRROR%"
if not defined UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=%XB_PYPI_MIRROR%"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"

echo [XB-SVCB] Checking prerequisites...
echo           auto install : %XB_PREREQ_AUTO%
echo           gpu request  : %XB_GPU_STACK_REQUESTED%
echo           HF mirror    : %HF_ENDPOINT%
echo           PyPI mirror  : %PIP_INDEX_URL%
echo.

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 5 正在解析依赖路径
call :RESOLVE_PATHS
call :RESOLVE_GPU_STACK
echo           gpu stack    : %XB_RESOLVED_GPU_STACK%
if defined XB_CUDA_VERSION echo           cuda toolkit: %XB_CUDA_VERSION%
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 9 正在检查 JUCE VST3 Host
call :CHECK_JUCE_HOST

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 12 正在检查 Python 3.10
call :CHECK_PYTHON
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 28 正在检查 Git
call :CHECK_GIT
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 40 正在检查 ffmpeg
call :CHECK_FFMPEG
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 52 正在检查 C++ Build Tools
call :CHECK_CPP_TOOLS
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 66 正在检查 CUDA Toolkit
call :CHECK_CUDA
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 80 正在检查 uv
call :CHECK_UV

if "%XB_ENV_CONFIGURE%"=="1" (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 94 正在写入用户环境变量
  echo.
  echo [XB-SVCB] Writing user environment variables...
  call :CONFIGURE_ENV
)

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 前置依赖检查完成
echo.
echo [XB-SVCB] Prerequisite bootstrap finished.
endlocal
exit /b 0

:RESOLVE_PATHS
if defined XB_PYTHON_DIR if exist "%XB_PYTHON_DIR%\python.exe" set "XB_PYTHON_EXE=%XB_PYTHON_DIR%\python.exe"

if defined XB_GIT_DIR (
  if exist "%XB_GIT_DIR%\cmd\git.exe" set "XB_GIT_BIN=%XB_GIT_DIR%\cmd"
  if not defined XB_GIT_BIN if exist "%XB_GIT_DIR%\bin\git.exe" set "XB_GIT_BIN=%XB_GIT_DIR%\bin"
)

if defined XB_FFMPEG_DIR (
  if exist "%XB_FFMPEG_DIR%\bin\ffmpeg.exe" set "XB_FFMPEG_BIN=%XB_FFMPEG_DIR%\bin"
  if not defined XB_FFMPEG_BIN if exist "%XB_FFMPEG_DIR%\ffmpeg.exe" set "XB_FFMPEG_BIN=%XB_FFMPEG_DIR%"
)

if defined XB_CUDA_DIR (
  if exist "%XB_CUDA_DIR%\bin\nvcc.exe" set "XB_CUDA_BIN=%XB_CUDA_DIR%\bin"
)
call :FIND_NVIDIA_SMI

if not defined XB_JUCE_HOST_EXE set "XB_JUCE_HOST_EXE=%~dp0engines\juce-vst3-host\xb-juce-vst3-host.exe"

if defined XB_VSBT_DIR (
  if exist "%XB_VSBT_DIR%\VC\Auxiliary\Build\vcvars64.bat" set "XB_VSINSTALLDIR=%XB_VSBT_DIR%\"
)

if defined XB_PYTHON_EXE set "PATH=%~dp0;%XB_PYTHON_DIR%;%XB_PYTHON_DIR%\Scripts;%PATH%"
if defined XB_GIT_BIN set "PATH=%XB_GIT_BIN%;%PATH%"
if defined XB_FFMPEG_BIN set "PATH=%XB_FFMPEG_BIN%;%PATH%"
if defined XB_CUDA_BIN set "PATH=%XB_CUDA_BIN%;%PATH%"
exit /b 0

:CHECK_JUCE_HOST
if not defined XB_JUCE_HOST_EXE set "XB_JUCE_HOST_EXE=%~dp0engines\juce-vst3-host\xb-juce-vst3-host.exe"
if exist "%XB_JUCE_HOST_EXE%" (
  echo [ok] JUCE VST3 Host found: %XB_JUCE_HOST_EXE%
  exit /b 0
)
echo [warn] JUCE VST3 Host not found: %XB_JUCE_HOST_EXE%
echo        VST3 plugin effects will be unavailable. Rebuild the installer with native\juce-vst3-host included.
exit /b 0

:RESOLVE_GPU_STACK
if /I "%XB_GPU_STACK_REQUESTED%"=="cpu" (
  set "XB_RESOLVED_GPU_STACK=cpu"
  set "XB_GPU_STACK=cpu"
  set "XB_CUDA_VERSION="
  set "XB_CUDA_DIR="
  set "XB_CUDA_BIN="
  exit /b 0
)

call :DETECT_GPU_STACK
if "%DETECTED_GPU_STACK%"=="cpu" (
  if /I not "%XB_GPU_STACK_REQUESTED%"=="auto" echo [gpu] No compatible NVIDIA GPU detected; CUDA will be skipped and CPU torch will be used.
  set "XB_RESOLVED_GPU_STACK=cpu"
  set "XB_GPU_STACK=cpu"
  set "XB_CUDA_VERSION="
  set "XB_CUDA_DIR="
  set "XB_CUDA_BIN="
  exit /b 0
)

if /I not "%XB_GPU_STACK_REQUESTED%"=="auto" if /I not "%XB_GPU_STACK_REQUESTED%"=="%DETECTED_GPU_STACK%" (
  echo [gpu] Requested %XB_GPU_STACK_REQUESTED%, but detected %DETECTED_GPU_STACK%; using the detected compatible stack.
)

set "XB_RESOLVED_GPU_STACK=%DETECTED_GPU_STACK%"
set "XB_GPU_STACK=%DETECTED_GPU_STACK%"
if "%XB_RESOLVED_GPU_STACK%"=="cu128" (
  set "XB_CUDA_VERSION=12.8"
) else (
  set "XB_CUDA_VERSION=12.1"
)
call :NORMALIZE_CUDA_DIR
exit /b 0

:FIND_NVIDIA_SMI
if defined XB_NVIDIA_SMI if exist "%XB_NVIDIA_SMI%" exit /b 0
set "XB_NVIDIA_SMI="
for %%P in (
  "%SystemRoot%\System32\nvidia-smi.exe"
  "%SystemRoot%\Sysnative\nvidia-smi.exe"
  "%ProgramFiles%\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
  "%ProgramW6432%\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
) do (
  if exist "%%~fP" if not defined XB_NVIDIA_SMI set "XB_NVIDIA_SMI=%%~fP"
)
if defined XB_NVIDIA_SMI exit /b 0
for /f "delims=" %%P in ('where nvidia-smi 2^>nul') do if not defined XB_NVIDIA_SMI set "XB_NVIDIA_SMI=%%P"
exit /b 0

:DETECT_GPU_STACK
set "DETECTED_GPU_STACK=cpu"
call :FIND_NVIDIA_SMI
if not defined XB_NVIDIA_SMI exit /b 0
for /f "tokens=1 delims=." %%A in ('"%XB_NVIDIA_SMI%" --query-gpu=compute_cap --format=csv,noheader 2^>nul') do (
  set "CAP_MAJOR=%%A"
  for /f "tokens=* delims= " %%B in ("!CAP_MAJOR!") do set "CAP_MAJOR=%%B"
  echo !CAP_MAJOR! | findstr /R "^[0-9][0-9]*$" >nul && (
    if !CAP_MAJOR! GEQ 12 set "DETECTED_GPU_STACK=cu128"
    if !CAP_MAJOR! GEQ 5 if not "!DETECTED_GPU_STACK!"=="cu128" set "DETECTED_GPU_STACK=cu121"
  )
)
if not "%DETECTED_GPU_STACK%"=="cpu" exit /b 0
for /f "delims=" %%G in ('"%XB_NVIDIA_SMI%" --query-gpu=name --format=csv,noheader 2^>nul') do (
  echo %%G | findstr /I /R "RTX *50[0-9][0-9]" >nul && set "DETECTED_GPU_STACK=cu128"
  if "!DETECTED_GPU_STACK!"=="cpu" set "DETECTED_GPU_STACK=cu121"
)
exit /b 0

:NORMALIZE_CUDA_DIR
if "%XB_RESOLVED_GPU_STACK%"=="cpu" exit /b 0
set "DEFAULT_CUDA_DIR=%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v%XB_CUDA_VERSION%"
if not defined XB_CUDA_DIR (
  set "XB_CUDA_DIR=%DEFAULT_CUDA_DIR%"
  exit /b 0
)
echo "%XB_CUDA_DIR%" | find /I "\NVIDIA GPU Computing Toolkit\CUDA\v12." >nul
if not errorlevel 1 (
  echo "%XB_CUDA_DIR%" | find /I "\v%XB_CUDA_VERSION%" >nul
  if errorlevel 1 set "XB_CUDA_DIR=%DEFAULT_CUDA_DIR%"
)
exit /b 0

:CHECK_PYTHON
where python >nul 2>&1 && (
  echo [ok] Python found in PATH
  exit /b 0
)
if defined XB_PYTHON_EXE if exist "%XB_PYTHON_EXE%" (
  echo [ok] Python found: %XB_PYTHON_EXE%
  exit /b 0
)
echo [miss] Python 3.10 not found.
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 18 正在安装 Python 3.10
call :WINGET_INSTALL "Python.Python.3.10" "%XB_PYTHON_DIR%" "Python 3.10"
call :RESOLVE_PATHS
exit /b 0

:CHECK_GIT
where git >nul 2>&1 && (
  echo [ok] Git found in PATH
  exit /b 0
)
if defined XB_GIT_BIN if exist "%XB_GIT_BIN%\git.exe" (
  echo [ok] Git found: %XB_GIT_BIN%\git.exe
  exit /b 0
)
echo [miss] Git not found.
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 32 正在安装 Git
call :WINGET_INSTALL "Git.Git" "%XB_GIT_DIR%" "Git"
call :RESOLVE_PATHS
exit /b 0

:CHECK_FFMPEG
where ffmpeg >nul 2>&1 && (
  echo [ok] ffmpeg found in PATH
  exit /b 0
)
if defined XB_FFMPEG_BIN if exist "%XB_FFMPEG_BIN%\ffmpeg.exe" (
  echo [ok] ffmpeg found: %XB_FFMPEG_BIN%\ffmpeg.exe
  exit /b 0
)
echo [miss] ffmpeg not found.
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 44 正在安装 ffmpeg
call :WINGET_INSTALL "Gyan.FFmpeg" "%XB_FFMPEG_DIR%" "ffmpeg"
call :RESOLVE_PATHS
exit /b 0

:CHECK_CPP_TOOLS
where cl >nul 2>&1 && (
  echo [ok] C++ compiler found in PATH
  exit /b 0
)
if defined XB_VSINSTALLDIR if exist "%XB_VSINSTALLDIR%VC\Auxiliary\Build\vcvars64.bat" (
  echo [ok] C++ Build Tools found: %XB_VSINSTALLDIR%
  exit /b 0
)
if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" (
  "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%TEMP%\xb_vs_path.txt" 2>nul
  set /p XB_VSINSTALLDIR=<"%TEMP%\xb_vs_path.txt"
  del "%TEMP%\xb_vs_path.txt" >nul 2>&1
  if defined XB_VSINSTALLDIR if exist "%XB_VSINSTALLDIR%\VC\Auxiliary\Build\vcvars64.bat" (
    set "XB_VSINSTALLDIR=%XB_VSINSTALLDIR%\"
    echo [ok] C++ Build Tools found: %XB_VSINSTALLDIR%
    exit /b 0
  )
  set "XB_VSINSTALLDIR="
)
echo [miss] Microsoft C++ Build Tools not found.
if "%XB_PREREQ_AUTO%"=="1" (
  where winget >nul 2>&1 && (
    if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 58 正在安装 C++ Build Tools
    echo      Installing C++ Build Tools through winget. This can take a long time...
    winget install -e --id Microsoft.VisualStudio.2022.BuildTools --silent --accept-package-agreements --accept-source-agreements --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  )
) else (
  echo      Auto install disabled; install "Desktop development with C++" if fairseq needs compilation.
)
exit /b 0

:CHECK_CUDA
call :RESOLVE_GPU_STACK
if "%XB_RESOLVED_GPU_STACK%"=="cpu" (
  echo [skip] CUDA check skipped for CPU mode or incompatible GPU.
  exit /b 0
)

call :USE_CUDA_DIR_IF_VERSION "%CUDA_PATH%" "CUDA_PATH" && exit /b 0
call :USE_CUDA_DIR_IF_VERSION "%XB_CUDA_DIR%" "selected path" && exit /b 0
call :USE_CUDA_DIR_IF_VERSION "%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v%XB_CUDA_VERSION%" "default path" && exit /b 0
call :USE_NVCC_FROM_PATH_IF_VERSION && exit /b 0

echo [miss] CUDA Toolkit %XB_CUDA_VERSION% not found for %XB_RESOLVED_GPU_STACK%.
echo        PyTorch wheels include CUDA runtime, but Toolkit tools will be installed only when they match the GPU stack.
if "%XB_PREREQ_AUTO%"=="1" (
  if "%XB_RESOLVED_GPU_STACK%"=="cu128" (
    if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 72 正在安装 CUDA Toolkit 12.8
    call :WINGET_INSTALL_VERSION "Nvidia.CUDA" "12.8" "%XB_CUDA_DIR%" "CUDA Toolkit 12.8"
  ) else (
    if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 72 正在安装 CUDA Toolkit 12.1
    call :WINGET_INSTALL_VERSION "Nvidia.CUDA" "12.1" "%XB_CUDA_DIR%" "CUDA Toolkit 12.1"
  )
)
call :RESOLVE_PATHS
call :USE_CUDA_DIR_IF_VERSION "%XB_CUDA_DIR%" "selected path" >nul 2>&1
exit /b 0

:USE_CUDA_DIR_IF_VERSION
set "CUDA_CANDIDATE=%~1"
set "CUDA_LABEL=%~2"
if not defined CUDA_CANDIDATE exit /b 1
if not exist "%CUDA_CANDIDATE%\bin\nvcc.exe" exit /b 1
"%CUDA_CANDIDATE%\bin\nvcc.exe" --version > "%TEMP%\xb_nvcc_version.txt" 2>nul
findstr /C:"release %XB_CUDA_VERSION%" "%TEMP%\xb_nvcc_version.txt" >nul
if errorlevel 1 (
  echo [mismatch] CUDA Toolkit found at %CUDA_CANDIDATE%, but it does not match required %XB_CUDA_VERSION% for %XB_RESOLVED_GPU_STACK%.
  exit /b 1
)
set "XB_CUDA_DIR=%CUDA_CANDIDATE%"
set "XB_CUDA_BIN=%CUDA_CANDIDATE%\bin"
echo [ok] CUDA Toolkit %XB_CUDA_VERSION% found from %CUDA_LABEL%: %CUDA_CANDIDATE%
exit /b 0

:USE_NVCC_FROM_PATH_IF_VERSION
where nvcc >nul 2>&1 || exit /b 1
nvcc --version > "%TEMP%\xb_nvcc_version.txt" 2>nul
findstr /C:"release %XB_CUDA_VERSION%" "%TEMP%\xb_nvcc_version.txt" >nul
if errorlevel 1 (
  echo [mismatch] CUDA Toolkit in PATH does not match required %XB_CUDA_VERSION% for %XB_RESOLVED_GPU_STACK%.
  exit /b 1
)
echo [ok] CUDA Toolkit %XB_CUDA_VERSION% found in PATH
exit /b 0

:CHECK_UV
where uv >nul 2>&1 && (
  echo [ok] uv found in PATH
  exit /b 0
)
if not "%XB_PREREQ_AUTO%"=="1" (
  echo [miss] uv not found. Auto install disabled; install.py can still try to install it when building env.
  exit /b 0
)
if defined XB_PYTHON_EXE if exist "%XB_PYTHON_EXE%" (
  echo [miss] uv not found; installing with Python pip...
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 86 正在安装 uv
  "%XB_PYTHON_EXE%" -m pip install -U uv -i "%PIP_INDEX_URL%" --extra-index-url https://pypi.org/simple
  if errorlevel 1 (
    echo [warn] PyPI mirror failed; retrying uv install with official PyPI...
    "%XB_PYTHON_EXE%" -m pip install -U uv -i https://pypi.org/simple
  )
  exit /b 0
)
where python >nul 2>&1 && (
  echo [miss] uv not found; installing with Python pip...
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 86 正在安装 uv
  python -m pip install -U uv -i "%PIP_INDEX_URL%" --extra-index-url https://pypi.org/simple
  if errorlevel 1 (
    echo [warn] PyPI mirror failed; retrying uv install with official PyPI...
    python -m pip install -U uv -i https://pypi.org/simple
  )
  exit /b 0
)
echo [miss] uv not installed and Python is unavailable.
exit /b 0

:WINGET_INSTALL
set "PKG=%~1"
set "LOCATION=%~2"
set "LABEL=%~3"
if not "%XB_PREREQ_AUTO%"=="1" (
  echo      Auto install disabled for %LABEL%.
  exit /b 0
)
where winget >nul 2>&1 || (
  echo      winget is not available; please install %LABEL% manually.
  exit /b 0
)
if defined LOCATION (
  echo      Installing %LABEL% to %LOCATION% ...
  winget install -e --id "%PKG%" --silent --accept-package-agreements --accept-source-agreements --location "%LOCATION%"
) else (
  echo      Installing %LABEL% ...
  winget install -e --id "%PKG%" --silent --accept-package-agreements --accept-source-agreements
)
exit /b 0

:WINGET_INSTALL_VERSION
set "PKG=%~1"
set "VER=%~2"
set "LOCATION=%~3"
set "LABEL=%~4"
if not "%XB_PREREQ_AUTO%"=="1" exit /b 0
where winget >nul 2>&1 || (
  echo      winget is not available; please install %LABEL% manually.
  exit /b 0
)
if defined LOCATION (
  echo      Installing %LABEL% to %LOCATION% ...
  winget install -e --id "%PKG%" --version "%VER%" --silent --accept-package-agreements --accept-source-agreements --location "%LOCATION%"
) else (
  echo      Installing %LABEL% ...
  winget install -e --id "%PKG%" --version "%VER%" --silent --accept-package-agreements --accept-source-agreements
)
exit /b 0

:CONFIGURE_ENV
if defined XB_PYTHON_DIR call :ADD_USER_PATH "%XB_PYTHON_DIR%"
if defined XB_PYTHON_DIR call :ADD_USER_PATH "%XB_PYTHON_DIR%\Scripts"
if defined XB_GIT_BIN call :ADD_USER_PATH "%XB_GIT_BIN%"
if defined XB_FFMPEG_BIN call :ADD_USER_PATH "%XB_FFMPEG_BIN%"
if defined XB_CUDA_BIN call :ADD_USER_PATH "%XB_CUDA_BIN%"
if defined XB_CUDA_DIR reg add HKCU\Environment /v CUDA_PATH /t REG_EXPAND_SZ /d "%XB_CUDA_DIR%" /f >nul
if defined XB_VSINSTALLDIR reg add HKCU\Environment /v VSINSTALLDIR /t REG_EXPAND_SZ /d "%XB_VSINSTALLDIR%" /f >nul
if defined XB_HF_MIRROR reg add HKCU\Environment /v XB_HF_MIRROR /t REG_SZ /d "%XB_HF_MIRROR%" /f >nul
if defined HF_ENDPOINT reg add HKCU\Environment /v HF_ENDPOINT /t REG_SZ /d "%HF_ENDPOINT%" /f >nul
if defined HUGGINGFACE_HUB_ENDPOINT reg add HKCU\Environment /v HUGGINGFACE_HUB_ENDPOINT /t REG_SZ /d "%HUGGINGFACE_HUB_ENDPOINT%" /f >nul
if defined XB_PYPI_MIRROR reg add HKCU\Environment /v XB_PYPI_MIRROR /t REG_SZ /d "%XB_PYPI_MIRROR%" /f >nul
if defined PIP_INDEX_URL reg add HKCU\Environment /v PIP_INDEX_URL /t REG_SZ /d "%PIP_INDEX_URL%" /f >nul
if defined UV_DEFAULT_INDEX reg add HKCU\Environment /v UV_DEFAULT_INDEX /t REG_SZ /d "%UV_DEFAULT_INDEX%" /f >nul
if defined PIP_DISABLE_PIP_VERSION_CHECK reg add HKCU\Environment /v PIP_DISABLE_PIP_VERSION_CHECK /t REG_SZ /d "%PIP_DISABLE_PIP_VERSION_CHECK%" /f >nul
exit /b 0

:ADD_USER_PATH
set "ADD_PATH=%~1"
if not defined ADD_PATH exit /b 0
if not exist "%ADD_PATH%" exit /b 0
set "USER_PATH="
for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v Path 2^>nul') do set "USER_PATH=%%B"
echo ;%USER_PATH%; | find /I ";%ADD_PATH%;" >nul && (
  echo [env] PATH already contains %ADD_PATH%
  set "PATH=%ADD_PATH%;%PATH%"
  exit /b 0
)
if defined USER_PATH (
  reg add HKCU\Environment /v Path /t REG_EXPAND_SZ /d "%USER_PATH%;%ADD_PATH%" /f >nul
) else (
  reg add HKCU\Environment /v Path /t REG_EXPAND_SZ /d "%ADD_PATH%" /f >nul
)
set "PATH=%ADD_PATH%;%PATH%"
echo [env] PATH += %ADD_PATH%
exit /b 0
