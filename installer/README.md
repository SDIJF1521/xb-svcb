# XB-SVCB 安装器与发布打包

本目录只维护当前发布方案。历史行为记录统一放在 `docs/release-notes/`，不再在这里重复维护逐版本清单。

## 当前发布方案

发布产物按硬件栈拆成五套完整安装包：

| 包 | 运行时布局 | Torch 栈 |
| --- | --- | --- |
| `XB-SVCB-Setup-CPU` | 兼容隔离环境 | CPU |
| `XB-SVCB-Setup-ROCm10` | SVC/RVC/Vocal 共享，其余隔离 | ROCm 10 |
| `XB-SVCB-Setup-DirectML` | 兼容隔离环境 | DirectML；DDSP 默认 CPU、显式实验 DirectML，Vocal 使用 CPU Torch |
| `XB-SVCB-Setup-CUDA126` | 两层共享环境 | Torch 2.7.1 + cu126 |
| `XB-SVCB-Setup-CUDA128` | 两层共享环境 | Torch 2.7.1 + cu128 |

CUDA 是默认发布路径：不传 `-Stacks` 时，`build.ps1` 构建 CUDA128 共享运行时安装包。CPU 和 DirectML 保留隔离布局；ROCm 10 的 SVC/RVC/Vocal 共用 `runtimes/svc-rocm10`，其余组件隔离。五套包都包含同一应用、引擎源码、模型、FFmpeg 和 JUCE Host，但只携带目标硬件栈需要的 wheels。DirectML 包额外携带 PyMSS 与 DDSP legacy 所需的 CPU wheels：PyMSS 2.0.x 需要 Torch 2.7.1，不能与固定 Torch 2.4.1 的 `torch-directml` 混装，因此在独立 `.venv-pymss` 中使用 CPU 推理。DDSP 自动设备同样走 CPU；用户显式选择 DirectML 才尝试 6.3 模型的实验推理，输出可能存在静默数值失真，需要试听确认。

CUDA 共享布局：

- `runtimes/core-cu126` / `runtimes/core-cu128`：UVR、SeedVC、DDSP-SVC。
- `runtimes/svc-cu126` / `runtimes/svc-cu128`：So-VITS-SVC、RVC、Vocal/DeepFilterNet3。
- `runtime.json` 保存各组件解释器路由，应用优先读取它，旧 `.venv-*` 仅作为兼容回退。

完整设计与修复规则见 [共享运行时布局](../docs/runtime-consolidation.md)。

## 构建前置

- 64 位 CPython 3.12.x。可用 `-Python C:\path\to\python.exe` 明确指定。
- Node.js，用于构建 `web/dist`。
- `app/.venv` 中的 PyInstaller 与桌面依赖。
- CMake、Visual C++ Build Tools 和 JUCE，用于 JUCE VST3 Host。
- Inno Setup 6，提供 `ISCC.exe`。
- 完整模型、引擎源码及 `assets/wheels`，或允许构建脚本重新准备 wheelhouse。
- CUDA 包还必须有 `assets/runtime/core-cu128` 的 candidate/compat 材料；可用
  `-RuntimeAssets C:\path\to\core-cu128` 从单独备份同步。

安装器内置一套干净的 64 位 CPython 3.12.x，安装到 `tools\python312` 并固定写入 `installer_env.cmd`；最终用户不需要另外安装或选择 Python。构建参数 `-Python` 指定的基础解释器既用于生成 wheelhouse，也用于暂存内置运行时；构建器会排除该解释器的 `Lib\site-packages`、`Scripts` 和缓存，避免携带开发机第三方包。`uv` 无需用户预装：wheelhouse 携带启动 wheel，缺失时由安装流程安装。

五种发布栈现在都只创建 Python 3.12 环境。CPU 的 SVC/RVC 仍保留独立目录和兼容 Torch 版本，但不再额外要求 Python 3.9。

## 默认构建

查看参数，不执行构建：

```powershell
& .\installer\build.ps1 -Help
& .\installer\build-all-packages.ps1 -Help
```

轻量校验五种配置，不生成发布包：

```powershell
& .\installer\build.ps1 -ValidateOnly
```

构建默认 CUDA128 共享包（自动通过 `py -3.12` 或 `PATH` 检测解释器）：

```powershell
& .\installer\build.ps1
```

构建指定硬件包：

```powershell
& .\installer\build.ps1 -Stacks cu126
& .\installer\build.ps1 -Stacks cpu
& .\installer\build.ps1 -Stacks rocm10
& .\installer\build.ps1 -Stacks directml
```

单独运行 `build.ps1` 且不传 `-SkipWheelhouse` 时，只为目标栈重新准备 wheelhouse；该路径会使用
`--clean` 清空现有全部 wheel 缓存。已经准备多栈缓存时不要使用该默认行为，应先增量准备缺失栈，
再通过 `-SkipWheelhouse` 打包，例如：

```powershell
& py -3.12 .\install\prepare_wheelhouse.py --stack directml
& .\installer\build.ps1 -Stacks directml -SkipWheelhouse
```

成功后产物为 `dist\XB-SVCB-Setup-DirectML.exe` 及同名前缀的 `.bin` 分卷。

CUDA 运行时材料不在 Git 中时，先从备份同步再构建：

```powershell
& .\installer\build.ps1 -Stacks cu126 `
  -RuntimeAssets "D:\XB-SVCB\assets\runtime\core-cu128"
```

`-RuntimeAssets` 也可以指向包含 `core-cu128` 子目录的 `assets\runtime` 目录，或通过
环境变量 `XB_RUNTIME_ASSETS` 指定。构建器会逐个校验 candidate/compat wheel 的大小和
SHA-256；缺少 `protobuf-7.36.0` 时会在编译 EXE 前停止。

已有前端、应用、JUCE Host 和完整 wheelhouse 时，可复用它们：

```powershell
& .\installer\build.ps1 -Stacks cu128 `
  -SkipWheelhouse -SkipWebBuild -SkipAppBuild -SkipJuceHostBuild
```

## 顺序构建五套包

五套包共享 staging 目录，必须顺序构建。脚本会先检查五栈必需 wheel 目录：已有缓存直接复用，
缺少的栈会自动增量准备，因此不需要等到对应安装器 staging 时才发现目录为空：

```powershell
& .\installer\build-all-packages.ps1
```

从独立运行时备份同步材料并构建五套包：

```powershell
& .\installer\build-all-packages.ps1 `
  -RuntimeAssets "D:\XB-SVCB\assets\runtime\core-cu128"
```

显式重新检查并增量补齐全部 wheels（已下载文件会复用，网络中断后也可直接重跑）：

```powershell
& .\installer\build-all-packages.ps1 `
  -Python C:\python3.12.9\python.exe `
  -RebuildWheelhouse
```

只有确认缓存已经损坏或需要彻底刷新时才清空重建：

```powershell
& .\installer\build-all-packages.ps1 `
  -RebuildWheelhouse -CleanWheelhouse
```

若只需从某个失败批次继续准备，可直接运行，例如：

```powershell
& C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py `
  --root . --stack rocm10 --from-batch "ddsp legacy rocm10 torch"
```

CPU、ROCm 已完成而其余三栈尚未准备时，直接补齐剩余栈，避免重新解析前两栈：

```powershell
& C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py `
  --root . --stack directml --stack cu126 --stack cu128
& .\installer\build-all-packages.ps1 `
  -Python C:\python3.12.9\python.exe
```

准备计划保证 CPU 的 `svc/py312/cpu` 和 `rvc/py312/cpu` 在进入 ROCm 批次前生成。因此后续 GPU
源失败不会留下“公共 CPU wheels 存在、CPU 组件目录为空”的半成品。ROCm 组件目录会通过硬链接
复用公共 ROCm 运行时；重复执行不会再次下载相同的大型 Torch/ROCm wheels。

常见恢复命令：

| 错误或当前状态 | 恢复命令 |
| --- | --- |
| `svc/py312/cpu` 或 `rvc/py312/cpu` 为空 | `C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py --root . --stack cpu --from-batch "svc cpu py312 setuptools"` |
| `ddsp-legacy/py312/rocm10` 在 Torch 批次失败 | `C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py --root . --stack rocm10 --from-batch "ddsp legacy rocm10 torch"` |
| 只缺 DirectML 与两套 CUDA 栈 | `C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py --root . --stack directml --stack cu126 --stack cu128` |

日志先出现 `ProxyError` / TLS handshake timeout，随后出现 `ResolutionImpossible` 时，通常是代理或
下载源不可达，不是版本约束真的冲突。先检查 `Get-ChildItem Env: | Where-Object Name -Match 'PROXY'`；
如果这些代理变量并非有意配置，只在当前 PowerShell 中移除对应的 `HTTP_PROXY`、`HTTPS_PROXY`、
`ALL_PROXY` 后重跑增量命令。不要为网络超时使用 `-CleanWheelhouse`。

可选开关：

- `-RebuildWeb`：首个包前重新构建前端。
- `-RebuildApp`：首个包前重新构建 PyInstaller 应用。
- `-RebuildJuceHost`：首个包前重新构建 JUCE Host。
- 默认会在首个包前重建前端、PyInstaller 应用和 JUCE Host，确保当前源码进入全部 EXE；
  `-ReuseBuildOutputs` 才会允许复用已有构建产物。
- `-KeepExistingInstallers`：不清理 `dist` 中旧的安装器分卷。
- `-CleanWheelhouse`：与 `-RebuildWheelhouse` 一起使用，删除现有缓存后从零下载；通常不需要。

## 在线安装器与 OSS 发布

v0.1.0 同时提供引导式在线安装器 `XB-SVCB-Online-Setup.exe`。它会自动检测或让用户手动选择硬件栈，先读取并校验发布清单，再显示完整安装包大小、缓存复用情况和下载位置。只有缺失或 SHA-256 不匹配的 EXE/BIN 分卷会下载；全部文件校验通过后，在线安装器会以当前语言启动完整离线安装向导。在线安装器支持简体中文、English 和日本語。

### 当前 OSS 桶配置

根据当前发布桶信息，Bucket 和公网 Endpoint 为：

```text
Bucket:  xb-svcb
Region:  oss-cn-hongkong
Endpoint: https://oss-cn-hongkong.aliyuncs.com
```

你已经在 Bucket 内创建了 `xb-svcb/0.1.0/` 对象前缀，因此在线安装器的基础地址为：

```text
https://xb-svcb.oss-cn-hongkong.aliyuncs.com/xb-svcb/0.1.0
```

注意：截图显示该 Bucket 当前是“私有”。当前在线安装器使用的是不带凭据的 HTTPS 下载，并且会拒绝把 AccessKey、Secret 或带查询参数的长期签名 URL 编译进去，所以私有桶的直接 URL 会返回 `403`，不能直接用于在线安装。推荐保留 Bucket 默认私有，仅通过 OSS Bucket Policy 对 `xb-svcb/0.1.0/*` 授予匿名 `oss:GetObject`；不要授予匿名列目录、上传或删除权限。若控制台无法配置按前缀授权，则使用公开 HTTPS CDN/下载域名作为 `-BaseUrl`，不要把密钥写入安装器。

构建在线安装器时可以直接使用这个地址：

```powershell
$env:XB_OSS_BASE_URL = "https://xb-svcb.oss-cn-hongkong.aliyuncs.com/xb-svcb/0.1.0"
& .\installer\build-online.ps1 `
  -Python C:\python3.12.9\python.exe
```

构建完成后，把 `dist\online-manifest.ini` 和五套离线安装器的 EXE/BIN 文件原名上传到 `xb-svcb/0.1.0/` 前缀。先上传全部 EXE/BIN，最后上传 `online-manifest.ini`。本地分发的 `dist\XB-SVCB-Online-Setup.exe` 是引导程序，不要求放在 OSS；如果也上传，必须放在单独位置，避免用户误把它当作某个硬件栈的离线安装器。

如果 OSS 上的五套离线包和 `online-manifest.ini` 没有变化，只修改了在线安装器代码，本地可以删除大分卷后复用现有清单。此时使用 `-ReuseManifest`，脚本会严格校验现有清单但不会要求本地保留五套 EXE/BIN：

```powershell
.\installer\build-online.ps1 `
  -ReuseManifest `
  -BaseUrl "https://xb-svcb.oss-accelerate.aliyuncs.com/xb-svcb/0.1.0" `
  -Python C:\python3.12.9\python.exe
```

该模式只能用于 OSS 文件与本地 `dist\online-manifest.ini` 完全对应的情况。若重新构建或替换了任何离线 EXE/BIN，必须恢复全部五套本地文件并重新生成、最后上传清单，不能复用旧清单。

在线安装器只把几 KB 的 `online-manifest.ini` 临时放入系统临时目录。大体积的 EXE/BIN 分卷由 Windows 自带 `curl.exe` 直接下载到在线安装器所在目录下，不经过 C 盘临时目录：

```text
<在线安装器所在目录>\XB-SVCB-Downloads\0.1.0\<stack>\
```

例如在线安装器在 `D:\Downloads` 中并选择 CUDA126，下载中的文件和最终文件都位于 `D:\Downloads\XB-SVCB-Downloads\0.1.0\cu126\`。未完成文件使用 `.part` 后缀并支持续传，SHA-256 校验通过后在同一目录原地改名。该目录保存用户选择的硬件栈 EXE 和全部 `.bin` 分卷，在线安装器从这里启动离线安装器。它不会在在线安装器退出时自动删除，因此也可作为完整离线包保留。在线安装器所在目录必须可写；若从只读目录、受保护目录或压缩包内运行，需要先把在线安装器移动到普通可写文件夹。

上传后先验证匿名读取（在 OSS 权限配置完成后执行）：

```powershell
$base = "https://xb-svcb.oss-cn-hongkong.aliyuncs.com/xb-svcb/0.1.0"
Invoke-WebRequest -UseBasicParsing -Method Head "$base/online-manifest.ini"
Invoke-WebRequest -UseBasicParsing -Method Head "$base/XB-SVCB-Setup-CPU.exe"
```

两个请求都应返回 `200`，并且 EXE/BIN 下载端点必须支持 HTTP Range；若仍是 `403`，先检查 Bucket Policy/防盗链配置，不要把 AccessKey 放入脚本或安装器。

先完整构建五套离线包，再生成在线清单和引导程序：

```powershell
& .\installer\build-all-packages.ps1 `
  -Python C:\python3.12.9\python.exe -RebuildWheelhouse
& .\installer\build-online.ps1 `
  -BaseUrl "https://你的公开下载域名/xb-svcb/0.1.0"
```

也可以通过环境变量提供公开目录 URL：

```powershell
$env:XB_OSS_BASE_URL = "https://你的公开下载域名/xb-svcb/0.1.0"
& .\installer\build-online.ps1
```

把下面这些文件原名上传到该 URL 对应的同一个 OSS 目录：

```text
online-manifest.ini
XB-SVCB-Setup-CPU.exe
XB-SVCB-Setup-CPU-*.bin
XB-SVCB-Setup-ROCm10.exe
XB-SVCB-Setup-ROCm10-*.bin
XB-SVCB-Setup-DirectML.exe
XB-SVCB-Setup-DirectML-*.bin
XB-SVCB-Setup-CUDA126.exe
XB-SVCB-Setup-CUDA126-*.bin
XB-SVCB-Setup-CUDA128.exe
XB-SVCB-Setup-CUDA128-*.bin
```

对外分发本地生成的 `dist\XB-SVCB-Online-Setup.exe`，它本身不必放在同一个 OSS 目录。OSS 发布要求：

- 推荐 Bucket 保持私有，只通过 Bucket Policy 给 `xb-svcb/0.1.0/*` 前缀开放匿名只读；不要开放匿名写入、删除或列目录权限。
- 绑定公开 HTTPS 域名或使用 OSS 公网 HTTPS Endpoint，不要使用内网 Endpoint，也不要把 AccessKey、Secret 或临时签名 URL 编译进安装器。
- 文件名和目录层级必须保持不变；开启 Range 请求，EXE/BIN 使用 `application/octet-stream`，INI 使用 `text/plain; charset=utf-8`，不要启用自动压缩或内容改写。
- 若开启防盗链，必须允许空 Referer，否则 Inno Setup 下载请求会返回 403。安装器直连不需要配置 CORS；只有网页 JavaScript 跨域读取文件时才需要 CORS。
- EXE/BIN 可设置 `Cache-Control: public, max-age=31536000, immutable`；清单建议设置 `Cache-Control: no-cache`。使用 CDN 时，替换清单后要刷新对应缓存。
- `online-manifest.ini` 的 SHA-256 固定在在线安装器内，清单又固定每个 EXE/BIN 的 SHA-256。替换任何发布文件后都必须重新运行 `build-online.ps1` 并重新分发在线安装器。
- CDN/OSS 更新时应先上传五套 EXE/BIN，最后上传清单，避免新清单短暂指向尚未到位的文件。

100GB 容量建议只保留当前版本目录，并预留至少 10GB 空间。完整构建后可在上传前计算实际占用：

```powershell
$upload = @(
  Get-Item .\dist\online-manifest.ini
  Get-ChildItem .\dist\XB-SVCB-Setup-*.exe
  Get-ChildItem .\dist\XB-SVCB-Setup-*.bin
)
$bytes = ($upload | Measure-Object Length -Sum).Sum
"{0:N2} GiB / {1:N2} GB" -f ($bytes / 1GB), ($bytes / 1e9)
```

总量不超过约 90GB 时适合放入 100GB Bucket；超过后应减少发布栈或扩容，不能删除某套包的部分 BIN。旧版本目录可设置生命周期规则，在确认不再分发旧在线安装器后延迟 7 到 14 天删除。OSS 下行流量、CDN 流量和请求次数通常单独计费，不包含在 100GB 存储容量内。

只生成清单或只做轻量编译校验：

```powershell
& .\installer\build-online.ps1 -ManifestOnly
& .\installer\build-online.ps1 -ValidateOnly
```

## Wheelhouse 与分卷

`install/prepare_wheelhouse.py` 准备完整离线缓存，`installer/stage_wheelhouse.py` 在每次编译前只暂存目标栈所需 wheels。暂存目录位于 `.tmp/installer-wheelhouse`，优先硬链接、失败时复制；成功编译后自动清理。

从 0.1.0 开始，`assets/wheels/wheelhouse.json` 还保存每个硬件栈的完成档案（依赖计划签名、wheel 文件名和大小）。构建器会逐项校验档案；只有目录存在或包含少量 `.whl` 不再视为完整。下载中断、旧版本清单或手动删除 wheel 都会在打包前失败，并要求重新准备对应栈。检查单个栈可运行：

```powershell
C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py --root . --check --stack directml
```

旧缓存没有完成档案时必须重新运行 `prepare_wheelhouse.py` 或 `build-all-packages.ps1 -RebuildWheelhouse`；不能使用 `-SkipWheelhouse` 绕过检查。

从旧 py39 CPU 缓存升级后必须执行一次 `-RebuildWheelhouse`。staging 会拒绝只有 `svc/py39/cpu`、`rvc/py39/cpu` 的旧缓存，避免生成表面成功、用户机实际缺包的 CPU 安装器。

CPU 包必须同时具有 `py312/cpu`、`svc/py312/cpu`、`rvc/py312/cpu`、`pymss/py312/cpu`
和 `ddsp-legacy/py312/cpu`。目录存在但没有 `.whl` 仍会被 staging 拒绝；不要删除该校验来绕过构建。
`-RebuildWheelhouse` 是增量补齐，`-CleanWheelhouse` 才会删除整个缓存。
DirectML 包除 `py312/directml`、`ddsp/py312/directml`、`vocal/py312/directml` 和
`hub/py312/directml` 外，还必须携带 `pymss/py312/cpu` 与 `ddsp-legacy/py312/cpu` 两个 CPU
回退组。staging 会拒绝缺少任意一组的 DirectML 安装包。

Inno Setup 的每个 `.bin` 分卷固定小于 2 GB。发布时必须把某个 EXE 与所有同名前缀 `.bin` 放在同一目录，例如：

```text
XB-SVCB-Setup-CUDA128.exe
XB-SVCB-Setup-CUDA128-1.bin
XB-SVCB-Setup-CUDA128-2.bin
...
```

五套完整包会重复公共应用和模型载荷，因此发布方总存储量大于单个通用包；用户只需下载与自己硬件匹配的一套。

## 安装器语言

安装器支持简体中文、English 和日本語。启动时会按 Windows UI 语言预选，并始终显示语言选择框。Inno Setup 的简中、日语基础消息固定在 `installer/languages/`，构建不依赖开发机是否安装可选语言包；自定义页面、依赖检测、进度、校验弹窗、完成页和开始菜单名称统一由 `xb-svcb.iss` 的 `[CustomMessages]` 提供。

从 v0.1.0 开始，离线包同时携带简体中文、英文和日文发布说明：`release_notes_v0_1_0.md`、`release_notes_v0_1_0.en.md`、`release_notes_v0_1_0.ja.md`。后续版本构建前也必须准备对应的三份文件。

新增安装器文案时必须同时提供 `zhcn`、`en`、`ja` 三个同名键，并从 Pascal Script 通过 `M` / `M1` 到 `M4` 调用。`app/tests/test_installer_runtime.py` 会检查三套键完全一致、引用键均存在，且 `[Code]` 中没有重新引入面向用户的中文硬编码。

## 用户机安装与修复

安装器会：

1. 校验应用、模型、引擎源码、FFmpeg、JUCE Host 和 wheels。
2. 校验并锁定安装包内置的 CPython 3.12.x。
3. 安装或复用 `uv`，按包内固定硬件栈创建环境。
4. CUDA126/CUDA128 调用两层共享入口；CPU/ROCm 10/DirectML 调用兼容入口，其中 ROCm 10 的 SVC/RVC/Vocal 使用单独共享层。
5. 对每个解释器执行真实 Python/Torch 校验，通过后写入 `runtime.json`。
6. 全部校验通过后删除安装目录中的 `assets/wheels`，降低最终占用；失败时保留缓存便于重试。

开始菜单的“搭建/修复运行环境”调用 `setup_env.bat`。它读取 `installer_env.cmd` 中保存的 `XB_RUNTIME_LAYOUT` 与 `XB_GPU_STACK`，因此 CUDA 安装后再次修复仍会走共享环境，不会退回旧隔离布局。

安装器执行 `setup_env.bat` 时会异步启动批处理，并轮询真实进程状态；安装窗口会持续刷新，不会因为 `uv`/`pip` 安装大型 wheel 长时间没有输出而显示为无响应。进度条优先使用脚本输出的 `[XB-PROGRESS]` 标记，等待依赖安装期间只做受限心跳推进，绝不会在进程退出前报告完成。每一步的完整输出保存在安装目录的 `install_logs\install_prereqs.log` 或 `install_logs\setup_env.log`；只有批处理返回 0 后才会继续进行各模型运行时校验。

## 文件职责

- `build.ps1`：构建一套硬件专用包；默认 CUDA128。
- `build-all-packages.ps1`：顺序构建五套专用包。
- `build-online.ps1`：生成带哈希清单并编译轻量在线安装器。
- `build_online_manifest.py`：校验五套离线产物并写出 EXE/BIN 的大小与 SHA-256。
- `xb-svcb-online.iss`：在线硬件选择、下载校验与离线安装器启动流程。
- `stage_wheelhouse.py`：筛选并暂存单一硬件栈 wheels。
- `xb-svcb.iss`：Inno Setup 安装流程、校验、分卷和缓存清理。
- `xb-svcb-app.spec`：PyInstaller 应用本体。
- `../install/install_shared.py`：CUDA 两层共享运行时编排。
- `../install/install.py`：公共组件实现及 CPU/ROCm 10/DirectML/旧安装兼容入口。
- `../setup_env.bat`：自动选择共享或兼容布局的统一修复入口。
- `../setup_shared_env.bat`：开发者显式调用的共享入口。
