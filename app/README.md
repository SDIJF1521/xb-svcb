# XB-SVCB 应用本体

版本：`0.0.15`

这里包含打包进 `XB-SVCB.exe` 的桌面应用壳、本地 API 桥接、领域服务和基础设施适配层。

## 运行结构

- `app/main.py` 启动 pywebview 桌面壳。
- `app/config.py` 提供应用元信息、路径与运行环境位置。
- 重型 AI 依赖不打进应用本体，由安装器放到 `.venv-svc`、`.venv-rvc`、`.venv-uvr`、`.venv-hub` 等隔离环境中。

## v0.0.15 重点

- 用户数据目录默认升级为 `.sb-svcb`，并兼容 `.xb_xvcb`、`.sv-xvcb` 等旧目录。
- 数据目录切换/迁移后会在当前会话内重定向模型、作品、设置和编辑工程仓储。
- 数据迁移改为后台任务，后端提供进度、阶段、已复制大小和结果状态。
- RVC worker 会优先使用自带 hubert/rmvpe 底模，并在必要时走 HuggingFace 镜像兜底。
