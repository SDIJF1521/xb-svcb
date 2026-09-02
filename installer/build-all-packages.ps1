<#
  Sequentially build the four dedicated XB-SVCB installer families.

  Default behavior reuses the existing assets/wheels cache and existing
  frontend/application/JUCE builds. Use the switches below when those inputs
  must also be rebuilt.

  Examples:
    ./installer/build-all-packages.ps1
    ./installer/build-all-packages.ps1 -RebuildWheelhouse
    ./installer/build-all-packages.ps1 -Python C:\Python310\python.exe
    ./installer/build-all-packages.ps1 -RebuildWeb -RebuildApp -RebuildJuceHost
#>

param(
  [switch]$RebuildWheelhouse,
  [switch]$RebuildWeb,
  [switch]$RebuildApp,
  [switch]$RebuildJuceHost,
  [switch]$KeepExistingInstallers,
  [string]$Python
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$BuildScript = Join-Path $PSScriptRoot 'build.ps1'
$WheelhouseScript = Join-Path $Root 'install\prepare_wheelhouse.py'
$DistDir = Join-Path $Root 'dist'
$Stacks = @('cpu', 'directml', 'cu126', 'cu128')

function Require-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label not found: $Path"
  }
}

function Test-Python310([string]$Path) {
  if ([string]::IsNullOrWhiteSpace($Path) -or
      -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    return $false
  }
  & $Path -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 10) and sys.maxsize > 2**32 else 1)"
  return $LASTEXITCODE -eq 0
}

function Resolve-Python310([string]$ExplicitPath) {
  if ($ExplicitPath) {
    $candidate = [IO.Path]::GetFullPath($ExplicitPath)
    if (-not (Test-Python310 $candidate)) {
      throw "-Python must point to a runnable CPython 3.10.x python.exe: $candidate"
    }
    return $candidate
  }
  if ($env:XB_PYTHON_EXE -and (Test-Python310 $env:XB_PYTHON_EXE)) {
    return [IO.Path]::GetFullPath($env:XB_PYTHON_EXE)
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidate = $null
    try {
      $candidate = (& py -3.10 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
    } catch {
      $candidate = $null
    }
    if ($LASTEXITCODE -eq 0 -and (Test-Python310 $candidate)) {
      return [IO.Path]::GetFullPath($candidate)
    }
  }
  foreach ($pythonCommand in @(Get-Command python -All -CommandType Application -ErrorAction SilentlyContinue)) {
    if (Test-Python310 $pythonCommand.Source) {
      return [IO.Path]::GetFullPath($pythonCommand.Source)
    }
  }
  $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'
  if (Test-Python310 $candidate) {
    return [IO.Path]::GetFullPath($candidate)
  }
  throw "CPython 3.10.x was not detected. Pass -Python C:\path\to\python.exe."
}

Require-File $BuildScript 'Installer build script'
Require-File $WheelhouseScript 'Wheelhouse preparation script'
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Set-Location -LiteralPath $Root

Write-Host '==== Validating all four installer configurations ====' -ForegroundColor Cyan
& $BuildScript -ValidateOnly
$BuildPython = Resolve-Python310 $Python
Write-Host ("Locked build Python 3.10: {0}" -f $BuildPython) -ForegroundColor Green

if ($RebuildWheelhouse) {
  Write-Host "`n==== Rebuilding the complete four-stack wheelhouse ====" -ForegroundColor Cyan
  & $BuildPython $WheelhouseScript `
    --root $Root `
    --clean `
    --stack cpu `
    --stack directml `
    --stack cu126 `
    --stack cu128
  if ($LASTEXITCODE -ne 0) {
    throw "Wheelhouse rebuild failed (exit code $LASTEXITCODE)"
  }
}

if (-not $KeepExistingInstallers) {
  Write-Host "`n==== Removing old installer artifacts only ====" -ForegroundColor Cyan
  $oldArtifacts = @(
    Get-ChildItem -LiteralPath $DistDir -File -ErrorAction SilentlyContinue |
      Where-Object {
        ($_.Name -eq 'XB-SVCB-Setup.exe') -or
        ($_.Name -like 'XB-SVCB-Setup-*.bin') -or
        ($_.Name -in @(
          'XB-SVCB-Setup-CPU.exe',
          'XB-SVCB-Setup-DirectML.exe',
          'XB-SVCB-Setup-CUDA126.exe',
          'XB-SVCB-Setup-CUDA128.exe'
        ))
      }
  )
  foreach ($artifact in $oldArtifacts) {
    Write-Host ("Removing {0}" -f $artifact.Name) -ForegroundColor DarkGray
    Remove-Item -LiteralPath $artifact.FullName -Force
  }
}

for ($index = 0; $index -lt $Stacks.Count; $index++) {
  $stack = $Stacks[$index]
  Write-Host "`n============================================================" -ForegroundColor Cyan
  Write-Host ("Building dedicated installer: {0}" -f $stack) -ForegroundColor Cyan
  Write-Host "============================================================" -ForegroundColor Cyan
  # Shared frontend/app/JUCE outputs only need to be rebuilt for the first
  # package. The remaining packages reuse those exact staged binaries.
  $buildArgs = @{
    Stacks = $stack
    SkipWheelhouse = $true
    SkipWebBuild = ($index -gt 0) -or (-not $RebuildWeb)
    SkipAppBuild = ($index -gt 0) -or (-not $RebuildApp)
    SkipJuceHostBuild = ($index -gt 0) -or (-not $RebuildJuceHost)
  }
  & $BuildScript -Python $BuildPython @buildArgs
}

$expectedExecutables = @(
  'XB-SVCB-Setup-CPU.exe',
  'XB-SVCB-Setup-DirectML.exe',
  'XB-SVCB-Setup-CUDA126.exe',
  'XB-SVCB-Setup-CUDA128.exe'
)
$missing = @(
  $expectedExecutables | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $DistDir $_) -PathType Leaf)
  }
)
if ($missing.Count -gt 0) {
  throw "Build finished without all expected installer EXEs: $($missing -join ', ')"
}

Write-Host "`n==== All dedicated installers completed ====" -ForegroundColor Green
foreach ($name in $expectedExecutables) {
  Write-Host ("  {0}" -f (Join-Path $DistDir $name)) -ForegroundColor Green
}
Write-Host 'Each EXE must be distributed together with the matching same-prefix .bin files.' -ForegroundColor Yellow
