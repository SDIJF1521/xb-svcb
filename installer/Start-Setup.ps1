<#
  启动 XB-SVCB 安装器，并自动规避「%TEMP% 不可写」导致的
  “安装程序无法创建目录 … 错误 5: 拒绝访问”。

  用法：
    pwsh -ExecutionPolicy Bypass -File .\installer\Start-Setup.ps1
    pwsh -ExecutionPolicy Bypass -File .\installer\Start-Setup.ps1 -Setup .\dist\XB-SVCB-Setup-CUDA126.exe
    pwsh -ExecutionPolicy Bypass -File .\installer\Start-Setup.ps1 -Elevate

  背景：Inno Setup 在显示任何界面之前，会先把自身解压到 %TEMP%\is-XXXX.tmp。
  如果当前进程对 %TEMP% 没有写权限（受限令牌、沙箱会话、杀软拦截等），
  就会在该步骤报错误 5。本脚本先探测 %TEMP%，不可写时改用
  %LOCALAPPDATA%\XB-SVCB\setup-temp 启动安装器，并把每一步写入
  dist\setup-launch.log。
#>
param(
  [string]$Setup = '',
  [switch]$Elevate,
  [switch]$Silent
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $root 'dist\setup-launch.log'

function Write-Log([string]$Message) {
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
  Write-Host $line
  try {
    $dir = Split-Path -Parent $logPath
    if (-not (Test-Path -LiteralPath $dir)) {
      New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
  } catch {
    # 日志写不进去时不影响启动流程。
  }
}

function Test-Writable([string]$Path) {
  try {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    $probe = Join-Path $Path ('probe-' + [guid]::NewGuid().ToString('N'))
    Set-Content -LiteralPath $probe -Value 'ok' -Encoding ascii -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
    return $true
  } catch {
    return $false
  }
}

try {
  $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
  $admin = (New-Object Security.Principal.WindowsPrincipal(
    [System.Security.Principal.WindowsIdentity]::GetCurrent()
  )).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  Write-Log ("user: {0}  elevated: {1}" -f $identity, $admin)
  Write-Log ("TEMP: {0}" -f $env:TEMP)
  Write-Log ("TMP : {0}" -f $env:TMP)

  if (-not $Setup) {
    $candidates = @(Get-ChildItem -LiteralPath (Join-Path $root 'dist') -Filter 'XB-SVCB-Setup-*.exe' -File -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -eq 0) {
      throw '没有找到 dist\XB-SVCB-Setup-*.exe，请先用 -Setup 指定安装器路径。'
    }
    $Setup = $candidates[0].FullName
    Write-Log ("setup: {0}（未指定时使用最近构建的一个）" -f $Setup)
  }
  $Setup = (Resolve-Path -LiteralPath $Setup).Path
  if (-not (Test-Path -LiteralPath $Setup -PathType Leaf)) {
    throw "安装器不存在：$Setup"
  }

  $candidates = @()
  if ($env:TEMP) { $candidates += $env:TEMP }
  $candidates += (Join-Path $env:LOCALAPPDATA 'XB-SVCB\setup-temp')
  $candidates += (Join-Path (Split-Path -Parent $Setup) 'setup-temp')
  $candidates += (Join-Path $env:USERPROFILE 'XB-SVCB-setup-temp')
  $tempDir = $null
  foreach ($candidate in $candidates) {
    if (-not $candidate) { continue }
    if (Test-Writable $candidate) {
      $tempDir = $candidate
      break
    }
    Write-Log ("temp not writable: {0}" -f $candidate)
  }
  if (-not $tempDir) {
    throw '所有候选临时目录都不可写；请以管理员身份运行本脚本，或检查杀软/沙箱策略。'
  }
  Write-Log ("using TEMP: {0}" -f $tempDir)

  $env:TEMP = $tempDir
  $env:TMP = $tempDir

  $argumentList = @('/SP-')
  if ($Silent) {
    $argumentList += @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
  }

  if ($Elevate) {
    Write-Log 'launching installer elevated (UAC)'
    $process = Start-Process -FilePath $Setup -ArgumentList $argumentList -Verb RunAs -PassThru
  } else {
    Write-Log 'launching installer'
    $process = Start-Process -FilePath $Setup -ArgumentList $argumentList -PassThru
  }
  Write-Log ("started pid {0}" -f $process.Id)
  $process.WaitForExit()
  Write-Log ("installer exit code: {0}" -f $process.ExitCode)
  exit $process.ExitCode
} catch {
  Write-Log ("ERROR: {0}" -f $_.Exception.Message)
  Write-Host ''
  Write-Host '诊断信息已写入：' -ForegroundColor Yellow
  Write-Host ("  {0}" -f $logPath)
  exit 1
}
