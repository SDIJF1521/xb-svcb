<#
  Build the XB-SVCB installer (setup.exe) - developer side.

  Steps:
    1) Build the frontend into web/dist (unless -SkipWebBuild)
    2) Build the app exe with PyInstaller into dist/XB-SVCB (unless -SkipAppBuild)
    3) Build the native JUCE VST3 host into engines/juce-vst3-host (unless -SkipJuceHostBuild)
    4) Compile installer/xb-svcb.iss with Inno Setup's ISCC
    4) Output: dist/XB-SVCB-Setup.exe

  Prerequisites: Node.js (frontend build), app/.venv with pywebview + pyinstaller,
                 CMake + C++17 compiler + JUCE for the VST3 host,
                 Inno Setup 6 (provides ISCC.exe)
                 Inno Setup download: https://jrsoftware.org/isdl.php

  Usage:
    ./installer/build.ps1
    ./installer/build.ps1 -SkipWebBuild     # skip when web/dist already built
    ./installer/build.ps1 -SkipAppBuild     # skip when dist/XB-SVCB already built
#>

param(
  [switch]$SkipWebBuild,
  [switch]$SkipAppBuild,
  [switch]$SkipJuceHostBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot   # repo root
Set-Location -Path $Root

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
if (-not (Test-Path (Join-Path $Root "web\dist\index.html"))) {
  throw "web\dist\index.html not found. Build the frontend first (do not use -SkipWebBuild)."
}

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
if (-not (Test-Path (Join-Path $Root "dist\XB-SVCB\XB-SVCB.exe"))) {
  throw "dist\XB-SVCB\XB-SVCB.exe not found. Build the app exe first (do not use -SkipAppBuild)."
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

  $hostSrc = Join-Path $Root "engines\juce-vst3-host"
  $hostDest = Join-Path $Root "dist\XB-SVCB\engines\juce-vst3-host"
  if (-not (Test-Path $hostSrc)) {
    throw "JUCE host output not found: $hostSrc"
  }
  New-Item -ItemType Directory -Force -Path $hostDest | Out-Null
  Copy-Item -Path (Join-Path $hostSrc "*") -Destination $hostDest -Recurse -Force
}
$stagedHostExe = Join-Path $Root "dist\XB-SVCB\engines\juce-vst3-host\xb-juce-vst3-host.exe"
if (-not (Test-Path $stagedHostExe)) {
  throw "JUCE VST3 host is not staged: $stagedHostExe. Build native/juce-vst3-host first; do not ship an installer without this exe."
}

# 4) Compile installer
Write-Host "`n==== Compiling installer (Inno Setup) ====" -ForegroundColor Cyan
$iscc = Find-ISCC
if (-not $iscc) {
  throw "ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php"
}
Write-Host ("ISCC: {0}" -f $iscc) -ForegroundColor Green

New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
& $iscc (Join-Path $Root "installer\xb-svcb.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed (exit code $LASTEXITCODE)" }

$out = Join-Path $Root "dist\XB-SVCB-Setup.exe"
if (Test-Path $out) {
  Write-Host ("`nInstaller created: {0}" -f $out) -ForegroundColor Green
} else {
  Write-Host "`nCompiled, but setup.exe not found in dist. Check ISCC output." -ForegroundColor Yellow
}
