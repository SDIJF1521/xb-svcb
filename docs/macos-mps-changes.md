# MPS 适配改造说明：改了什么 · 为什么

本文面向开发者，记录为支持 **macOS（Apple Silicon / MPS）** 而对项目做的全部改造：每一处改了哪里、
为什么必须改、以及为什么用这种方式改。安装与使用方式见 [macOS 安装与启动](macos-mps.md)，
配方细节见 [install/runtime_profiles/mps/README.md](../install/runtime_profiles/mps/README.md)。

实测基线：Apple M4 Pro / macOS 27.0.1 / CPython 3.12.13 / torch 2.7.1（PyPI macOS arm64 wheel）。

## 0. 总体策略

| 原则 | 说明 |
| --- | --- |
| **平台能力集中到设备层** | 所有「是不是 MPS / 能不能 fp16 / ONNX 用哪个 provider」的判断只写在 `app/infrastructure/inference_device.py`，Worker 不再各自比字符串（历史上正是这种散落判断导致 MPS 被漏判）。 |
| **不改 Windows 行为** | 新增分支全部 gate 在 `backend` / `sys.platform` 上，默认值与既有代码路径保持原样；CUDA、ROCm、DirectML、CPU 的选择逻辑与输出不变。 |
| **显式选择不静默回退** | 用户显式选 `mps` 而设备不可用时**报错**，不悄悄退回 CPU（有测试固定该行为）。 |
| **精度优先正确** | MPS 上统一 fp32：MPS 的 fp16 覆盖不完整且与 CPU 数值有差异；实测 So-VITS-SVC 的 MPS 输出与 CPU **逐位一致**。 |
| **环境按依赖选 Python** | 隔离环境允许各组件用不同解释器版本（引擎 3.12；歌声增强 3.11，因为 `deepfilterlib` 没有 cp312 wheel）。 |
| **资产判据用运行时位置** | 源码签出里 `assets/models/**` 是 git-lfs 指针，是否可用以「引擎真正读取的路径」为准，而不是发布包自带位置。 |
| **可观测** | 每个 Worker 打出统一的设备/编码器日志（`SVC_DEVICE`、`F0_DEVICE`、`UVR_DEVICE`、`PYMSS_DEVICE`、`XB_SVC_ENCODER`…），便于排障与回归。 |

## 1. 设备层（核心）`app/infrastructure/inference_device.py`

MPS 支持的地基，改动最集中（+138 行）。

| 改动 | 为什么 |
| --- | --- |
| `normalize_device()` 增加 `mps:0`、`apple`、`metal` 别名 | 用户/前端可能传不同写法，统一归一化避免下游各自判断。 |
| `_mps_device()` + `XB_MPS_DISABLED` 开关 | 探测 Apple GPU；提供显式禁用手段（等价于 CPU 降级开关）。 |
| `resolve_torch_device()` 新增 `XB_FORCE_CPU` 与 `mps` 显式分支 | 需要「一键强制 CPU」的退路；显式 `mps` 时若不可用则抛错，**不静默回退**。 |
| 新增 `supports_fp16(backend)`（fp32 集合 = `cpu/mps/directml`） | 过去各 Worker 手写 `backend not in {"cpu","directml"}`，MPS 被漏掉 → SeedVC/RVC 在 Apple 上按半精度加载。收敛成唯一判据后不会再漏。 |
| `runtime_probe()` 增加 `mps` / `mlx` 探测、`backends`、`devices` 与 `preferred` 顺序（cuda → directml → mps → cpu） | 设置页与任务提交都依赖能力探测；此前只有 cuda/directml，MPS 机器会被报成 CPU。 |
| `inference_device_capabilities()`：选项循环加入 `mps`/`mlx`、补充标签、PyMSS 的 `preferred` 可为 `mlx` | 让前端拿到 `Apple MPS` / `Apple MLX` 选项；PyMSS 在 Apple 上的首选后端与其它框架不同（MLX）。 |
| 新增 `resolve_onnx_providers()` + `patch_onnx_apple_providers()` | 上游 so-vits-svc 的 ONNX 语音编码器只会请求 `CUDAExecutionProvider`/`CPUExecutionProvider`，在 macOS 上编码器会**默默留在 CPU**。这里改成 CoreML 优先、CPU 兜底，且只在 `mps`/`mlx` 下生效（Windows 不受影响）。 |
| 新增 `_mlx_available()` | MLX 没有 `torch.device` 等价物，只能探测模块；限定 `darwin` 以免影响其它平台。 |
| `runtime_device_label()` / `environment_device_label()` 增加 MPS/MLX 文案 | UI 与日志里能正确显示「Apple MPS」，而不是回落成 CPU。 |

## 2. 配置与业务层

| 文件 | 改动 | 为什么 |
| --- | --- | --- |
| `app/config.py` | 解析 `runtime.json` 清单得到各组件解释器（`_manifest_python` / `_venv_python`），并保留约定目录名回退 | macOS 采用 isolated 布局，路径不由 Windows 的 `runtimes/*` 约定决定，必须由安装器写清单、运行时读清单。 |
| `app/config.py` | 新增 `data_dir_rejection_reason()` / `usable_data_dir()`，并在 `_apply_data_dir()`、`_external_install_roots()`、`_read_data_home_file()` 使用 | 旧版 Windows 写下的 `D:\XB-SVCB\.xb_svcb` 在 POSIX 上不是绝对路径，会被当成相对路径就地建目录；这是真实发生过的脏目录问题，现在由**唯一闸门**拒绝。 |
| `app/api/bridge.py` | `_resolve_data_dir_target()` 先做跨平台路径校验 | 界面与 HTTP API 都能传任意路径字符串，不校验就会被 `mkdir -p` 出来。 |
| `app/api/http_server.py` | 所有设备的 `Literal[...]` 与 API 文档文案加入 `mps`/`mlx`（推理参数、编辑器分离、设备能力响应） | 接口层是白名单校验，不加就 422；文档文案同步说明 auto 的语义与「显式不可用会失败」。 |
| `app/domain/entities.py` | `InferenceParams.device` 注释更新 | 与接口白名单保持一致，避免后续误判可选值。 |

## 3. Worker 层（逐引擎）

| Worker | 改动 | 为什么 |
| --- | --- | --- |
| `svc_worker.py` | 新增 `_log_speech_encoder()`：读取模型 `model.speech_encoder`；`*-onnx` 编码器在 mps/mlx 下注入 CoreML provider；fairseq 类编码器缺失时抛出**带修复命令**的错误 | 上游编码器分流（fairseq / ONNX）在 macOS 上表现不同：ONNX 版默认落 CPU、fairseq 版没有 mac wheel。给用户可执行的提示比抛 ImportError 有用。 |
| `rvc_worker.py` | ① fp32 判定改用 `supports_fp16()`；② 显式 CPU 时把 `rvc.config.device`/`instead` 纠正回 `cpu` | ① rvc-python 的半精度路径在 MPS 上不完整；② **rvc-python 在 Apple 上会把任何非 CUDA 请求改写成 MPS**，会吞掉用户显式选择的 CPU（以及 CPU 降级开关）。 |
| `seedvc_worker.py` | `fp16 = fp16 and supports_fp16(resolved.backend)`；移除重复的 DirectML 特判 | 同一件事（MPS 不能跑 fp16）在多个 Worker 重复判断必然漏；统一判据后 DirectML 特判变成冗余。 |
| `seedvc_engine.py` | 新增 `_fp16_flag(device)`，提交参数时按设备决定 `--fp16 True/False` | 引擎进程在启动 Worker 前就要决定参数；`auto` 无法提前解析，因此 `auto` 保持宽松，Worker 侧再复核。 |
| `ddsp_worker.py` | `_patch_torch_load(...)` 的条件加入 `mps`（即在 MPS 上把 checkpoint 的 CUDA 存储恢复到 CPU） | 很多 checkpoint 是在 CUDA 机器上保存的，MPS 机器没有 CUDA，必须先按 CPU 恢复再把模型搬到 MPS，否则加载即失败。 |
| `uvr_worker.py` | ① 设备白名单加入 `mps`；② `_torch_backend()` 补 `mps` 分支 | ① 拒收白名单外的值；② audio-separator 在 Apple 上**自己**把 `torch_device` 设为 `mps`，旧代码把它上报为 `cpu`，选 `mps` 时还会误判失败。 |
| `pymss_worker.py` | ① `_resolve_device()`：Apple 上 `auto` 原样交给上游（优先 MLX，回退 MPS），显式 `mps` 需真实可用；② 新增 `_mlx_available()`/`_mps_available()`；③ 记录 `PYMSS_DEVICE {backend} torch={device}` 并对账显式选择；④ 第二轨匹配 `instrument` | ① PyMSS 的后端语义与 Torch 设备不同（见下）；②③避免「选了 mlx 却显示 mps」的歧义，并让显式选择可核验；④ 上游第二轨叫 `instrument`，只匹配 `instrumental` 会丢伴奏轨（此 bug 与平台无关，一并修）。 |
| `f0_worker.py` / `uvr_tool.py` | 设备帮助文本、白名单与标签加入 `mps`；UVR 的 `strict_accelerator` 纳入 `mps` | 与设备层保持同一套可选值；显式选 `mps` 时也走「严格校验、不静默回退」。 |

> **`mlx` 的语义**（容易误解，故记录）：PyMSS 把 `mlx` 实现为「**MPS 张量设备 + MLX 模型后端**」
> （`inference_params` 为 `mps_model_backend=mlx_full`、`compute_dtype=float16`），并没有独立的
> `mlx` torch 设备；显式选 `mps` 才是纯 Torch MPS（fp32）。因此结果里同时记录 `device`（后端语义）
> 与 `torch_device`（真实设备）。

## 4. 安装器层

### 4.1 `install/install.py`（共用入口）

| 改动 | 为什么 |
| --- | --- |
| 新增 `--mps` 与 `--svc-encoder {onnx,fairseq}`，并在 `main()` 早期分派到 `install_macos.py` | 让 macOS 复用同一入口与 `--only/--skip` 习惯；同时显式校验互斥（非 darwin、与 CPU/CUDA/ROCm/DirectML、`--consolidated/--core-*/--preflight-only` 冲突直接报错退出）。 |
| 新增 `_is_lfs_pointer()`，`copy_bundled()` 遇到指针**拒绝部署并返回 False**；目录型资源改为「全部子项成功才算成功」 | 源码签出里 `assets/models/**` 是约 130 字节的指针。部署指针会造成「安装成功但引擎加载失败」的假象；目录型资源只报整体成功会掩盖个别缺件。 |
| `step_models(*, require_fcpe=False)`；新增 `fetch_fcpe_model()` | 发布包必须离线自带 FCPE，但源码签出拿不到它；非严格模式下改为联网获取，拿不到就降级（应用会自动回退 CREPE），不阻断安装。 |
| 新增 `_fetch_deepfilter_bundle()`，`_prepare_vocal_deepfilter_model()` 在自带权重不可用时调用它 | 这里原本直接 `raise`（发布包永远自带，所以一直没暴露）；源码签出必须能联网补齐。 |

### 4.2 `install/install_macos.py`（新增，macOS 专用配方）

`run_macos_install()` 负责 12 个步骤（`app/plugins/web/uvr/pymss/svc/rvc/seedvc/ddsp/vocal/hub/models`），
每个组件一个隔离环境，最后写 `runtime.json` 路由。

| 关键设计 | 为什么 |
| --- | --- |
| 不生成平台锁文件、不启用共享运行时 | Windows 的 `uv pip compile --python-platform windows` 与离线 wheelhouse 只覆盖 win/linux wheel；macOS 直接解析 PyPI 上带 MPS 的 arm64 wheel。 |
| 剔除/覆盖上游 requirements 中的 torch 与旧钉死 | 上游钉死（如 `fairseq==0.12.2`、SeedVC 的 `requirements-mac.txt` 会拉 CUDA 版 torch）在 Apple Silicon + CPython 3.12 上不可安装；torch/torchaudio 由配方统一为 2.7.1。 |
| fairseq 一律用 `uv pip install --no-cache` 单独安装 | uv 的共享 sdist 缓存目录会让 `bdist_wheel` 的清理触发沙箱批量删除保护，报出误导性的 `Failed to build fairseq-fixed`；跳过缓存即编译成功。同时**不能**经 requirements 注入，否则会绕过 `--no-cache`。 |
| 歌声增强环境固定 Python 3.11 | `deepfilterlib 0.5.6` 只发布 cp38/39/310/311 wheel，3.12 下只能源码编译（需要 Rust/maturin）；增强环境本身隔离，用 3.11 即可直接吃官方 arm64 wheel。 |
| UVR 环境：先让 `audio-separator[cpu]` 解析依赖，再回落已验证的 torch 组合，并补 `audioread`/`filetype`、回落 `librosa<1.0`、清理失效的 `torchvision` | 依次对应四个真实故障：torch/torchaudio 版本错配、`uvr_lib_v5` 未声明的 import、`librosa 1.0` 移除 `get_duration(filename=)`、以及回落 torch 后 `torchvision::nms` 失效。 |
| 每个环境都跑 `_verify_mps()`（`torch` 版本 + `torch.backends.mps.is_available()`） | 安装成功不等于能推理；把设备可用性作为安装验收条件。 |

### 4.3 `install/fetch_assets.py`（新增，资产供给与体检）

`problem_rows` / `runtime_report` / `materialize_engine_equivalents` / `ensure_asset` / `fetch_missing`，
CLI 支持 `--fetch`、`--only`、`--uvr-python`、`--list-missing`、`--strict`。

| 关键设计 | 为什么 |
| --- | --- |
| 以清单 `assets/models/model-manifest.json` 为准做 `min_bytes`/`sha256` 校验，并识别 LFS 指针 | 让「缺件」可判定、可复现，而不是靠打开文件猜。 |
| 判据用**运行时位置**（`runtime` 字段），而不是发布包自带位置（`source`） | 源码签出拿不到发布包里的某些大文件（如 ContentVec），但引擎侧的官方副本已能推理；只看自带位置会永远报错。 |
| 能用引擎目录里的同源权重回填自带位置（`materialize_engine_equivalents`） | 避免为了「好看」重复下载数百 MB。 |
| 按引擎收敛下载范围（`--only uvr seedvc ddsp`） | 只装 SVC 的用户不该被迫下载 UVR/SeedVC 的权重。 |

### 4.4 其他

- `install/runtime_profiles/mps/README.md`（新增）：固定组合、与 Windows 配方的有意差异、已验证结论（fairseq 可编译、MPS 算子覆盖、pyworld 无 mac wheel）与已知限制。
- `.gitignore`：忽略 `data_home.json`（本机路径文件）与单字母盘符开头的目录，避免脏目录再次入库。

## 5. 前端

| 文件 | 改动 | 为什么 |
| --- | --- | --- |
| `web/src/api/types.ts` | `InferenceDeviceBackend` 增加 `mps`/`mlx`；`EditorSeparationOptions.device` 同步 | 与后端 `Literal` 对齐，否则类型检查与请求都会被拒。 |
| `web/src/stores/system.ts` | `backendLabels` 增加 `Apple MPS` / `Apple MLX` | 设置页显示真实后端名，而不是裸值。 |

## 6. 测试

| 文件 | 覆盖内容 |
| --- | --- |
| `app/tests/test_inference_devices.py`（+116 行） | `test_explicit_mps_uses_apple_gpu_backend`、`test_explicit_mps_never_silently_falls_back_to_cpu`、`test_auto_prefers_mps_when_apple_gpu_is_the_only_accelerator`、`test_mps_disabled_flag_blocks_the_backend`、`test_runtime_probe_reports_apple_mps` |
| `app/tests/test_macos_recipe.py`（新增，32 用例） | 平台分支（非 darwin 拒绝 `--mps`、与 Windows 栈互斥、默认 ONNX 编码器）、LFS 指针识别与 `copy_bundled` 拒绝、清单体检与 `ensure_asset`、PyMSS 设备解析（auto→Apple、显式 mps 校验、仍拒绝 DirectML）、SVC 编码器日志与 fairseq 缺失提示、UVR 设备上报 mps、PyMSS 伴奏轨命名、vocal 环境用 3.11、DeepFilterNet3/FCPE 回退下载、数据目录跨平台闸门 |

## 7. 验证矩阵（实测）

| 引擎 | 设备 | 结果 |
| --- | --- | --- |
| So-VITS-SVC 4.1 | `SVC_DEVICE mps` | 出音正常；与 CPU 输出**逐位一致**（相关 1.000000，最大差 0.0000） |
| RVC | `RVC_DEVICE mps` | 设备层验证通过（`is_half=False`） |
| SeedVC | mps | 出音正常 |
| DDSP-SVC 6.3 | mps | 出音正常 |
| UVR 分离 | audio-separator 自选 mps | 8.8s / 8s 音频；双轨相加与输入相关 1.0000 |
| PyMSS 分离 | `PYMSS_DEVICE mlx torch=mps` | 10.9s / 8s；双轨齐全，相关 1.0000 |
| F0 提取（RMVPE/FCPE） | `F0_DEVICE mps` | 两条曲线相关 0.897 |
| 歌声增强（DeepFilterNet3） | CPU | 18s / 8s（上游无 MPS 后端） |
| 整体回归 | — | `app/tests` 634 passed；与改造前基线逐条比对**无新增失败**（基线中另有 15 个既有失败，与本次改造无关） |

## 8. 有意不做的部分

- **Windows 专有功能**保持原状、在 macOS 上降级或不可用：系统音频实时变声（WASAPI 回环 / VB-CABLE）、
  C++ JUCE VST3 宿主、单实例锁与窗口主题（DWM）、剪贴板复制文件、随包 ffmpeg（macOS 用系统 ffmpeg）。
- **macOS 打包/安装器**（.app / .dmg / PyInstaller）不在本次范围，当前提供源码安装路径。
- **不追求吞吐**：目标是「可用且正确」，性能优化（taa、批处理、fp16 例外清单）留待后续。

## 9. 复现与自检

~~~bash
# 安装（可分组）
python3.12 install/install.py --mps
python3.12 install/install.py --mps --only app plugins web models

# 资产体检（应无输出）
python3.12 install/fetch_assets.py --list-missing

# 设备能力自检：启动后查看数据目录中的 inference_devices.json
app/.venv/bin/python app/main.py

# 回归
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs
~~~

## 10. 改动文件清单

**新增**

- `install/install_macos.py`：macOS 配方入口（12 步）
- `install/fetch_assets.py`：资产供给与体检
- `install/runtime_profiles/mps/README.md`：MPS 配方说明
- `docs/macos-mps.md`：用户向安装/启动文档（本文是开发者向的改造说明）
- `app/tests/test_macos_recipe.py`：平台分支与供给回归

**修改（app）**

- `app/infrastructure/`：`inference_device.py`（核心）、`svc_worker.py`、`rvc_worker.py`、`seedvc_worker.py`、
  `seedvc_engine.py`、`ddsp_worker.py`、`uvr_worker.py`、`pymss_worker.py`、`f0_worker.py`、`uvr_tool.py`
- `app/config.py`、`app/api/http_server.py`、`app/api/bridge.py`、`app/domain/entities.py`

**修改（其它）**

- `install/install.py`（`--mps` 分派、LFS 指针拦截、FCPE/DeepFilterNet 回退）
- `web/src/api/types.ts`、`web/src/stores/system.ts`
- `README.md`、`docs/README.md`、`docs/getting-started.md`、`.gitignore`
- `app/tests/test_inference_devices.py`（新增 MPS 用例）
- 资产回填：`assets/models/**` 中原本为 git-lfs 指针的文件（真实权重、`config.json` 等）
