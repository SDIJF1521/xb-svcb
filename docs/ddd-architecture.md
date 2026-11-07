[简体中文](ddd-architecture.md)

# 分层架构约束（DDD）

本文定义 `app/` 的分层契约。规则不只写在文档里：`app/tests/test_architecture.py`
会用 AST 静态分析把下列约束变成会失败的测试，防止后续改动悄悄破坏依赖方向。

## 四条红线

| 层 | 目录 | 允许依赖 | 禁止依赖 |
| --- | --- | --- | --- |
| 表现层 | `app/api/` | 标准库、`config`、`application`、`domain`、pywebview/FastAPI | `infrastructure`、`composition` |
| 用例层 | `app/application/` | 标准库、`config`、`domain`、`application.ports`、`application.adapters` | `api`、`infrastructure`、`composition` |
| 领域层 | `app/domain/` | 标准库、`domain.*` | `application`、`infrastructure`、`api`、`config`、任何三方框架 |
| 适配层 | `app/infrastructure/` | 标准库、`config`、`domain` | `application`、`api`、`composition` |

依赖方向：

    api ─────► application ─────► domain
     │              │                ▲
     │              │                │
     │        application.ports      │
     │              ▲                │
     │              │                │
     └─ 注入 ── composition ──► infrastructure ┘

* 内层不认识外层：`domain` 不知道 Python 进程里有没有 FFmpeg、FastAPI 或 pywebview。
* 用例层只依赖抽象：需要转码、分离、推理、存储时，依赖 `application/ports.py` 中的
  协议，而不是 `infrastructure` 的具体类。
* 适配层实现抽象：`infrastructure` 里的类以结构化方式满足端口协议，
  由 `app/tests/test_architecture.py` 校验是否仍有对应属性和方法。
* 只有一个装配点：`app/composition.py` 创建适配器、仓储与用例服务，
  再注入表现层 `Api`。`app/main.py` 只调用 `composition.build_api()`。

## 各层职责

### `app/domain/` — 领域层（内核）

纯业务规则，无 I/O、无框架、可单测：

- `entities.py`：`ModelInfo` / `Work` / `PipelineStep` / `InferenceParams` 等实体与值对象；
- `enums.py`：`JobStatus` / `StepStatus` / `ModelType`；
- `audio_editor.py`：时间轴工程、轨道、片段实体；
- `workflow_graph.py`：自定义工作流的节点图模型、图校验与拓扑排序；
- `work_request.py`：任务创建请求的业务规则（模式、工作流、模型、分句、参考音频）；
- `vocal_enhancement.py`：歌声增强等级、强度归一化与设置解析规则；
- `identity.py`：实体 ID 生成；
- `formatting.py`：体积/时长的纯格式化函数。

### `app/application/` — 用例层（编排）

每个服务 = 一个用例集合，负责「取数据 → 调领域规则/端口 → 落库 → 返回 DTO」：

- 作品与推理：`work_service`、`conversion_service`、`realtime_cover_service`；
- 模型：`model_service`、`model_hub_service`；
- 编辑器与媒体：`audio_editor_service`、`media_service`（试听/导出/时长）、
  `audio_import_service`（拖拽与分块上传）、`theme_media_service`（背景媒体）；
- 其他：`music_service`、`plugin_service`、`system_service`、
  `data_maintenance_service`（数据目录查看/切换/迁移）。

`ports.py` 定义仓储与网关协议，`adapters.py` 是唯一的默认适配器接缝：
里面用**函数内延迟导入**提供默认实现，供「没有组合根」的脚本与单测使用。
新代码应优先显式注入，不要继续往接缝里加默认值。

### `app/api/` — 表现层（适配器）

- `bridge.py`：pywebview JS 桥 `Api`，只做参数转换、原生对话框与用例委派；
- `http_server.py`：FastAPI 路由与响应模型，与 Bridge 复用同一批用例服务。

表现层不做业务计算、不读写业务文件、不新建基础设施对象。

### `app/infrastructure/` — 适配层

- 存储：`storage.py`（JSON 仓储）；`theme_media.py`、`audio_import.py`（本地媒体落盘）
- 音频：`ffmpeg_tool.py`、`audio_engine.py`、`ffmpeg` 之上的渲染能力
- 分离与推理：`uvr_tool.py`、`pymss_tool.py`、`*_engine.py`、`*_worker.py`
- 系统集成：`clipboard.py`、`system_audio.py`、`juce_vst3_host.py`、`window_theme.py`、`single_instance.py`

### 层外模块

- `app/config.py`：全局元信息与数据目录，被各层使用，但**领域层不得依赖**。
- `app/composition.py`：组合根，唯一可以同时认识所有层的地方。
- `app/main.py`：桌面入口（pywebview 窗口、单实例、退出清理）。

## 新增功能该放哪

1. 是纯计算 / 校验 / 状态流转？→ `domain/`（配 `app/tests/` 单测）。
2. 需要读写文件、进程、网络、模型？→ `infrastructure/`，并在
   `application/ports.py` 声明它暴露给用例层的协议。
3. 是「用户能触发的一次操作」？→ `application/` 的用例服务方法。
4. 只是把参数搬进搬出、弹对话框？→ `api/`，且只调用用例服务。
5. 需要在启动时接线？→ `composition.build_api()`。

改完运行：

    app\.venv\Scripts\python.exe -m pytest app\tests\test_architecture.py -q

## 迁移台账

已收敛的违例：

- 组合根从 `api/bridge.py` 移到 `app/composition.py`，表现层不再 import 基础设施；
- 用例层 42 处 `from infrastructure...` 全部改为 `application.ports` / `application.adapters`；
- 工作流节点图、歌声增强规则、ID 与体积格式化下沉到 `domain/`；
- 主题媒体、音频导入、作品试听/导出、VST3 目录扫描从表现层迁出，
  分别落到 `theme_media_service`、`audio_import_service`、`media_service`、`plugin_service`；
- 数据目录查看/切换/迁移整段（约 500 行）迁到 `DataMaintenanceService`，
  文件系统能力落到 `infrastructure/data_transfer.py`（`DataTransferPort`），
  `api/bridge.py` 只剩转发，覆盖见 `app/tests/test_data_maintenance.py`；
- 任务创建请求规则（模式 / 工作流 / 模型 / 分句 / SeedVC 参考音频）集中到
  `domain/work_request.py`，由 `WorkService.validate_request` 编排；
  HTTP 适配器只保留上传件解析与错误映射，覆盖见 `app/tests/test_work_request.py`；
- HTTP 层不再访问门面私有成员，改用 `facade.models` / `facade.editor` /
  `facade.work_stem_path` / `facade.validate_work_request`。

仍存在的债务（按优先级，属于持续演进项）：

1. 用例层仍有直接的文件 I/O：编辑器工程包（zip）导入导出、作品运行日志、
   渲染缓存与波形缓存。下一步把它们收敛到端口，例如
   `ProjectBundleStore`（读写工程包）与 `WorkFilesPort`（工作目录、日志、缓存），
   实现放在 `infrastructure`。
2. 多数用例服务仍以 `dict[str, Any]` 作为内部传输结构，实体只在作品创建、
   编辑器工程、模型记录等路径使用。建议按用例逐个归一化入参为领域实体/值对象，
   边界（Bridge/HTTP）继续使用 DTO——边界 DTO 本身不是违例。
3. `audio_editor_service`（约 3600 行）与 `plugin_service` 仍偏大，可按用例继续拆分
   （时间轴渲染、片段重推理、插件市场、插件运行时）。
4. 编辑器工程与效果的归一化规则（`_clean_*`）仍在用例层，可继续下沉到
   `domain/audio_editor.py`，作为工程实体的不变量。
