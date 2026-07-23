<#
  构建 XB-SVCB 安装程序（setup.exe）——开发方。
  步骤：
  1）将前端构建为 web/dist（除非使用 -SkipWebBuild）
  2）使用 PyInstaller 将应用程序打包成 exe 文件，存入 dist/XB-SVCB（除非使用 -SkipAppBuild）
  3）将原生 JUCE VST3 主机构建为 engines/juce-vst3-host（除非使用 -SkipJuceHostBuild）
  4）验证生成的运行时捆绑包
  5）使用 Inno Setup 的 ISCC 编译 installer/xb-svcb.iss
  6）输出结果：dist/XB-SVCB-Setup.exe + 分割后的 .bin 数据包

  Prerequisites: Node.js (frontend build), app/.venv with pywebview + pyinstaller,
                 CMake + C++17 compiler + JUCE for the VST3 host,
                 Inno Setup 6 (provides ISCC.exe)
                 Inno Setup download: https://jrsoftware.org/isdl.php

  Usage:
    ./installer/build.ps1
    ./installer/build.ps1 -SkipWebBuild     # skip when web/dist already built
    ./installer/build.ps1 -SkipAppBuild     # skip when dist/XB-SVCB already built
    ./installer/build.ps1 -ValidateOnly     # validate scripts without packaging models
#>

param(
  [switch]$SkipWebBuild,
  [switch]$SkipAppBuild,
  [switch]$SkipJuceHostBuild,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot   # repo root
Set-Location -Path $Root

function Require-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label not found: $Path"
  }
}

function Require-FileSize([string]$Path, [long]$MinimumBytes, [string]$Label) {
  Require-File $Path $Label
  $item = Get-Item -LiteralPath $Path
  if ($item.Length -lt $MinimumBytes) {
    throw "$Label is incomplete: $Path ($($item.Length) bytes; expected at least $MinimumBytes)"
  }
}

function Read-RegexValue([string]$Path, [string]$Pattern, [string]$Label) {
  Require-File $Path $Label
  $text = Get-Content -LiteralPath $Path -Raw
  if ($text -notmatch $Pattern) {
    throw "Unable to read $Label from $Path"
  }
  return $Matches[1]
}

function Find-ISCC {
  $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
  )
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  return $null
}

# Refuse to publish mismatched app/frontend/installer versions.
$appVersion = Read-RegexValue (Join-Path $Root "app\config.py") 'APP_VERSION\s*=\s*["'']([^"'']+)["'']' "app version"
$appProjectVersion = Read-RegexValue (Join-Path $Root "app\pyproject.toml") '(?m)^version\s*=\s*["'']([^"'']+)["'']' "app project version"
$appLockVersion = Read-RegexValue (Join-Path $Root "app\uv.lock") '(?s)\[\[package\]\]\s*name\s*=\s*["'']app["'']\s*version\s*=\s*["'']([^"'']+)["'']' "app lock version"
$appExeVersion = Read-RegexValue (Join-Path $Root "installer\xb-svcb-version.txt") 'StringStruct\(u["'']ProductVersion["''],\s*u["'']([^"'']+)["'']\)' "app executable version"
$installerVersion = Read-RegexValue (Join-Path $Root "installer\xb-svcb.iss") '#define\s+MyAppVersion\s+["'']([^"'']+)["'']' "installer version"
$webPackage = Get-Content -LiteralPath (Join-Path $Root "web\package.json") -Raw | ConvertFrom-Json
$webVersion = [string]$webPackage.version
$webLockVersion = Read-RegexValue (Join-Path $Root "web\package-lock.json") '\A\s*\{\s*["'']name["'']\s*:\s*["''][^"'']+["'']\s*,\s*["'']version["'']\s*:\s*["'']([^"'']+)["'']' "web lock version"
if (($appVersion -ne $appProjectVersion) -or
    ($appVersion -ne $appLockVersion) -or
    ($appVersion -ne $appExeVersion) -or
    ($appVersion -ne $installerVersion) -or
    ($appVersion -ne $webVersion) -or
    ($appVersion -ne $webLockVersion)) {
  throw "Version mismatch: config=$appVersion, pyproject=$appProjectVersion, uv.lock=$appLockVersion, app-exe=$appExeVersion, installer=$installerVersion, web=$webVersion, package-lock=$webLockVersion"
}
Write-Host ("Release version: {0}" -f $appVersion) -ForegroundColor Green

$workerFiles = @(
  "inference_device.py",
  "svc_worker.py",
  "f0_worker.py",
  "uvr_worker.py",
  "hub_worker.py",
  "rvc_worker.py",
  "seedvc_worker.py",
  "ddsp_worker.py"
)
foreach ($worker in $workerFiles) {
  Require-File (Join-Path $Root "app\infrastructure\$worker") "Worker source $worker"
}
Require-File (Join-Path $Root "release_notes_v023.md") "v0.0.23 release notes"
Require-File (Join-Path $Root "docs\api.md") "FastAPI integration guide"
Require-File (Join-Path $Root "install\configure_user_env.py") "User environment helper"

# Reject Git LFS pointers or partial DDSP/SeedVC snapshots before producing a release.
Require-FileSize (Join-Path $Root "assets\models\pretrain\rmvpe.pt") 314572800 "Bundled SeedVC RMVPE"
$pcVocoderConfigPath = Join-Path $Root "assets\models\pretrain\pc_nsf_hifigan\config.json"
Require-File $pcVocoderConfigPath "Bundled DDSP PC-NSF-HiFiGAN config"
Require-FileSize (Join-Path $Root "assets\models\pretrain\pc_nsf_hifigan\model.ckpt") 33554432 "Bundled DDSP PC-NSF-HiFiGAN weights"
$pcVocoderConfig = Get-Content -LiteralPath $pcVocoderConfigPath -Raw | ConvertFrom-Json
if ($pcVocoderConfig.pc_aug -ne $true) {
  throw "Bundled DDSP vocoder is not pitch-controllable: $pcVocoderConfigPath"
}
Require-FileSize (Join-Path $Root "assets\models\seedvc\campplus_cn_common.bin") 20971520 "Bundled SeedVC CampPlus"
Require-File (Join-Path $Root "assets\models\seedvc\whisper-small\config.json") "Bundled Whisper config"
Require-File (Join-Path $Root "assets\models\seedvc\whisper-small\preprocessor_config.json") "Bundled Whisper preprocessor"
Require-FileSize (Join-Path $Root "assets\models\seedvc\whisper-small\model.safetensors") 943718400 "Bundled Whisper weights"
Require-File (Join-Path $Root "assets\models\seedvc\bigvgan_v2_44khz_128band_512x\config.json") "Bundled BigVGAN config"
Require-FileSize (Join-Path $Root "assets\models\seedvc\bigvgan_v2_44khz_128band_512x\bigvgan_generator.pt") 419430400 "Bundled BigVGAN weights"

if ($ValidateOnly) {
  $iscc = Find-ISCC
  if (-not $iscc) {
    throw "ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php"
  }
  $validateDir = Join-Path $Root ".tmp\installer-validate"
  if (Test-Path -LiteralPath $validateDir) {
    Remove-Item -LiteralPath $validateDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $validateDir | Out-Null
  try {
    & $iscc "/DXB_VALIDATE_ONLY=1" "/O$validateDir" "/FXB-SVCB-Installer-Validation" (Join-Path $Root "installer\xb-svcb.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup validation failed (exit code $LASTEXITCODE)" }
  } finally {
    if (Test-Path -LiteralPath $validateDir) {
      Remove-Item -LiteralPath $validateDir -Recurse -Force
    }
  }
  Write-Host "Installer scripts validated successfully." -ForegroundColor Green
  exit 0
}

# 1) Build frontend
if (-not $SkipWebBuild) {
  Write-Host "==== Building frontend (web/dist) ====" -ForegroundColor Cyan
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Install Node.js LTS, or pass -SkipWebBuild."
  }
  Push-Location (Join-Path $Root "web")
  try {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    if ($LASTEXITCODE -ne 0) { throw "npm install/ci failed (exit code $LASTEXITCODE). Frontend NOT rebuilt." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit code $LASTEXITCODE). Frontend NOT rebuilt." }
  } finally {
    Pop-Location
  }
}
Require-File (Join-Path $Root "web\dist\index.html") "Frontend entry (build without -SkipWebBuild)"

# 2) Build app exe with PyInstaller
if (-not $SkipAppBuild) {
  Write-Host "`n==== Building app exe (PyInstaller) ====" -ForegroundColor Cyan
  $venvPy = Join-Path $Root "app\.venv\Scripts\python.exe"
  if (-not (Test-Path $venvPy)) {
    throw "app\.venv not found. Run setup first (uv sync in app/), then: uv pip install --python app\.venv\Scripts\python.exe pyinstaller"
  }
  & $venvPy -c "import PyInstaller" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller missing in app/.venv, installing..." -ForegroundColor Yellow
    & uv pip install --python $venvPy pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Failed to install PyInstaller into app/.venv" }
  }
  & $venvPy -m PyInstaller (Join-Path $Root "installer\xb-svcb-app.spec") --noconfirm --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build")
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit code $LASTEXITCODE)" }
}
Require-File (Join-Path $Root "dist\XB-SVCB\XB-SVCB.exe") "Staged app executable (build without -SkipAppBuild)"

# PyInstaller data files must be present on disk for the external AI environments.
$stagedInternal = Join-Path $Root "dist\XB-SVCB\_internal"
Require-File (Join-Path $stagedInternal "web\dist\index.html") "Staged frontend entry"
foreach ($worker in $workerFiles) {
  Require-File (Join-Path $stagedInternal "infrastructure\$worker") "Staged worker $worker"
}

# 3) Build native JUCE VST3 host and stage it next to the app exe.
if (-not $SkipJuceHostBuild) {
  Write-Host "`n==== Building JUCE VST3 host ====" -ForegroundColor Cyan
  $hostBuild = Join-Path $Root "native\juce-vst3-host\build.ps1"
  if (-not (Test-Path $hostBuild)) {
    throw "native\juce-vst3-host\build.ps1 not found."
  }
  & $hostBuild
  if ($LASTEXITCODE -ne 0) { throw "JUCE VST3 host build failed (exit code $LASTEXITCODE)" }
}
$hostSrc = Join-Path $Root "engines\juce-vst3-host"
$hostDest = Join-Path $Root "dist\XB-SVCB\engines\juce-vst3-host"
if (-not (Test-Path $hostSrc)) {
  throw "JUCE host output not found: $hostSrc"
}
# A PyInstaller rebuild replaces dist/XB-SVCB, so even a cached Host must be staged again.
New-Item -ItemType Directory -Force -Path $hostDest | Out-Null
Copy-Item -Path (Join-Path $hostSrc "*") -Destination $hostDest -Recurse -Force
$stagedHostExe = Join-Path $Root "dist\XB-SVCB\engines\juce-vst3-host\xb-juce-vst3-host.exe"
Require-File $stagedHostExe "Staged JUCE VST3 host (build without -SkipJuceHostBuild)"

Require-File (Join-Path $Root "setup_env.bat") "Runtime setup entry"
Require-File (Join-Path $Root "install_prereqs.bat") "Prerequisite installer"
Require-File (Join-Path $Root "install\install.py") "Runtime installer"
Write-Host "Staged runtime bundle validated." -ForegroundColor Green

# 5) Compile installer
Write-Host "`n==== Compiling installer (Inno Setup) ====" -ForegroundColor Cyan
$iscc = Find-ISCC
if (-not $iscc) {
  throw "ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php"
}
Write-Host ("ISCC: {0}" -f $iscc) -ForegroundColor Green

New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
# Never leave an older setup payload next to a newly compiled bootstrapper.
Get-ChildItem -LiteralPath (Join-Path $Root "dist") -Filter "XB-SVCB-Setup*" -File -ErrorAction SilentlyContinue |
  Remove-Item -Force
& $iscc (Join-Path $Root "installer\xb-svcb.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed (exit code $LASTEXITCODE)" }

$out = Join-Path $Root "dist\XB-SVCB-Setup.exe"
Require-File $out "Installer bootstrapper"
$artifacts = Get-ChildItem -LiteralPath (Join-Path $Root "dist") -Filter "XB-SVCB-Setup*" -File |
  Sort-Object Name
if (-not ($artifacts | Where-Object { $_.Extension -eq ".bin" })) {
  throw "Installer payload slices were not generated. Check DiskSpanning in installer/xb-svcb.iss."
}
Write-Host "`nInstaller artifacts:" -ForegroundColor Green
$artifacts | ForEach-Object {
  Write-Host ("  {0} ({1:N1} MiB)" -f $_.FullName, ($_.Length / 1MB))
}
