# 系统架构

XB-SVCB 是一个本地优先的桌面应用。前端负责交互和状态展示，Python 负责业务编排，重型模型和音频工具通过隔离 Worker 执行。

## 总体结构

    桌面用户 -> pywebview + Vue 3 -> Api Facade -> Application Services
    外部客户端 -> FastAPI -----------------------> Api Facade
                                                      |
                                          串行推理队列 / 本地数据
                                                      |
                             UVR -> EngineRegistry -> Model Worker -> FFmpeg
                                                      |
                                               离线模型资产

也可以打开[带连接解释的系统架构图](archify/xb-svcb-system.architecture.html)查看完整布局和说明卡片。

## 连接说明

| 连接 | 作用 |
| --- | --- |
| 桌面用户 -> pywebview + Vue | 用户选择音频、模型、设备和推理参数，并查看任务状态。 |
| 外部客户端 -> FastAPI | 通过 HTTP 上传音频、创建任务、查询进度和下载成品。服务默认关闭。 |
| Vue -> Api Facade | 前端通过 window.pywebview.api 调用 Python 方法。 |
| FastAPI -> Api Facade | HTTP 层复用桌面桥接使用的 Api，避免重复实现业务规则。 |
| Api Facade -> Application Services | 将界面或 HTTP 请求分发给作品、模型、转换、编辑器等用例服务。 |
| Application Services -> 串行推理队列 | 创建任务并排队执行，控制 GPU 显存峰值和任务状态。 |
| 串行推理队列 -> EngineRegistry | 根据模型的 framework 选择 So-VITS-SVC、RVC、SeedVC 或 DDSP-SVC 适配器。 |
| Application Services -> UVR Worker | 执行人声与伴奏分离、去混响等前置处理。 |
| EngineRegistry -> Model Worker | 启动或复用隔离 Worker；真正的 checkpoint 加载发生在 Worker 内。 |
| Model Worker -> 离线模型资产 | 读取主模型、底模、F0、声码器和框架配置。 |
| Application Services -> Vocal Enhancement | 按任务配置执行可选的人声修复、对齐、修音和母带增强。 |
| Model Worker -> FFmpeg | 表示推理结果进入后处理和最终混音流程；FFmpeg 的实际调用由业务流程编排。 |

## 主要模块

### app/main.py

桌面入口。负责单实例控制、解析开发/生产模式、创建 pywebview 窗口、绑定 Api，并在退出时停止后台服务和清理临时文件。

### app/api/

表现层：

- bridge.py 定义暴露给 Vue 的 Api 和组合根 build_api()。
- http_server.py 创建可手动启停的 FastAPI/Uvicorn 服务。

### app/application/

用例和业务编排层，包含模型管理、作品管理、音乐资源、音频编辑、实时翻唱、插件和转换任务等服务。普通推理任务在 conversion_service.py 中进入串行队列。

### app/domain/

保存编辑工程、任务、模型等领域对象和枚举，尽量不依赖 pywebview、FastAPI 或具体 AI 框架。

### app/infrastructure/

负责文件存储、路径、FFmpeg、系统音频、UVR、F0、模型引擎适配和 Worker 进程。svc_engine.py、rvc_engine.py、seedvc_engine.py、ddsp_engine.py 是框架适配入口。

### web/

Vue 3 + Vite 前端。views/ 组织页面，stores/ 管理跨页面状态，src/api/ 对接 pywebview Bridge 和 HTTP 类型。

## 运行边界

- 主程序环境只承载桌面壳、API 和业务服务。
- AI 框架使用 .venv-svc、.venv-rvc、.venv-seedvc、.venv-ddsp 等独立环境。
- Worker 隔离的是进程和依赖，不是操作系统权限沙箱。
- FastAPI 与桌面 UI 共享任务队列，因此两种入口创建的任务在同一个应用中可见。
- 普通任务通常按队列串行运行；实时模式使用常驻 UVR 与模型 Worker，减少重复加载。
