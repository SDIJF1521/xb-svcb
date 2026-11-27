<#
  Publish one XB-SVCB release to a public ModelScope model repository and build
  the ModelScope online bootstrapper from it.

  Steps: regenerate online-manifest.ini -> build the bootstrapper -> stage the
  manifest, the bootstrapper and all five installer sets -> upload them with the
  ModelScope CLI -> create the v<app-version> tag that the bootstrapper pins.

  The bootstrapper always reads files from the tag revision, so the upload goes
  to `master` first and the tag is created last; a partially uploaded release is
  therefore never reachable through the version the bootstrapper pins.
#>

param(
  [Alias('h')]
  [switch]$Help,
  [string]$Repo = 'lkpp233/xb-svcb-bate',
  [string]$Revision,
  [string]$Python,
  [string]$MsCli,
  [string]$Token,
  [switch]$ReuseManifest,
  [switch]$SkipBuild,
  [switch]$SkipUpload,
  [switch]$SkipTag
)

if ($Help -or $args -contains '--help') {
  @'
Usage: .\installer\publish-modelscope.ps1 [options]

Options:
  -Repo <owner/name>     Public ModelScope model repository.
                         Defaults to lkpp233/xb-svcb-bate.
  -Revision <revision>   Version tag to create. Defaults to v<app-version>.
  -Python <path>         Python used to build the manifest.
  -MsCli <path>          ModelScope CLI (ms.exe). Defaults to `ms` on PATH.
  -Token <token>         ModelScope access token used to create the tag.
                         Defaults to $env:MODELSCOPE_API_TOKEN, then
                         ~\.modelscope\credentials\git_token.
  -ReuseManifest         Reuse and validate dist\online-manifest.ini.
  -SkipBuild             Do not rebuild the online bootstrapper.
  -SkipUpload            Do not upload release files.
  -SkipTag               Do not create the version tag.
  -Help, -h, --help      Show this help and exit.

Example:
  .\installer\publish-modelscope.ps1 -Python C:\python3.12.9\python.exe

Verify afterwards (anonymous, no token):
  https://www.modelscope.cn/models/lkpp233/xb-svcb-bate/files?version=v0.1.2
'@ | Write-Output
  return
}

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $Root 'dist'
$ManifestPath = Join-Path $Dist 'online-manifest.ini'
$ManifestBuilder = Join-Path $PSScriptRoot 'build_online_manifest.py'
$OnlineBuild = Join-Path $PSScriptRoot 'build-online.ps1'
Set-Location -LiteralPath $Root

function Read-RegexValue([string]$Path, [string]$Pattern, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label not found: $Path"
  }
  $text = Get-Content -LiteralPath $Path -Raw
  if ($text -notmatch $Pattern) {
    throw "Unable to read $Label from $Path"
  }
  return $Matches[1]
}

function Resolve-Python([string]$Requested) {
  $candidates = @()
  if ($Requested) {
    if (-not (Test-Path -LiteralPath $Requested -PathType Leaf)) {
      throw "Requested Python was not found: $Requested"
    }
    $candidates += $Requested
  }
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

function Resolve-MsCli([string]$Requested) {
  $candidates = @()
  if ($Requested) {
    if (-not (Test-Path -LiteralPath $Requested -PathType Leaf)) {
      throw "Requested ModelScope CLI was not found: $Requested"
    }
    $candidates += $Requested
  }
  foreach ($name in @('ms.exe', 'modelscope.exe')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
  }
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }
  throw 'ModelScope CLI was not found. Install it with `pip install modelscope` or pass -MsCli.'
}

function Resolve-Token([string]$Requested) {
  if ($Requested) { return $Requested.Trim() }
  if ($env:MODELSCOPE_API_TOKEN) { return $env:MODELSCOPE_API_TOKEN.Trim() }
  $saved = Join-Path $env:USERPROFILE '.modelscope\credentials\git_token'
  if (Test-Path -LiteralPath $saved -PathType Leaf) {
    $value = (Get-Content -LiteralPath $saved -Raw).Trim()
    if ($value) { return $value }
  }
  throw 'No ModelScope token. Pass -Token or set MODELSCOPE_API_TOKEN.'
}

if ($Repo -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$') {
  throw 'ModelScope repository must use the owner/name form.'
}
$appVersion = Read-RegexValue (Join-Path $Root 'app\config.py') 'APP_VERSION\s*=\s*["'']([^"'']+)["'']' 'app version'
if (-not $Revision) { $Revision = "v$appVersion" }
if ($Revision -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
  throw 'ModelScope revision contains unsupported characters.'
}

$pythonExe = Resolve-Python $Python
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
if ($ReuseManifest) {
  & $pythonExe $ManifestBuilder --validate-existing $ManifestPath --version $appVersion
} else {
  & $pythonExe $ManifestBuilder --dist $Dist --output $ManifestPath --version $appVersion
}
if ($LASTEXITCODE -ne 0) {
  throw "Online manifest generation failed (exit code $LASTEXITCODE)"
}
$versionDir = Join-Path $Dist "v$appVersion"
New-Item -ItemType Directory -Force -Path $versionDir | Out-Null
Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $versionDir 'online-manifest.ini') -Force
$manifestHash = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host ("Manifest SHA-256: {0}" -f $manifestHash) -ForegroundColor Green

$stacks = @('CPU', 'ROCm10', 'DirectML', 'CUDA126', 'CUDA128')
$artifacts = @()
foreach ($stack in $stacks) {
  $setup = Join-Path $Dist "XB-SVCB-Setup-$stack.exe"
  if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) {
    throw "Offline installer not found: $setup"
  }
  $artifacts += $setup
  $parts = Get-ChildItem -LiteralPath $Dist -Filter "XB-SVCB-Setup-$stack-*.bin" -File |
    Sort-Object { [int]([regex]::Match($_.BaseName, '-(\d+)$').Groups[1].Value) }
  if (-not $parts) {
    throw "Split payload files not found for $stack"
  }
  $artifacts += $parts.FullName
}

$bootstrapper = Join-Path $Dist 'XB-SVCB-Online-Setup-ModelScope.exe'
if (-not $SkipBuild) {
  & $OnlineBuild -Source modelscope -ModelScopeRepo $Repo -ModelScopeRevision $Revision -ModelScopeRoot -ReuseManifest
  if ($LASTEXITCODE -ne 0) {
    throw "Online installer build failed (exit code $LASTEXITCODE)"
  }
}
if (-not (Test-Path -LiteralPath $bootstrapper -PathType Leaf)) {
  throw "Online bootstrapper not found: $bootstrapper"
}

$totalBytes = ($artifacts | ForEach-Object { (Get-Item -LiteralPath $_).Length } | Measure-Object -Sum).Sum
Write-Host ("Release v{0}: {1} files, {2:N2} GiB" -f $appVersion, ($artifacts.Count + 2), ($totalBytes / 1GB)) -ForegroundColor Cyan

if (-not $SkipUpload) {
  $msExe = Resolve-MsCli $MsCli
  $stage = Join-Path $Root ".tmp\release-$appVersion"
  if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $stage | Out-Null
  foreach ($file in @($artifacts + $ManifestPath + $bootstrapper)) {
    New-Item -ItemType HardLink -Path (Join-Path $stage (Split-Path -Leaf $file)) -Target $file | Out-Null
  }
  Write-Host "Uploading to $Repo (revision master) ..." -ForegroundColor Cyan
  & $msExe upload $Repo $stage --repo-type model --revision master `
    --commit-message "XB-SVCB v${appVersion}: online manifest, five installer sets, ModelScope online setup" `
    --use-cache --disable-tqdm
  if ($LASTEXITCODE -ne 0) {
    throw "ModelScope upload failed (exit code $LASTEXITCODE)"
  }
}

if (-not $SkipTag) {
  $accessToken = Resolve-Token $Token
  $headers = @{ Authorization = "Bearer $accessToken"; Cookie = "m_session_id=$accessToken" }
  $body = @{ TagName = $Revision; Ref = 'master' } | ConvertTo-Json
  Write-Host "Creating version tag $Revision ..." -ForegroundColor Cyan
  $response = Invoke-RestMethod -Method Post -Uri "https://www.modelscope.cn/api/v1/models/$Repo/repo/tag" `
    -Headers $headers -ContentType 'application/json' -Body $body
  if ($response.Code -ne 200) {
    throw "Tag creation failed: $($response.Message)"
  }
  Write-Host ("Version tag ready: https://www.modelscope.cn/models/{0}/files?version={1}" -f $Repo, $Revision) -ForegroundColor Green
}

Write-Host "`nDistribute dist\XB-SVCB-Online-Setup-ModelScope.exe (it pins manifest SHA-256 $manifestHash)." -ForegroundColor Green
