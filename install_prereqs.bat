@echo off
rem ============================================================
rem  XB-SVCB - prerequisite checker used by the Inno setup.
rem
rem  It is intentionally plain batch: no PowerShell dependency.
rem  The installer writes installer_env.cmd before calling this file.
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul

if exist "%~dp0installer_env.cmd" call "%~dp0installer_env.cmd"

if not defined XB_ENV_CONFIGURE set "XB_ENV_CONFIGURE=1"
if not defined XB_GPU_STACK set "XB_GPU_STACK=auto"
if not defined XB_GPU_STACK_REQUESTED set "XB_GPU_STACK_REQUESTED=%XB_GPU_STACK%"
if not defined XB_HF_MIRROR set "XB_HF_MIRROR=https://hf-mirror.com"
if not defined HF_ENDPOINT set "HF_ENDPOINT=%XB_HF_MIRROR%"
if not defined HUGGINGFACE_HUB_ENDPOINT set "HUGGINGFACE_HUB_ENDPOINT=%XB_HF_MIRROR%"
if not defined XB_PYPI_MIRROR set "XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=%XB_PYPI_MIRROR%"
if not defined UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=%XB_PYPI_MIRROR%"
if not defined XB_WHEELHOUSE if exist "%~dp0assets\wheels\wheelhouse.json" set "XB_WHEELHOUSE=%~dp0assets\wheels"
if defined XB_WHEELHOUSE if not defined XB_WHEELHOUSE_STRICT set "XB_WHEELHOUSE_STRICT=1"
if not defined UV_LINK_MODE set "UV_LINK_MODE=copy"
if not defined PIP_DISABLE_PIP_VERSION_CHECK set "PIP_DISABLE_PIP_VERSION_CHECK=1"
if not defined XB_FFMPEG_DIR if exist "%~dp0tools\ffmpeg\bin\ffmpeg.exe" set "XB_FFMPEG_DIR=%~dp0tools\ffmpeg"

echo [XB-SVCB] Checking prerequisites...
echo           install mode : user-assisted (no automatic system installs)
echo           gpu request  : %XB_GPU_STACK_REQUESTED%
echo           HF mirror    : %HF_ENDPOINT%
echo           PyPI mirror  : %PIP_INDEX_URL%
if defined XB_WHEELHOUSE echo           wheelhouse   : %XB_WHEELHOUSE%
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
if errorlevel 1 exit /b 1
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 28 正在检查 Git
call :CHECK_GIT
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 40 正在检查 ffmpeg
call :CHECK_FFMPEG
if errorlevel 1 exit /b 1
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 52 正在检查 C++ Build Tools
call :CHECK_CPP_TOOLS
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 60 正在检查 VB-CABLE 虚拟音频线
call :CHECK_VBCABLE
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 66 正在检查 GPU 运行环境
call :CHECK_CUDA
if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 80 正在检查 uv
call :CHECK_UV

if "%XB_ENV_CONFIGURE%"=="1" (
  if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 94 正在写入用户环境变量
  echo.
  echo [XB-SVCB] Writing user environment variables...
  call :CONFIGURE_ENV
  if errorlevel 1 exit /b 1
)

if "%XB_FROM_INSTALLER%"=="1" echo [XB-PROGRESS] 100 前置依赖检查完成
echo.
echo [XB-SVCB] Prerequisite check finished.
endlocal
exit /b 0

:RESOLVE_PATHS
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
  if exist "!XB_VSBT_DIR!\VC\Auxiliary\Build\vcvars64.bat" set "XB_VSINSTALLDIR=!XB_VSBT_DIR!\"
)

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
set "DETECTED_GPU_STACK="
if /I "%XB_GPU_STACK_REQUESTED%"=="auto" if /I "%XB_GPU_STACK%"=="cpu" set "DETECTED_GPU_STACK=cpu"
if /I "%XB_GPU_STACK_REQUESTED%"=="auto" if /I "%XB_GPU_STACK%"=="directml" set "DETECTED_GPU_STACK=directml"
if /I "%XB_GPU_STACK_REQUESTED%"=="auto" if /I "%XB_GPU_STACK%"=="cu121" set "DETECTED_GPU_STACK=cu121"
if /I "%XB_GPU_STACK_REQUESTED%"=="auto" if /I "%XB_GPU_STACK%"=="cu128" set "DETECTED_GPU_STACK=cu128"
if /I "%XB_GPU_STACK_REQUESTED%"=="cpu" (
  set "XB_RESOLVED_GPU_STACK=cpu"
  set "XB_GPU_STACK=cpu"
  set "XB_CUDA_VERSION="
  set "XB_CUDA_DIR="
  set "XB_CUDA_BIN="
  exit /b 0
)
if /I "%XB_GPU_STACK_REQUESTED%"=="directml" (
  set "XB_RESOLVED_GPU_STACK=directml"
  set "XB_GPU_STACK=directml"
  set "XB_CUDA_VERSION="
  set "XB_CUDA_DIR="
  set "XB_CUDA_BIN="
  exit /b 0
)

if not defined DETECTED_GPU_STACK call :DETECT_GPU_STACK
if "%DETECTED_GPU_STACK%"=="cpu" (
  if /I not "%XB_GPU_STACK_REQUESTED%"=="auto" echo [gpu] No compatible NVIDIA or AMD GPU detected; CPU torch will be used.
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
if "%XB_RESOLVED_GPU_STACK%"=="directml" (
  set "XB_CUDA_VERSION="
  set "XB_CUDA_DIR="
  set "XB_CUDA_BIN="
  exit /b 0
)
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
if not defined XB_NVIDIA_SMI goto DETECT_ADAPTER_GPU
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
if not "%DETECTED_GPU_STACK%"=="cpu" exit /b 0
:DETECT_ADAPTER_GPU
for /f "delims=" %%G in ('powershell.exe -NoProfile -Command "Get-CimInstance Win32_VideoController ^| Select-Object -ExpandProperty Name" 2^>nul') do (
  echo %%G | findstr /I /C:"NVIDIA" /C:"GeForce" >nul && (
    echo %%G | findstr /I /R "RTX *50[0-9][0-9]" >nul && set "DETECTED_GPU_STACK=cu128"
    if "!DETECTED_GPU_STACK!"=="cpu" set "DETECTED_GPU_STACK=cu121"
  )
)
if not "%DETECTED_GPU_STACK%"=="cpu" exit /b 0
for /f "delims=" %%G in ('powershell.exe -NoProfile -Command "Get-CimInstance Win32_VideoController ^| Select-Object -ExpandProperty Name" 2^>nul') do (
  echo %%G | findstr /I /C:"AMD" /C:"Radeon" >nul && set "DETECTED_GPU_STACK=directml"
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
set "PYTHON_DETECTOR=%~dp0install\detect_python.bat"
if not exist "!PYTHON_DETECTOR!" (
  echo [fail] Python detector not found: !PYTHON_DETECTOR!
  exit /b 1
)
call "!PYTHON_DETECTOR!"
if not errorlevel 1 (
  set "PATH=!XB_PYTHON_DIR!;!XB_PYTHON_DIR!\Scripts;!PATH!"
  echo [ok] Python 3.10+ verified: !XB_PYTHON_EXE!
  exit /b 0
)
echo [fail] A runnable Python 3.10 or newer was not found.
call :MANUAL_GUIDANCE "Python 3.10" "https://www.python.org/downloads/windows/"
exit /b 1

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
call :MANUAL_GUIDANCE "Git" "https://git-scm.com/download/win"
call :RESOLVE_PATHS
exit /b 0

:CHECK_FFMPEG
ffmpeg -version >nul 2>&1 && ffprobe -version >nul 2>&1 && (
  set "XB_FFMPEG_BIN="
  for /f "delims=" %%P in ('where ffmpeg 2^>nul') do if not defined XB_FFMPEG_BIN set "XB_FFMPEG_BIN=%%~dpP"
  if defined XB_FFMPEG_BIN set "XB_FFMPEG_BIN=!XB_FFMPEG_BIN:~0,-1!"
  if defined XB_FFMPEG_BIN (
    for %%D in ("!XB_FFMPEG_BIN!") do set "FFMPEG_BIN_NAME=%%~nxD"
    if /I "!FFMPEG_BIN_NAME!"=="bin" (
      for %%D in ("!XB_FFMPEG_BIN!\..") do set "XB_FFMPEG_DIR=%%~fD"
    ) else (
      set "XB_FFMPEG_DIR=!XB_FFMPEG_BIN!"
    )
  )
  if /I "!XB_FFMPEG_BIN!"=="%~dp0tools\ffmpeg\bin" (
    echo [ok] bundled ffmpeg found: !XB_FFMPEG_BIN!\ffmpeg.exe
  ) else (
    echo [ok] system ffmpeg found; bundled deployment skipped: !XB_FFMPEG_BIN!\ffmpeg.exe
  )
  exit /b 0
)
if defined XB_FFMPEG_BIN if exist "%XB_FFMPEG_BIN%\ffmpeg.exe" if exist "%XB_FFMPEG_BIN%\ffprobe.exe" (
  echo [ok] bundled ffmpeg/ffprobe found: %XB_FFMPEG_BIN%
  exit /b 0
)
echo [fail] A working ffmpeg/ffprobe pair was not found in PATH and the bundled payload is missing.
echo        Expected: %~dp0tools\ffmpeg\bin\ffmpeg.exe and ffprobe.exe
exit /b 1

:CHECK_CPP_TOOLS
set "VSWHERE_EXE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
where cl >nul 2>&1 && (
  echo [ok] C++ compiler found in PATH
  exit /b 0
)
if defined XB_VSINSTALLDIR if exist "!XB_VSINSTALLDIR!VC\Auxiliary\Build\vcvars64.bat" (
  echo [ok] C++ Build Tools found: !XB_VSINSTALLDIR!
  exit /b 0
)
if exist "!VSWHERE_EXE!" (
  "!VSWHERE_EXE!" -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%TEMP%\xb_vs_path.txt" 2>nul
  set /p XB_VSINSTALLDIR=<"%TEMP%\xb_vs_path.txt"
  del "%TEMP%\xb_vs_path.txt" >nul 2>&1
  if defined XB_VSINSTALLDIR if exist "!XB_VSINSTALLDIR!\VC\Auxiliary\Build\vcvars64.bat" (
    set "XB_VSINSTALLDIR=!XB_VSINSTALLDIR!\"
    echo [ok] C++ Build Tools found: !XB_VSINSTALLDIR!
    exit /b 0
  )
  set "XB_VSINSTALLDIR="
)
echo [miss] Microsoft C++ Build Tools not found.
call :MANUAL_GUIDANCE "Microsoft C++ Build Tools" "https://visualstudio.microsoft.com/visual-cpp-build-tools/"
exit /b 0

:CHECK_CUDA
call :RESOLVE_GPU_STACK
if "%XB_RESOLVED_GPU_STACK%"=="cpu" (
  echo [skip] CUDA check skipped for CPU mode or incompatible GPU.
  exit /b 0
)
if "%XB_RESOLVED_GPU_STACK%"=="directml" (
  echo [skip] CUDA check skipped for AMD DirectML mode.
  exit /b 0
)

call :USE_CUDA_DIR_IF_VERSION "%CUDA_PATH%" "CUDA_PATH" && exit /b 0
call :USE_CUDA_DIR_IF_VERSION "%XB_CUDA_DIR%" "selected path" && exit /b 0
call :USE_CUDA_DIR_IF_VERSION "%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v%XB_CUDA_VERSION%" "default path" && exit /b 0
call :USE_NVCC_FROM_PATH_IF_VERSION && exit /b 0

echo [miss] CUDA Toolkit %XB_CUDA_VERSION% not found for %XB_RESOLVED_GPU_STACK%.
echo        PyTorch wheels include CUDA runtime, but Toolkit tools will be installed only when they match the GPU stack.
if "%XB_RESOLVED_GPU_STACK%"=="cu128" (
  call :MANUAL_GUIDANCE "CUDA Toolkit 12.8" "https://developer.nvidia.com/cuda-downloads"
) else (
  call :MANUAL_GUIDANCE "CUDA Toolkit 12.1" "https://developer.nvidia.com/cuda-downloads"
)
call :RESOLVE_PATHS
call :USE_CUDA_DIR_IF_VERSION "%XB_CUDA_DIR%" "selected path" >nul 2>&1
exit /b 0

:CHECK_VBCABLE
set "XB_VBCABLE_INPUT="
set "XB_VBCABLE_OUTPUT="
for /f "delims=" %%D in ('powershell.exe -NoProfile -NonInteractive -Command "(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue).Name; (Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FriendlyName)" 2^>nul') do (
  echo %%D | findstr /I /C:"CABLE Input" >nul && set "XB_VBCABLE_INPUT=1"
  echo %%D | findstr /I /C:"CABLE Output" >nul && set "XB_VBCABLE_OUTPUT=1"
)
if defined XB_VBCABLE_INPUT if defined XB_VBCABLE_OUTPUT (
  set "XB_VBCABLE_READY=1"
  echo [ok] VB-CABLE virtual audio endpoints found.
  exit /b 0
)
reg query "HKLM\SOFTWARE\VB-Audio\VBCABLE" >nul 2>&1 && (
  set "XB_VBCABLE_READY=1"
  echo [ok] VB-CABLE installation record found.
  exit /b 0
)
reg query "HKLM\SOFTWARE\WOW6432Node\VB-Audio\VBCABLE" >nul 2>&1 && (
  set "XB_VBCABLE_READY=1"
  echo [ok] VB-CABLE installation record found.
  exit /b 0
)
set "XB_VBCABLE_READY="
echo [optional] VB-CABLE not detected. System audio voice changing will need it.
echo            Install manually from: https://vb-audio.com/Cable/
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
call :FIND_LOCAL_UV && exit /b 0
if not defined XB_PYTHON_EXE call :CHECK_PYTHON
if not defined XB_PYTHON_EXE (
  echo [skip] uv will be installed automatically after Python is available.
  exit /b 0
)
echo [auto] uv not found. Installing uv with the detected Python...
"%XB_PYTHON_EXE%" -m ensurepip --upgrade
if errorlevel 1 echo [warn] ensurepip did not complete; trying existing pip anyway.
call :PIP_INSTALL_UV "%PIP_INDEX_URL%"
if errorlevel 1 (
  echo [warn] uv install from mirror failed; retrying fallback PyPI mirror.
  call :PIP_INSTALL_UV "https://mirrors.cloud.tencent.com/pypi/simple"
)
if errorlevel 1 (
  echo [fail] uv automatic installation failed.
  exit /b 1
)
call :FIND_LOCAL_UV && exit /b 0
where uv >nul 2>&1 && (
  echo [ok] uv installed and found in PATH
  exit /b 0
)
echo [fail] uv was installed, but uv.exe was not found in the Python Scripts directory.
exit /b 1

:PIP_INSTALL_UV
set "UV_INDEX_URL=%~1"
if defined XB_WHEELHOUSE if exist "%XB_WHEELHOUSE%\bootstrap" (
  "%XB_PYTHON_EXE%" -m pip install --user --upgrade uv --disable-pip-version-check --no-index --find-links "%XB_WHEELHOUSE%\bootstrap"
  if not errorlevel 1 exit /b 0
  if "%XB_WHEELHOUSE_STRICT%"=="1" exit /b 1
  echo [warn] bundled uv wheel failed; retrying online PyPI.
)
if defined UV_INDEX_URL (
  "%XB_PYTHON_EXE%" -m pip install --user --upgrade uv --disable-pip-version-check --index-url "%UV_INDEX_URL%"
) else (
  "%XB_PYTHON_EXE%" -m pip install --user --upgrade uv --disable-pip-version-check
)
exit /b %ERRORLEVEL%

:FIND_LOCAL_UV
if not defined XB_PYTHON_EXE exit /b 1
set "XB_UV_BIN="
for /f "delims=" %%P in ('"%XB_PYTHON_EXE%" -c "import sysconfig; print(sysconfig.get_path('scripts') or '')" 2^>nul') do if not defined XB_UV_BIN set "XB_UV_BIN=%%P"
if defined XB_UV_BIN if exist "!XB_UV_BIN!\uv.exe" (
  set "XB_PYTHON_SCRIPTS=!XB_UV_BIN!"
  set "PATH=!XB_UV_BIN!;!PATH!"
  echo [ok] uv found in Python Scripts: !XB_UV_BIN!\uv.exe
  exit /b 0
)
set "XB_UV_BIN="
for /f "delims=" %%P in ('"%XB_PYTHON_EXE%" -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user') or '')" 2^>nul') do if not defined XB_UV_BIN set "XB_UV_BIN=%%P"
if defined XB_UV_BIN if exist "!XB_UV_BIN!\uv.exe" (
  set "XB_PYTHON_SCRIPTS=!XB_UV_BIN!"
  set "PATH=!XB_UV_BIN!;!PATH!"
  echo [ok] uv found in user Scripts: !XB_UV_BIN!\uv.exe
  exit /b 0
)
exit /b 1

:MANUAL_GUIDANCE
set "GUIDANCE_LABEL=%~1"
set "GUIDANCE_URL=%~2"
echo      Please install %GUIDANCE_LABEL% manually, then run the check again.
echo      Download: %GUIDANCE_URL%
exit /b 0

:CONFIGURE_ENV
set "ENV_CONFIG_HELPER=%~dp0install\configure_user_env.py"
if not exist "!ENV_CONFIG_HELPER!" (
  echo [fail] Environment configuration helper not found: !ENV_CONFIG_HELPER!
  exit /b 1
)
if not defined XB_PYTHON_EXE (
  call :CHECK_PYTHON
  if errorlevel 1 (
    echo [fail] Python executable unavailable for environment configuration.
    exit /b 1
  )
)
if defined XB_PYTHON_DIR set "XB_PYTHON_SCRIPTS=%XB_PYTHON_DIR%\Scripts"
set "ENV_CONFIG_DRY_RUN="
if "%XB_ENV_DRY_RUN%"=="1" set "ENV_CONFIG_DRY_RUN=--dry-run"

"!XB_PYTHON_EXE!" -X utf8 "!ENV_CONFIG_HELPER!" !ENV_CONFIG_DRY_RUN! ^
  --path-env XB_PYTHON_DIR ^
  --path-env XB_PYTHON_SCRIPTS ^
  --path-env XB_GIT_BIN ^
  --path-env XB_FFMPEG_BIN ^
  --path-env XB_CUDA_BIN ^
  --value-env XB_FFMPEG_DIR=XB_FFMPEG_DIR ^
  --expand-value-env FFMPEG_HOME=XB_FFMPEG_DIR ^
  --expand-value-env CUDA_PATH=XB_CUDA_DIR ^
  --expand-value-env VSINSTALLDIR=XB_VSINSTALLDIR ^
  --value-env XB_HF_MIRROR=XB_HF_MIRROR ^
  --value-env HF_ENDPOINT=HF_ENDPOINT ^
  --value-env HUGGINGFACE_HUB_ENDPOINT=HUGGINGFACE_HUB_ENDPOINT ^
  --value-env XB_PYPI_MIRROR=XB_PYPI_MIRROR ^
  --value-env PIP_INDEX_URL=PIP_INDEX_URL ^
  --value-env UV_DEFAULT_INDEX=UV_DEFAULT_INDEX ^
  --value-env XB_WHEELHOUSE=XB_WHEELHOUSE ^
  --value-env XB_WHEELHOUSE_STRICT=XB_WHEELHOUSE_STRICT ^
  --value-env PIP_DISABLE_PIP_VERSION_CHECK=PIP_DISABLE_PIP_VERSION_CHECK
set "ENV_CONFIG_RC=!ERRORLEVEL!"
if not "!ENV_CONFIG_RC!"=="0" echo [fail] User environment configuration failed with exit code !ENV_CONFIG_RC!.
exit /b !ENV_CONFIG_RC!
