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

- `entities.py`：`ModelInfo` / `Work` / `PipelineStep` / `InferenceParams` 等实体与值对象。
  其中 `InferenceParams.from_dict` 是所有推理入口的参数归一化点，`ModelInfo.engine_paths`
  是「模型记录 → 引擎文件路径」的唯一映射（作品/编辑器/实时翻唱三个服务共用），
  `PipelineStep` 负责流水线步骤的初始状态，`apply_step_status` 负责状态迁移校验；
  `Work` 只用于作品创建（记录携带大量扩展字段，故不提供有损的 `from_dict`）；
- `enums.py`：`JobStatus` / `StepStatus` / `ModelType`；
- `audio_editor.py`：时间轴工程、轨道、片段实体；
- `audio_editor_rules.py`：工程/效果/包络归一化、时长与拉伸度量、片段与轨道查找、波形重算判定；
- `lyrics.py`：LRC 与普通 TXT 歌词解析、按比例自动配时、由静音区间推导演唱范围；
- `workflow_graph.py`：自定义工作流的节点图模型、图校验与拓扑排序；
- `work_request.py`：任务创建请求的业务规则（模式、工作流、模型、分句、参考音频）；
- `vocal_enhancement.py`：歌声增强等级、强度归一化与设置解析规则；
- `identity.py`：实体 ID 生成；
- `formatting.py`：体积/时长的纯格式化函数。

### `app/application/` — 用例层（编排）

每个服务 = 一个用例集合，负责「取数据 → 调领域规则/端口 → 落库 → 返回 DTO」：

- 作品与推理：`work_service`、`conversion_service`、`realtime_cover_service`；
- 模型：`model_service`、`model_hub_service`；
- 编辑器与媒体：`audio_editor_service`（工程/轨道/片段与插件会话）、
  `editor_render_service`（渲染、预览、波形）、`media_service`（试听/导出/时长）、
  `audio_import_service`（拖拽与分块上传）、`theme_media_service`（背景媒体）；
- 其他：`music_service`、`plugin_service`（插件安装/运行时）、
  `plugin_market.py`（插件市场解析规则）、`system_service`、
  `data_maintenance_service`（数据目录查看/切换/迁移）。

`ports.py` 定义仓储与网关协议，`adapters.py` 是唯一的默认适配器接缝：
里面用**函数内延迟导入**提供默认实现，供「没有组合根」的脚本与单测使用。
新代码应优先显式注入，不要继续往接缝里加默认值。

### `app/api/` — 表现层（适配器）

- `bridge.py`：pywebview JS 桥 `Api`，只做参数转换、原生对话框与用例委派；
- `http_server.py`：FastAPI 路由与响应模型，与 Bridge 复用同一批用例服务。

表现层不做业务计算、不读写业务文件、不新建基础设施对象。

### `app/infrastructure/` — 适配层

- 存储：`storage.py`（JSON 仓储）；`theme_media.py`、`audio_import.py`（本地媒体落盘）、
  `work_files.py`（作品工作目录与运行日志）、`editor_project_store.py`（编辑器工程目录、
  渲染/波形缓存、工程包 zip）、`data_transfer.py`（数据目录迁移搬运）
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

已收敛（全部完成）：

- 组合根从 `api/bridge.py` 移到 `app/composition.py`，表现层不再 import 基础设施；
- 用例层 42 处 `from infrastructure...` 全部改为 `application.ports` / `application.adapters`；
- 工作流节点图、歌声增强规则、ID 与体积格式化下沉到 `domain/`；
- 主题媒体、音频导入、作品试听/导出、VST3 目录扫描从表现层迁出；
- 数据目录查看/切换/迁移整段（约 500 行）迁到 `DataMaintenanceService`，
  文件系统能力落到 `infrastructure/data_transfer.py`；
- 任务创建请求规则集中到 `domain/work_request.py`，由 `WorkService.validate_request` 编排，
  HTTP 适配器只保留上传件解析与错误映射；
- HTTP 层不再访问门面私有成员（`facade.models` / `facade.editor` / `facade.work_stem_path` /
  `facade.validate_work_request`）；
- 领域实体承担真实职责：`ModelInfo.engine_paths` 收敛三处重复映射、
  `PipelineStep` + `apply_step_status` 统一流水线步骤与状态校验、
  框架判定由 `config` 委托领域层，删除无人调用的 `Work.from_dict`；
- 编辑器纯规则下沉到 `domain/audio_editor_rules.py` 与 `domain/lyrics.py`
  （用例层保留同名薄封装），覆盖见 `app/tests/test_domain_editor_rules.py`；
- 用例层不再直接做文件 I/O：作品工作目录/日志走 `WorkFilesPort`（`infrastructure/work_files.py`），
  编辑器工程目录、渲染/波形缓存、音频 data URI、工程包 zip 走 `EditorProjectStorePort`
  （`infrastructure/editor_project_store.py`），两者由组合根显式注入；
- `audio_editor_service` 按用例拆分：渲染/预览/波形移到 `application/editor_render_service.py`，
  `plugin_service` 的市场解析规则移到 `application/plugin_market.py`；
- 重新审视后确认无需清理的点：`JobStatus` / `StepStatus` / `ModelType` 枚举、
  `EditorClip/Track/Project` 实体、`InferenceParams` 均在生产路径上被使用（见
  `app/tests/test_domain_entities.py`、`app/tests/test_domain_editor_rules.py`）。

## 架构约定（不是债务）

以下几点是**有意的设计选择**，后续改动请保持，而不是当作待清理项：

1. **边界 DTO**：Bridge / FastAPI 的入参出参与仓储里持久化的作品记录都是 `dict`
   （记录含大量前端消费的扩展字段）。领域实体负责规则与映射，边界保持 JSON 友好的
   字典；不要为了「纯实体」把这些结构改成对象，那会破坏前端契约。
2. **服务规模**：拆分依据是「一个用例集合」，不是行数。`audio_editor_service`
   仍包含工程生命周期、片段编辑、插件会话与重推理编排，这些共享同一批不变量，
   不宜继续机械拆分；新增用例优先新建服务，不要继续加进已有大类。
3. **默认适配器接缝**：`application/adapters.py` 允许函数内延迟导入基础设施，
   仅用于「组合根未注入时」的默认实现与单测；生产路径由 `composition.py` 显式注入，
   新代码优先走显式注入。
4. **进程内音频工具调用**：FFmpeg / UVR / 引擎都是端口后面的适配器，
   用例层可以编排它们的调用顺序，但不能在模块级 import 它们。

## 校验

    app\.venv\Scripts\python.exe -m pytest app\tests -q
    app\.venv\Scripts\python.exe -m pytest app\tests\test_architecture.py -q
