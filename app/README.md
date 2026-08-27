# XB-SVCB Python 后端

这里是 XB-SVCB 的桌面应用壳、本地 API、应用服务、领域对象和基础设施适配层。

## 入口

- main.py：创建 pywebview 窗口，绑定 Python Api，处理开发/生产模式和退出清理。
- api/bridge.py：定义 Api 外观和 build_api() 组合根。
- api/http_server.py：可手动启停的 FastAPI/Uvicorn 外部接口。
- application/：模型、作品、转换、编辑器、实时翻唱、插件等用例服务。
- domain/：任务、模型、编辑工程等领域实体和枚举。
- infrastructure/：Worker、引擎适配、FFmpeg、存储、系统音频和设备探测。

## 运行关系

    api -> application -> domain
                     \-> infrastructure

重型模型不在主进程启动时统一加载，而是在 .venv-svc、.venv-rvc、.venv-seedvc、.venv-ddsp 等隔离环境的 Worker 进程中按任务加载。普通任务通过转换服务的串行队列执行，实时任务使用常驻 Worker。

详细说明见：

- [系统架构](../docs/architecture.md)
- [启动与推理链路](../docs/startup-chain.md)
- [开发与发布](../docs/development.md)
- [FastAPI 接入](../docs/api.md)

## 测试

    cd app
    uv run pytest
