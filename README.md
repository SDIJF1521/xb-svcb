<div align="center">

# XB-SVCB

桌面级 AI 歌声转换与翻唱创作工作站

导入歌曲、分离人声、模型推理、AI 增强、混音和作品管理在一个 Windows 应用中完成。

[![License](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/SDIJF1521/xb-svcb?include_prereleases&label=release&color=ff6b9d)](https://github.com/SDIJF1521/xb-svcb/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](#)
[![Vue](https://img.shields.io/badge/Vue-3-42b883?logo=vuedotjs&logoColor=white)](#)

[下载安装包](https://github.com/SDIJF1521/xb-svcb/releases/latest) · [文档目录](docs/README.md) · [问题反馈](https://github.com/SDIJF1521/xb-svcb/issues)

</div>

## 项目简介

XB-SVCB 是一个面向 Windows 的本地 AI 歌声转换应用。它以 pywebview + Vue 3 提供桌面界面，以 Python 应用服务组织任务和本地数据，并把不同 AI 引擎放入独立 Worker 和虚拟环境中运行。

当前支持以下主要能力：

- So-VITS-SVC、RVC、SeedVC、DDSP-SVC 多框架模型管理与推理。
- UVR 人声分离、去混响、分离结果修复和 FFmpeg 混音后处理。
- 单模型翻唱、多模型时间轴编排、跨框架混唱和合唱。
- AI 歌声增强、音频编辑器、歌词时间轴、效果器和 VST3 Host。
- RVC / SeedVC 实时翻唱，以及 WASAPI 回环或 VB-CABLE 系统音频变声。
- 网易云、QQ 音乐、酷我音乐资源获取和歌词导入。
- 可选 FastAPI 外部接口和可扩展插件系统。
- NVIDIA CUDA、Windows AMD DirectML 与 CPU 推理路径。

## 快速选择

| 目标 | 入口 |
| --- | --- |
| 普通用户安装使用 | [下载安装包](https://github.com/SDIJF1521/xb-svcb/releases/latest) |
| 从源码运行 | [源码安装与启动](docs/getting-started.md) |
| 了解 Python 后端和模型链路 | [系统架构](docs/architecture.md) · [启动与推理链路](docs/startup-chain.md) |
| 调用本地 HTTP API | [FastAPI 接入文档](docs/api.md) |
| 开发插件 | [插件开发文档](docs/plugins/README.md) |
| 构建安装包 | [发布与构建文档](docs/development.md) · [安装器说明](installer/README.md) |

## 安装与运行

### 安装包方式

1. 从 Releases 下载同一版本的 XB-SVCB-Setup.exe 和全部 XB-SVCB-Setup-*.bin。
2. 将这些文件放在同一目录，运行 XB-SVCB-Setup.exe。
3. 选择安装目录和用户数据目录。模型、作品、编辑工程和缓存建议放在空间充足的磁盘。
4. 按安装器提示搭建 AI 运行环境，然后从桌面或开始菜单启动 XB-SVCB。

安装包自带前端、FFmpeg、引擎源码、离线模型和依赖 wheel。用户无需安装 Node.js；首次搭建运行环境仍需要 Python 和网络或可用的离线 wheelhouse。

### 源码方式

要求：Windows、Python 3.10+、Node.js 20.19+ 或 22.12+。如果需要构建 VST3 Host，还需要 CMake、Visual C++ Build Tools 和 JUCE。

在项目根目录执行：

    setup_env.bat
    run.bat

setup_env.bat 会创建主程序环境和各 AI 组件的隔离环境，并构建 web/dist。环境已存在时可重复执行，或直接使用 install/install.py --only COMPONENT 单独补装组件。

常用启动方式：

    run.bat

    app\.venv\Scripts\python.exe app\main.py

前端热更新开发：

    cd web
    npm install
    npm run dev

另开终端启动 Python 桌面壳：

    app\.venv\Scripts\python.exe app\main.py --dev

默认开发前端地址为 http://localhost:5173，也可以通过 XB_DEV_URL 覆盖。

## 典型使用流程

1. 在模型管理中导入或下载模型。
2. 选择本地音频或从在线曲库下载素材。
3. 创建单模型或多模型翻唱任务。
4. 应用依次执行人声分离、去混响、模型推理、可选增强和混音。
5. 在作品库试听、导出或继续进入音频编辑器处理。

系统音频变声和 FastAPI 服务默认关闭，需要在应用内手动启用。局域网 API 只应在可信网络使用，不要直接暴露到公网。

## 系统架构

    桌面用户 -> pywebview + Vue 3 -> Api Facade -> Application Services
    外部客户端 -> FastAPI -----------------------> Api Facade
                                                      |
                                          串行推理队列 / 本地数据
                                                      |
                             UVR -> EngineRegistry -> Model Worker -> FFmpeg
                                                      |
                                               离线模型资产

架构设计的关键点：

- 桌面桥接和 FastAPI 共用同一个 Api 外观、应用服务和推理队列。
- FastAPI 默认不监听端口，必须由用户在应用内手动启动。
- 重型模型 checkpoint 在隔离 Worker 进程中加载，避免污染主进程依赖。
- 不同 AI 框架使用独立 Python 环境，降低 torch、numpy 和上游依赖冲突。
- 普通任务通过串行队列执行，以控制单 GPU 的显存峰值；实时模式使用常驻 Worker。

可直接查看带连接解释的图：

- [系统架构图 HTML](docs/archify/xb-svcb-system.architecture.html)
- [系统架构图源数据 JSON](docs/archify/xb-svcb-system.architecture.json)
- [启动与推理时序图 HTML](docs/archify/xb-svcb-startup-inference.sequence.html)
- [启动链路说明页](docs/startup-chain.html)

## 代码结构

    app/
    ├─ main.py                    桌面程序入口
    ├─ api/                       pywebview Bridge 与 FastAPI
    ├─ application/               用例服务、任务队列和业务编排
    ├─ domain/                    领域实体、枚举和编辑工程模型
    ├─ infrastructure/            引擎、Worker、存储、音频和系统适配
    ├─ tests/                     Python 测试
    └─ pyproject.toml             主程序依赖
    web/
    ├─ src/api/                   前端 API 类型与桥接
    ├─ src/stores/                Pinia 状态
    ├─ src/views/                 页面
    └─ src/components/            可复用组件
    assets/models/                随包或开发环境使用的离线模型资产
    engines/                      上游 AI 引擎源码和运行载荷
    install/                      运行环境安装与修复脚本
    installer/                    PyInstaller / Inno Setup 发布流程
    native/                       JUCE VST3 Host
    plugin-sdk/                   插件 SDK、示例和测试
    docs/                         API、架构、开发和插件文档

后端采用 api -> application -> domain <- infrastructure 的分层方式。application 负责业务流程，infrastructure 负责调用外部引擎、文件系统和子进程，domain 保存不依赖具体 UI 的业务结构。

## 测试与构建

Python 测试：

    cd app
    uv run pytest

前端类型检查和构建：

    cd web
    npm run type-check
    npm run build
    npm run test:unit -- --run

构建安装包前先执行轻量校验：

    .\installer\build.ps1 -ValidateOnly

完整构建：

    .\installer\build.ps1

发布产物包括 dist/XB-SVCB-Setup.exe 及全部 dist/XB-SVCB-Setup-*.bin，不能遗漏分卷文件。完整构建要求 CMake、C++ Build Tools、JUCE 和 Inno Setup 已配置；详细流程见 [开发与发布文档](docs/development.md)。

## 数据目录与配置

用户数据默认位于项目或安装目录下的 .xb_svcb，包括模型、作品、下载素材、编辑工程、日志和临时文件。可通过应用内的数据存储设置迁移，也可使用以下环境变量覆盖：

| 变量 | 用途 |
| --- | --- |
| XB_DATA_DIR | 当前用户数据目录 |
| XB_DEV | 设置为 1 时启用开发模式 |
| XB_DEV_URL | 开发模式前端地址 |
| XB_JUCE_DIR | JUCE 源码目录，用于构建 VST3 Host |
| XB_HF_MIRROR / HF_ENDPOINT | Hugging Face 镜像地址 |
| XB_PYPI_MIRROR / UV_DEFAULT_INDEX | Python 包镜像地址 |

运行时环境目录通常包括 .venv-svc、.venv-rvc、.venv-seedvc、.venv-ddsp、.venv-uvr、.venv-vocal 和 .venv-hub。这些目录属于本地运行产物，不应提交到 Git。

## 相关文档

- [文档总目录](docs/README.md)
- [源码安装与启动](docs/getting-started.md)
- [系统架构与连接说明](docs/architecture.md)
- [启动与模型推理链路](docs/startup-chain.md)
- [FastAPI 接入](docs/api.md)
- [插件开发](docs/plugins/README.md)
- [插件 SDK](plugin-sdk/README.md)
- [安装器与发布](installer/README.md)
- [贡献指南](CONTRIBUTING.md)
- [模型资产说明](assets/models/README.md)

## 版本与许可证

当前代码版本为 v0.0.29。历史版本说明集中在 [docs/release-notes/](docs/release-notes/) 中，最新版本请查看 [v0.0.29 更新说明](docs/release-notes/release_notes_v029.md)。

本项目自有代码采用 [GPL-3.0-only](LICENSE)。上游引擎、第三方库、模型和音频资源可能使用不同许可证，使用和再分发时请分别遵守其原始授权条款。
