# 源码安装与启动

本文面向希望从源码运行 XB-SVCB 的开发者或高级用户。普通用户建议直接使用 GitHub Releases 中的安装包。

## 环境要求

- Windows。
- Python 3.10 或更高版本。
- Node.js 20.19+ 或 22.12+，仅源码构建前端需要。
- 可联网访问 PyPI、模型源和上游仓库，或准备好离线 wheelhouse 与模型资产。
- NVIDIA CUDA、AMD DirectML 或 CPU 均可运行，但不同模型框架的加速能力不同。
- 如果使用音频编辑器的 VST3 Host，需要 CMake、Visual C++ Build Tools 和 JUCE。

## 一键搭建

在项目根目录执行：

    setup_env.bat

脚本调用 install/install.py，按顺序准备：

| 组件 | 目录 | 作用 |
| --- | --- | --- |
| 主程序 | app/.venv | pywebview 桌面壳和 Python 业务层 |
| 前端 | web/dist | Vue 3 生产构建产物 |
| UVR | .venv-uvr | 人声分离和去混响 |
| So-VITS-SVC | engines/so-vits-svc、.venv-svc | So-VITS-SVC 推理 |
| RVC | .venv-rvc | RVC 推理 |
| SeedVC | engines/seed-vc、.venv-seedvc | SeedVC 推理 |
| DDSP-SVC | engines/ddsp-svc、.venv-ddsp | DDSP-SVC 推理 |
| Vocal | .venv-vocal | AI 歌声增强 |
| Hub | .venv-hub | ModelScope 模型上传，可选 |
| 模型资产 | models/、engines/*/pretrain | 模型、底模和辅助权重 |

每一步都可以重复执行。只重跑某一组件时使用：

    python install\install.py --only uvr
    python install\install.py --only svc
    python install\install.py --only rvc
    python install\install.py --only seedvc
    python install\install.py --only ddsp
    python install\install.py --only vocal
    python install\install.py --only models

CPU 或 DirectML 安装：

    python install\install.py --cpu
    python install\install.py --directml

## 启动

生产模式：

    run.bat

等价的直接命令：

    app\.venv\Scripts\python.exe app\main.py

开发模式需要先启动 Vite：

    cd web
    npm install
    npm run dev

然后在另一个终端执行：

    app\.venv\Scripts\python.exe app\main.py --dev

app/main.py 会在生产模式加载 web/dist/index.html，在开发模式加载 http://localhost:5173。也可以通过 XB_DEV_URL 指定其他前端地址。

## 设备选择

- NVIDIA 用户根据显卡使用 CUDA 依赖；RTX 50 系使用安装器提供的 cu128 栈。
- Windows AMD Radeon 使用 DirectML；DDSP-SVC 在部分 AMD 环境保持 CPU 路径以保证稳定性。
- 无可用 GPU 时使用 CPU。显式选择 CUDA、DirectML 或 CPU 时，应用会校验对应环境是否真实可用。

## 数据目录

默认数据目录为 .xb_svcb，保存模型库、作品、编辑工程、下载文件、设置、日志和缓存。推荐把它放在空间充足的磁盘。可通过应用内迁移功能或设置 XB_DATA_DIR 更改位置。

## 常见排障

### 窗口提示缺少前端

生产模式要求 web/dist/index.html 存在。先执行：

    cd web
    npm run build

或者使用 --dev 连接 Vite 开发服务器。

### AI 环境搭建失败

先确认 Python 已加入 PATH，再按组件重跑 install/install.py --only COMPONENT。如果网络不稳定，设置镜像后重试：

    set XB_HF_MIRROR=https://hf-mirror.com
    set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
    set XB_GH_MIRROR=https://ghfast.top

### 运行时找不到 FFmpeg

源码运行需要系统 PATH 中存在 ffmpeg，或者把可执行文件放到 assets/tools/ffmpeg/bin/ffmpeg.exe 并重新执行安装步骤。

### 修改前端后桌面仍显示旧页面

生产模式会使用 WebView2 缓存。关闭应用后重新启动；app/main.py 会清理 HTTP 和代码缓存，但会保留 localStorage 中的主题、头像等设置。
