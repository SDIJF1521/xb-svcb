<#
  XB-SVCB launcher (Windows).
  Runs the installed desktop app. If the runtime is not ready, run ./install.ps1 first.
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot "app\.venv\Scripts\python.exe"
$main = Join-Path $PSScriptRoot "app\main.py"

if (-not (Test-Path $py)) {
  Write-Host "Runtime not found (app\.venv). Run ./install.ps1 first." -ForegroundColor Red
  exit 1
}

& $py $main
