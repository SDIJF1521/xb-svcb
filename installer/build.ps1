<#
  构建 XB-SVCB 安装程序（setup.exe）——开发方。
  步骤：
  1）将前端构建为 web/dist（除非使用 -SkipWebBuild）
  2）使用 PyInstaller 将应用程序打包成 exe 文件，存入 dist/XB-SVCB（除非使用 -SkipAppBuild）
  3）将原生 JUCE VST3 主机构建为 engines/juce-vst3-host（除非使用 -SkipJuceHostBuild）
  4）预下载 Windows wheelhouse（uv + 各 AI 环境依赖 whl）
  5）验证生成的运行时捆绑包
  6）使用 Inno Setup 的 ISCC 编译 installer/xb-svcb.iss
  7）输出一个硬件专用安装包及分割后的 .bin 数据包
     -BootstrapperOnly 时只刷新 EXE，复用已有的 .bin 分卷，不会重建或删除它们

  Prerequisites: Node.js (frontend build), app/.venv with pywebview + pyinstaller,
                 CMake + C++17 compiler + JUCE for the VST3 host,
                 Inno Setup 6 (provides ISCC.exe)
                 Inno Setup download: https://jrsoftware.org/isdl.php

  Usage:
    ./installer/build.ps1 -Help            # show options without running a build
    ./installer/build.ps1                 # default: CUDA128 shared-runtime package
    ./installer/build.ps1 -Stacks cpu
    ./installer/build.ps1 -SkipWebBuild     # skip when web/dist already built
    ./installer/build.ps1 -SkipAppBuild     # skip when dist/XB-SVCB already built
    ./installer/build.ps1 -SkipWheelhouse   # skip only when assets/wheels is already prepared
    ./installer/build.ps1 -Stacks cu126     # build one hardware-specific package
    ./installer/build.ps1 -Stacks cu128 -Python C:\Python312\python.exe
    ./installer/build.ps1 -Stacks cu126 -RuntimeAssets D:\XB-SVCB\assets\runtime\core-cu128
    ./installer/build.ps1 -Stacks rocm10
    ./installer/build.ps1 -Stacks directml
    ./installer/build.ps1 -Stacks cu128 -BootstrapperOnly # refresh only this package EXE
    ./installer/build.ps1 -ValidateOnly     # validate scripts without packaging models
#>

param(
  [Alias('h')]
  [switch]$Help,
  [switch]$SkipWebBuild,
  [switch]$SkipAppBuild,
  [switch]$SkipJuceHostBuild,
  [switch]$SkipWheelhouse,
  [ValidateSet('cpu', 'rocm10', 'directml', 'cu126', 'cu128')]
  [string[]]$Stacks,
  [string]$Python,
  [string]$RuntimeAssets,
  [switch]$BootstrapperOnly,
  [switch]$ValidateOnly
)

if ($Help -or $args -contains '--help') {
  @'
Usage: .\installer\build.ps1 [-Stacks <stack>] [options]

Stacks (one per build): cpu, rocm10, directml, cu126, cu128
Default: cu128

Options:
  -Python <path>        Use a 64-bit CPython 3.12 executable.
  -RuntimeAssets <dir>  Supply the shared CUDA core runtime assets.
  -SkipWebBuild         Reuse an existing web/dist build.
  -SkipAppBuild         Reuse an up-to-date dist/XB-SVCB app build.
  -SkipJuceHostBuild    Reuse the existing JUCE VST3 host.
  -SkipWheelhouse       Reuse an already prepared wheelhouse.
  -BootstrapperOnly     Refresh the EXE using existing split .bin volumes.
  -ValidateOnly         Validate installer scripts without packaging.
  -Help, -h, --help     Show this help and exit.

By default, wheelhouse preparation clears assets/wheels before downloading.
Use -SkipWheelhouse only after preparing the selected stack's wheels.

Examples:
  .\installer\build.ps1 -Stacks directml -Python C:\Python312\python.exe
  .\installer\build.ps1 -Stacks directml -SkipWheelhouse -SkipWebBuild
  .\installer\build.ps1 -ValidateOnly -Stacks directml
'@ | Write-Output
  return
}

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot   # repo root
Set-Location -Path $Root

$selectedStacks = @(
  if ($PSBoundParameters.ContainsKey('Stacks')) {
    $Stacks | Select-Object -Unique
  } elseif (-not $ValidateOnly) {
    'cu128'
  }
)
if ($selectedStacks.Count -gt 1) {
  throw "Dedicated installers must be built one stack at a time. Pass exactly one of: cpu, rocm10, directml, cu126, cu128."
}
if ((-not $ValidateOnly) -and $selectedStacks.Count -ne 1) {
  throw "A release build requires exactly one -Stacks value: cpu, rocm10, directml, cu126, or cu128."
}
$outputBaseNames = @{
  cpu      = 'XB-SVCB-Setup-CPU'
  rocm10 = 'XB-SVCB-Setup-ROCm10'
  directml = 'XB-SVCB-Setup-DirectML'
  cu126    = 'XB-SVCB-Setup-CUDA126'
  cu128    = 'XB-SVCB-Setup-CUDA128'
}
$packageStack = if ($selectedStacks.Count -eq 1) { [string]($selectedStacks[0]) } else { $null }
$outputBaseName = if ($packageStack) { [string]($outputBaseNames[$packageStack]) } else { $null }

function Require-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label not found: $Path"
  }
}

function Require-MatchingFile([string]$Source, [string]$Destination, [string]$Label) {
  Require-File $Source "$Label source"
  Require-File $Destination "$Label staged copy"
  $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
  $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($sourceHash -ne $destinationHash) {
    throw "$Label is stale; source and staged copy differ: $Source -> $Destination"
  }
}

function Require-WorkerContract([string]$Path, [string]$Label, [string[]]$Required, [string[]]$Forbidden) {
  Require-File $Path $Label
  $content = Get-Content -LiteralPath $Path -Raw
  foreach ($marker in $Required) {
    if ($content -notmatch [regex]::Escape($marker)) {
      throw "$Label has an unexpected implementation: missing '$marker' in $Path"
    }
  }
  foreach ($marker in $Forbidden) {
    if ($content -match [regex]::Escape($marker)) {
      throw "$Label has been replaced by another worker: found '$marker' in $Path"
    }
  }
}

function Require-FileSize([string]$Path, [long]$MinimumBytes, [string]$Label) {
  Require-File $Path $Label
  $item = Get-Item -LiteralPath $Path
  if ($item.Length -lt $MinimumBytes) {
    throw "$Label is incomplete: $Path ($($item.Length) bytes; expected at least $MinimumBytes)"
  }
}

function Require-WindowsLineEndings([string]$Path, [string]$Label) {
  Require-File $Path $Label
  $bytes = [IO.File]::ReadAllBytes($Path)
  for ($index = 0; $index -lt $bytes.Length; $index++) {
    if ($bytes[$index] -eq 10 -and ($index -eq 0 -or $bytes[$index - 1] -ne 13)) {
      throw "$Label contains a bare LF line ending; normalize the complete batch file to CRLF before packaging: $Path"
    }
  }
}

function Assert-CoreRuntimeAssets {
  <#
    The cu126 installer uses the same verified NumPy/protobuf/AudioTools
    compatibility materials as the cu128 recipe. Inno's
    skipifsourcedoesntexist flag is intentionally not trusted here: a missing
    wheel must stop the build before an unusable EXE is produced.
  #>
  $profilePath = Join-Path $Root 'install\runtime_profiles\core-cu128\profile.json'
  Require-File $profilePath 'Shared core runtime profile'
  $coreProfile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
  if ($coreProfile.schema -ne 1 -or $coreProfile.id -ne 'core-cu128') {
    throw "Unsupported shared core runtime profile: $profilePath"
  }

  $lockPath = Join-Path (Split-Path -Parent $profilePath) ([string]$coreProfile.lock)
  Require-File $lockPath 'Shared core lock file'
  $lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($lockHash -ne ([string]$coreProfile.lock_sha256).ToLowerInvariant()) {
    throw "Shared core lock hash mismatch: $lockPath"
  }

  $rootFull = ([IO.Path]::GetFullPath($Root)).TrimEnd('\') + '\'
  $runtimeArtifacts = @(
    $coreProfile.artifacts | Where-Object { $_.group -in @('candidate', 'compat') }
  )
  if ($runtimeArtifacts.Count -eq 0) {
    throw "Shared core profile has no candidate/compatibility artifacts: $profilePath"
  }

  $seen = @{}
  foreach ($artifact in $runtimeArtifacts) {
    $relative = [string]$artifact.path
    if ([IO.Path]::IsPathRooted($relative)) {
      throw "Shared core artifact path must be relative: $relative"
    }
    $resolved = [IO.Path]::GetFullPath((Join-Path $Root $relative))
    if (-not $resolved.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Shared core artifact escapes the source tree: $relative"
    }
    if ($seen.ContainsKey($resolved)) {
      throw "Shared core profile contains a duplicate artifact path: $relative"
    }
    $seen[$resolved] = $true
    Require-File $resolved ("Shared core artifact " + $relative)
    $item = Get-Item -LiteralPath $resolved
    if ([long]$item.Length -ne [long]$artifact.bytes) {
      throw "Shared core artifact size mismatch: $resolved ($($item.Length) bytes; expected $($artifact.bytes))"
    }
    $actualHash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$artifact.sha256).ToLowerInvariant()) {
      throw "Shared core artifact SHA-256 mismatch: $resolved"
    }
  }

  # Keep the exact files visible in the build log/error, especially the wheel
  # whose absence caused the previous cu126 EXE to fail during uv resolution.
  $requiredRelative = @(
    'assets/runtime/core-cu128/candidate/numpy-2.2.6-cp312-cp312-win_amd64.whl',
    'assets/runtime/core-cu128/candidate/protobuf-7.36.0-cp310-abi3-win_amd64.whl',
    'assets/runtime/core-cu128/candidate/tensorboardx-2.6.5-py3-none-any.whl',
    'assets/runtime/core-cu128/compat/descript_audiotools-0.7.2+xb1-py3-none-any.whl'
  )
  foreach ($relative in $requiredRelative) {
    $resolved = [IO.Path]::GetFullPath((Join-Path $Root $relative))
    if (-not $seen.ContainsKey($resolved)) {
      throw "Shared core profile does not declare required artifact: $relative"
    }
  }
  Write-Host ("Verified {0} hash-checked shared core candidate/compatibility wheels." -f $runtimeArtifacts.Count) -ForegroundColor Green
}

function Ensure-CoreRuntimeAssets([string]$SourcePath) {
  if ([string]::IsNullOrWhiteSpace($SourcePath)) {
    $SourcePath = $env:XB_RUNTIME_ASSETS
  }
  if ([string]::IsNullOrWhiteSpace($SourcePath)) {
    return
  }

  $source = [IO.Path]::GetFullPath($SourcePath)
  if (Test-Path -LiteralPath (Join-Path $source 'core-cu128') -PathType Container) {
    $source = Join-Path $source 'core-cu128'
  }
  if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Runtime assets source directory not found: $source"
  }

  $destination = [IO.Path]::GetFullPath((Join-Path $Root 'assets\runtime\core-cu128'))
  if ($source.TrimEnd('\') -ieq $destination.TrimEnd('\')) {
    return
  }
  New-Item -ItemType Directory -Force -Path $destination | Out-Null
  foreach ($group in @('candidate', 'compat', 'rollback')) {
    $sourceGroup = Join-Path $source $group
    if (-not (Test-Path -LiteralPath $sourceGroup -PathType Container)) {
      continue
    }
    $destinationGroup = Join-Path $destination $group
    New-Item -ItemType Directory -Force -Path $destinationGroup | Out-Null
    Get-ChildItem -LiteralPath $sourceGroup -File -Force | ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $destinationGroup $_.Name) -Force
    }
  }
  Write-Host ("Synchronized shared core runtime materials from {0}" -f $source) -ForegroundColor Cyan
}

function Assert-AppPayloadFresh {
  $appExe = Join-Path $Root 'dist\XB-SVCB\XB-SVCB.exe'
  Require-File $appExe 'Staged app executable'
  $sourceRoots = @(
    (Join-Path $Root 'app\api'),
    (Join-Path $Root 'app\application'),
    (Join-Path $Root 'app\domain'),
    (Join-Path $Root 'app\infrastructure'),
    (Join-Path $Root 'app\main.py'),
    (Join-Path $Root 'app\config.py'),
    (Join-Path $Root 'installer\xb-svcb-app.spec')
  )
  $sourceFiles = @()
  foreach ($sourceRoot in $sourceRoots) {
    if (Test-Path -LiteralPath $sourceRoot -PathType Container) {
      $sourceFiles += @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Filter '*.py')
    } elseif (Test-Path -LiteralPath $sourceRoot -PathType Leaf) {
      $sourceFiles += @(Get-Item -LiteralPath $sourceRoot)
    }
  }
  $outputTime = (Get-Item -LiteralPath $appExe).LastWriteTimeUtc
  $newer = @($sourceFiles | Where-Object { $_.LastWriteTimeUtc -gt $outputTime })
  if ($newer.Count -gt 0) {
    $sample = ($newer | Select-Object -First 3 | ForEach-Object { $_.FullName }) -join ', '
    throw "Staged app executable is older than current source ($sample). Remove -SkipAppBuild or rebuild the application before packaging."
  }
}

function Test-Python312([string]$Path) {
  if ([string]::IsNullOrWhiteSpace($Path) -or
      -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    return $false
  }
  & $Path -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)"
  return $LASTEXITCODE -eq 0
}

function Resolve-BuildPython312([string]$ExplicitPath) {
  if ($ExplicitPath) {
    $resolved = [IO.Path]::GetFullPath($ExplicitPath)
    if (-not (Test-Python312 $resolved)) {
      throw "-Python must point to a runnable CPython 3.12.x python.exe: $resolved"
    }
    return $resolved
  }

  if ($env:XB_PYTHON_EXE -and (Test-Python312 $env:XB_PYTHON_EXE)) {
    return [IO.Path]::GetFullPath($env:XB_PYTHON_EXE)
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidate = $null
    try {
      $candidate = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
    } catch {
      # py.exe may exist without a registered 3.12 runtime. Continue with
      # PATH and the common installation directory in that case.
      $candidate = $null
    }
    if ($LASTEXITCODE -eq 0 -and (Test-Python312 $candidate)) {
      return [IO.Path]::GetFullPath($candidate)
    }
  }
  foreach ($pythonCommand in @(Get-Command python -All -CommandType Application -ErrorAction SilentlyContinue)) {
    if (Test-Python312 $pythonCommand.Source) {
      return [IO.Path]::GetFullPath($pythonCommand.Source)
    }
  }
  $common = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  if (Test-Python312 $common) {
    return [IO.Path]::GetFullPath($common)
  }
  throw "CPython 3.12.x was not detected. Pass its exact path with -Python C:\path\to\python.exe."
}

function Stop-WebNodeProcesses([string]$WebDir) {
  $resolvedWebDir = [IO.Path]::GetFullPath($WebDir).TrimEnd('\')
  $webPrefix = ($resolvedWebDir + '\').ToLowerInvariant()
  $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  $processById = @{}
  foreach ($process in $allProcesses) {
    $processById[[int]$process.ProcessId] = $process
  }
  $webProcesses = @(
    $allProcesses | Where-Object {
      if ($_.Name -ine 'node.exe') { return $false }
      $commandLine = [string]$_.CommandLine
      if ([string]::IsNullOrWhiteSpace($commandLine)) { return $false }
      $commandLine.Replace('/', '\').ToLowerInvariant().Contains($webPrefix)
    }
  )
  if ($webProcesses.Count -eq 0) { return }

  $stopIds = [Collections.Generic.HashSet[int]]::new()
  $stopOrder = [Collections.Generic.List[int]]::new()
  foreach ($webProcess in $webProcesses) {
    $chain = [Collections.Generic.List[int]]::new()
    $current = $webProcess
    [void]$chain.Add([int]$current.ProcessId)
    while ($processById.ContainsKey([int]$current.ParentProcessId)) {
      $parent = $processById[[int]$current.ParentProcessId]
      $parentCommandLine = [string]$parent.CommandLine
      $isNpmNode = $parent.Name -ieq 'node.exe' -and $parentCommandLine -match '(?i)npm-cli\.js'
      $isCommandWrapper = $parent.Name -ieq 'cmd.exe' -and $parentCommandLine -match '(?i)(?:^|\s)/c(?:\s|$)'
      if (-not ($isNpmNode -or $isCommandWrapper)) { break }
      [void]$chain.Add([int]$parent.ProcessId)
      $current = $parent
    }
    for ($index = $chain.Count - 1; $index -ge 0; $index--) {
      $processId = $chain[$index]
      if ($stopIds.Add($processId)) { [void]$stopOrder.Add($processId) }
    }
  }

  Write-Host "Stopping frontend processes that would lock web/node_modules..." -ForegroundColor Yellow
  foreach ($processId in $stopOrder) {
    $process = $processById[$processId]
    Write-Host ("  PID {0}: {1}" -f $processId, $process.CommandLine) -ForegroundColor DarkYellow
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
  }

  $deadline = [DateTime]::UtcNow.AddSeconds(10)
  do {
    $remaining = @($stopIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($remaining.Count -eq 0) { return }
    Start-Sleep -Milliseconds 200
  } while ([DateTime]::UtcNow -lt $deadline)

  $remainingIds = $remaining -join ', '
  throw "Unable to stop frontend process(es): $remainingIds. Close the web development server and retry."
}

function Ensure-EngineSource(
  [string]$Path,
  [string]$Marker,
  [string]$Repository,
  [string]$Branch,
  [string]$Label
) {
  $markerPath = Join-Path $Path $Marker
  if (Test-Path -LiteralPath $markerPath -PathType Leaf) { return }
  if (Test-Path -LiteralPath $Path) {
    throw "$Label payload directory exists but is incomplete: $Path (missing $Marker)"
  }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to stage the bundled $Label source."
  }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
  Write-Host ("Staging bundled {0} source ({1})..." -f $Label, $Branch) -ForegroundColor Cyan
  & git clone --depth 1 --branch $Branch $Repository $Path
  if ($LASTEXITCODE -ne 0) { throw "Failed to stage bundled $Label source." }
  Require-File $markerPath "$Label payload marker"
}

function Ensure-FfmpegPayload([string]$PayloadDir) {
  $ffmpegExe = Join-Path $PayloadDir "bin\ffmpeg.exe"
  $ffprobeExe = Join-Path $PayloadDir "bin\ffprobe.exe"
  if ((Test-Path -LiteralPath $ffmpegExe -PathType Leaf) -and
      (Test-Path -LiteralPath $ffprobeExe -PathType Leaf)) { return }

  $downloadDir = Join-Path $Root ".tmp\ffmpeg-payload"
  $archive = Join-Path $downloadDir "ffmpeg-release-essentials.zip"
  $extractDir = Join-Path $downloadDir "extract"
  New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
  Write-Host "Downloading the bundled Windows FFmpeg payload..." -ForegroundColor Cyan
  Invoke-WebRequest -UseBasicParsing `
    -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
    -OutFile $archive
  if (Test-Path -LiteralPath $extractDir) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
  }
  Expand-Archive -LiteralPath $archive -DestinationPath $extractDir -Force
  $sourceExe = Get-ChildItem -LiteralPath $extractDir -Filter "ffmpeg.exe" -File -Recurse |
    Select-Object -First 1
  if (-not $sourceExe) { throw "Downloaded FFmpeg archive does not contain ffmpeg.exe." }
  $sourceBin = $sourceExe.Directory.FullName
  New-Item -ItemType Directory -Force -Path (Join-Path $PayloadDir "bin") | Out-Null
  Copy-Item -LiteralPath (Join-Path $sourceBin "ffmpeg.exe") -Destination $ffmpegExe -Force
  Copy-Item -LiteralPath (Join-Path $sourceBin "ffprobe.exe") -Destination $ffprobeExe -Force
  $sourceRoot = Split-Path -Parent $sourceBin
  foreach ($notice in @("LICENSE", "README.txt")) {
    $noticePath = Join-Path $sourceRoot $notice
    if (Test-Path -LiteralPath $noticePath) {
      Copy-Item -LiteralPath $noticePath -Destination (Join-Path $PayloadDir $notice) -Force
    }
  }
}

function Ensure-DdspContentvecPayload([string]$Path) {
  $minimumBytes = 300MB
  if ((Test-Path -LiteralPath $Path -PathType Leaf) -and
      ((Get-Item -LiteralPath $Path).Length -ge $minimumBytes)) { return }

  $partial = "$Path.download"
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
  $urls = @(
    "https://hf-mirror.com/lengyue233/content-vec-best/resolve/main/pytorch_model.bin",
    "https://huggingface.co/lengyue233/content-vec-best/resolve/main/pytorch_model.bin"
  )
  foreach ($url in $urls) {
    try {
      Write-Host "Downloading the bundled DDSP ContentVec payload..." -ForegroundColor Cyan
      Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $partial
      if ((Get-Item -LiteralPath $partial).Length -lt $minimumBytes) {
        throw "Downloaded file is smaller than expected."
      }
      Move-Item -LiteralPath $partial -Destination $Path -Force
      return
    } catch {
      if (Test-Path -LiteralPath $partial) {
        Remove-Item -LiteralPath $partial -Force
      }
    }
  }
  throw "Failed to stage the bundled DDSP ContentVec payload: $Path"
}

function Stage-EngineTree([string]$SourceDir, [string]$DestinationDir, [string]$Engine) {
  if (Test-Path -LiteralPath $DestinationDir) {
    Remove-Item -LiteralPath $DestinationDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
  $sourceRoot = (Resolve-Path -LiteralPath $SourceDir).Path
  foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File) {
    $relative = $file.FullName.Substring($sourceRoot.Length + 1)
    $parts = $relative -split '[\\/]'
    $lowerParts = @($parts | ForEach-Object { $_.ToLowerInvariant() })
    $skip = $lowerParts -contains '.git' -or
      $lowerParts -contains '__pycache__' -or
      $lowerParts -contains 'cache' -or
      $lowerParts -contains 'data' -or
      $lowerParts -contains 'examples' -or
      $lowerParts -contains 'logs' -or
      $lowerParts -contains 'outputs'
    if ($Engine -eq 'sovits') {
      $skip = $skip -or ($lowerParts -contains 'exp') -or ($lowerParts -contains 'pretrain')
    } elseif ($Engine -eq 'ddsp') {
      $skip = $skip -or ($lowerParts -contains 'pretrain')
    } elseif ($Engine -eq 'seedvc') {
      $skip = $skip -or ($lowerParts -contains 'checkpoints') -or ($lowerParts -contains 'assets')
      $skip = $skip -or ($file.Name -ieq 'campplus_cn_common.bin')
      $skip = $skip -or ($file.Extension.ToLowerInvariant() -in @('.pt', '.pth', '.ckpt', '.safetensors'))
    }
    if ($skip) { continue }
    $target = Join-Path $DestinationDir $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
  }
}

function Prepare-BundledEnginePayloads([string]$PayloadRoot) {
  if (Test-Path -LiteralPath $PayloadRoot) {
    Remove-Item -LiteralPath $PayloadRoot -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $PayloadRoot | Out-Null
  Stage-EngineTree (Join-Path $Root 'engines\so-vits-svc') (Join-Path $PayloadRoot 'so-vits-svc') 'sovits'
  Stage-EngineTree (Join-Path $Root 'engines\ddsp-svc') (Join-Path $PayloadRoot 'ddsp-svc') 'ddsp'
  Stage-EngineTree (Join-Path $Root 'engines\seed-vc') (Join-Path $PayloadRoot 'seed-vc') 'seedvc'
  $contentvec = Join-Path $PayloadRoot 'ddsp-svc\pretrain\contentvec\pytorch_model.bin'
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $contentvec) | Out-Null
  Copy-Item -LiteralPath (Join-Path $Root 'engines\ddsp-svc\pretrain\contentvec\pytorch_model.bin') -Destination $contentvec -Force
  foreach ($marker in @(
    (Join-Path $PayloadRoot 'so-vits-svc\inference\infer_tool.py'),
    (Join-Path $PayloadRoot 'ddsp-svc\main_reflow.py'),
    (Join-Path $PayloadRoot 'ddsp-svc\legacy\main.py'),
    (Join-Path $PayloadRoot 'ddsp-svc\legacy\main_diff.py'),
    (Join-Path $PayloadRoot 'ddsp-svc\6.2\main_reflow.py'),
    (Join-Path $PayloadRoot 'seed-vc\inference.py'),
    (Join-Path $PayloadRoot 'seed-vc\inference_v2.py'),
    $contentvec
  )) { Require-File $marker 'Staged bundled engine payload' }
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

function Assert-InnoConstants([string]$Path) {
  Require-File $Path "Inno Setup script"
  $allowed = @(
    'app', 'autopf', 'cmd', 'commondesktop', 'group', 'localappdata',
    'pf32', 'tmp', 'uninstallexe', 'userappdata', 'win'
  )
  $text = Get-Content -LiteralPath $Path -Raw
  $used = [regex]::Matches($text, '\{([A-Za-z][A-Za-z0-9]*)\}') |
    ForEach-Object { $_.Groups[1].Value.ToLowerInvariant() } |
    Sort-Object -Unique
  $unknown = @($used | Where-Object { $allowed -notcontains $_ })
  if ($unknown.Count -gt 0) {
    throw "Unknown Inno Setup constant(s): $($unknown -join ', '). Add only documented constants to installer/xb-svcb.iss."
  }
}

# Refuse to publish mismatched app/frontend/installer versions.
$appVersion = Read-RegexValue (Join-Path $Root "app\config.py") 'APP_VERSION\s*=\s*["'']([^"'']+)["'']' "app version"
$appProjectVersion = Read-RegexValue (Join-Path $Root "app\pyproject.toml") '(?m)^version\s*=\s*["'']([^"'']+)["'']' "app project version"
$appLockVersion = Read-RegexValue (Join-Path $Root "app\uv.lock") '(?s)\[\[package\]\]\s*name\s*=\s*["'']app["'']\s*version\s*=\s*["'']([^"'']+)["'']' "app lock version"
$appExeVersion = Read-RegexValue (Join-Path $Root "installer\xb-svcb-version.txt") 'StringStruct\(u["'']ProductVersion["''],\s*u["'']([^"'']+)["'']\)' "app executable version"
$installerVersion = Read-RegexValue (Join-Path $Root "installer\xb-svcb.iss") '#define\s+MyAppVersion\s+["'']([^"'']+)["'']' "installer version"
$installerScript = Join-Path $Root "installer\xb-svcb.iss"
Assert-InnoConstants $installerScript
$installerSliceSize = [long](Read-RegexValue (Join-Path $Root "installer\xb-svcb.iss") '(?m)^DiskSliceSize\s*=\s*([0-9]+)\s*$' "installer slice size")
if ($installerSliceSize -ge 2GB) {
  throw "Installer DiskSliceSize must stay below 2 GiB; found $installerSliceSize bytes."
}
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
  "inference_naturalizer.py",
  "svc_worker.py",
  "f0_worker.py",
  "vocal_tuning_worker.py",
  "formant_pitch_worker.py",
  "uvr_worker.py",
  "pymss_worker.py",
  "hub_worker.py",
  "rvc_worker.py",
  "seedvc_worker.py",
  "ddsp_worker.py",
  "vocal_enhancement_worker.py"
)
foreach ($worker in $workerFiles) {
  Require-File (Join-Path $Root "app\infrastructure\$worker") "Worker source $worker"
}
Require-WorkerContract `
  (Join-Path $Root "app\infrastructure\f0_worker.py") `
  "F0 worker source" `
  @("--out-npy", "F0_OK") `
  @("--high-threshold", "FORMANT_PITCH_OK")
Require-WorkerContract `
  (Join-Path $Root "app\infrastructure\formant_pitch_worker.py") `
  "Formant pitch worker source" `
  @("--high-threshold", "FORMANT_PITCH_OK") `
  @("--out-npy", "F0_OK")
Require-File (Join-Path $Root "docs\release-notes\release_notes_v031.md") "v0.0.31 release notes"
Require-File (Join-Path $Root "docs\api.md") "FastAPI integration guide"
Require-File (Join-Path $Root "install\configure_user_env.py") "User environment helper"
Require-File (Join-Path $Root "install\detect_python.bat") "Python runtime detector"
Require-File (Join-Path $Root "install\prepare_wheelhouse.py") "Wheelhouse preparation script"
$installScriptPath = Join-Path $Root "install\install.py"
Require-File $installScriptPath "Runtime installer"
$installSource = Get-Content -LiteralPath $installScriptPath -Raw
if ($installSource -notmatch 'def python_spec_for_venv\(uv: str, python_version: str\)') {
  throw "Runtime installer is missing the concrete Python-path fix; refusing to build an installer with uv --python 3.12 resolution."
}
$runtimeInstallerDeclarations = @(
  'CORE_COMPAT_WHEEL_DIRS: tuple[Path, ...] = ()',
  'def _configure_core_compatibility_materials() -> None:',
  'onnx-weekly==1.23.0.dev20260831'
)
foreach ($declaration in $runtimeInstallerDeclarations) {
  if ($installSource -notmatch [regex]::Escape($declaration)) {
    throw "Runtime installer is missing the synchronized shared-core fix: '$declaration'."
  }
}
$sharedInstallScriptPath = Join-Path $Root "install\install_shared.py"
Require-File $sharedInstallScriptPath "Shared runtime installer"
$sharedInstallSource = Get-Content -LiteralPath $sharedInstallScriptPath -Raw
$sharedRuntimeDeclarations = [ordered]@{
  'cu126 selector' = 'add_argument\("--cu126"'
  'cu128 selector' = 'add_argument\("--cu128"'
  'core-cu128 profile' = '"core-cu128"'
  'cu126 candidate material activation' = '_configure_core_compatibility_materials\(\)'
  'profile-only post-install check' = 'if impl\.CORE_PROFILE is not None:'
  'two-layer shared layout' = '_configure_runtime_layout\(consolidated=True,\s*gpu_stack=stack\)'
}
foreach ($declaration in $sharedRuntimeDeclarations.GetEnumerator()) {
  if ($sharedInstallSource -notmatch $declaration.Value) {
    throw "Shared runtime installer is missing the $($declaration.Key) declaration."
  }
}
$batchEntrypoints = [ordered]@{
  'Runtime setup entry' = (Join-Path $Root 'setup_env.bat')
  'Shared runtime setup entry' = (Join-Path $Root 'setup_shared_env.bat')
  'Prerequisite installer' = (Join-Path $Root 'install_prereqs.bat')
  'Python runtime detector' = (Join-Path $Root 'install\detect_python.bat')
}
foreach ($entrypoint in $batchEntrypoints.GetEnumerator()) {
  Require-WindowsLineEndings $entrypoint.Value $entrypoint.Key
}

function Assert-WheelhouseProfile([string]$SelectedStack) {
  $wheelRoot = Join-Path $Root 'assets\wheels'
  $required = @("py312\$SelectedStack", 'bootstrap')
  $missing = @($required | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $wheelRoot $_) -PathType Container)
  })
  if ($missing.Count -gt 0) {
    throw "Wheelhouse profile is incomplete; missing: $($missing -join ', ')"
  }
  $legacy = Join-Path $wheelRoot 'py312\cu121'
  if (Test-Path -LiteralPath $legacy) {
    throw "旧 cu121 wheelhouse remains: $legacy. Run the cleanup command before packaging."
  }
  if ($SelectedStack -in @('cu126', 'cu128')) {
    foreach ($name in @(
      'onnx_weekly-1.23.0.dev20260831-cp312-cp312-win_amd64.whl',
      'numpy-2.2.6-cp312-cp312-win_amd64.whl',
      'tensorboardx-2.6.5-py3-none-any.whl'
    )) {
      Require-File (Join-Path $wheelRoot ("py312\{0}\{1}" -f $SelectedStack, $name)) `
        ("$SelectedStack wheelhouse candidate $name")
    }
  }
}
if ((Get-Content -LiteralPath $installScriptPath -Raw) -notmatch 'def _resolved_file_path\(path: Path\) -> Path \| None:') {
  throw "Runtime installer is missing Junction resolution; refusing to build an installer that may pass a Windows mount point to uv."
}

$assetValidationStacks = if ($packageStack) { @($packageStack) } else { @('cpu', 'rocm10', 'directml', 'cu126', 'cu128') }
if (@($assetValidationStacks | Where-Object { $_ -in @('cu126', 'cu128') }).Count -gt 0) {
  Ensure-CoreRuntimeAssets $RuntimeAssets
  Assert-CoreRuntimeAssets
}
$licensePath = Join-Path $Root "LICENSE"
Require-File $licensePath "GPLv3 license"
if ((Get-Content -LiteralPath $licensePath -Raw) -notmatch 'GNU GENERAL PUBLIC LICENSE\s+Version 3, 29 June 2007') {
  throw "LICENSE must contain the complete GNU GPL version 3 text."
}

# Reject Git LFS pointers or partial DDSP/SeedVC snapshots before producing a release.
Require-FileSize (Join-Path $Root "assets\models\pretrain\rmvpe.pt") 314572800 "Bundled SeedVC RMVPE"
Require-FileSize (Join-Path $Root "assets\models\pretrain\fcpe.pt") 67108864 "Bundled high-range FCPE"
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
Require-FileSize (Join-Path $Root "assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\config.ini") 1024 "Bundled DeepFilterNet3 config"
Require-FileSize (Join-Path $Root "assets\models\vocal-enhancement\DeepFilterNet\DeepFilterNet\Cache\DeepFilterNet3\checkpoints\model_120.ckpt.best") 8388608 "Bundled DeepFilterNet3 weights"

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
    $validateStacks = if ($packageStack) { @($packageStack) } else { @('cpu', 'rocm10', 'directml', 'cu126', 'cu128') }
    foreach ($validateStack in $validateStacks) {
      $validateOutput = [string]($outputBaseNames[$validateStack])
      & $iscc "/DXB_VALIDATE_ONLY=1" "/DXB_PACKAGE_STACK=$validateStack" "/DXB_OUTPUT_BASENAME=$validateOutput" `
        "/O$validateDir" "/F$validateOutput-Validation" (Join-Path $Root "installer\xb-svcb.iss")
      if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup validation failed for $validateStack (exit code $LASTEXITCODE)"
      }
    }
  } finally {
    if (Test-Path -LiteralPath $validateDir) {
      Remove-Item -LiteralPath $validateDir -Recurse -Force
    }
  }
  Write-Host "Installer scripts validated successfully." -ForegroundColor Green
  exit 0
}

$buildPython = Resolve-BuildPython312 $Python
Write-Host ("Build Python 3.12: {0}" -f $buildPython) -ForegroundColor Green

# Stage payloads that are downloaded only on the release builder. User machines
# receive these files through Inno Setup's split data volumes and never fetch the
# engine repositories or FFmpeg themselves.
Ensure-FfmpegPayload (Join-Path $Root "assets\tools\ffmpeg")
Ensure-EngineSource `
  (Join-Path $Root "engines\so-vits-svc") `
  "inference\infer_tool.py" `
  "https://github.com/svc-develop-team/so-vits-svc.git" `
  "4.1-Stable" `
  "So-VITS-SVC"
Ensure-EngineSource `
  (Join-Path $Root "engines\ddsp-svc") `
  "main_reflow.py" `
  "https://github.com/yxlllc/DDSP-SVC.git" `
  "6.3" `
  "DDSP-SVC"
& $buildPython -c "import importlib.util; s=importlib.util.spec_from_file_location('xb_install', r'$Root\install\install.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.fetch_ddsp_compat()"
if ($LASTEXITCODE -ne 0) { throw 'Failed to stage DDSP compatibility sources' }
Ensure-DdspContentvecPayload `
  (Join-Path $Root "engines\ddsp-svc\pretrain\contentvec\pytorch_model.bin")
Ensure-EngineSource `
  (Join-Path $Root "engines\seed-vc") `
  "inference.py" `
  "https://github.com/Plachtaa/seed-vc.git" `
  "main" `
  "SeedVC"
& $buildPython -c "import importlib.util; s=importlib.util.spec_from_file_location('xb_install', r'$Root\install\install.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.fetch_seedvc()"
if ($LASTEXITCODE -ne 0) { throw 'Failed to stage SeedVC V1/V2 sources' }
Require-File (Join-Path $Root "assets\tools\ffmpeg\bin\ffmpeg.exe") "Bundled FFmpeg"
Require-File (Join-Path $Root "assets\tools\ffmpeg\bin\ffprobe.exe") "Bundled ffprobe"
Require-FileSize `
  (Join-Path $Root "engines\ddsp-svc\pretrain\contentvec\pytorch_model.bin") `
  314572800 `
  "Bundled DDSP ContentVec"

# 0b) Prepare Python wheelhouse for runtime setup. The installed machine uses
# these whl files through assets/wheels and should not resolve AI libraries from
# PyPI unless a developer explicitly disables strict wheelhouse mode.
if (-not $SkipWheelhouse) {
  Write-Host "`n==== Preparing Python wheelhouse (assets/wheels) ====" -ForegroundColor Cyan
  # Resolve the wheelhouse with the exact developer-selected CPython 3.12.
  # This avoids selecting the wrong ABI or a managed/Junction interpreter.
  $pythonCmd = Get-Item -LiteralPath $buildPython
  & $pythonCmd.FullName -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
  if ($LASTEXITCODE -ne 0) {
    throw "Bundled Python is not a runnable CPython 3.12 interpreter: $($pythonCmd.FullName)"
  }
  $wheelArgs = @('--root', $Root, '--clean')
  $wheelArgs += @('--stack', $packageStack)
  & $pythonCmd.FullName (Join-Path $Root "install\prepare_wheelhouse.py") @wheelArgs
  if ($LASTEXITCODE -ne 0) { throw "Wheelhouse preparation failed (exit code $LASTEXITCODE)" }
} else {
  Write-Host "`n==== Skipping Python wheelhouse preparation ====" -ForegroundColor Yellow
}
Require-File (Join-Path $Root "assets\wheels\wheelhouse.json") "Bundled wheelhouse manifest (build without -SkipWheelhouse)"
Assert-WheelhouseProfile $packageStack
$installerWheelhouse = Join-Path $Root '.tmp\installer-wheelhouse'
$wheelhouseStager = Join-Path $Root 'installer\stage_wheelhouse.py'
Require-File $wheelhouseStager 'Dedicated wheelhouse staging tool'
Write-Host "`n==== Staging $packageStack wheel payload only ====" -ForegroundColor Cyan
& $buildPython $wheelhouseStager --root $Root --stack $packageStack --output $installerWheelhouse
if ($LASTEXITCODE -ne 0) { throw "Wheelhouse staging failed (exit code $LASTEXITCODE)" }
Require-File (Join-Path $installerWheelhouse 'wheelhouse.json') "Staged $packageStack wheelhouse manifest"

# 1) Build frontend
if (-not $SkipWebBuild) {
  Write-Host "==== Building frontend (web/dist) ====" -ForegroundColor Cyan
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Install Node.js LTS, or pass -SkipWebBuild."
  }
  $webDir = Join-Path $Root "web"
  Stop-WebNodeProcesses $webDir
  Push-Location $webDir
  try {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    if ($LASTEXITCODE -ne 0) {
      throw "npm install/ci failed (exit code $LASTEXITCODE). Frontend NOT rebuilt. If npm reports EPERM, check antivirus or another process locking web/node_modules."
    }
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
  if (-not (Test-Python312 $venvPy)) {
    throw "app\.venv must use 64-bit CPython 3.12. Run uv sync --python 3.12 in app/ before packaging."
  }
  # Use importlib for the probe so a missing optional build tool does not emit
  # a misleading Python traceback through PowerShell's native stderr handler.
  & $venvPy -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('PyInstaller') else 1)" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller missing in app/.venv, installing..." -ForegroundColor Yellow
    $uvCommand = Get-Command "uv" -ErrorAction SilentlyContinue
    if (-not $uvCommand) {
      throw "uv not found. Install uv or run: uv pip install --python app\.venv\Scripts\python.exe pyinstaller"
    }
    & $uvCommand.Source pip install --python $venvPy pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Failed to install PyInstaller into app/.venv" }
  }
  & $venvPy -c "import PyInstaller; print('PyInstaller ' + getattr(PyInstaller, '__version__', 'unknown'))"
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller is unavailable in app/.venv after installation" }
  & $venvPy -m PyInstaller (Join-Path $Root "installer\xb-svcb-app.spec") --clean --noconfirm --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build")
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit code $LASTEXITCODE)" }
}
Require-File (Join-Path $Root "dist\XB-SVCB\XB-SVCB.exe") "Staged app executable (build without -SkipAppBuild)"
if ($SkipAppBuild) {
  Assert-AppPayloadFresh
}

# PyInstaller data files must be present on disk for the external AI environments.
$stagedInternal = Join-Path $Root "dist\XB-SVCB\_internal"
Require-File (Join-Path $stagedInternal "python312.dll") "Staged CPython 3.12 runtime (rebuild app without -SkipAppBuild)"
Require-File (Join-Path $stagedInternal "web\dist\index.html") "Staged frontend entry"
foreach ($worker in $workerFiles) {
  Require-File (Join-Path $stagedInternal "infrastructure\$worker") "Staged worker $worker"
  Require-MatchingFile `
    (Join-Path $Root "app\infrastructure\$worker") `
    (Join-Path $stagedInternal "infrastructure\$worker") `
    "Staged worker $worker"
}
Require-WorkerContract `
  (Join-Path $stagedInternal "infrastructure\f0_worker.py") `
  "Staged F0 worker" `
  @("--out-npy", "F0_OK") `
  @("--high-threshold", "FORMANT_PITCH_OK")
Require-WorkerContract `
  (Join-Path $stagedInternal "infrastructure\formant_pitch_worker.py") `
  "Staged formant pitch worker" `
  @("--high-threshold", "FORMANT_PITCH_OK") `
  @("--out-npy", "F0_OK")

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
# Remove stale payloads left by older PyInstaller builds. The three source trees
# and FFmpeg are staged below from their filtered release payloads.
foreach ($staleEngine in @('ffmpeg', 'so-vits-svc', 'ddsp-svc', 'seed-vc')) {
  $stalePath = Join-Path $Root ("dist\XB-SVCB\engines\{0}" -f $staleEngine)
  if (Test-Path -LiteralPath $stalePath) {
    Remove-Item -LiteralPath $stalePath -Recurse -Force
  }
}
# A PyInstaller rebuild replaces dist/XB-SVCB, so even a cached Host must be staged again.
New-Item -ItemType Directory -Force -Path $hostDest | Out-Null
Copy-Item -Path (Join-Path $hostSrc "*") -Destination $hostDest -Recurse -Force
$stagedHostExe = Join-Path $Root "dist\XB-SVCB\engines\juce-vst3-host\xb-juce-vst3-host.exe"
Require-File $stagedHostExe "Staged JUCE VST3 host (build without -SkipJuceHostBuild)"

Require-File (Join-Path $Root "setup_env.bat") "Runtime setup entry"
Require-File (Join-Path $Root "setup_shared_env.bat") "Shared runtime setup entry"
Require-File (Join-Path $Root "install_prereqs.bat") "Prerequisite installer"
Require-File (Join-Path $Root "install\install.py") "Runtime installer"
Prepare-BundledEnginePayloads (Join-Path $Root '.tmp\bundled-engines')
Write-Host "Staged runtime bundle validated." -ForegroundColor Green

# 5) Compile installer
Write-Host "`n==== Compiling installer (Inno Setup) ====" -ForegroundColor Cyan
$iscc = Find-ISCC
if (-not $iscc) {
  throw "ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php"
}
Write-Host ("ISCC: {0}" -f $iscc) -ForegroundColor Green

New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
$distDir = Join-Path $Root "dist"
if ($BootstrapperOnly) {
  $existingSlices = @(Get-ChildItem -LiteralPath $distDir -Filter "$outputBaseName-*.bin" -File -ErrorAction SilentlyContinue)
  if ($existingSlices.Count -eq 0) {
    throw "BootstrapperOnly requires existing $outputBaseName-*.bin files in dist. Build this stack's full installer once first."
  }
  $compileDir = Join-Path $Root ".tmp\installer-bootstrapper"
  if (Test-Path -LiteralPath $compileDir) {
    Remove-Item -LiteralPath $compileDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $compileDir | Out-Null
  try {
    & $iscc "/DXB_PACKAGE_STACK=$packageStack" "/DXB_OUTPUT_BASENAME=$outputBaseName" "/O$compileDir" (Join-Path $Root "installer\xb-svcb.iss")
    if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed (exit code $LASTEXITCODE)" }

    $tempExe = Join-Path $compileDir "$outputBaseName.exe"
    Require-File $tempExe "Installer bootstrapper"
    Copy-Item -LiteralPath $tempExe -Destination (Join-Path $distDir "$outputBaseName.exe") -Force

    $artifacts = Get-ChildItem -LiteralPath $compileDir -Filter "$outputBaseName*" -File |
      Sort-Object Name
    if (-not ($artifacts | Where-Object { $_.Extension -eq ".bin" })) {
      throw "Installer payload slices were not generated. Check DiskSpanning in installer/xb-svcb.iss."
    }
    $oversizedArtifacts = $artifacts | Where-Object { $_.Length -ge 2GB }
    if ($oversizedArtifacts) {
      $names = ($oversizedArtifacts | ForEach-Object { "{0} ({1} bytes)" -f $_.Name, $_.Length }) -join ", "
      throw "Installer artifacts must each stay below 2 GiB: $names"
    }
    Write-Host "`nInstaller bootstrapper refreshed; existing split volumes left untouched." -ForegroundColor Green
    Write-Host ("  {0}" -f (Join-Path $distDir "$outputBaseName.exe")) -ForegroundColor Green
  } finally {
    if (Test-Path -LiteralPath $compileDir) {
      Remove-Item -LiteralPath $compileDir -Recurse -Force
    }
  }
} else {
  # Replace only this hardware package; keep the other three package families.
  Get-ChildItem -LiteralPath $distDir -Filter "$outputBaseName*" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force
  & $iscc "/DXB_PACKAGE_STACK=$packageStack" "/DXB_OUTPUT_BASENAME=$outputBaseName" (Join-Path $Root "installer\xb-svcb.iss")
  if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed (exit code $LASTEXITCODE)" }

  $out = Join-Path $distDir "$outputBaseName.exe"
  Require-File $out "Installer bootstrapper"
  $artifacts = Get-ChildItem -LiteralPath $distDir -Filter "$outputBaseName*" -File |
    Sort-Object Name
  if (-not ($artifacts | Where-Object { $_.Extension -eq ".bin" })) {
    throw "Installer payload slices were not generated. Check DiskSpanning in installer/xb-svcb.iss."
  }
  $oversizedArtifacts = $artifacts | Where-Object { $_.Length -ge 2GB }
  if ($oversizedArtifacts) {
    $names = ($oversizedArtifacts | ForEach-Object { "{0} ({1} bytes)" -f $_.Name, $_.Length }) -join ", "
    throw "Installer artifacts must each stay below 2 GiB: $names"
  }
  Write-Host "`nInstaller artifacts:" -ForegroundColor Green
  $artifacts | ForEach-Object {
    Write-Host ("  {0} ({1:N1} MiB)" -f $_.FullName, ($_.Length / 1MB))
  }
}

# The staged directory is a disposable, filtered view of assets/wheels.  The
# developer cache remains intact when -SkipWheelhouse is used, while temporary
# hardlinks/copies are removed after a successful package build.
if (Test-Path -LiteralPath $installerWheelhouse) {
  Remove-Item -LiteralPath $installerWheelhouse -Recurse -Force
  Write-Host "Removed temporary $packageStack wheel payload staging." -ForegroundColor DarkGray
}
