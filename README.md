<div align="center">

# 🎤 XB-SVCB · AI 翻唱工具

#### 开箱即用的桌面级 AI 翻唱工作站

**🎵 导入歌曲 ｜ 🎚️ 人声分离 ｜ 🌫️ 去混响 ｜ 🗣️ AI 歌声转换 ｜ 🎧 AI 歌声增强 ｜ 🎼 合并伴奏 ｜ 🎤 成品翻唱**

一条龙完成整首歌的 AI 翻唱 · 支持 **So-VITS-SVC / RVC 多框架推理** · **多人混合翻唱** · **实时系统音频变声** · **AI 歌声增强工程** · **在线曲库** · **模型站** · **音频编辑器**

<br/>

[![License](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/SDIJF1521/xb-svcb?include_prereleases&label=release&color=ff6b9d)](https://github.com/SDIJF1521/xb-svcb/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/SDIJF1521/xb-svcb/total?color=brightgreen&label=downloads)](https://github.com/SDIJF1521/xb-svcb/releases)
[![Stars](https://img.shields.io/github/stars/SDIJF1521/xb-svcb?style=flat&color=yellow)](https://github.com/SDIJF1521/xb-svcb/stargazers)

[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#)
[![Python](https://img.shields.io/badge/python-3.9%20|%203.10-3776AB?logo=python&logoColor=white)](#)
[![Vue](https://img.shields.io/badge/Vue%203-Element%20Plus-42b883?logo=vuedotjs&logoColor=white)](#)
[![Engines](https://img.shields.io/badge/engines-So--VITS--SVC%20·%20RVC%20·%20SeedVC%20·%20DDSP--SVC-8a2be2)](#architecture)

<br/>

### ⬇️ [**点此下载安装器 · XB-SVCB-Setup.exe**](https://github.com/SDIJF1521/xb-svcb/releases/latest)

<sub>Windows 一键安装 · 内置前端与底模 · 无需手动配置 Python / Node</sub>

<sub>用户交流 / 反馈 QQ 群：**1038366109**</sub>

</div>
<a id="features"></a>

#### 开箱即用的桌面级 AI 翻唱工作站

导入歌曲、分离人声、AI 歌声转换、混合翻唱、音频编辑，一站完成。

[![License](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/SDIJF1521/xb-svcb?include_prereleases&label=release&color=ff6b9d)](https://github.com/SDIJF1521/xb-svcb/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10-3776AB?logo=python&logoColor=white)](#)
[![Vue](https://img.shields.io/badge/Vue%203-Element%20Plus-42b883?logo=vuedotjs&logoColor=white)](#)

### ⬇️ [下载安装器 · XB-SVCB-Setup.exe](https://github.com/SDIJF1521/xb-svcb/releases/latest)

Windows 一键安装 · 内置前端与底模 · 支持 NVIDIA CUDA、AMD DirectML 和 CPU

用户交流 / 反馈 QQ 群：**1038366109**

</div>

---

## 项目简介

XB-SVCB 是一个 Windows 本地优先的 AI 翻唱与音频创作工具。它以 Vue 3 作为界面，以 Python 作为业务核心，并将不同 AI 框架放在独立环境和 Worker 进程中运行。

项目目前支持 So-VITS-SVC、RVC、SeedVC 和 DDSP-SVC 四种歌声转换框架，同时提供 UVR 人声分离、AI 歌声增强、在线曲库、模型站、实时系统音频变声和 Audio Editor Lite 音频编辑器。

## 主要功能

- 一键完成「人声分离 → 去混响 → F0 分析 → 歌声转换 → 增强 → 混音」。
- 统一管理 So-VITS-SVC、RVC、SeedVC、DDSP-SVC 模型，并按模型框架选择推理参数。
- 通过歌词或静音检测切分歌曲，在可视化时间轴中分配模型，支持多人混唱和一句多模型合唱。
- 使用 Audio Editor Lite 进行多轨编辑、剪切、淡化、声道分配、效果处理和 WAV / MP3 / FLAC 导出。
- 支持 TXT / LRC 歌词导入、角色管理和独唱、对唱、和声等时间轴模板。
- 通过 WASAPI 回环或 VB-CABLE 对播放器音频进行实时人声转换，伴奏保持原样。
- 通过 ModelScope 搜索、上传和下载模型，支持后台传输、断点续传和模型清单校验。
- 支持网易云、QQ 音乐、酷我音乐的搜索、试听、下载和歌词获取。
- 支持 GPU / CPU 切换：NVIDIA 使用 CUDA，Windows AMD 使用 DirectML，无法使用 GPU 时回退 CPU。
- 提供可选 FastAPI 服务，供外部程序创建任务、查询进度、管理模型和下载成品。
- 支持插件中心、自定义插件页面、Python 插件 Worker 和 C++ JUCE VST3 Host。

## 快速开始

### 使用安装包

普通用户建议直接使用 GitHub Releases 安装：

1. 下载同一版本的 <code>XB-SVCB-Setup.exe</code> 和全部 <code>XB-SVCB-Setup-*.bin</code> 文件，并放在同一目录。
2. 运行 EXE，选择应用安装目录和用户数据目录。
3. 勾选「安装后立即搭建运行环境」，按安装器提示完成环境准备。
4. 通过桌面或开始菜单中的 XB-SVCB 启动应用。

安装包内已包含前端、FFmpeg、模型框架源码、关键底模和离线 Python 依赖。应用安装完成后，AI 子环境会根据本机设备选择 CUDA、DirectML 或 CPU 依赖。

### 从源码安装

源码运行需要 Windows、Python 3.10+、Node.js 20.19+ 或 22.12+。在项目根目录执行：

~~~bat
setup_env.bat
~~~

该脚本会调用 <code>install/install.py</code>，创建主程序、UVR、SVC、RVC、SeedVC、DDSP-SVC、Vocal 和 ModelScope 所需的隔离环境，并准备底模。

常用的单组件安装命令：

~~~bat
python install\install.py --only uvr
python install\install.py --only svc
python install\install.py --only rvc
python install\install.py --only seedvc
python install\install.py --only ddsp
python install\install.py --only vocal
python install\install.py --only models
~~~

明确使用 CPU 或 AMD DirectML 时：

~~~bat
python install\install.py --cpu
python install\install.py --directml
~~~

`--consolidated` 目前仅供实验。上游原始依赖存在 NumPy/protobuf 冲突；本分支的 cu128 配方使用 NumPy 2.2.6、protobuf 7.36.0、TensorBoardX 2.6.5 和本地 AudioTools 兼容 wheel，已通过整体依赖解析和关键运行检查，但真实音频验收暂缓。当前 RTX 50 系主环境位于 `runtimes/core-cu128`，复现固定版本使用 `--core-profile core-cu128`，并加 `--preflight-only` 只解析、不安装；需先备齐配方所列本地 wheel。`--core-compat-wheel` 仅保留用于开发候选配方。旧安装仍兼容 `.venv-uvr`，新安装不再把它作为当前共享环境。详见 [固定配方及回滚材料](install/runtime_profiles/core-cu128/README.md) 和 [运行环境整合记录](docs/runtime-consolidation.md)。

安装器部署大体积只读底模时优先尝试硬链接，跨卷时回退为复制；已有同尺寸权重只有 SHA-256 一致才会去重。硬链接共享内容，训练或修改权重前须另存副本。此机制不负责删除旧环境。

### 启动应用

生产模式会加载已构建的 <code>web/dist</code>：

~~~bat
run.bat
~~~

也可以直接运行：

~~~bat
app\.venv\Scripts\python.exe app\main.py
~~~

开发模式需要两个终端。第一个终端启动前端：

~~~bat
cd web
npm install
npm run dev
~~~

第二个终端启动 Python 后端：

~~~bat
app\.venv\Scripts\python.exe app\main.py --dev
~~~

开发模式默认连接 <code>http://localhost:5173</code>，也可以通过 <code>XB_DEV_URL</code> 指定前端地址。完整环境说明见[源码安装与启动](docs/getting-started.md)。

## 基本使用流程

1. 在「模型管理」中导入或下载声音模型。
2. 在创建页选择歌曲、人声分离方式、目标模型和设备。
3. 单模型翻唱直接提交任务；多人翻唱先导入歌词或使用静音检测生成时间轴。
4. 在时间轴上调整片段边界，为片段分配一个或多个模型。
5. 等待推理、增强和混音完成，在作品库试听或导出成品。
6. 需要进一步处理时，将作品送入 Audio Editor Lite，进行局部重推理、效果处理或多轨编辑。

系统音频实时模式只支持一个 RVC 或 SeedVC 模型。它会采集播放器输出的混合音频，用 UVR 提取人声，再将转换后的人声与原伴奏重新混音并输出。

## 系统架构

XB-SVCB 的核心原则是：桌面 UI 和 FastAPI 共用同一套 Python 业务核心，重型模型与音频工具通过隔离 Worker 执行。

~~~mermaid
flowchart LR
    USER[桌面用户] --> UI[Vue 3 + pywebview]
    CLIENT[外部客户端] --> HTTP[FastAPI]
    UI --> BRIDGE[Bridge API]
    HTTP --> FACADE[Api Facade]
    BRIDGE --> FACADE
    FACADE --> APP[Application Services]
    APP --> QUEUE[推理队列]
    QUEUE --> ROUTER[EngineRegistry]
    ROUTER --> SVC[So-VITS-SVC Worker]
    ROUTER --> RVC[RVC Worker]
    ROUTER --> SEED[SeedVC Worker]
    ROUTER --> DDSP[DDSP-SVC Worker]
    APP --> UVR[UVR Worker]
    APP --> VOCAL[Vocal Enhancement Worker]
    APP --> FFMPEG[FFmpeg]
    APP <--> DATA[.xb_svcb 用户数据]
    SVC -.-> ASSETS[随包模型资产]
    RVC -.-> ASSETS
    SEED -.-> ASSETS
    DDSP -.-> ASSETS
    UVR -.-> ASSETS
~~~

上图中各连接的含义：

| 连接 | 作用 |
| --- | --- |
| 桌面用户 → Vue + pywebview | 用户选择歌曲、模型、参数，并查看任务状态。 |
| 外部客户端 → FastAPI | 通过 HTTP 上传文件、创建任务、查询进度和下载结果。 |
| Vue → Bridge API | 前端通过 pywebview 调用 Python 方法。 |
| FastAPI → Api Facade | HTTP 层复用桌面入口使用的同一个业务契约。 |
| Api Facade → Application Services | 将请求分发到模型、作品、转换、编辑器和插件等业务服务。 |
| Application Services → 推理队列 | 统一管理普通任务，控制任务状态和 GPU 资源占用。 |
| 推理队列 → EngineRegistry | 根据模型的 framework 选择对应的引擎适配器。 |
| EngineRegistry → 模型 Worker | 启动独立 Python 环境中的实际推理进程。 |
| Application Services → UVR / Vocal / FFmpeg | 执行分离、增强、转码、混音和导出等音频处理。 |
| Worker → 随包模型资产 | 优先读取本地 checkpoint、声码器和 F0 模型，缺失时才联网获取。 |
| Application Services ↔ .xb_svcb | 保存模型记录、任务、作品、编辑工程、设置、日志和缓存。 |

主程序环境只负责桌面壳、API 和业务编排，不会把所有模型权重加载到同一个 Python 进程。各 AI 框架使用独立的 <code>.venv-*</code> 环境，隔离依赖、Torch 版本和设备运行时。详细的 Python 后端、启动链路和模型加载时机见：

- [系统架构说明](docs/architecture.md)
- [启动与模型推理链路](docs/startup-chain.md)
- [系统架构图（含连接解释）](docs/archify/xb-svcb-system.architecture.html)
- [启动与推理时序图](docs/archify/xb-svcb-startup-inference.sequence.html)

## FastAPI 外部接入

FastAPI 默认关闭，不会在应用启动时自动监听端口。打开软件中的「资料库 → API 接入」，配置监听地址、端口和 API Key 后手动启动服务。

服务支持：

- 模型列表、导入和管理；
- 单模型、多模型和批量推理；
- 大音频流式上传；
- 任务进度、历史记录和预设；
- 作品查询与成品下载；
- Audio Editor Lite 的工程、音轨、片段、分离、局部重推理和渲染接口。

API 文档、鉴权方式和 Python / PowerShell 示例见 [FastAPI 接入文档](docs/api.md)。桌面 UI 和 HTTP 创建的任务共享同一个业务核心和任务队列。

## 插件系统

插件由 PluginService 负责安装、启停、配置和生命周期管理。插件前端运行在受限 iframe 中，通过 Client SDK 和宿主 Bridge 使用能力；Python 或混合插件的动作在独立 Worker 中执行。

插件可以包含：

- Vue / HTML / JavaScript 前端页面；
- Python Worker 和动作；
- TypeScript / Python SDK；
- 清单、权限、配置和资源文件。

开发入口：

- [插件开发总览](docs/plugins/README.md)
- [插件开发完整指南](docs/plugin-development.md)
- [插件清单规范](docs/plugins/manifest.md)

## 目录结构

~~~text
xb-svcb/
├─ app/                         Python 后端、业务服务、引擎适配和测试
│  ├─ api/                      pywebview Bridge 与 FastAPI
│  ├─ application/              用例和业务编排
│  ├─ domain/                   任务、模型、工程等领域对象
│  └─ infrastructure/           Worker、FFmpeg、仓储和引擎实现
├─ web/                         Vue 3 + Vite 前端
├─ engines/                     So-VITS-SVC、SeedVC、DDSP-SVC 等引擎源码
├─ assets/                      随包模型、工具和离线 wheelhouse
├─ install/                     环境搭建和模型部署脚本
├─ installer/                   PyInstaller / Inno Setup 安装器
├─ native/                      JUCE VST3 Host 工程
├─ plugin-sdk/                  插件 SDK
├─ docs/                        使用、架构、API、插件和发布文档
├─ run.bat / run.ps1            源码启动入口
└─ setup_env.bat                运行环境搭建入口
~~~

## 数据目录与配置

默认用户数据目录是 <code>.xb_svcb</code>，与程序文件分离，主要包含：

- <code>models</code>：用户导入和下载的声音模型；
- <code>works</code>：作品、伴奏、人声和导出文件；
- <code>editor_projects</code>：音频编辑工程；
- <code>uploads</code>、<code>cache</code>、<code>logs</code>、<code>settings</code>：API 上传、缓存、日志和设置；
- <code>plugins</code>、<code>plugin-data</code>、<code>theme/media</code>：插件数据和主题媒体。

数据目录可以在软件内迁移，也可以通过 <code>XB_DATA_DIR</code> 指定。安装包升级通常不会覆盖该目录。

常用环境变量：

| 变量 | 用途 |
| --- | --- |
| <code>XB_DATA_DIR</code> | 自定义用户数据目录。 |
| <code>XB_DEV</code> | 设置为 <code>1</code> 时启用开发模式。 |
| <code>XB_DEV_URL</code> | 指定开发模式使用的前端地址。 |
| <code>XB_HF_MIRROR</code> / <code>HF_ENDPOINT</code> | 指定 Hugging Face 镜像。 |
| <code>XB_PYPI_MIRROR</code> | 指定 Python 包镜像。 |
| <code>XB_GH_MIRROR</code> | 指定 GitHub 资源镜像。 |

## 测试与开发

后端测试（项目根目录）：

~~~bat
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs
~~~

运行时、安装器、离线打包和真实推理的分组与前置条件见 [测试说明](docs/testing.md)。

前端检查和测试：

~~~bat
cd web
npm run type-check
npm run test:unit -- --run
npm run build
~~~

修改 Python 后端时，建议从 <code>app/api/bridge.py</code>、<code>app/application/</code> 开始，再阅读 <code>app/infrastructure/</code> 中的引擎和 Worker。发布校验与安装包构建命令见[开发与发布](docs/development.md)和[安装器说明](installer/README.md)。

## 常见问题

### 生产模式提示找不到前端

生产模式要求 <code>web/dist/index.html</code> 存在。进入 <code>web</code> 执行 <code>npm install</code> 和 <code>npm run build</code>，或者使用 <code>--dev</code> 连接 Vite。

### AI 环境搭建失败

确认 Python 已加入 PATH，并按组件重新执行 <code>install/install.py --only COMPONENT</code>。网络不稳定时可设置镜像：

~~~bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
~~~

### 推理提示缺少 pkg_resources

旧的 SVC 环境可能缺少兼容版本的 setuptools，可执行：

~~~bat
uv pip install --python <安装目录>\.venv-svc\Scripts\python.exe "setuptools<81" wheel
~~~

### 分离或推理速度很慢

确认安装器选择的设备与本机硬件一致。NVIDIA 40 系及以下通常使用 cu121，RTX 50 系使用 cu128，AMD Radeon 使用 DirectML；不兼容或没有 GPU 时会使用 CPU。

### 任务失败如何排查

在作品库中打开失败任务的日志，先查看 <code>run.log</code> 和对应 Worker 的输出。启动链路、环境路径和常见错误见[源码安装与启动](docs/getting-started.md)。

## Roadmap

当前版本：**v0.0.30**

已完成的核心方向：

- So-VITS-SVC、RVC、SeedVC、DDSP-SVC 多框架推理；
- 多模型时间轴混唱和基础合唱；
- Audio Editor Lite 音频编辑工程；
- ModelScope 模型站；
- FastAPI 外部接入；
- NVIDIA CUDA、AMD DirectML 和 CPU 路径；
- 插件中心与 Python / 前端插件运行时。

后续重点：

- 自动歌词识别和更完善的自动时间轴；
- 模型元数据标准化、兼容性检查和自动识别；
- 工程导入导出与自动保存；
- 更多歌声转换框架；
- 作品分类、视频导出和歌词视频能力；
- Intel GPU、CPU 性能和多 GPU 调度优化。

完整版本历史见 [docs/release-notes/](docs/release-notes/)，当前版本说明见 [v0.0.30 更新说明](docs/release-notes/release_notes_v030.md)。

## 进一步阅读

- [文档总目录](docs/README.md)
- [源码安装与启动](docs/getting-started.md)
- [系统架构](docs/architecture.md)
- [启动与推理链路](docs/startup-chain.md)
- [FastAPI 接入](docs/api.md)
- [开发与发布](docs/development.md)
- [插件开发](docs/plugins/README.md)

---

<a id="thanks"></a>

## 🙏 致谢

- 🧁 **模型来源** —— 目前软件内可用 / 演示的**绝大部分声音模型，均由「白菜工厂1145号员工」提供**。在此特别致谢 🙏，正是这些模型让本工具能开箱即用地体验完整翻唱流程。
- 📌 模型版权归原作者所有，请在其授权范围内使用；如有侵权或需要下架，请联系作者处理。
- 🛠️ 同时感谢上游开源项目：[so-vits-svc](https://github.com/svc-develop-team/so-vits-svc)、[rvc-python](https://github.com/daswer123/rvc-python) / RVC、[Seed-VC](https://github.com/Plachtaa/seed-vc)、[DDSP-SVC](https://github.com/yxlllc/DDSP-SVC)、[Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui)、[DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)、[Pedalboard](https://github.com/spotify/pedalboard)、[ModelScope 魔搭社区](https://www.modelscope.cn/) 等。
- 🚀 后续会把更多模型逐一上传到「模型站」，方便在软件内直接搜索下载。

---

## 📄 许可

本项目自身代码采用 **[GNU General Public License v3.0 only（GPL-3.0-only）](LICENSE)**。Copyright © 2026 SDIJF1521。

> ⚠️ 本项目依赖/附带的第三方组件各自遵循其原始协议，使用与再分发时请遵守：
>
> - **so-vits-svc 4.1**（`svc-develop-team/so-vits-svc`）：源码随安装分卷携带，遵循上游 **AGPL-3.0**。
> - **DDSP-SVC 6.3**（`yxlllc/DDSP-SVC`）：源码随安装分卷携带，遵循上游 **MIT License**。
> - **底模**：ContentVec、NSF-HiFiGAN、RMVPE、FCPE 等各有其许可。
> - **UVR 模型**：`5_HP-Karaoke-UVR`、`UVR-DeEcho-DeReverb` 等遵循 Ultimate Vocal Remover 项目相应许可。
>
> GPL-3.0-only 仅覆盖本仓库自有代码，不改变上述第三方组件、模型和资源的原始授权条款。
