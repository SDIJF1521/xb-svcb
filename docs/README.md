# XB-SVCB 文档

这里按使用者、开发者和插件作者整理项目文档。根目录 README 只保留项目概览和入口，具体内容从下面选择。

## 使用者

- [源码安装与启动](getting-started.md)：环境要求、安装脚本、运行模式、数据目录和常见排障。
- [FastAPI 接入](api.md)：服务启动、鉴权、任务接口、上传下载和调用示例。
- [模型资产说明](../assets/models/README.md)：随包模型、底模、来源和缺失时的处理方式。

## 开发者

- [系统架构](architecture.md)：Python 后端、Vue 前端、Worker、队列、模型和音频工具的职责与连接。
- [启动与推理链路](startup-chain.md)：从 app/main.py 启动到一次普通任务和实时任务完成的过程。
- [开发与发布](development.md)：代码结构、测试、前端构建、JUCE Host 和安装包构建。
- [安装器说明](../installer/README.md)：PyInstaller、运行环境、离线 wheelhouse 和 Inno Setup 分卷。
- [共享运行时与兼容布局](runtime-consolidation.md)：CUDA 两层共享环境、CPU/DirectML 兼容布局、路由与修复边界。

## 插件作者

- [插件开发总览](plugins/README.md)
- [插件开发完整指南](plugin-development.md)
- [Plugin SDK README](../plugin-sdk/README.md)

## 架构图与生成产物

- [系统架构图](archify/xb-svcb-system.architecture.html)
- [系统架构图 JSON](archify/xb-svcb-system.architecture.json)
- [启动与推理时序图](archify/xb-svcb-startup-inference.sequence.html)

## 版本记录

历史更新说明集中在 [release-notes/](release-notes/)。新增版本建议继续使用 release_notes_vXYZ.md 命名，并在根 README 只链接当前版本。
