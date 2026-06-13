# XB-SVCB · AI 翻唱工具

一个开箱即用的桌面 AI 翻唱应用：导入歌曲 → 人声分离 → 去混响 → so-vits-svc 歌声转换 → 自动合并伴奏，生成完整翻唱。

前端 Vue 3 + Element Plus，桌面壳 pywebview，重型 AI 任务在隔离的 Python 子环境中以子进程运行，互不污染。

应用本体打包为单个 **`XB-SVCB.exe`**（由 PyInstaller 生成，内置前端与 worker 脚本，起界面无需 Python/Node）；只有「人声分离 / so-vits-svc 推理」这类重型 AI 能力需要在安装目录旁单独搭建隔离环境（由安装器完成，全程无 PowerShell）。

---

## 一、环境要求

请先自行安装以下基础软件（安装器会检测并提示缺失项）：

| 软件 | 用途 | 说明 |
| --- | --- | --- |
| **Python 3.10+** | 运行安装器与主程序 | 安装时勾选 *Add to PATH* |
| Git（可选） | 获取 so-vits-svc 仓库 | 没有也行：安装器会自动改用下载 ZIP |
| **Node.js LTS**（含 npm） | 构建前端 | 仅「从源码安装」需要；用 setup.exe 的最终用户无需 |
| **ffmpeg** | 音频转码 / 混音 | 需在 PATH 中可用 |
| NVIDIA 显卡 + 驱动（可选） | GPU 加速 | 有则自动装 CUDA 版，无则用 CPU |

> 安装器使用 [uv](https://github.com/astral-sh/uv) 管理虚拟环境（缺失会自动安装），并能自动获取 Python 3.10 用于引擎环境。

---

## 二、安装方式

### 方式 A：图形安装器 `setup.exe`（推荐给最终用户）

下载 `XB-SVCB-Setup.exe`，双击运行：

1. 在「选择安装位置」页**自定义安装路径**（默认 `%LOCALAPPDATA%\Programs\XB-SVCB`，无需管理员权限）。应用 exe 与之后搭建的全部依赖（`engines/`、`.venv-svc`、`.venv-uvr`、`models/`）都会装进**这个目录**；
2. 安装器会释放打包好的应用本体 **`XB-SVCB.exe`**（前端与 worker 已内置，起界面无需 Python/Node）；
3. 勾选「安装后立即搭建运行环境」即可联网创建 AI 子环境、下载依赖与模型到所选目录（由 `setup_env.bat` 调 `install.py --root <安装目录>`，无 PowerShell）；
4. 完成后通过桌面/开始菜单的 **XB-SVCB** 快捷方式启动。

> 该安装器由开发者用 PyInstaller + Inno Setup 构建（见文末「构建 setup.exe」）。**应用界面本身无需任何依赖即可打开**；只有「搭建运行环境」这一步需要 **Python 3.10+** 与 **ffmpeg**（**Git 可选**，没有会自动改用下载 ZIP 获取 so-vits-svc）。安装器会在开始时检测并提示缺失项。若某步失败，可从开始菜单的「搭建/修复运行环境」重试。

### 方式 B：脚本搭建（开发者 / 高级用户，无 PowerShell）

环境搭建由 `install/install.py` 负责，入口是纯批处理 `setup_env.bat`（内部直接调用 Python，全程不涉及 PowerShell）。在项目根目录运行：

```bat
setup_env.bat
```

安装器会自动完成（全部落在项目目录内，便于卸载）：

1. `app/.venv` —— 主程序环境（pywebview）
2. `web/dist` —— 前端构建产物
3. `.venv-uvr` —— 人声分离环境（audio-separator）
4. `engines/so-vits-svc` + `.venv-svc` —— so-vits-svc 4.1 仓库与推理环境
5. `models/` 与 `engines/so-vits-svc/pretrain/` —— UVR 模型与底模

`setup_env.bat` 默认带 `--skip-web`（前端已预构建）。需要更细的控制时，直接调用 `install.py`：

```bat
python install\install.py --cpu          rem 强制 CPU 版
python install\install.py --gpu          rem 强制 CUDA 版
python install\install.py --only svc     rem 只重跑某一步：app / web / uvr / svc / models
python install\install.py --only models  rem 只重下底模与 UVR 模型
python install\install.py --skip-svc     rem 跳过 so-vits-svc（仅装壳 + 分离 + 前端）
```

> 首次安装需要下载较多依赖与模型（CUDA 版 torch、底模等，合计数 GB），请保持网络通畅、耐心等待。每一步都是**幂等**的：失败后重跑只会补齐缺失部分。

**国内下载加速 / 离线镜像**：底模默认走 `hf-mirror.com` 镜像，GitHub 资源带 ghproxy 回退。如某镜像仍不通，可用环境变量覆盖后重跑 `python install\install.py --only models`：

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_GH_MIRROR=https://ghfast.top
```

跨平台 / 手动调用：

```bash
python install/install.py            # 全自动
python install/install.py --cpu
python install/install.py --only models
```

---

## 三、启动

```bat
run.bat
```

或手动：

```bat
app\.venv\Scripts\python.exe app\main.py
```

---

## 四、使用流程

1. **模型管理**：导入你训练好的 so-vits-svc 角色模型（主模型 `G_*.pth` + `config.json`，可选浅扩散 `model_*.pt` + `diffusion.yaml`）。
2. **新建翻唱**：选择歌曲与角色模型，设置变调 / F0 预测器 / 推理设备（GPU/CPU）等。
3. **处理流水线**：
   - 人声分离（`5_HP-Karaoke-UVR`）→ 得到人声与伴奏；
   - 去混响（`UVR-DeEcho-DeReverb`）→ 得到干净干声；
   - F0 提取（rmvpe 等）→ 真实基频曲线 + 人声有效性校验；
   - SVC 推理 → 转换音色；
   - ffmpeg 合并人声 + 伴奏 → 成品。
4. **作品库**：试听 / 导出成品，也可单独试听分离出的**背景音乐**与**干声**；失败任务可一键打开日志。

---

## 五、目录结构

```
翻唱工具/
├─ app/                  # 主程序（pywebview + 业务分层）
│  ├─ api/               #   暴露给前端的桥接层
│  ├─ application/       #   编排：转换流水线、作品/模型服务
│  ├─ infrastructure/    #   ffmpeg / uvr / svc / f0 worker 等
│  ├─ config.py          #   全部路径配置（项目相对 + 环境变量覆盖）
│  └─ main.py
├─ web/                  # 前端（Vue 3 + Vite + Element Plus）
├─ installer/
│  ├─ xb-svcb-app.spec   #   PyInstaller 规格（打 XB-SVCB.exe）
│  ├─ xb-svcb.iss        #   Inno Setup 脚本（打 setup.exe）
│  └─ build.ps1          #   一键构建（前端 + PyInstaller + ISCC，仅开发者用）
├─ install/install.py    # 在用户机搭建 AI 子环境 / 下载模型
├─ setup_env.bat         # 搭建/修复运行环境入口（纯 batch 调 Python，无 PS）
├─ run.bat               # 源码运行启动脚本（开发用；安装版用 XB-SVCB.exe）
├─ engines/              # 安装器克隆的 so-vits-svc（git 忽略）
└─ models/               # 安装器下载的 UVR 模型（git 忽略）
```

---

## 六、自定义路径（环境变量覆盖）

无需改代码，用环境变量即可指向自有的引擎 / 模型（优先级高于项目内默认）：

| 变量 | 含义 |
| --- | --- |
| `XB_SOVITS_REPO` | so-vits-svc 仓库根目录 |
| `XB_SVC_PYTHON` | 运行 SVC 推理的 Python 解释器 |
| `XB_UVR_PYTHON` | 运行 audio-separator 的 Python 解释器 |
| `XB_UVR_MODEL_DIR` | UVR 模型目录 |
| `XB_UVR_SEP_MODEL` | 分离模型文件名（默认 `5_HP-Karaoke-UVR.pth`） |
| `XB_UVR_DEREVERB_MODEL` | 去混响模型文件名（默认 `UVR-DeEcho-DeReverb.pth`） |

---

## 七、底模来源（自带优先，缺失才联网下载）

模型获取采用 **「自带优先」** 策略：若项目 `assets/models/` 目录内已随安装包附带对应文件，
安装时**直接本地复制**（瞬间完成、不联网）；只有缺失的项才回退到下表的镜像下载。

| 模型 | 用途 | 自带去向 / 下载来源 |
| --- | --- | --- |
| `checkpoint_best_legacy_500.pt` | ContentVec 语音编码器（so-vits-svc 4.1 默认 `vec768l12`） | `assets/models/pretrain/` → `engines/so-vits-svc/pretrain/`；缺失则 HuggingFace |
| `nsf_hifigan/` | NSF-HiFiGAN 声码器 / 浅扩散 | 同上；缺失则 openvpi/vocoders Releases |
| `rmvpe.pt` | RMVPE F0 预测器 | 同上；缺失则 yxlllc/RMVPE Releases |
| `fcpe.pt`（可选） | FCPE F0 预测器 | 仅在自带目录存在时复制 |
| `5_HP-Karaoke-UVR.pth` / `UVR-DeEcho-DeReverb.pth` | 人声分离 / 去混响 | `assets/models/uvr/` → `models/uvr/`；缺失则 audio-separator 下载 |

> 自带模型为二进制大文件（约 2 GB），已被 `.gitignore` 忽略、不进版本库；只需物理存在于
> `assets/models/`，编译安装包时会被打进 `XB-SVCB-Setup.exe`。详见 `assets/models/README.md`。
> 联网回退时底模走 **hf-mirror 镜像**、GitHub 资源带 **ghproxy 回退**并自动逐源重试。

---

## 八、常见问题

- **so-vits-svc 依赖现场编译失败（numpy 1.19.5 / pyworld 等 `_Py_HashDouble`、`could not get source code`）**：so-vits-svc 4.1 的依赖是为 **Python 3.8~3.9** 钉的旧版本，只有 3.9 及更低才有预编译 wheel，在 3.10 上会回退到源码编译并失败。安装器已把 **SVC 引擎固定用 Python 3.9**（uv 自动下载，无需你手动装），整套依赖直接装 wheel、零编译；UVR 分离环境仍用 3.10。若你是从旧版本升级，重跑 `--only svc` 会自动把 `.venv-svc` 重建为 3.9（会重新下载 torch）。
- **推理报 `No module named 'pkg_resources'`**：`.venv-svc` 由 `uv venv` 创建，默认不含 setuptools，而 librosa 运行时需要 `pkg_resources`（属于 setuptools）。**注意 setuptools 81+ 已移除 pkg_resources**，必须钉 `<81`。安装器已自动给 `.venv-svc` / `.venv-uvr` 装 `setuptools<81`；若是旧环境，手动补一行即可：`uv pip install --python <安装目录>\.venv-svc\Scripts\python.exe "setuptools<81" wheel`。
- **`playsound==1.3.0` 构建失败**：该包仅 WebUI 播放用、推理用不到，安装器已自动从依赖清单里**剔除 playsound / gradio / pyaudio / sounddevice / onnxsim / onnxoptimizer**（实时变声与 ONNX 导出专用，文件翻唱用不到，且在 Windows 上常需编译），无需理会。
- **底模下载超时（`WinError 10060` / huggingface 连不上）**：安装器默认走 `hf-mirror.com` 镜像并自动换源重试。仍不行时设 `XB_HF_MIRROR` / `XB_GH_MIRROR` 后重跑 `python install\install.py --only models`，或手动下载放入对应目录。
- **`so-vits-svc` 依赖（fairseq 等）安装失败**：fairseq 在 Windows 上对编译环境较敏感。可安装「Microsoft C++ Build Tools」后重跑 `python install\install.py --only svc`；或设置 `XB_SVC_PYTHON` 指向一个已配置好 so-vits-svc 依赖的 Python。
- **分离 / 去混响很慢**：CPU 模式下 VR 模型较慢。装有 NVIDIA 显卡时用 `python install\install.py --gpu` 重装分离环境即可走 GPU。
- **中文歌名相关问题**：内部已统一用 UTF-8 + 结果文件传递路径，支持中文文件名。
- **任务失败**：在「作品库」点失败项的「打开日志」，查看 `run.log` 与各步骤子进程输出定位原因。

---

## 九、构建 setup.exe 安装器（开发者）

最终用户用的图形安装器由 Inno Setup 生成。开发者侧构建步骤：

1. 安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)（提供 `ISCC.exe`）。
2. 在项目根目录运行构建脚本（会先构建前端，再编译安装器）：

```powershell
./installer/build.ps1
```

3. 产物输出在 `dist/XB-SVCB-Setup.exe`，即可分发。

构建相关文件：

| 文件 | 作用 |
| --- | --- |
| `installer/xb-svcb.iss` | Inno Setup 脚本（打包内容、快捷方式、安装后搭建环境、卸载清理） |
| `installer/build.ps1` | 构建前端 + 调 ISCC 编译为 setup.exe（仅开发者构建用，最终用户安装过程不涉及 PS） |
| `install/install.py` | 安装器在用户机搭建环境/下载模型的核心逻辑（被 setup_env.bat 调用） |
| `setup_env.bat` | 用户机搭建/修复环境入口（纯 batch 调 Python，无 PowerShell） |
| `run.bat` | 启动器（快捷方式指向 `run.bat`） |

设计说明：

- 安装器**打包预构建的 `web/dist`**，因此最终用户无需安装 Node.js。
- 安装器**自带 `assets/models/` 内的底模与 UVR 模型**（约 2 GB），「搭建运行环境」时直接本地复制，免去缓慢的联网下载；安装包因此较大（约 2 GB），换来近乎瞬时的模型部署。Python 环境、so-vits-svc 仓库仍在该阶段联网获取。
- 卸载时会清理安装目录内生成的 `.venv-*`、`engines/`、`models/`；用户作品数据位于 `~/.xb-svcb`，予以保留。

---

## 许可（License）

本项目自身代码采用 **MIT License**（见仓库根目录 [`LICENSE`](LICENSE)）。Copyright (c) 2026 SDIJF1521。

注意：本项目依赖/附带的第三方组件各自遵循其原始协议，使用与再分发时请遵守：

- **so-vits-svc 4.1**（`svc-develop-team/so-vits-svc`）：安装时联网获取，遵循其上游协议（AGPL-3.0）。
- **底模**：ContentVec、NSF-HiFiGAN、RMVPE、FCPE 等各有其许可。
- **UVR 模型**：`5_HP-Karaoke-UVR`、`UVR-DeEcho-DeReverb` 等遵循 Ultimate Vocal Remover 项目的相应许可。

MIT 仅覆盖本仓库自有代码，不改变上述第三方组件的授权条款。
