<# Build the ModelScope-hosted XB-SVCB online installer edition. #>

param(
  [Alias('h')]
  [switch]$Help,
  [string]$Repo = 'lkpp233/xb-svcb',
  [string]$Revision,
  [string]$RepositoryPath,
  [switch]$RootFiles,
  [string]$Python,
  [switch]$ManifestOnly,
  [switch]$ReuseManifest,
  [switch]$ValidateOnly
)

if ($Help -or $args -contains '--help') {
  @'
Usage: .\installer\build-online-modelscope.ps1 [options]

Options:
  -Repo <owner/name>       Public ModelScope model repository. Defaults to
                           lkpp233/xb-svcb.
  -Revision <revision>     Repository revision. Defaults to v<app-version>.
  -RepositoryPath <path>   Optional release subdirectory. The default is the
                           repository root shown on the versioned files page.
  -RootFiles               Explicitly read from the repository root (default).
  -Python <path>           Python used to generate online-manifest.ini.
  -ManifestOnly            Generate the manifest without compiling Setup.
  -ReuseManifest           Reuse and validate dist\online-manifest.ini.
  -ValidateOnly            Compile-check both online installer editions.
  -Help, -h, --help        Show this help and exit.

Source files:
  https://www.modelscope.cn/models/lkpp233/xb-svcb/files?version=v0.1.1

Example:
  .\installer\build-online-modelscope.ps1
'@ | Write-Output
  return
}

$buildScript = Join-Path $PSScriptRoot 'build-online.ps1'
$forward = @{
  Source = 'modelscope'
}
# Omit the revision unless explicitly pinned so build-online.ps1 derives
# v<app-version> from app/config.py and the two cannot drift apart.
if ($Revision) { $forward.ModelScopeRevision = $Revision }
if ($Repo) { $forward.ModelScopeRepo = $Repo }
if ($RepositoryPath) {
  $forward.ModelScopePath = $RepositoryPath
} else {
  $forward.ModelScopeRoot = $true
}
if ($Python) { $forward.Python = $Python }
if ($ManifestOnly) { $forward.ManifestOnly = $true }
if ($ReuseManifest) { $forward.ReuseManifest = $true }
if ($ValidateOnly) { $forward.ValidateOnly = $true }

& $buildScript @forward
exit $LASTEXITCODE
