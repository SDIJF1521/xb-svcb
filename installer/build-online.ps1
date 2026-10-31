<#
  Build the small XB-SVCB online bootstrapper.

  The OSS directory is public and contains online-manifest.ini plus all five
  offline installer EXE/BIN sets. The bootstrapper pins the manifest SHA-256;
  the manifest pins every downloaded artifact.
#>

param(
  [Alias('h')]
  [switch]$Help,
  [string]$BaseUrl,
  [string]$Python,
  [switch]$ManifestOnly,
  [switch]$ReuseManifest,
  [switch]$ValidateOnly
)

if ($Help -or $args -contains '--help') {
  @'
Usage: .\installer\build-online.ps1 [options]

Options:
  -BaseUrl <url>      Public OSS directory containing the release files.
                      Defaults to the XB_OSS_BASE_URL environment variable.
  -Python <path>      Python used to generate online-manifest.ini.
  -ManifestOnly       Generate the manifest without compiling the bootstrapper.
  -ReuseManifest      Reuse and validate dist\online-manifest.ini without
                      requiring all five local EXE/BIN package sets.
  -ValidateOnly       Compile-check the Inno script without release artifacts.
  -Help, -h, --help   Show this help and exit.

Examples:
  .\installer\build-online.ps1 -ValidateOnly
  .\installer\build-online.ps1 -ManifestOnly
  .\installer\build-online.ps1 -ReuseManifest -BaseUrl https://downloads.example.com/xb-svcb/0.1.0
  .\installer\build-online.ps1 -BaseUrl https://downloads.example.com/xb-svcb/0.1.0
'@ | Write-Output
  return
}

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $Root 'dist'
$ManifestPath = Join-Path $Dist 'online-manifest.ini'
$OnlineScript = Join-Path $PSScriptRoot 'xb-svcb-online.iss'
$ManifestBuilder = Join-Path $PSScriptRoot 'build_online_manifest.py'
Set-Location -LiteralPath $Root

function Require-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label not found: $Path"
  }
}

function Read-RegexValue(
  [string]$Path,
  [string]$Pattern,
  [string]$Label
) {
  Require-File $Path $Label
  $text = Get-Content -LiteralPath $Path -Raw
  if ($text -notmatch $Pattern) {
    throw "Unable to read $Label from $Path"
  }
  return $Matches[1]
}

function Find-ISCC {
  $command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $candidates = @(
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      return $candidate
    }
  }
  return $null
}

function Resolve-Python([string]$Requested) {
  if ($Requested -and -not (Test-Path -LiteralPath $Requested -PathType Leaf)) {
    throw "Requested Python was not found: $Requested"
  }
  $candidates = @()
  if ($Requested) { $candidates += $Requested }
  $candidates += (Join-Path $Root 'app\.venv\Scripts\python.exe')
  $command = Get-Command 'python.exe' -ErrorAction SilentlyContinue
  if ($command) { $candidates += $command.Source }

  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }
  throw 'Python was not found. Pass -Python C:\path\to\python.exe.'
}

function Normalize-BaseUrl([string]$Value) {
  if (-not $Value) {
    throw 'OSS base URL is required. Pass -BaseUrl or set XB_OSS_BASE_URL.'
  }
  try {
    $uri = [Uri]$Value
  } catch {
    throw "OSS base URL is invalid: $Value"
  }
  if (-not $uri.IsAbsoluteUri) {
    throw "OSS base URL must be absolute: $Value"
  }
  $isLocalTest = $uri.Host -in @('localhost', '127.0.0.1', '::1')
  if (($uri.Scheme -ne 'https') -and -not (($uri.Scheme -eq 'http') -and $isLocalTest)) {
    throw 'OSS base URL must use HTTPS (plain HTTP is allowed only for localhost tests).'
  }
  if ($uri.UserInfo -or $uri.Query -or $uri.Fragment) {
    throw 'OSS base URL must not contain credentials, a query string, or a fragment.'
  }
  if ($Value.Contains("'") -or $Value.Contains('"')) {
    throw 'OSS base URL contains an unsupported quote character.'
  }
  return $Value.Trim().TrimEnd('/')
}

Require-File $OnlineScript 'Online Inno Setup script'
$appVersion = Read-RegexValue `
  (Join-Path $Root 'app\config.py') `
  'APP_VERSION\s*=\s*["'']([^"'']+)["'']' `
  'app version'
$onlineVersion = Read-RegexValue `
  $OnlineScript `
  '#define\s+MyAppVersion\s+["'']([^"'']+)["'']' `
  'online installer version'
if ($appVersion -ne $onlineVersion) {
  throw "Version mismatch: app=$appVersion, online-installer=$onlineVersion"
}

$iscc = Find-ISCC
if ($ValidateOnly) {
  if (-not $iscc) {
    throw 'ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php'
  }
  $validateDir = Join-Path $Root '.tmp\online-installer-validate'
  New-Item -ItemType Directory -Force -Path $validateDir | Out-Null
  try {
    & $iscc `
      '/DXB_ONLINE_BASE_URL=https://invalid.example/xb-svcb/0.1.0' `
      '/DXB_ONLINE_MANIFEST_SHA256=0000000000000000000000000000000000000000000000000000000000000000' `
      "/O$validateDir" `
      '/FXB-SVCB-Online-Validation' `
      $OnlineScript
    if ($LASTEXITCODE -ne 0) {
      throw "Online installer validation failed (exit code $LASTEXITCODE)"
    }
  } finally {
    if (Test-Path -LiteralPath $validateDir) {
      Remove-Item -LiteralPath $validateDir -Recurse -Force
    }
  }
  Write-Host "Online installer validation passed for v$appVersion." -ForegroundColor Green
  return
}

Require-File $ManifestBuilder 'Online manifest builder'
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
$pythonExe = Resolve-Python $Python
if ($ReuseManifest -and $ManifestOnly) {
  throw '-ReuseManifest cannot be combined with -ManifestOnly.'
}
if ($ReuseManifest) {
  Require-File $ManifestPath 'Existing online manifest'
  & $pythonExe $ManifestBuilder --validate-existing $ManifestPath --version $appVersion
} else {
  & $pythonExe $ManifestBuilder --dist $Dist --output $ManifestPath --version $appVersion
}
if ($LASTEXITCODE -ne 0) {
  $operation = if ($ReuseManifest) { 'validation' } else { 'generation' }
  throw "Online manifest $operation failed (exit code $LASTEXITCODE)"
}
Require-File $ManifestPath 'Online manifest'
$manifestHash = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host ("Manifest SHA-256: {0}" -f $manifestHash) -ForegroundColor Green

if ($ManifestOnly) {
  Write-Host ("Manifest ready: {0}" -f $ManifestPath) -ForegroundColor Green
  return
}

$publicBaseUrl = if ($BaseUrl) { $BaseUrl } else { $env:XB_OSS_BASE_URL }
$publicBaseUrl = Normalize-BaseUrl $publicBaseUrl
if (-not $iscc) {
  throw 'ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php'
}

& $iscc `
  "/DXB_ONLINE_BASE_URL=$publicBaseUrl" `
  "/DXB_ONLINE_MANIFEST_SHA256=$manifestHash" `
  $OnlineScript
if ($LASTEXITCODE -ne 0) {
  throw "Online installer compile failed (exit code $LASTEXITCODE)"
}

$bootstrapper = Join-Path $Dist 'XB-SVCB-Online-Setup.exe'
Require-File $bootstrapper 'Online installer bootstrapper'
Write-Host "`nOnline installer ready:" -ForegroundColor Green
Write-Host ("  {0}" -f $bootstrapper) -ForegroundColor Green
if ($ReuseManifest) {
  Write-Host "`nExisting manifest reused. Keep the matching OSS manifest and EXE/BIN files unchanged." -ForegroundColor Yellow
  Write-Host "Only redistribute the rebuilt online bootstrapper:" -ForegroundColor Cyan
  Write-Host ("  {0}" -f $bootstrapper)
  return
}

Write-Host "`nUpload these files to $publicBaseUrl/:" -ForegroundColor Cyan
Write-Host ("  {0}" -f $ManifestPath)
$packageNames = @(
  'XB-SVCB-Setup-CPU',
  'XB-SVCB-Setup-ROCm10',
  'XB-SVCB-Setup-DirectML',
  'XB-SVCB-Setup-CUDA126',
  'XB-SVCB-Setup-CUDA128'
)
foreach ($packageName in $packageNames) {
  Write-Host ("  {0}" -f (Join-Path $Dist "$packageName.exe"))
  Get-ChildItem -LiteralPath $Dist -Filter "$packageName-*.bin" -File |
    Sort-Object { [int]([regex]::Match($_.BaseName, '-(\d+)$').Groups[1].Value) } |
    ForEach-Object { Write-Host ("  {0}" -f $_.FullName) }
}
Write-Host "`nDistribute XB-SVCB-Online-Setup.exe; do not upload OSS credentials." -ForegroundColor Green
