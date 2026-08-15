d

# API 速查

本页把插件开发中最常查的 TypeScript、页面 Client、Vue、Python、CLI、包格式和运行限制放在一起。需要背景解释和完整教程时，再跳到对应章节。

## 1. API 入口

| 入口                           | 运行位置          | 用途                                           |
| ------------------------------ | ----------------- | ---------------------------------------------- |
| `@xb-svcb/plugin-sdk`        | 开发机 Node.js    | 生成、校验和打包`xb-svcb-plugin.json`        |
| `@xb-svcb/plugin-sdk/client` | 自定义页面 iframe | 调用宿主动作、创建作品、读取插件资源和发送通知 |
| `@xb-svcb/plugin-sdk/vue`    | Vue 3 组件        | 页面 Client 的响应式封装                       |
| `xb_svcb_plugin`             | Python Worker     | 注册动作、流程钩子、生命周期并读写插件配置     |

不要把这些入口混用。`src/plugin.ts` 不会在用户页面中执行；`frontend/src/` 不会在 Node.js 清单构建阶段执行；Python 入口不会和页面共享内存。

## 2. CLI

```text
xb-plugin create <dir> --id <id> --name <name>
  [--type frontend|python|hybrid]
  [--language ts|js]
  [--framework vue|vanilla]
  [--version <version>]
  [--author <author>]

xb-plugin validate <dir>
xb-plugin pack <dir> [output.xbplugin]
```

| 命令         | 读取                          | 写入                 | 说明                                                        |
| ------------ | ----------------------------- | -------------------- | ----------------------------------------------------------- |
| `create`   | 命令行参数                    | 插件脚手架和初始清单 | TypeScript 前端默认 Vue；`--language js` 只能使用原生页面 |
| `validate` | `<dir>/xb-svcb-plugin.json` | 无                   | 只校验清单结构和 SDK 规则，不检查入口文件是否存在           |
| `pack`     | 插件目录                      | `.xbplugin`        | 先校验清单，再复制目录并压缩                                |

`pack` 默认忽略：

```text
node_modules, .git, .venv, __pycache__, .pytest_cache, *.xbplugin
```

宿主安装时还会检查包大小、路径穿越、入口路径和清单格式。打包成功不代表安装一定成功，安装成功也不代表 Python 入口一定能导入。

## 3. 清单顶层字段

`xb-svcb-plugin.json` 是宿主识别插件的唯一入口。推荐使用 `src/plugin.ts` 或 `build.mjs` 生成，不要长期手写构建产物。

| 字段            | 类型                                 | 必需 | 宿主处理                                             |
| --------------- | ------------------------------------ | ---- | ---------------------------------------------------- |
| `id`          | `string`                           | 是   | 稳定安装 ID，必须匹配`^[a-z0-9][a-z0-9._-]{2,63}$` |
| `name`        | `string`                           | 是   | 展示名，宿主截到 80 字符                             |
| `version`     | `string`                           | 是   | 版本，宿主截到 32 字符                               |
| `description` | `string`                           | 否   | 简介，宿主截到 400 字符                              |
| `author`      | `string`                           | 否   | 作者，宿主截到 80 字符                               |
| `runtime`     | `frontend`、`python`、`hybrid` | 是   | 决定是否加载前端和 Python                            |
| `python`      | `{ entry?: string }`               | 是   | Python 入口配置                                      |
| `frontend`    | `{ entry?: string }`               | 是   | 自定义页面入口配置                                   |
| `permissions` | `PluginPermission[]`               | 是   | 权限声明和审计展示                                   |
| `pages`       | `Page[]`                           | 是   | 声明式页面元数据                                     |
| `actions`     | `Action[]`                         | 是   | 页面可请求的动作                                     |
| `workflow`    | `{ before_create?: { params } }`   | 是   | 静态翻唱流程补丁                                     |

路径规则：

| 字段               | 允许                                                                        | 禁止                         |
| ------------------ | --------------------------------------------------------------------------- | ---------------------------- |
| `python.entry`   | 插件目录内相对`.py` 文件，例如 `plugin.py`、`backend/__init__.py`     | 绝对路径、`..`、非 `.py` |
| `frontend.entry` | 插件目录内相对`.html` 或 `.htm` 文件，例如 `dist/frontend/index.html` | 绝对路径、`..`、非 HTML    |

## 4. 运行类型

| Builder                                                            | 生成`runtime` | 典型用途                      |
| ------------------------------------------------------------------ | --------------- | ----------------------------- |
| `.frontend('dist/frontend/index.html')`                          | `frontend`    | 自定义页面或声明式页面        |
| `.python('plugin.py')`                                           | `python`      | Python 动作、钩子、声明式页面 |
| `.hybrid('plugin.py').frontendEntry('dist/frontend/index.html')` | `hybrid`      | 自定义页面调用 Python 动作    |

注意：

- `.frontend()` 会把运行时改为 `frontend` 并清空 Python 配置。
- `.python()` 和 `.hybrid()` 会自动加入 `python.execute` 权限。
- 混合插件设置页面入口时应使用 `.frontendEntry()`，不要在 `.hybrid()` 后再调用 `.frontend()`。

## 5. 权限

```ts
.permission('filesystem.data', 'network')
```

| 权限                  | 建议声明场景            |
| --------------------- | ----------------------- |
| `python.execute`    | Python 或混合插件，必需 |
| `filesystem.plugin` | 读取插件包内资源        |
| `filesystem.data`   | 读写插件数据目录或配置  |
| `network`           | 访问网络                |
| `process`           | 启动子进程              |
| `environment`       | 读取环境变量            |

权限不是操作系统沙箱。它们用于展示、审计和用户判断；Python 代码仍以当前用户权限运行。

## 6. 页面与字段

```ts
page('home', '快速翻唱', {
  description: '填写参数并创建任务。',
  fields: [],
  actions: ['create'],
})
```

| 字段            | 类型         | 说明                                |
| --------------- | ------------ | ----------------------------------- |
| `id`          | `string`   | 页面 ID，使用清单 ID 同样的格式规则 |
| `title`       | `string`   | 页面标题                            |
| `description` | `string`   | 页面说明                            |
| `fields`      | `Field[]`  | 声明式控件数组，校验要求存在        |
| `actions`     | `string[]` | 声明式页面显示的动作 ID             |

字段工厂：

```ts
fields.text(id, label, options?)
fields.textarea(id, label, options?)
fields.number(id, label, options?)
fields.switch(id, label, options?)
fields.select(id, label, options, config?)
```

| 类型         | `default` 类型         | 可用附加项                             |
| ------------ | ------------------------ | -------------------------------------- |
| `text`     | `string`               | `placeholder`、`help`              |
| `textarea` | `string`               | `placeholder`、`help`              |
| `number`   | `number`               | `placeholder`、`help`              |
| `switch`   | `boolean`              | `help`                               |
| `select`   | `string` 或 `number` | `options`、`placeholder`、`help` |

`select.options` 必须是非空数组，每项包含 `label` 和 `value`。当前插件中心通常只打开 `pages[0]`；如果需要多页面体验，建议在自定义 Vue 页面内部实现 tabs 或 memory router。

## 7. 动作

```ts
.message('hello', '打招呼', '你好，{{name}}！')
.createWork('create', '创建翻唱', payload)
.pythonAction('analyse', '分析参数', 'analyse_values')
```

| 类型            | 清单形状                                        | 宿主行为                                       |
| --------------- | ----------------------------------------------- | ---------------------------------------------- |
| `message`     | `{ id, label, type: 'message', message }`     | 插值后返回消息并显示成功通知                   |
| `create_work` | `{ id, label, type: 'create_work', payload }` | 插值后返回创建任务 payload，页面再触发正式创建 |
| `python`      | `{ id, label, type: 'python', handler }`      | 启动 Worker 调用 Python handler                |

动作 ID 使用清单 ID 同样的格式规则。Python `handler` 必须匹配：

```text
^[a-zA-Z_][a-zA-Z0-9_]{0,63}$
```

占位符规则：

- 只识别 `{{fieldId}}`，不执行表达式。
- `fieldId` 必须匹配 `^[a-zA-Z][a-zA-Z0-9_]{0,40}$`。
- 整个字符串只有一个占位符时，数字和布尔值保留原类型。
- 占位符嵌在其他文字中时，值转成字符串。
- 缺少值时，占位符原样保留。
- 对对象和数组递归插值。

## 8. `before_create` 静态参数

```ts
.beforeCreate({
  f0_method: 'rmvpe',
  device: 'auto',
})
```

静态补丁只补充 `payload.params` 中缺少的键，不覆盖用户已有选择。允许键：

```text
pitch, f0_method, index_rate, rms_mix, uvr_model, diffusion_ratio,
device, protect, filter_radius, rvc_version, ddsp_infer_steps,
ddsp_formant_shift, speaker
```

需要条件逻辑、读取配置、修改完整请求或处理多模型 payload 时，使用 Python `before_create` 钩子。

## 9. TypeScript 清单 SDK

```ts
import {
  fields,
  page,
  plugin,
  messageAction,
  createWorkAction,
  pythonAction,
  validateManifest,
  writeManifest,
  packPlugin,
} from '@xb-svcb/plugin-sdk'
```

核心类型：

```ts
type FieldType = 'text' | 'number' | 'select' | 'switch' | 'textarea'
type ActionType = 'message' | 'create_work' | 'python'
type PluginRuntime = 'frontend' | 'python' | 'hybrid'
type PluginPermission =
  | 'python.execute'
  | 'filesystem.plugin'
  | 'filesystem.data'
  | 'network'
  | 'process'
  | 'environment'
```

Builder 方法：

```ts
plugin(id: string, name: string, version = '1.0.0'): PluginBuilder

builder
  .description(value)
  .author(value)
  .frontend(entryOrConfig?)
  .frontendEntry(entry, config?)
  .python(entry = 'plugin.py')
  .hybrid(entry = 'plugin.py')
  .permission(...permissions)
  .page(pageObject)
  .page(id, title, configOrFactory)
  .action(actionObject)
  .message(id, label, message)
  .createWork(id, label, payload, options?)
  .pythonAction(id, label, handler?, options?)
  .beforeCreate(params)
  .build()
```

工厂函数：

```ts
page(id, title, configure?): Page
messageAction(id, label, message): MessageAction
createWorkAction(id, label, payload, options?): CreateWorkAction
pythonAction(id, label, handler = id, options?): PythonAction
validateManifest(input): ValidationResult
writeManifest(manifestOrBuilder, directory): Promise<string>
packPlugin(directory, output?): Promise<string>
createPlugin(options): Promise<PluginBuilder>
```

`validateManifest()` 只校验清单对象。它不会检查入口文件存在、Python 可导入、handler 已注册、包大小、页面能运行或创建任务 payload 满足业务规则。

## 10. 页面 Client

```ts
import {
  host,
  isHosted,
  request,
  type CreateWorkPayload,
  type HostMessageResult,
  type PluginHostContext,
} from '@xb-svcb/plugin-sdk/client'
```

宿主 API：

```ts
isHosted(): boolean

request<T = unknown>(
  method: string,
  payload?: Record<string, unknown>,
  options?: { timeoutMs?: number },
): Promise<T>

host.getContext(): Promise<PluginHostContext>
host.runAction(actionId, values?): Promise<HostMessageResult>
host.createWork(payload): Promise<CreatedWork>
host.assetData(path): Promise<HostAssetResult>
host.assetUrl(path): Promise<string>
host.notify(message, type?): Promise<true>
```

固定 method：`getContext`、`runAction`、`createWork`、`assetData`、`notify`。

请求规则：

- 页面必须在宿主注入 token 后才能调用；浏览器预览中会 reject。
- 默认超时 30 秒；`request(..., { timeoutMs: 0 })` 表示不设 Client 超时。
- 宿主失败时 Promise reject。
- 当前没有 AbortSignal、请求取消、自定义 RPC 或主题变化订阅。

上下文：

```ts
interface PluginHostContext {
  plugin: Manifest
  page?: Page
  theme?: string
}
```

动作结果：

```ts
interface HostMessageResult {
  ok?: boolean
  type?: 'message' | 'create_work'
  message?: string
  payload?: CreateWorkPayload
  work?: CreatedWork
  error?: string
}
```

资源结果：

```ts
interface HostAssetResult {
  ok: boolean
  name: string
  mime: string
  data: string
  error?: string
}
```

`assetUrl(path)` 返回 Data URL 字符串。路径相对插件安装根目录，不能是绝对路径，不能包含 `..`，单个资源最大 10 MB。

## 11. 创建作品类型

```ts
type CreateWorkflow =
  | 'auto_mix'
  | 'auto_vocal_merge'
  | 'manual_vocal_merge'
  | 'auto_then_editor'
  | 'full_manual_editor'

interface CreateWorkPayload {
  title?: string
  model_id?: string
  source_path?: string | null
  params?: InferenceParams
  workflow?: CreateWorkflow
  vocal_enhancement?: VocalEnhancementOptions
  mode?: 'single' | 'multi'
  models?: BlendModel[]
  segments?: BlendSegment[]
}

interface InferenceParams extends BeforeCreateParams {
  reference_audio?: string
}

interface BeforeCreateParams {
  pitch?: number
  f0_method?: string
  index_rate?: number
  rms_mix?: number
  uvr_model?: string
  diffusion_ratio?: number
  device?: string
  protect?: number
  filter_radius?: number
  rvc_version?: string
  ddsp_infer_steps?: number
  ddsp_formant_shift?: number
  speaker?: string | number
}
```

多模型：

```ts
interface BlendModel {
  model_id: string
  params: InferenceParams
}

interface BlendSegment {
  start: number
  end: number
  model_id: string
  model_ids?: string[]
}
```

美声增强：

```ts
interface VocalEnhancementOptions {
  enabled: boolean
  level: 'basic' | 'advanced'
  pitch_correction: number
  timing_alignment: number
  timbre_focus: number
  ai_eq: number
  ai_compressor: number
  ai_exciter: number
  stereo_width: number
  loudness_envelope: number
}
```

类型字段可选是为了兼容不同工作流。真实创建时仍要提供该工作流需要的模型、音频路径、参数和片段信息；业务校验失败会由宿主返回错误。

## 12. Vue `usePluginHost()`

```ts
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const {
  hosted,
  context,
  plugin,
  page,
  theme,
  loading,
  error,
  refreshContext,
  runAction,
  createWork,
  assetData,
  assetUrl,
  notify,
  clearError,
} = usePluginHost()
```

签名摘要：

```ts
usePluginHost(options?: { loadContext?: boolean }): {
  hosted: Readonly<Ref<boolean>>
  context: Readonly<Ref<PluginHostContext | null>>
  plugin: ComputedRef<Manifest | undefined>
  page: ComputedRef<Page | undefined>
  theme: ComputedRef<string>
  loading: Readonly<Ref<boolean>>
  error: Readonly<Ref<Error | null>>
  refreshContext(): Promise<PluginHostContext | undefined>
  runAction(actionId, values?): Promise<HostMessageResult>
  createWork(payload): Promise<CreatedWork>
  assetData(path): Promise<HostAssetResult>
  assetUrl(path): Promise<string>
  notify(message, type?): Promise<true>
  clearError(): void
}
```

行为：默认在 `onMounted()` 调用 `refreshContext()`；`{ loadContext: false }` 可关闭自动加载；浏览器预览中 `refreshContext()` 返回 `undefined`；失败会写入 `error` 并继续 throw；`loading` 使用并发计数。

## 13. Python SDK

```python
from xb_svcb_plugin import (
    ActionResult,
    Plugin,
    PluginContext,
    action,
    before_create,
    get_plugin,
)
```

入口模板：

```python
from xb_svcb_plugin import ActionResult, Plugin, PluginContext

plugin = Plugin("com.example.my-plugin")

@plugin.action("hello")
def hello(ctx: PluginContext, values: dict):
    return ActionResult.message_result("你好")

@plugin.before_create
def before_create(ctx: PluginContext, payload: dict):
    payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")
    return payload
```

`Plugin`：

| 成员                    | 说明                               |
| ----------------------- | ---------------------------------- |
| `Plugin(plugin_id)`   | 创建注册表并设为当前活动插件       |
| `id`                  | 插件 ID，必须与清单`id` 完全一致 |
| `actions`             | `dict[str, Handler]`             |
| `hooks`               | `dict[str, list[Handler]]`       |
| `action(name=None)`   | 注册动作；省略时使用函数名         |
| `hook(name)`          | 注册通用钩子                       |
| `before_create(func)` | 注册翻唱创建前钩子                 |
| `on_enable(func)`     | 注册启用生命周期                   |
| `on_disable(func)`    | 注册禁用生命周期                   |

处理函数签名：

| 类型              | 签名               | 返回值                                        |
| ----------------- | ------------------ | --------------------------------------------- |
| 动作              | `(ctx, values)`  | `ActionResult`、`dict`、`str`、`None` |
| `before_create` | `(ctx, payload)` | `dict` 或 `None`                          |
| `on_enable`     | `(ctx)`          | 返回值忽略                                    |
| `on_disable`    | `(ctx)`          | 返回值忽略                                    |

同步函数和 `async def` 都支持。Worker 会等待 awaitable。

`ActionResult`：

```python
ActionResult(type="message", message="", payload=None)
ActionResult.message_result(message)
ActionResult.create_work(payload)
result.to_dict()
```

返回值规范：

| Python 返回      | Worker 结果                                 |
| ---------------- | ------------------------------------------- |
| `ActionResult` | `result.to_dict()`                        |
| `str`          | `{ "type": "message", "message": value }` |
| `dict`         | 原样返回                                    |
| `None`         | `{}`                                      |

所有返回值必须能被 JSON 序列化。不要返回 `Path`、`bytes`、`set`、异常对象或自定义类实例。

`PluginContext`：

| 属性或方法                                                | 说明                                       |
| --------------------------------------------------------- | ------------------------------------------ |
| `plugin_id`                                             | 当前插件 ID                                |
| `plugin_dir`                                            | 插件安装根目录`Path`                     |
| `data_dir`                                              | 插件数据目录`Path`，创建上下文时确保存在 |
| `config`                                                | 从`data_dir/config.json` 读取的字典      |
| `save_config()`                                         | 原子写回`config.json`                    |
| `PluginContext.create(plugin_id, plugin_dir, data_dir)` | 本地单元测试时手工创建上下文               |

`plugin_dir` 适合读取包内只读资源；持久状态写入 `data_dir`。模块全局变量不会跨 Worker 调用可靠保留。

## 14. Python Worker 行为

```text
启动 Worker
  -> 加载宿主提供的 Python SDK
  -> 把插件入口目录加入 sys.path
  -> 如果存在 vendor/，加入 sys.path
  -> 导入 python.entry
  -> 校验 Plugin.id
  -> 创建 PluginContext
  -> 调用动作、钩子或生命周期
  -> JSON 返回结果
```

运行边界：

- 每个动作、钩子和生命周期调用都会启动新进程。
- 单次调用包含启动、导入和函数执行，总计 30 秒。
- 入口顶层不要做耗时初始化、下载、长连接或大模型加载。
- `print()` 会被重定向到 Worker 标准错误，成功调用不保证保存日志。
- 入口失败或处理函数异常时，宿主会把最多 12 层 traceback 写入插件数据目录的 `error.log`。
- `on_enable` 失败会阻止启用；`on_disable` 失败不阻止禁用。

## 15. 生命周期和数据保留

| 操作          | 代码目录 | 数据目录             | 状态                     |
| ------------- | -------- | -------------------- | ------------------------ |
| 首次安装      | 创建     | 首次上下文使用时创建 | 插件默认关闭             |
| 重新安装同 ID | 替换     | 保留                 | 插件重置为关闭           |
| 禁用插件      | 保留     | 保留                 | 调用`on_disable`       |
| 卸载插件      | 删除     | 删除                 | 不保证调用`on_disable` |

配置迁移建议放在 `on_enable` 中，并通过 `ctx.config["schema_version"]` 做可重复迁移。

## 16. 包格式和安装限制

| 项目                 | 限制        |
| -------------------- | ----------- |
| 压缩包               | 最大 20 MB  |
| 解压后总大小         | 最大 50 MB  |
| 清单文件             | 最大 512 KB |
| 自定义页面入口 HTML  | 最大 2 MB   |
| 单个页面资源         | 最大 10 MB  |
| 页面 Client 默认超时 | 30 秒       |
| Python Worker 调用   | 30 秒       |

安装器要求：

- 包中必须恰好包含一份 `xb-svcb-plugin.json`。
- 清单位于包根目录，或位于单一顶级目录内；安装时会规范化到插件根目录。
- 压缩包不能包含路径穿越。
- `frontend.entry` 若存在，安装时会确认文件存在且是 HTML。
- `python.entry` 的文件存在性在启用或执行时再次确认。
- 新安装和重新安装后插件都处于关闭状态。

## 17. 市场索引

插件市场配置和远程安装只接受 GitHub HTTPS 地址，包括 `github.com`、`api.github.com` 和 `githubusercontent.com` 相关域名。

```json
{
  "plugins": [
    {
      "id": "com.example.my-plugin",
      "name": "我的插件",
      "version": "1.0.0",
      "description": "插件简介",
      "author": "Example",
      "bundle_url": "https://github.com/example/repo/releases/download/v1.0.0/my-plugin.xbplugin"
    }
  ]
}
```

宿主读取市场时会忽略 ID 无效、`bundle_url` 非 GitHub HTTPS 或形状不正确的条目。

## 18. 常见失败点

| 现象                      | 首先检查                                                             |
| ------------------------- | -------------------------------------------------------------------- |
| `npm run validate` 失败 | 清单 ID、`pages[].fields`、运行类型、权限、入口路径格式            |
| 能打包但不能安装          | 包大小、清单数量、入口 HTML 是否存在、路径是否含`..`               |
| 安装后打不开页面          | 全局插件功能、单插件启用状态、`frontend.entry`、入口 HTML 大小     |
| 浏览器预览调用失败        | 这是正常的，普通浏览器没有宿主 token                                 |
| Python 插件不能启用       | `python.entry` 是否打包、入口导入是否失败、`Plugin(id)` 是否匹配 |
| 未注册 Python 动作        | 页面 action ID、清单 handler、`@plugin.action()` 注册名是否一致    |
| 动作超时                  | 入口导入和函数执行合计超过 30 秒                                     |
| 配置没保存                | 修改`ctx.config` 后是否调用 `ctx.save_config()`                  |
| `before_create` 没生效  | 全局开关、插件启用、装饰器、返回值、其他插件后续覆盖                 |
| 资源读取失败              | 路径是否相对插件根、是否包含`..`、文件是否超过 10 MB               |

## 19. 发布前最低检查

```powershell
npm run typecheck
npm run validate
npm run pack
```

然后在真实 XB-SVCB 中完成：

- 安装 `.xbplugin`；
- 开启全局插件功能；
- 单独启用插件；
- 打开自定义页面或声明式页面；
- 运行每个动作；
- 创建一次真实测试任务；
- 禁用插件并确认不会继续执行；
- 检查 Python 插件数据目录中的 `error.log`。

发布包不要包含令牌、私有路径、测试音频、未审查依赖、`.venv`、`node_modules` 或旧 `.xbplugin`。
