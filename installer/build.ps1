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
    (Join-Path $PayloadRoot 'seed-vc\inference.py'),
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
  "svc_worker.py",
  "f0_worker.py",
  "vocal_tuning_worker.py",
  "uvr_worker.py",
  "hub_worker.py",
  "rvc_worker.py",
  "seedvc_worker.py",
  "ddsp_worker.py",
  "vocal_enhancement_worker.py"
)
foreach ($worker in $workerFiles) {
  Require-File (Join-Path $Root "app\infrastructure\$worker") "Worker source $worker"
}
Require-File (Join-Path $Root "release_notes_v026.md") "v0.0.26 release notes"
Require-File (Join-Path $Root "docs\api.md") "FastAPI integration guide"
Require-File (Join-Path $Root "install\configure_user_env.py") "User environment helper"
$licensePath = Join-Path $Root "LICENSE"
Require-File $licensePath "GPLv3 license"
if ((Get-Content -LiteralPath $licensePath -Raw) -notmatch 'GNU GENERAL PUBLIC LICENSE\s+Version 3, 29 June 2007') {
  throw "LICENSE must contain the complete GNU GPL version 3 text."
}

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
Ensure-DdspContentvecPayload `
  (Join-Path $Root "engines\ddsp-svc\pretrain\contentvec\pytorch_model.bin")
Ensure-EngineSource `
  (Join-Path $Root "engines\seed-vc") `
  "inference.py" `
  "https://github.com/Plachtaa/seed-vc.git" `
  "main" `
  "SeedVC"
Require-File (Join-Path $Root "assets\tools\ffmpeg\bin\ffmpeg.exe") "Bundled FFmpeg"
Require-File (Join-Path $Root "assets\tools\ffmpeg\bin\ffprobe.exe") "Bundled ffprobe"
Require-FileSize `
  (Join-Path $Root "engines\ddsp-svc\pretrain\contentvec\pytorch_model.bin") `
  314572800 `
  "Bundled DDSP ContentVec"

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
$oversizedArtifacts = $artifacts | Where-Object { $_.Length -ge 2GB }
if ($oversizedArtifacts) {
  $names = ($oversizedArtifacts | ForEach-Object { "{0} ({1} bytes)" -f $_.Name, $_.Length }) -join ", "
  throw "Installer artifacts must each stay below 2 GiB: $names"
}
Write-Host "`nInstaller artifacts:" -ForegroundColor Green
$artifacts | ForEach-Object {
  Write-Host ("  {0} ({1:N1} MiB)" -f $_.FullName, ($_.Length / 1MB))
}
