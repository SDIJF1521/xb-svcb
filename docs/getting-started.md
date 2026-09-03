# 安装、源码启动与修复

普通用户应下载与硬件匹配的专用安装包。源码方式面向开发者和需要修改引擎的人。

## 选择安装包

| 设备 | 安装包 | 运行时布局 |
| --- | --- | --- |
| 无兼容 GPU | CPU | 隔离兼容环境 |
| Windows AMD Radeon | DirectML | 隔离兼容环境 |
| NVIDIA RTX 40 系及以下 | CUDA126 | `core-cu126` + `svc-cu126` 两层共享环境 |
| NVIDIA RTX 50 系 Blackwell | CUDA128 | `core-cu128` + `svc-cu128` 两层共享环境 |

项目最低 CUDA wheel 栈为 cu126，不再使用 cu121。每套专用包只携带自己的硬件 wheels，但应用、模型和引擎源码相同。

安装器不内置完整 Python。请选择 64 位 CPython 3.10.x；如果自动检测结果不正确，可在安装向导中手动指定 `python.exe`。`uv` 无需预装，安装器会从自带启动 wheel 安装。

## 安装后的运行环境

CUDA126/CUDA128 默认共享：

| 目录 | 组件 |
| --- | --- |
| `runtimes/core-cu126` / `core-cu128` | UVR、SeedVC、DDSP-SVC |
| `runtimes/svc-cu126` / `svc-cu128` | So-VITS-SVC、RVC、Vocal/DeepFilterNet3 |

CPU/DirectML 使用 `.venv-uvr`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp` 和 `.venv-vocal` 等隔离目录。应用通过 `runtime.json` 识别实际解释器，不应只根据目录名判断安装是否完成。

完整布局和旧安装兼容规则见 [共享运行时与兼容布局](runtime-consolidation.md)。

## 修复安装包环境

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

## 源码环境要求

- Windows。
- 64 位 CPython 3.10.x，用于安装器和当前离线 wheels。
- Node.js 20.19+ 或 22.12+，仅构建前端需要。
- 可访问 PyPI、模型源和上游仓库，或已准备离线 wheelhouse 与模型资产。
- 构建 VST3 Host 时需要 CMake、Visual C++ Build Tools 和 JUCE。

在源码根目录显式选择环境：

```bat
setup_env.bat --cu128
setup_env.bat --cu126
setup_env.bat --cpu
setup_env.bat --directml
```

CUDA 参数调用共享入口；CPU/DirectML 调用隔离兼容入口。开发者也可直接运行：

```bat
setup_shared_env.bat --cu128
python install\install.py --cpu
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

安装器只接受可运行的 64 位 CPython 3.10.x，因为离线 wheels 是 `cp310-win_amd64`。优先选择普通 Python 或 Conda 解释器，不要选择某个 AI 项目的 `.venv`。

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
