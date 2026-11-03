[简体中文](development.md) | [English](en/development.md) | [日本語](ja/development.md)

# 开发与发布

## 推荐工作流

    安装源码环境
      -> 修改 app / web
      -> 运行 Python 和前端测试
      -> 构建 web/dist
      -> 启动桌面应用验证 Bridge
      -> 验证 FastAPI、模型和 Worker
      -> 构建 JUCE Host（需要时）
      -> 执行发布校验
      -> 构建 Inno Setup 安装包

## 后端开发

主程序依赖定义在 app/pyproject.toml，运行时入口是 app/main.py。建议从 app/api/bridge.py 和 app/application/ 开始阅读业务调用，再进入 app/infrastructure/ 查看具体引擎和 Worker。

运行测试：

    cd app
    uv run pytest

重点测试范围包括模型服务、推理回归、设备探测、HTTP API、实时翻唱、编辑器、插件和安装器运行时。

## 前端开发

    cd web
    npm install
    npm run dev
    npm run type-check
    npm run build
    npm run test:unit -- --run

前端构建输出为 web/dist。生产桌面应用会把这个目录作为内置资源加载。

## JUCE VST3 Host

设置 JUCE 路径并构建：

    $env:XB_JUCE_DIR="C:\path\to\JUCE"
    .\native\juce-vst3-host\build.ps1

产物应位于 engines/juce-vst3-host/xb-juce-vst3-host.exe。更多限制和插件兼容说明见安装器说明。

## 安装包构建

构建脚本可用 `-Help` 或 `--help` 查看参数，不启动预检或打包。

v0.1.0 的版本起点是提交 `fc8d214e068457a273929e80c108b33f55b4e9e8`，且该提交属于 v0.1.0。生成本版提交列表时使用：

    git log --reverse fc8d214e068457a273929e80c108b33f55b4e9e8^..HEAD

审计完整差异时使用同一包含起点的范围，不要写成 `fc8d214e068457a273929e80c108b33f55b4e9e8..HEAD`，否则会漏掉起点提交。

轻量校验：

    .\installer\build.ps1 -ValidateOnly

构建默认 CUDA128 共享运行时包：

    .\installer\build.ps1

顺序构建 CPU、ROCm 10、DirectML、CUDA126、CUDA128 五套专用包：

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe

该命令会在构建前检测五栈的公共目录和必需组件目录，只自动准备缺失栈；完整缓存不会重复下载。

首次构建、依赖变更或网络中断后，使用增量模式补齐五栈 wheelhouse：

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe -RebuildWheelhouse

`-RebuildWheelhouse` 会复用现有 wheels。只有确认缓存损坏时才同时使用 `-CleanWheelhouse`；它会
删除所有栈并从零下载。若 CPU、ROCm 已完成而只缺后续栈，可先运行：

    C:\path\to\python.exe .\install\prepare_wheelhouse.py --root . --stack directml --stack cu126 --stack cu128

CPU 的 SVC/RVC 组件在 ROCm 之前准备，ROCm 组件复用公共 ROCm wheels。日志中先出现
`ProxyError` 或 TLS 握手超时、随后出现 `ResolutionImpossible` 时，应先检查代理和下载源，
不要清空已经完成的缓存。具体续跑命令见安装器说明。

CUDA 包使用 Git 外部保存的共享核心材料时，构建命令需要额外指定材料目录：

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe -RuntimeAssets D:\XB-SVCB\assets\runtime\core-cu128

构建流程大致为：

1. 校验应用、前端、版本号和关键运行载荷。
2. 构建 Vue 前端，并在五套包之间复用同一份结果。
3. 使用 PyInstaller 生成桌面应用及其内置资源，并在五套包之间复用同一份结果。
4. 构建或复用 JUCE VST3 Host。
5. 按目标硬件栈筛选离线 wheelhouse，校验 CUDA candidate/compat 材料和运行环境载荷。
6. 使用 Inno Setup 生成硬件专用 EXE 和多个小于 2GB 的同名前缀 `.bin` 分卷。

`assets/wheels/wheelhouse.json` 会记录每个栈的依赖计划签名、wheel 文件名和大小。打包前会逐文件校验完成档案；旧清单或下载中断留下的半成品缓存会被拒绝，不能用 `-SkipWheelhouse` 绕过。可单独检查：

    C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py --root . --check --stack directml

发布时必须同时上传 EXE 和全部 BIN 文件。安装器说明、运行环境列表和分卷规则见 installer/README.md。

## 文档维护约定

- 根 README 只放项目概览、快速开始和文档链接。
- API 细节只维护在 docs/api.md。
- 插件内容优先维护在 docs/plugins/，旧版单文件指南仅作兼容和全文搜索。
- 架构源数据放在 docs/archify/*.json，HTML 是可交付查看产物。
- 版本更新说明统一放在 `docs/release-notes/`，README 只链接当前版本。从 v0.1.0 开始，每版同步维护简体中文主文件、`.en.md` 和 `.ja.md` 三份内容一致的发布说明。
- 修改启动流程、目录结构、环境名称或 API 合同时同步更新对应文档。
