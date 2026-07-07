param(
  [string]$Configuration = "Release",
  [string]$JuceDir = $env:XB_JUCE_DIR,
  [string]$BuildDir = "",
  [switch]$FetchJuce,
  [switch]$CleanFetch
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $Root

function Find-CMake {
  $cmd = Get-Command cmake -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  $candidates = @(
    "C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
    "C:\Program Files\CMake\bin\cmake.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\CMake\bin\cmake.exe")
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) { return $candidate }
  }
  return $null
}

function Find-JUCE {
  param([string]$Preferred)

  if ($Preferred -and (Test-Path -LiteralPath (Join-Path $Preferred "CMakeLists.txt"))) {
    return $Preferred
  }

  $candidates = @(
    $env:XB_JUCE_DIR,
    $env:JUCE_DIR,
    "D:\JUCE",
    "C:\JUCE",
    (Join-Path $RepoRoot "JUCE"),
    (Join-Path $RepoRoot "native\JUCE")
  )

  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate "CMakeLists.txt"))) {
      return $candidate
    }
  }

  return ""
}

function Remove-BuildChild {
  param(
    [string]$BuildRoot,
    [string]$ChildPath
  )

  if (-not (Test-Path -LiteralPath $ChildPath)) { return }

  $buildFull = [System.IO.Path]::GetFullPath($BuildRoot).TrimEnd('\', '/')
  $targetFull = [System.IO.Path]::GetFullPath($ChildPath).TrimEnd('\', '/')
  if (-not $targetFull.StartsWith($buildFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean path outside build directory: $targetFull"
  }

  Write-Host "Cleaning stale JUCE fetch cache: $targetFull" -ForegroundColor Yellow
  Get-ChildItem -LiteralPath $targetFull -Recurse -Force -ErrorAction SilentlyContinue |
    ForEach-Object {
      try { $_.Attributes = $_.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly) } catch {}
    }
  Remove-Item -LiteralPath $targetFull -Recurse -Force -ErrorAction Stop
}

if ($BuildDir -eq "") {
  $BuildDir = Join-Path $PSScriptRoot "build"
}

if ($CleanFetch) {
  $depsDir = Join-Path $BuildDir "_deps"
  Remove-BuildChild -BuildRoot $BuildDir -ChildPath (Join-Path $depsDir "juce-src")
  Remove-BuildChild -BuildRoot $BuildDir -ChildPath (Join-Path $depsDir "juce-build")
  Remove-BuildChild -BuildRoot $BuildDir -ChildPath (Join-Path $depsDir "juce-subbuild")
}

$CMake = Find-CMake
if (-not $CMake) {
  throw "cmake not found. Install CMake or Visual Studio Build Tools with the CMake component, then rerun this script."
}

$JuceDir = Find-JUCE -Preferred $JuceDir
if ($JuceDir) {
  Write-Host "JUCE: $JuceDir" -ForegroundColor Green
}

$configureArgs = @(
  "-S", $PSScriptRoot,
  "-B", $BuildDir,
  "-DCMAKE_BUILD_TYPE=$Configuration"
)

if ($JuceDir) {
  $configureArgs += "-DXB_JUCE_DIR=$JuceDir"
}

if ($FetchJuce) {
  $configureArgs += "-DXB_JUCE_FETCH=ON"
}

& $CMake @configureArgs
if ($LASTEXITCODE -ne 0) {
  throw "CMake configure failed."
}

& $CMake --build $BuildDir --config $Configuration
if ($LASTEXITCODE -ne 0) {
  throw "JUCE host build failed."
}

$exeName = if ($IsWindows -or $env:OS -eq "Windows_NT") { "xb-juce-vst3-host.exe" } else { "xb-juce-vst3-host" }
$hostPath = Join-Path $RepoRoot "engines\juce-vst3-host\$exeName"
if (-not (Test-Path $hostPath)) {
  throw "Build completed, but host executable was not found: $hostPath"
}

Write-Host "JUCE VST3 Host built: $hostPath" -ForegroundColor Green
