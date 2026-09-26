<#
  XB-SVCB 一键安装器（Windows 入口）

  用法：
    右键“使用 PowerShell 运行”，或在项目根目录执行：
      ./install.ps1            # 全自动（检测显卡决定 CUDA/ROCm 10/CPU）
      ./install.ps1 --cpu      # 强制 CPU
      ./install.ps1 --gpu      # 自动选择 NVIDIA CUDA 或 AMD ROCm 10
      ./install.ps1 --rocm10   # 强制 AMD ROCm 10
      ./install.ps1 --only seedvc # 只跑某一步（app/web/uvr/svc/rvc/seedvc/hub/models）

  前置要求（脚本会检测并提示）：Git、Node.js LTS（含 npm）、64 位 CPython 3.12.x、ffmpeg。
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Cmd($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "==== XB-SVCB 安装前环境检查 ====" -ForegroundColor Cyan

# Resolve and validate a concrete 64-bit CPython 3.12 interpreter.
$python = $null
if (Test-Cmd "py") {
  try { $candidate = & py -3.12 -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0) { $python = $candidate.Trim() } } catch {}
}
if (-not $python -and (Test-Cmd "python")) { $python = (Get-Command python).Source }
if ($python) {
  & $python -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)" *> $null
  if ($LASTEXITCODE -ne 0) { $python = $null }
}
if (-not $python) {
  Write-Host "未检测到匹配的 Python。请安装 64 位 CPython 3.12.x（勾选 Add to PATH）后重试：" -ForegroundColor Red
  Write-Host "  https://www.python.org/downloads/" -ForegroundColor Yellow
  exit 1
}
Write-Host ("Python : {0}" -f $python) -ForegroundColor Green

# 软性检查（缺失只警告，由 install.py 在对应步骤再次处理）
foreach ($t in @("ffmpeg", "npm")) {
  if (Test-Cmd $t) { Write-Host ("{0,-7}: 已安装" -f $t) -ForegroundColor Green }
  else { Write-Host ("{0,-7}: 未检测到（对应步骤可能失败）" -f $t) -ForegroundColor Yellow }
}
# Git 可选：缺失时安装器会自动改用下载 ZIP 获取 so-vits-svc
if (Test-Cmd "git") { Write-Host "git    : 已安装" -ForegroundColor Green }
else { Write-Host "git    : 未检测到（可选，将自动改用下载 ZIP）" -ForegroundColor Yellow }

Write-Host "`n==== 开始安装（首次运行会下载较多依赖与模型，请耐心等待）====" -ForegroundColor Cyan

# 透传所有参数给 install.py
$installer = Join-Path $PSScriptRoot "install\install.py"
& $python $installer @args
$code = $LASTEXITCODE

if ($code -eq 0) {
  Write-Host "`n安装完成！双击 run.ps1 或执行 ./run.ps1 启动应用。" -ForegroundColor Green
} else {
  Write-Host "`n安装过程中有步骤失败（退出码 $code），请查看上方日志。" -ForegroundColor Red
}
exit $code
