# 安装、源码启动与修复

普通用户应下载与硬件匹配的专用安装包。源码方式面向开发者和需要修改引擎的人。

## 选择安装包

| 设备                       | 安装包  | 运行时布局                                  |
| -------------------------- | ------- | ------------------------------------------- |
| 无兼容 GPU                 | CPU     | 隔离兼容环境                                |
| Windows AMD Radeon（首选） | ROCm 10 | SVC/RVC/Vocal 共享，其余隔离                 |
| Windows AMD（可选）        | DirectML | 隔离兼容环境；DDSP 自动使用 CPU             |
| NVIDIA RTX 40 系及以下     | CUDA126 | `core-cu126` + `svc-cu126` 两层共享环境 |
| NVIDIA RTX 50 系 Blackwell | CUDA128 | `core-cu128` + `svc-cu128` 两层共享环境 |

项目最低 CUDA wheel 栈为 cu126，不再使用 cu121。每套专用包只携带自己的硬件 wheels，但应用、模型和引擎源码相同。

安装器不内置完整 Python。请选择 64 位 CPython 3.12.x；如果自动检测结果不正确，可在安装向导中手动指定 `python.exe`。`uv` 无需预装，安装器会从自带启动 wheel 安装。

## 安装后的运行环境

CUDA126/CUDA128 默认共享：

| 目录                                     | 组件                                   |
| ---------------------------------------- | -------------------------------------- |
| `runtimes/core-cu126` / `core-cu128` | UVR、SeedVC、DDSP-SVC                  |
| `runtimes/svc-cu126` / `svc-cu128`   | So-VITS-SVC、RVC、Vocal/DeepFilterNet3 |

CPU 使用 `.venv-uvr`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp` 和 `.venv-vocal` 等隔离目录。DirectML 也隔离，但 RVC 使用 `.venv-rvc-directml`。ROCm 10 的 SVC/RVC/Vocal 共用 `runtimes/svc-rocm10`，其余组件隔离。应用通过 `runtime.json` 识别实际解释器，不应只根据目录名判断安装是否完成。

完整布局和旧安装兼容规则见 [共享运行时与兼容布局](runtime-consolidation.md)。

## 仅旧版 0.0.31：RTX 50 安装修复

0.0.32 的 CUDA128 配方已包含 `gin-config`，无需执行下面的旧版补丁。只有暂时无法升级、且 0.0.31 因缺少此依赖而安装失败时，才在 PowerShell 中对旧安装目录执行：

```powershell
Set-Location '安装目录'

$lock = Join-Path (Get-Location) 'install\runtime_profiles\core-cu128\requirements.lock'
$profile = Join-Path (Get-Location) 'install\runtime_profiles\core-cu128\profile.json'

if (!(Test-Path -LiteralPath $lock) -or !(Test-Path -LiteralPath $profile)) {
    throw '找不到 core-cu128 配方文件，请确认当前目录是 安装目录地址'
}

$utf8 = New-Object System.Text.UTF8Encoding($false)

Copy-Item -LiteralPath $lock -Destination ($lock + '.bak') -Force
Copy-Item -LiteralPath $profile -Destination ($profile + '.bak') -Force

$text = [System.IO.File]::ReadAllText($lock)

if ($text -notmatch '(?m)^gin-config==') {
    $match = [regex]::Match($text, '(?m)^fsspec==[^\r\n]*')
    if (!$match.Success) {
        throw '锁文件格式不符合预期'
    }

    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $text = $text.Insert(
        $match.Index + $match.Length,
        $newline + 'gin-config==0.5.0'
    )

    [System.IO.File]::WriteAllText($lock, $text, $utf8)
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $lock).Hash.ToLowerInvariant()
$json = [System.IO.File]::ReadAllText($profile) | ConvertFrom-Json
$json.lock_sha256 = $hash

[System.IO.File]::WriteAllText(
    $profile,
    ($json | ConvertTo-Json -Depth 10),
    $utf8
)

.\setup_env.bat
```

从开始菜单运行“搭建/修复运行环境”，或在安装目录执行：

```bat
setup_env.bat
```

安装器会把硬件栈和布局写入 `installer_env.cmd`。因此 CUDA 包无参数修复时仍使用共享环境，不会误建六个旧隔离环境。

只修复某个非原子组件可使用 `--only`。CUDA core 的 UVR、SeedVC、DDSP 必须作为一组修复：

```bat
setup_env.bat --only uvr seedvc ddsp
setup_env.bat --only svc rvc vocal
setup_env.bat --only models
```

安装失败时先保留 `assets\wheels` 和 `install_logs`。只有全部环境通过最终校验后，安装器才自动删除离线 wheels。

### v0.0.32 CUDA128 离线安装修复

若 RTX 50 系安装在 `torch-2.7.1+cu128` 处报错 `The wheel is invalid: Missing .dist-info directory`，这不是 CUDA Toolkit 或显卡驱动错误。先关闭 XB-SVCB，在安装目录打开 PowerShell，并核对安装包释放出的 Torch wheel：

```powershell
$root = "E:\XB-SVCB" # 改为实际安装目录
$torchWheel = "$root\assets\wheels\py312\cu128\torch-2.7.1+cu128-cp312-cp312-win_amd64.whl"

(Get-Item $torchWheel).Length
(Get-FileHash $torchWheel -Algorithm SHA256).Hash
```

v0.0.32 CUDA128 包的正确结果是：

```text
大小：3273024349
SHA256：2BB8C05D48BA815B316879A18195D53A6472A03E297D971E916753F8E1053D30
```

若大小或哈希不一致，应重新下载完整的 CUDA128 安装包，并确保安装器 EXE 与所有同名前缀 BIN 分卷位于同一目录。不要继续使用损坏的 wheel 修复环境。

若大小和哈希一致，从安装日志或 `installer_env.cmd` 取得锁定的 `XB_PYTHON_EXE` 路径，然后强制重装随包 `uv`、清理 Torch 缓存并重试共享核心组：

```powershell
$py = "C:\Path\To\Python312\python.exe" # 替换为 XB_PYTHON_EXE
$uv = "$env:APPDATA\Python\Python312\Scripts\uv.exe"

& $py -m ensurepip --upgrade
& $py -m pip install --user --force-reinstall --no-index `
  --find-links "$root\assets\wheels\bootstrap" "uv==0.12.22"
& $uv --version
& $uv cache clean torch

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

如果 UVR、SeedVC 和 DDSP 均显示成功，但最终校验报告 `missing: ["exceptiongroup"]`，Torch 和 CUDA 已经安装成功，只需补装本地 wheel 后再次执行同一修复入口：

```powershell
& $uv pip install `
  --python "$root\runtimes\core-cu128\Scripts\python.exe" `
  --no-index --no-build `
  --find-links "$root\assets\wheels\py312\cu128" `
  "exceptiongroup==1.3.1"

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

最终输出应显示共享运行环境完成并写入 `runtime.json`。报告中的 `hf-xet` 属于允许缺失的可选包；DDSP 输出的 `Please install tensorboardX` 也不是本次安装失败原因。

## 源码环境要求

- Windows。
- 64 位 CPython 3.12.x，用于安装器和当前离线 wheels。
- Node.js 20.19+ 或 22.12+，仅构建前端需要。
- 可访问 PyPI、模型源和上游仓库，或已准备离线 wheelhouse 与模型资产。
- 构建 VST3 Host 时需要 CMake、Visual C++ Build Tools 和 JUCE。

在源码根目录显式选择环境：

```bat
setup_env.bat --cu128
setup_env.bat --cu126
setup_env.bat --cpu
setup_env.bat --rocm10
setup_env.bat --directml
```

CUDA 参数调用两层共享入口；ROCm 10 调用带 SVC 共享层的兼容入口，CPU/DirectML 调用隔离入口。开发者也可直接运行：

```bat
setup_shared_env.bat --cu128
python install\install.py --cpu
python install\install.py --rocm10
python install\install.py --directml
```

每一步都可重复执行。`install/install.py` 仍包含公共组件实现和旧安装兼容代码，不表示新 CUDA 安装默认使用隔离布局。

## 启动

生产模式：

```bat
run.bat
```

等价命令：

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py
```

前端开发模式：

```powershell
Set-Location .\web
npm install
npm run dev
```

再在另一个终端运行：

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py --dev
```

生产模式加载 `web/dist/index.html`，开发模式默认连接 `http://localhost:5173`。

## 数据目录

默认数据目录为 `.xb_svcb`，保存模型库、作品、编辑工程、下载文件、设置、日志和缓存。推荐放在空间充足的磁盘。可通过应用内迁移功能或 `XB_DATA_DIR` 更改位置。

## 常见排障

### 找不到 Python

安装器只接受可运行的 64 位 CPython 3.12.x，因为离线 wheels 是 `cp312-win_amd64`。优先选择普通 Python 或 Conda 解释器，不要选择某个 AI 项目的 `.venv`。

### 缺少前端

源码生产模式要求 `web/dist/index.html`：

```powershell
Set-Location .\web
npm run build
```

### AI 环境搭建失败

查看安装目录中的 `install_logs`。联网修复可先设置镜像：

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
setup_env.bat
```

### 找不到 FFmpeg

安装包自带 FFmpeg。源码运行需要系统 `PATH` 中存在 `ffmpeg`，或把完整 Windows 构建放到 `assets/tools/ffmpeg`。

### 修改前端后仍显示旧页面

重新构建 `web/dist` 并完全退出应用后启动。开发期间优先使用 `--dev` 连接 Vite。
