# macOS（Apple Silicon / MPS）安装与启动

在 Apple Silicon Mac 上从源码搭建并启动 XB-SVCB。推理走 PyTorch **MPS**（Apple GPU），
PyMSS 分离可额外使用 **MLX**，与 Windows 版本的引擎功能面对齐。

本文档只描述 macOS 路径；Windows 安装包和共享运行时见[源码安装与启动](getting-started.md)与
[共享运行时与兼容布局](runtime-consolidation.md)。

实测基线（本文命令与数据均来自该环境）：

| 项目 | 值 |
| --- | --- |
| 机型 / 系统 | Apple M4 Pro / macOS 27.0.1（arm64） |
| Python | 3.12.13（Homebrew `python@3.12`）；增强环境单独用 3.11 |
| Node | v24.15.0 |
| Torch | torch 2.7.1 + torchaudio 2.7.1（PyPI macOS arm64 wheel，自带 MPS） |
| onnxruntime | 1.31.0，提供 `CoreMLExecutionProvider` / `AzureExecutionProvider` / `CPUExecutionProvider` |
| 设备探测结果 | `backends: ["cpu", "mps", "mlx"]`，`preferred: "mps"` |

> 说明：Apple 芯片以外的 Mac（Intel）没有 MPS 后端，**不在支持范围内**。

## 1. 前置条件

~~~bash
# Homebrew 依赖（未安装 Homebrew 请先装：https://brew.sh）
brew install python@3.12 node ffmpeg uv

python3.12 -V     # 需要 3.12.x
node -v           # 需要 >=22.12.0（web/package.json 的 engines 要求）
ffmpeg -version   # macOS 必须用系统 ffmpeg
~~~

三点必须注意：

1. **Python 必须是 3.12.x**：引擎环境固定 3.12，`app/pyproject.toml` 要求 `>=3.12,<3.13`。
   （例外：AI 歌声增强环境使用 3.11，由 uv 自动准备受管解释器，见第 3 节。）
2. **必须安装系统 ffmpeg**：程序内置的 ffmpeg 是 Windows 版二进制，macOS 上不可用。
3. **不需要 Rust / CUDA 工具链**：默认走 ONNX 语音编码器；只有显式选择
   `--svc-encoder fairseq` 时才需要本地编译 fairseq（安装器已处理编译方式，见第 7 节）。

## 2. 安装运行环境

在项目根目录执行一键安装：

~~~bash
python3.12 install/install.py --mps
~~~

默认按顺序执行 12 个步骤，产物如下：

| 步骤 | 产物 | 说明 |
| --- | --- | --- |
| `app` | `app/.venv` | 主程序环境（pywebview + 业务核心） |
| `plugins` | `.venv-plugins` | Python 插件运行环境 |
| `web` | `web/dist` | 前端构建产物（生产模式必需） |
| `uvr` | `.venv-uvr` | UVR 人声分离（audio-separator 0.44.2） |
| `pymss` | `.venv-pymss` | PyMSS 分离（含 `mlx-metal`，装不上时自动回落 Torch MPS） |
| `svc` | `.venv-svc` | So-VITS-SVC 4.1 |
| `rvc` | `.venv-rvc` | RVC（rvc-python） |
| `seedvc` | `.venv-seedvc` | Seed-VC |
| `ddsp` | `.venv-ddsp` | DDSP-SVC 6.3（Transformers HuBERT，无 fairseq 依赖） |
| `vocal` | `.venv-vocal` | AI 歌声增强（DeepFilterNet3 + Pedalboard，Python **3.11**） |
| `hub` | `models/` | 模型站与下载目录准备 |
| `models` | 引擎目录下的底模 | 底模供给 + git-lfs 指针校验 |

隔离环境与解释器版本会写入 `runtime.json`，主程序据此路由 Worker：

~~~json
{
  "version": 1,
  "stack": "mps",
  "layout": "isolated",
  "python": {
    "plugins": ".venv-plugins/bin/python",
    "seedvc": ".venv-seedvc/bin/python",
    "ddsp": ".venv-ddsp/bin/python",
    "rvc": ".venv-rvc/bin/python",
    "svc": ".venv-svc/bin/python",
    "pymss": ".venv-pymss/bin/python",
    "uvr": ".venv-uvr/bin/python",
    "vocal": ".venv-vocal/bin/python"
  }
}
~~~

### 分步安装与常用参数

~~~bash
# 只装需要的一部分（可多选）
python3.12 install/install.py --mps --only app plugins web models
python3.12 install/install.py --mps --only svc rvc
python3.12 install/install.py --mps --only uvr pymss
python3.12 install/install.py --mps --only vocal          # 可选：AI 歌声增强

# 跳过某一步
python3.12 install/install.py --mps --skip-web

# So-VITS-SVC 语音编码器：onnx（默认，无需编译）或 fairseq（源码编译）
python3.12 install/install.py --mps --only svc --svc-encoder fairseq

# 安装到其它目录 / 查看全部参数
python3.12 install/install.py --mps --root /path/to/install
python3.12 install/install.py --mps --help
~~~

某个步骤失败不影响已完成的部分，按日志提示单独重试即可：

~~~bash
python3.12 install/install.py --mps --only vocal
~~~

## 3. 底模与权重供给

源码签出里 `assets/models/**` 存的是 **git-lfs 指针**（约 130 字节）。安装器与供给器会
拒绝指针并改为联网获取，**判据是「引擎运行时真正读取的位置」**，不是发布包自带位置。

~~~bash
# 补齐缺失资产（按引擎收敛下载范围）
python3.12 install/fetch_assets.py --fetch --only uvr seedvc ddsp \
  --uvr-python .venv-uvr/bin/python

# 只体检、不下载
python3.12 install/fetch_assets.py --list-missing

# 指定镜像
XB_HF_MIRROR=https://hf-mirror.com XB_GH_MIRROR=https://ghfast.top \
  python3.12 install/fetch_assets.py --fetch
~~~

各引擎运行时读取位置：

| 引擎 | 权重落点 | 说明 |
| --- | --- | --- |
| So-VITS-SVC | `engines/so-vits-svc/pretrain/` | ContentVec(181MB)、RMVPE(352MB)、NSF-HiFiGAN(55MB)、FCPE(69MB) |
| DDSP-SVC | `engines/ddsp-svc/pretrain/` | ContentVec(378MB)、RMVPE(368MB)、NSF-HiFiGAN(57MB) |
| SeedVC | `assets/models/seedvc/` + `engines/seed-vc/checkpoints/` | whisper-small(967MB)、bigvgan(489MB)、campplus(28MB)、`seedvc_v2_pruned.pth`(420MB) |
| UVR | `models/uvr/` | 5_HP-Karaoke(127MB)、UVR-DeEcho-DeReverb(224MB)、3 个元数据 JSON |
| PyMSS | `models/pymss/` | 在「模型站」按需下载，默认 `bs_roformer_voc_hyperacev2`(289MB) |
| 歌声增强 | `models/vocal-enhancement/` | DeepFilterNet3 权重 + `runtime.ready` 标记 |

> `assets/models/**` 里的指针文件**不用处理**：它们是发布包自带位置的占位，引擎不会读它。

**两个可选件**（缺失不影响主流程，按需补齐）：

1. **AI 歌声增强**（DeepFilterNet3 + Pedalboard）：

   ~~~bash
   python3.12 install/install.py --mps --only vocal
   ~~~

   该步骤会创建 `.venv-vocal`（Python 3.11）、获取官方 DeepFilterNet3 权重并写入
   `models/vocal-enhancement/runtime.ready`。

2. **FCPE 高音域自适应**：非严格模式下安装器会自动联网获取 `pretrain/fcpe.pt`；
   缺失时应用把高音域自适应回退到 CREPE，功能仍可用。

## 4. 启动应用

> **启动命令必须在项目根目录执行**：命令里的 `app/.venv/bin/python` 与 `app/main.py` 都是相对路径。
> 若要在其它目录启动，请使用绝对路径：
> `/你的路径/xb-svcb/app/.venv/bin/python /你的路径/xb-svcb/app/main.py`。
> 数据目录与 `web/dist` 都是按 `app/config.py` 所在位置解析成绝对路径的，所以从别处启动不会写错数据目录，
> 只是相对命令不可用。

### 生产模式（加载 `web/dist`）

~~~bash
cd /path/to/xb-svcb                                   # ① 进入项目根目录
python3.12 install/install.py --mps --only web        # ② 若 web/dist 不存在，先构建前端
app/.venv/bin/python app/main.py                      # ③ 启动
~~~

### 开发模式（Vite 热更新，需要两个终端）

两个终端同样都在**项目根目录**执行：

~~~bash
# 终端 1：前端
cd web
npm install
npm run dev

# 终端 2：后端（回到项目根目录）
cd /path/to/xb-svcb
app/.venv/bin/python app/main.py --dev
~~~

开发模式默认连接 `http://localhost:5173`，可用 `XB_DEV_URL` 指定其它地址。

### 退出与进程清理

关闭窗口或按 <code>Ctrl+C</code> 退出；退出前建议等当前任务结束，避免中断推理。
排查残留进程（例如上次非正常退出）：

~~~bash
pgrep -fl "app/main.py"        # 列出仍在运行的实例
pkill -f "app/main.py"         # 结束它们
~~~

应用日志与数据都保存在用户数据目录（默认 `<项目根>/.xb_svcb`，可用 `XB_DATA_DIR` 修改）；
单次任务的日志在作品库里查看 `run.log`。

### 常用环境变量

| 变量 | 用途 |
| --- | --- |
| `XB_DATA_DIR` | 自定义用户数据目录（默认 `.xb_svcb`） |
| `XB_DEV` / `XB_DEV_URL` | 开发模式开关与前端地址 |
| `XB_PYPI_MIRROR` | Python 包镜像 |
| `XB_HF_MIRROR` / `HF_ENDPOINT` | Hugging Face 镜像 |
| `XB_GH_MIRROR` | GitHub 资源镜像 |
| `XB_APP_ROOT` | 指定安装根目录（引擎、隔离环境与模型的查找起点） |

> 数据目录指针文件 `data_home.json` 只记录**本机**路径，不随仓库分发。如果它记录了其它平台的路径
> （例如 `D:\XB-SVCB\.xb_svcb`），应用会忽略该条目、回退到默认的 `.xb_svcb`，不会在工作目录里
> 生成同名目录。

启动成功后，`<数据目录>/inference_devices.json` 会记录设备探测结果，可用于确认 MPS 已就位：

~~~json
{
  "ok": true,
  "torch_version": "2.7.1",
  "backends": ["cpu", "mps", "mlx"],
  "devices": [
    { "backend": "mps", "name": "Apple MPS", "index": 0 },
    { "backend": "mlx", "name": "Apple MLX", "index": 0 }
  ],
  "preferred": "mps"
}
~~~

## 5. 设备与精度

界面里的设备选项为 **自动 / Apple MPS / Apple MLX / CPU**：

- **自动**：macOS 上解析为 `mps`（PyMSS 的自动模式会交给上游优先 MLX）。
- **PyMSS 的 `mlx`**：等价于「MPS 张量设备 + MLX 模型后端」
  （`inference_params` 为 `mps_model_backend=mlx_full`、`mps_model_compute_dtype=float16`）；
  显式选 `mps` 才是纯 Torch MPS（fp32）。
- **精度策略**：MPS 上统一使用 fp32（`supports_fp16()` 对 mps/mlx 返回否），SeedVC 在
  非 CPU 设备下也会关闭 fp16；只有 PyMSS 的 MLX 后端使用 fp16。

各引擎实测结果（素材为 8 秒 44.1kHz 人声）：

| 引擎 | 设备 | 实测 |
| --- | --- | --- |
| So-VITS-SVC | `SVC_DEVICE mps` | 出音正常，7.6s；与 CPU 输出**逐位一致**（相关系数 1.000000，最大差 0.0000） |
| RVC | `RVC_DEVICE mps` | 设备层验证通过（`is_half=False`）；模型架构需为 RVC 权重，见下方提示 |
| SeedVC | mps | 出音正常 |
| DDSP-SVC | mps | 出音正常 |
| UVR 分离 | audio-separator 自选 mps | 8.8s；人声 + 伴奏，双轨相加与输入相关系数 1.0000 |
| PyMSS 分离 | `PYMSS_DEVICE mlx torch=mps` | 10.9s；双轨齐全，相关系数 1.0000 |
| F0 提取 | `F0_DEVICE mps` | RMVPE / FCPE 均可，fcpe 与 rmvpe 曲线相关系数 0.897 |
| AI 歌声增强 | CPU（上游无 MPS 后端） | 18s；DeepFilterNet3 仅支持 CPU |

> **导入模型时的架构提示**：So-VITS-SVC 的 `G_*.pth` + `config.json` 必须按
> **So-VITS-SVC** 框架导入；RVC 引擎只接受 RVC 权重。判断依据：`config.json` 的
> `model.speech_encoder`（`vec256l9` / `vec768l12`）与权重键布局（so-vits 含
> `pre` / `enc_q` / `f0_decoder`，RVC 含 `emb_phone`）。

## 6. 与 Windows 版本的能力差异

macOS 采用隔离环境布局，绝大多数功能可用，以下功能依赖 Windows 专有接口：

| 功能 | macOS 状态 |
| --- | --- |
| So-VITS-SVC / RVC / SeedVC / DDSP-SVC 推理 | 可用（MPS） |
| UVR / PyMSS 分离、去混响、人声净化 | 可用 |
| AI 歌声增强（DeepFilterNet3） | 可用（CPU） |
| 音频编辑器、时间轴混唱、作品库、模型站、FastAPI | 可用 |
| 系统音频实时变声（WASAPI 回环 / VB-CABLE） | 不可用，需 Windows |
| 单实例锁、窗口主题（DWM） | 降级为 no-op |
| C++ JUCE VST3 Host、剪贴板复制文件 | 不可用（仅有 Windows 产物） |
| 内置 ffmpeg | 不可用，改用系统 `ffmpeg` |
| `run.bat` / `setup_env.bat` / Inno 安装包 | Windows 专用，macOS 用本文命令 |

## 7. 排障速查

以下都是 macOS 实测遇到过的报错与处理方式：

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `Failed to build fairseq-fixed` | uv 的共享 sdist 缓存目录触发批量删除保护，`bdist_wheel` 清理失败 | 安装器已改为 `uv pip install --no-cache`，手动安装时同样加 `--no-cache` |
| `ModuleNotFoundError: No module named 'audioread'` | audio-separator 的 `uvr_lib_v5` 会无条件导入，但未声明该依赖 | 已由 `--only uvr` 自动安装；手动补 `uv pip install audioread filetype` |
| `get_duration() got an unexpected keyword argument 'filename'` | 解析器拉到 librosa 1.0，移除了该参数 | 已由配方回落 `librosa<1.0`；手动补 `uv pip install "librosa<1.0"` |
| `Failed to build deepfilterlib`（maturin / Rust 缺失） | `deepfilterlib 0.5.6` 没有 cp312 wheel | 增强环境固定用 Python 3.11（配方已内置） |
| `安装包缺少 DeepFilterNet3 自带模型` | 自带权重是 git-lfs 指针 | 安装器已回退到官方发布包下载；有网重试 `--only vocal` |
| 生产模式提示「未找到前端构建产物」 | `web/dist/index.html` 不存在 | `python3.12 install/install.py --mps --only web`，或用 `--dev` |
| 分离日志显示 `UVR_DEVICE cpu` | 旧版本设备上报漏判 mps | 已修复；确认 `uvr_worker.py` 含 mps 分支 |
| PyMSS 分离只有人声没有伴奏 | 上游第二轨命名为 `instrument` | 已修复匹配；确认 `pymss_worker.py` 同时匹配 `instrument` |
| 工作目录出现 `D:\XB-SVCB\.xb_svcb` | `data_home.json` 里记录了 Windows 数据目录，旧版本把它当相对路径处理 | 已修：跨平台路径在「指针解析 / 数据目录对话框 / HTTP API」三处都被拒绝并保留原数据目录，该空目录可直接删除；`data_home.json` 也不再随仓库分发 |
| 引擎全部显示未安装 | Python 版本不符或步骤未执行 | 用 3.12.x 重跑 `--only ...`，并检查 `runtime.json` |

排查任务的完整日志：作品库中打开失败任务，先看 `run.log` 与对应 Worker 输出；
启动链路见[启动与推理链路](startup-chain.md)。

> 💡 关于 `D:\XB-SVCB\.xb_svcb` 这类目录：反斜杠在 macOS / Linux 上只是**普通字符**，
> 整条 `D:\XB-SVCB\.xb_svcb` 就是**一个目录名**（不会嵌套）。删除时要带完整名字：
> `rm -rf 'D:\XB-SVCB\.xb_svcb'`；写成 `rm -rf 'D:\XB-SVCB'` 是另一个路径，不会删掉它。

## 8. 测试与更新

~~~bash
# 后端测试
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs

# 前端检查与测试
cd web && npm run type-check && npm run test:unit -- --run && npm run build

# 资产体检（应无输出）
python3.12 install/fetch_assets.py --list-missing
~~~

更新代码后建议按需重跑对应步骤（例如只改了引擎代码时 `--only svc`），
新增/缺失的底模用第 3 节的 `fetch_assets.py` 补齐。

## 延伸阅读

- [MPS 适配改造说明](macos-mps-changes.md)：为支持 Apple Silicon / MPS 具体改了哪些文件、每处为什么改、以及验证矩阵（开发者向）。
- [MPS 运行时配方](../install/runtime_profiles/mps/README.md)：固定依赖组合、与 Windows 配方的有意差异、已知限制。
