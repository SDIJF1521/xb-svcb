# XB-SVCB 安装器与发布打包

本目录只维护当前发布方案。历史行为记录统一放在 `docs/release-notes/`，不再在这里重复维护逐版本清单。

## 当前发布方案

发布产物按硬件栈拆成四套完整安装包：

| 包 | 运行时布局 | Torch 栈 |
| --- | --- | --- |
| `XB-SVCB-Setup-CPU` | 兼容隔离环境 | CPU |
| `XB-SVCB-Setup-DirectML` | 兼容隔离环境 | DirectML |
| `XB-SVCB-Setup-CUDA126` | 两层共享环境 | Torch 2.7.1 + cu126 |
| `XB-SVCB-Setup-CUDA128` | 两层共享环境 | Torch 2.7.1 + cu128 |

CUDA 是默认发布路径：不传 `-Stacks` 时，`build.ps1` 构建 CUDA128 共享运行时安装包。CPU 和 DirectML 因依赖组合不同，继续保留隔离布局。四套包都包含同一应用、引擎源码、模型、FFmpeg 和 JUCE Host，但只携带目标硬件栈需要的 wheels。

CUDA 共享布局：

- `runtimes/core-cu126` / `runtimes/core-cu128`：UVR、SeedVC、DDSP-SVC。
- `runtimes/svc-cu126` / `runtimes/svc-cu128`：So-VITS-SVC、RVC、Vocal/DeepFilterNet3。
- `runtime.json` 保存各组件解释器路由，应用优先读取它，旧 `.venv-*` 仅作为兼容回退。

完整设计与修复规则见 [共享运行时布局](../docs/runtime-consolidation.md)。

## 构建前置

- 64 位 CPython 3.10.x。可用 `-Python C:\path\to\python.exe` 明确指定。
- Node.js，用于构建 `web/dist`。
- `app/.venv` 中的 PyInstaller 与桌面依赖。
- CMake、Visual C++ Build Tools 和 JUCE，用于 JUCE VST3 Host。
- Inno Setup 6，提供 `ISCC.exe`。
- 完整模型、引擎源码及 `assets/wheels`，或允许构建脚本重新准备 wheelhouse。

Python 不随安装器内置。用户安装时可从检测结果中选择 CPython 3.10.x，安装器把选择写入安装目录的 `installer_env.cmd`。`uv` 无需用户预装：wheelhouse 携带启动 wheel，缺失时由安装流程安装。

四种发布栈现在都只创建 Python 3.10 环境。CPU 的 SVC/RVC 仍保留独立目录和兼容 Torch 版本，但不再额外要求 Python 3.9。

## 默认构建

轻量校验四种配置，不生成发布包：

```powershell
& .\installer\build.ps1 -ValidateOnly
```

构建默认 CUDA128 共享包：

```powershell
& .\installer\build.ps1 -Python "C:\Python310\python.exe"
```

构建指定硬件包：

```powershell
& .\installer\build.ps1 -Stacks cu126 -Python "C:\Python310\python.exe"
& .\installer\build.ps1 -Stacks cpu -Python "C:\Python310\python.exe"
& .\installer\build.ps1 -Stacks directml -Python "C:\Python310\python.exe"
```

已有前端、应用、JUCE Host 和完整 wheelhouse 时，可复用它们：

```powershell
& .\installer\build.ps1 -Stacks cu128 -Python "C:\Python310\python.exe" `
  -SkipWheelhouse -SkipWebBuild -SkipAppBuild -SkipJuceHostBuild
```

## 顺序构建四套包

四套包共享 staging 目录，必须顺序构建：

```powershell
& .\installer\build-all-packages.ps1 -Python "C:\Python310\python.exe"
```

需要从头刷新全部 wheels：

```powershell
& .\installer\build-all-packages.ps1 `
  -Python "C:\Python310\python.exe" `
  -RebuildWheelhouse
```

可选开关：

- `-RebuildWeb`：首个包前重新构建前端。
- `-RebuildApp`：首个包前重新构建 PyInstaller 应用。
- `-RebuildJuceHost`：首个包前重新构建 JUCE Host。
- `-KeepExistingInstallers`：不清理 `dist` 中旧的安装器分卷。

## Wheelhouse 与分卷

`install/prepare_wheelhouse.py` 准备完整离线缓存，`installer/stage_wheelhouse.py` 在每次编译前只暂存目标栈所需 wheels。暂存目录位于 `.tmp/installer-wheelhouse`，优先硬链接、失败时复制；成功编译后自动清理。

从旧 py39 CPU 缓存升级后必须执行一次 `-RebuildWheelhouse`。staging 会拒绝只有 `svc/py39/cpu`、`rvc/py39/cpu` 的旧缓存，避免生成表面成功、用户机实际缺包的 CPU 安装器。

Inno Setup 的每个 `.bin` 分卷固定小于 2 GB。发布时必须把某个 EXE 与所有同名前缀 `.bin` 放在同一目录，例如：

```text
XB-SVCB-Setup-CUDA128.exe
XB-SVCB-Setup-CUDA128-1.bin
XB-SVCB-Setup-CUDA128-2.bin
...
```

四套完整包会重复公共应用和模型载荷，因此发布方总存储量大于单个通用包；用户只需下载与自己硬件匹配的一套。

## 用户机安装与修复

安装器会：

1. 校验应用、模型、引擎源码、FFmpeg、JUCE Host 和 wheels。
2. 检测并锁定用户选择的 CPython 3.10.x。
3. 安装或复用 `uv`，按包内固定硬件栈创建环境。
4. CUDA126/CUDA128 调用共享入口；CPU/DirectML 调用隔离兼容入口。
5. 对每个解释器执行真实 Python/Torch 校验，通过后写入 `runtime.json`。
6. 全部校验通过后删除安装目录中的 `assets/wheels`，降低最终占用；失败时保留缓存便于重试。

开始菜单的“搭建/修复运行环境”调用 `setup_env.bat`。它读取 `installer_env.cmd` 中保存的 `XB_RUNTIME_LAYOUT` 与 `XB_GPU_STACK`，因此 CUDA 安装后再次修复仍会走共享环境，不会退回旧隔离布局。

## 文件职责

- `build.ps1`：构建一套硬件专用包；默认 CUDA128。
- `build-all-packages.ps1`：顺序构建四套专用包。
- `stage_wheelhouse.py`：筛选并暂存单一硬件栈 wheels。
- `xb-svcb.iss`：Inno Setup 安装流程、校验、分卷和缓存清理。
- `xb-svcb-app.spec`：PyInstaller 应用本体。
- `../install/install_shared.py`：CUDA 两层共享运行时编排。
- `../install/install.py`：公共组件实现及 CPU/DirectML/旧安装兼容入口。
- `../setup_env.bat`：自动选择共享或兼容布局的统一修复入口。
- `../setup_shared_env.bat`：开发者显式调用的共享入口。
