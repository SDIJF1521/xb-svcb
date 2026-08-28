# Python 插件开发

本文面向 XB-SVCB 的纯 Python 插件和混合插件后端开发者。按照本文操作，可以在不阅读主项目源码的情况下完成插件创建、动作与钩子编写、持久化、依赖打包、测试、调试和发布。

本文描述的是当前 Python SDK `0.1.0` 和当前宿主实现。Python 插件是受信任代码：宿主使用独立进程隔离崩溃，但它不是安全沙箱。只安装和启用你信任的 Python 插件。

## 1. 先理解运行模型

一个 Python 插件由两部分组成：

- `xb-svcb-plugin.json` 描述插件身份、运行时、入口、权限、页面和动作；
- Python 入口在导入时创建一个 `Plugin`，并通过装饰器注册动作、翻唱钩子和生命周期函数。

宿主执行一次 Python 调用时，流程如下：

```text
用户点击动作 / 宿主创建翻唱 / 用户启用插件
                    │
                    ▼
             启动新的 Python Worker
                    │
                    ▼
        加载宿主提供的 xb_svcb_plugin SDK
                    │
                    ▼
      加载本次安装包内声明的 Python 入口
                    │
                    ▼
       校验 Plugin.id 与清单 id 完全相同
                    │
                    ▼
          创建本次调用的 PluginContext
                    │
                    ▼
          调用同步或异步处理函数
                    │
                    ▼
        通过 JSON 把结果返回给桌面宿主
```

必须记住以下事实：

1. 每个动作、钩子或生命周期调用都会启动一个新进程并重新导入入口模块。
2. 模块全局变量不会在两次调用之间可靠保留；需要持久化的数据应写入 `ctx.config` 或 `ctx.data_dir`。
3. 单次调用包含进程启动、模块导入和处理函数执行，合计最多 30 秒。
4. Worker 与桌面进程隔离，因此插件崩溃通常不会直接导致桌面进程退出。
5. Worker 继承当前用户的系统权限；它可以像普通本地 Python 程序一样访问文件、网络、环境变量和子进程。

## 2. 选择纯 Python 还是混合插件

两种插件使用同一套 Python SDK。

| 模式 | `runtime` | 页面 | 适合场景 |
| --- | --- | --- | --- |
| 纯 Python | `python` | 可以没有页面，也可以使用清单声明的宿主表单 | 翻唱默认参数、自动处理、简单表单动作 |
| 混合插件 | `hybrid` | 自定义 Vue/TypeScript 页面 + Python 后端 | 自定义布局、复杂交互、需要后端计算的工具 |

纯 Python 不等于“不能有界面”。它可以通过清单的 `pages`、`fields` 和 `actions` 使用宿主提供的声明式表单，只是不包含自定义前端代码。

混合插件的自定义页面通过页面 SDK 调用清单中的 Python 动作：

```ts
const result = await runAction('create', {
  source_path: sourcePath.value,
  model_id: modelId.value,
})
```

宿主根据动作 ID 找到清单中的 `handler`，再调用 Python 入口里注册的同名处理函数。

## 3. 环境准备

### 3.1 必需环境

- Python 3.10 或更高版本；
- Node.js `^20.19.0` 或 `>=22.12.0`，用于官方脚手架、清单校验和打包；
- XB-SVCB，用于最终安装测试。

Python SDK 本身没有第三方依赖。宿主运行插件时会自动提供 SDK，插件包中不需要也不应复制 `xb_svcb_plugin`。

### 3.2 创建本地虚拟环境

在插件项目目录执行：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Linux 或 macOS 的本地开发环境可以使用：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

`.venv` 只用于本地开发。官方打包器会忽略 `.venv`，宿主也不会使用插件自己的虚拟环境。

### 3.3 安装本地 Python SDK

如果插件项目位于 XB-SVCB 仓库内，可以从仓库根目录执行：

```powershell
python -m pip install -e .\plugin-sdk\python
```

如果插件是独立仓库，传入本机 XB-SVCB 仓库中的 SDK 路径：

```powershell
python -m pip install -e "D:\path\to\XB-SVCB\plugin-sdk\python"
```

确认安装成功：

```powershell
python -c "from xb_svcb_plugin import Plugin, PluginContext, ActionResult; print('SDK OK')"
```

编辑安装 `-e` 只影响本地开发环境。运行已安装插件时，宿主始终加载自己附带的 SDK。

## 4. 五分钟完成第一个纯 Python 插件

### 4.1 创建脚手架

```powershell
npx @xb-svcb/plugin-sdk create my-python-plugin `
  --id com.example.my-python-plugin `
  --name "我的 Python 插件" `
  --type python

cd my-python-plugin
npm install
```

如果你正在 XB-SVCB 仓库内开发，也可以直接运行本地 CLI：

```powershell
node .\plugin-sdk\bin\xb-plugin.mjs create my-python-plugin `
  --id com.example.my-python-plugin `
  --name "我的 Python 插件" `
  --type python
```

脚手架默认生成以下文件：

```text
my-python-plugin/
├─ src/
│  └─ plugin.ts               # 构建 xb-svcb-plugin.json 的清单源码
├─ plugin.py                  # Python 入口
├─ package.json               # 校验和打包脚本
├─ package-lock.json          # npm install 后生成的依赖锁文件
├─ tsconfig.json              # 清单源码类型检查
└─ xb-svcb-plugin.json        # 构建生成的清单
```

`src/plugin.ts` 是构建源，`xb-svcb-plugin.json` 是生成结果。使用脚手架时应修改前者，不要只修改后者，因为下一次 `npm run build` 会重新生成 JSON。

### 4.2 编写 Python 入口

将 `plugin.py` 替换为：

```python
from typing import Any

from xb_svcb_plugin import Plugin, PluginContext


plugin = Plugin("com.example.my-python-plugin")


@plugin.on_enable
def on_enable(ctx: PluginContext) -> None:
    ctx.config.setdefault("create_count", 0)
    ctx.save_config()


@plugin.before_create
def apply_defaults(
    ctx: PluginContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    params = payload.setdefault("params", {})
    params.setdefault("f0_method", "rmvpe")
    params.setdefault("device", "auto")

    ctx.config["create_count"] = int(ctx.config.get("create_count", 0)) + 1
    ctx.save_config()
    return payload
```

`Plugin(...)` 中的 ID 必须与清单 ID 完全一致，包括大小写。当前清单 ID 只允许小写字母、数字、点、下划线和连字符。

### 4.3 定义清单

将 `src/plugin.ts` 写成：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin(
  'com.example.my-python-plugin',
  '我的 Python 插件',
  '1.0.0',
)
  .description('为每次翻唱补充默认参数。')
  .author('你的名字')
  .python('plugin.py')
  .permission('filesystem.data')

await writeManifest(app, '.')
```

`.python('plugin.py')` 会设置 `runtime: "python"` 并自动声明 `python.execute`。因为示例写入持久化配置，所以额外声明 `filesystem.data`。

### 4.4 校验、打包和安装

```powershell
npm run typecheck
npm run validate
npm run pack
```

打包成功后会生成 `.xbplugin` 文件。进入 XB-SVCB 的插件中心：

1. 开启全局“插件功能”；
2. 安装本地 `.xbplugin`；
3. 单独启用刚安装的插件；
4. 创建一次翻唱，检查缺失的 `f0_method` 和 `device` 是否被补充。

新安装或重新安装的插件默认处于禁用状态。Python 插件启用时会先导入入口并运行 `on_enable`；如果入口导入或 `on_enable` 失败，插件不会被启用。

## 5. 完整目录设计

单文件入口适合最小插件。稍复杂的插件建议使用包入口：

```text
my-cover-assistant/
├─ backend/
│  ├─ __init__.py             # python.entry，创建 Plugin 并注册处理函数
│  ├─ rules.py                # 可测试的业务规则
│  └─ resources.py            # 资源读取等辅助逻辑
├─ assets/
│  └─ defaults.json           # 随插件安装的只读资源
├─ vendor/                    # 打包的第三方 Python 依赖
├─ tests/
│  └─ test_backend.py
├─ src/
│  └─ plugin.ts               # 清单构建源码
├─ plugin.py                  # 使用包入口后可以删除
├─ package.json
├─ package-lock.json
├─ tsconfig.json
├─ xb-svcb-plugin.json        # npm run build 生成
└─ my-cover-assistant.xbplugin
```

混合插件在此基础上增加前端源码和构建结果：

```text
my-hybrid-plugin/
├─ backend/
│  ├─ __init__.py
│  └─ rules.py
├─ frontend/
│  ├─ index.html
│  └─ src/
│     ├─ App.vue
│     ├─ main.ts
│     └─ components/
├─ dist/
│  └─ frontend/
│     └─ index.html           # Vite 单文件构建结果
├─ vendor/
├─ tests/
├─ src/plugin.ts
├─ vite.config.ts
├─ package.json
├─ tsconfig.json
└─ xb-svcb-plugin.json
```

官方打包器不会包含以下目录：`node_modules`、`.git`、`.venv`、`__pycache__`、`.pytest_cache`。它也不会把已有的 `.xbplugin` 再打进新包。

## 6. Python 清单字段

插件包内必须只有一份 `xb-svcb-plugin.json`。官方打包器把它放在插件包根目录，这也是推荐结构。安装器也兼容“单一顶级目录中包含清单”的压缩包，并在安装时把该目录规范化为插件根目录，但不要依赖更深或含多份清单的结构。

`id`、`name` 和 `version` 必须是非空字符串。宿主读取后会把 `name` 截到 80 个字符、`version` 截到 32 个字符、`description` 截到 400 个字符、`author` 截到 80 个字符。`pages` 和 `actions` 应为数组；SDK 构建器会自动生成所有基础字段。

Python 后端相关的最小清单如下：

```json
{
  "id": "com.example.my-plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "description": "示例插件",
  "author": "Example",
  "runtime": "python",
  "python": {
    "entry": "backend/__init__.py"
  },
  "frontend": {},
  "permissions": [
    "python.execute",
    "filesystem.plugin",
    "filesystem.data"
  ],
  "pages": [],
  "actions": [],
  "workflow": {}
}
```

### 6.1 `id`

规则为：

- 长度 3 到 64 个字符；
- 第一个字符必须是小写字母或数字；
- 其余字符只能是小写字母、数字、`.`、`_`、`-`。

推荐反向域名格式，例如 `com.example.cover-tools`。Python 中的 `Plugin(id)` 必须与它完全一致。

### 6.2 `runtime`

- 纯 Python：`python`；
- 自定义前端 + Python：`hybrid`。

不要在 `frontend` 运行时中声明 Python 动作。它没有可运行的 Python 入口。

### 6.3 `python.entry`

入口必须满足：

- 是插件根目录内的相对路径；
- 以 `.py` 结尾；
- 不能是绝对路径；
- 路径中不能出现 `..`；
- 打包后文件必须真实存在。

有效示例：

```json
{ "entry": "plugin.py" }
```

```json
{ "entry": "backend/__init__.py" }
```

无效示例：

```json
{ "entry": "../shared/plugin.py" }
```

```json
{ "entry": "C:/plugins/plugin.py" }
```

安装阶段会校验入口路径格式，但当前宿主在启用或实际执行时才确认 Python 文件存在。因此“安装成功但启用失败”时，首先检查包内入口文件。

### 6.4 `permissions`

Python 或混合插件必须声明 `python.execute`。当前允许值如下：

| 权限 | 应在何时声明 |
| --- | --- |
| `python.execute` | 所有 Python 和混合插件，必需 |
| `filesystem.plugin` | 读取插件包内资源 |
| `filesystem.data` | 读取或写入插件数据目录、配置 |
| `network` | 发起网络请求 |
| `process` | 启动外部进程 |
| `environment` | 读取或使用环境变量 |

这些权限当前用于清单校验、展示和安全审计，不是操作系统级能力开关。声明较少的权限不会把 Python 进程限制在对应能力内，声明权限也不会让代码获得当前用户原本没有的系统权限。

### 6.5 Python 动作声明

Python 函数只有同时满足“入口中注册”和“清单中声明”才可以从页面调用：

```json
{
  "id": "create",
  "label": "创建翻唱",
  "type": "python",
  "handler": "build_cover"
}
```

- `id` 是页面调用的动作 ID；
- `handler` 是 Python 注册名；
- `handler` 必须是 1 到 64 位的 Python 标识符形式：字母或下划线开头，后续只能包含字母、数字和下划线。

动作 ID 可以含连字符，但处理器名不能。例如动作 ID 可以是 `create-cover`，对应处理器应显式写为 `build_cover`。

## 7. 创建和注册 `Plugin`

入口模块导入时必须创建 `Plugin`：

```python
from xb_svcb_plugin import Plugin

plugin = Plugin("com.example.my-plugin")
```

Worker 完成入口导入后会读取当前活动插件。如果入口没有创建 `Plugin`，会得到：

```text
插件入口必须先创建 Plugin(plugin_id)
```

不要在函数内部延迟创建插件，也不要根据运行参数有条件地创建。注册代码必须在模块导入时执行。

一个入口应只创建一个 `Plugin`。如果创建多个实例，最后创建的实例会成为活动插件，之前实例上注册的处理函数不会被 Worker 使用。

### 7.1 实例装饰器

推荐始终使用实例装饰器：

```python
@plugin.action("hello")
def hello(ctx, values):
    return "你好"


@plugin.before_create
def before_create(ctx, payload):
    return payload


@plugin.on_enable
def on_enable(ctx):
    pass
```

`action` 必须带括号：使用 `@plugin.action()` 或 `@plugin.action("name")`，不要写成 `@plugin.action`。

### 7.2 模块级装饰器

SDK 也导出模块级 `action` 和 `before_create`：

```python
from xb_svcb_plugin import Plugin, action, before_create

plugin = Plugin("com.example.my-plugin")


@action("hello")
def hello(ctx, values):
    return "你好"


@before_create
def patch(ctx, payload):
    return payload
```

模块级装饰器依赖已经存在的活动插件，因此必须先执行 `Plugin(...)`。生命周期和通用钩子建议使用实例方法。

### 7.3 重名和注册顺序

- 相同名称的动作重复注册时，后注册的函数覆盖前一个；
- 同名钩子可以注册多个，按注册顺序执行；
- 生命周期本质上也是名为 `on_enable` 和 `on_disable` 的钩子列表。

## 8. 编写 Python 动作

动作处理函数签名是：

```python
def handler(
    ctx: PluginContext,
    values: dict[str, Any],
) -> ActionResult | dict[str, Any] | str | None:
    ...
```

异步函数使用完全相同的参数：

```python
async def handler(ctx: PluginContext, values: dict[str, Any]):
    ...
```

`values` 来自声明式页面字段或自定义前端调用 `runAction(actionId, values)` 时传入的对象。它经过 JSON 通信，因此只应依赖 JSON 类型：对象、数组、字符串、数字、布尔值和 `null`。

### 8.1 注册名与清单映射

Python：

```python
@plugin.action("build_cover")
def build_cover(ctx: PluginContext, values: dict[str, Any]):
    ...
```

清单：

```json
{
  "id": "create",
  "label": "创建翻唱",
  "type": "python",
  "handler": "build_cover"
}
```

页面调用：

```ts
await runAction('create', values)
```

三处名称的关系是：页面使用动作 `id`，宿主读取它的 `handler`，Worker 在 `plugin.actions` 中查找注册名。

如果装饰器不传名称，会使用函数名：

```python
@plugin.action()
def build_cover(ctx, values):
    ...
```

### 8.2 动作返回值

Worker 接受四种返回值：

| Python 返回值 | 返回给宿主的结果 |
| --- | --- |
| `ActionResult` | 调用 `to_dict()` 后返回 |
| `str` | `{"type": "message", "message": value}` |
| `dict` | 原样作为结果对象返回 |
| `None` | 空结果对象 `{}` |

其他类型会失败，并显示：

```text
插件返回值必须是 dict、str、ActionResult 或 None
```

所有返回内容必须能够被 `json.dumps` 序列化。不要返回 `Path`、`set`、`bytes`、异常对象、自定义类实例或未转换的 dataclass。

推荐不要在自定义字典中返回 `ok` 键。宿主会把结果合并到自己的响应中，自定义 `ok` 可能覆盖宿主的成功状态。

### 8.3 返回消息

最简方式是返回字符串：

```python
@plugin.action("hello")
def hello(ctx, values):
    return f"你好，{values.get('name') or '朋友'}"
```

等价的显式写法：

```python
return ActionResult.message_result("处理完成")
```

### 8.4 返回创建翻唱任务

```python
from xb_svcb_plugin import ActionResult


@plugin.action("build_cover")
async def build_cover(ctx: PluginContext, values: dict[str, Any]) -> ActionResult:
    return ActionResult.create_work(
        {
            "source_path": str(values.get("source_path") or ""),
            "model_id": str(values.get("model_id") or ""),
            "title": str(values.get("title") or "插件翻唱"),
            "workflow": "auto_mix",
            "params": {
                "pitch": 0,
                "f0_method": "rmvpe",
            },
        }
    )
```

声明式页面和自定义插件页面收到 `type: "create_work"` 后，当前宿主会调用正式的创建翻唱接口。正式创建阶段仍会统一执行一次 `before_create`，所以动作函数不要自行重复调用钩子。

### 8.5 返回自定义数据

自定义 Vue 页面可以消费任意 JSON 字典：

```python
@plugin.action("analyse")
def analyse(ctx, values):
    return {
        "type": "analysis",
        "payload": {
            "score": 0.92,
            "warnings": [],
        },
    }
```

前端应自行判断 `result.type`。当前宿主只对 `message` 和 `create_work` 提供内置行为。

## 9. 翻唱流程钩子 `before_create`

`before_create` 在正式创建翻唱任务前运行，用于补充或修改请求：

```python
@plugin.before_create
def apply_defaults(
    ctx: PluginContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    params = payload.setdefault("params", {})
    params.setdefault("f0_method", "rmvpe")
    params.setdefault("device", "auto")
    return payload
```

处理函数接收：

- `ctx`：插件上下文；
- `payload`：当前完整创建请求。

返回规则：

- 返回 `dict`：用该字典作为后续处理的新请求；
- 返回 `None`：保留当前请求，包括函数对字典做的原地修改；
- 返回其他类型：本次钩子执行失败。

推荐显式返回 `payload`，更容易测试和阅读。

### 9.1 保留未知字段

请求结构可能随着宿主版本扩展。不要重新构造只含已知字段的新字典：

```python
# 不推荐：会丢失宿主或其他插件添加的字段
return {"params": {"f0_method": "rmvpe"}}
```

应在现有对象上做最小修改：

```python
params = payload.setdefault("params", {})
params.setdefault("f0_method", "rmvpe")
return payload
```

### 9.2 静态参数与 Python 钩子的顺序

清单也可以声明静态 `workflow.before_create.params`。当前执行顺序是：

1. 为当前插件合并清单静态参数；
2. 只补充当前 `params` 中不存在的键；
3. 再运行当前插件的 Python `before_create`；
4. 继续处理下一个已启用插件。

静态参数只允许以下键：

```text
pitch
f0_method
index_rate
rms_mix
uvr_model
diffusion_ratio
device
protect
filter_radius
rvc_version
ddsp_infer_steps
ddsp_formant_shift
speaker
```

Python 钩子属于受信任代码，当前不会被这份静态白名单限制。仍建议只修改你明确理解的字段。

多个插件按当前安装目录名称排序执行，安装目录通常就是插件 ID。同一插件中多个 `before_create` 按注册顺序执行。不要依赖其他插件一定存在，也不要假定自己永远最后运行。

### 9.3 钩子失败时的行为

如果 Python `before_create` 抛出异常、超时或返回非字典，宿主会记录错误并保留进入该钩子前的请求，然后继续创建流程。用户不一定会在创建页面直接看到钩子异常，因此开发时必须检查插件数据目录中的 `error.log`。

### 9.4 通用 `hook`

可以注册任意名称：

```python
@plugin.hook("my_hook")
def my_hook(ctx, payload):
    return payload
```

但当前宿主业务流程只主动调用 `before_create`、`on_enable` 和 `on_disable`。自定义名称目前没有公开触发入口，不应作为可用扩展点依赖。

## 10. 生命周期

### 10.1 `on_enable`

插件从禁用切换到启用时调用：

```python
@plugin.on_enable
def on_enable(ctx: PluginContext) -> None:
    ctx.config.setdefault("schema_version", 1)
    ctx.save_config()
```

签名只有 `ctx`，返回值会被忽略。适合：

- 初始化配置默认值；
- 检查资源是否存在；
- 迁移旧配置；
- 做快速、可重复执行的环境检查。

入口导入或任意 `on_enable` 处理函数失败时，启用操作失败，插件保持禁用。不要在这里执行耗时下载；整个调用仍受 30 秒限制。

### 10.2 `on_disable`

```python
@plugin.on_disable
def on_disable(ctx: PluginContext) -> None:
    ctx.config["last_disabled"] = True
    ctx.save_config()
```

插件从启用切换到禁用后调用。返回值同样被忽略。`on_disable` 失败不会重新启用插件，错误只会被记录。

不要依赖 `on_disable` 完成关键数据提交或必须执行的清理：重新安装、卸载、程序异常退出等路径不保证调用它。重要数据应在产生时立即持久化。

### 10.3 多个生命周期函数

生命周期函数可以注册多个，按入口导入时的注册顺序运行：

```python
@plugin.on_enable
def migrate(ctx):
    ...


@plugin.on_enable
def validate_resources(ctx):
    ...
```

任意一个抛出异常都会终止本次 Worker 调用，后续处理函数不会执行。

## 11. 同步与异步处理函数

动作、钩子和生命周期都支持普通函数与 `async def`。Worker 调用函数后，如果结果可等待，就会自动 `await`。

同步动作：

```python
@plugin.action("read_defaults")
def read_defaults(ctx, values):
    return {"payload": ctx.config}
```

异步动作：

```python
@plugin.action("request_remote")
async def request_remote(ctx, values):
    result = await call_remote_service(values)
    return {"payload": result}
```

异步钩子：

```python
@plugin.before_create
async def resolve_profile(ctx, payload):
    profile = await load_profile(payload)
    payload.setdefault("params", {}).update(profile)
    return payload
```

注意：

- 同步阻塞代码会阻塞本次 Worker，但不会直接阻塞插件主进程；
- `async` 不会延长 30 秒总超时；
- 不要创建需要跨调用存活的后台任务，Worker 在返回结果后就会退出；
- 不要假设不同调用之间共享同一个事件循环；
- 多次调用可能使用不同进程，文件写入应考虑并发和覆盖问题。

## 12. `PluginContext`、配置和数据文件

每次处理函数都会收到一个 `PluginContext`：

```python
@dataclass(slots=True)
class PluginContext:
    plugin_id: str
    plugin_dir: Path
    data_dir: Path
    config: dict[str, Any]
```

### 12.1 字段含义

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plugin_id` | `str` | 当前清单 ID |
| `plugin_dir` | `Path` | 已安装插件根目录的绝对路径 |
| `data_dir` | `Path` | 当前插件独立数据目录的绝对路径，创建上下文时自动建立 |
| `config` | `dict[str, Any]` | 从 `data_dir/config.json` 加载的配置字典 |

### 12.2 配置读写

```python
@plugin.action("set_profile")
def set_profile(ctx: PluginContext, values: dict[str, Any]) -> str:
    ctx.config["profile"] = str(values.get("profile") or "default")
    ctx.save_config()
    return "配置已保存"
```

修改 `ctx.config` 后必须调用 `ctx.save_config()`，否则修改只存在于本次 Worker 内存中，进程退出后就会丢失。

`save_config()` 的行为：

1. 将字典以 UTF-8 JSON 写入 `config.json.tmp`；
2. 使用 `ensure_ascii=False` 和两空格缩进；
3. 用临时文件替换 `config.json`。

配置值必须能被 JSON 序列化。

上下文创建时，如果 `config.json` 不存在、无法读取、JSON 损坏或顶层不是对象，`ctx.config` 会变成空字典。SDK不会自动备份损坏文件。

### 12.3 保存普通数据文件

SDK只为配置提供专用方法，其他文件直接通过 `ctx.data_dir` 管理：

```python
import json


def save_history(ctx: PluginContext, records: list[dict[str, Any]]) -> None:
    target = ctx.data_dir / "history.json"
    temporary = ctx.data_dir / "history.json.tmp"
    temporary.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
```

缓存、索引和用户生成数据应写入 `data_dir`，不要写入 `plugin_dir`。重新安装会替换插件目录，但保留数据目录；卸载插件会删除插件目录和该插件的数据目录。

`save_config()` 提供原子替换，但没有跨进程文件锁。如果页面可能快速并发调用多个动作，不要用“读取旧值、递增、保存”实现必须严格准确的计数器；需要时自行使用适合本机的锁或数据库。

### 12.4 读取随包资源

```python
import json


def load_defaults(ctx: PluginContext) -> dict[str, Any]:
    path = ctx.plugin_dir / "assets" / "defaults.json"
    return json.loads(path.read_text(encoding="utf-8"))
```

使用 `ctx.plugin_dir`，不要依赖当前工作目录。虽然当前 Worker 的工作目录是插件根目录，但上下文路径更明确，也更容易测试。

如果文件名来自用户输入，必须防止 `..` 或绝对路径逃逸：

```python
def data_file(ctx: PluginContext, relative: str) -> Path:
    root = ctx.data_dir.resolve()
    candidate = (root / relative).resolve()
    candidate.relative_to(root)  # 越界时抛出 ValueError
    return candidate
```

## 13. 包入口与相对导入

### 13.1 单文件入口

清单：

```json
{ "python": { "entry": "plugin.py" } }
```

目录：

```text
plugin.py
helpers.py
```

Worker 会把入口所在目录加入 `sys.path`，因此可以使用普通同级导入：

```python
from helpers import build_payload
```

单文件入口以内部模块名 `xb_user_plugin` 加载，不是 Python 包。不要在 `plugin.py` 中写 `from .helpers import ...`。

### 13.2 包入口

需要相对导入时，把入口设为包的 `__init__.py`：

```text
backend/
├─ __init__.py
├─ rules.py
└─ schemas.py
```

清单：

```json
{ "python": { "entry": "backend/__init__.py" } }
```

`backend/__init__.py`：

```python
from xb_svcb_plugin import Plugin

from .rules import build_payload


plugin = Plugin("com.example.package-plugin")
```

Worker 对名为 `__init__.py` 的入口建立包加载上下文，所以 `.rules` 这样的相对导入可以正常工作。推荐中大型插件使用这种结构。

入口在 Worker 中的内部包名是 `xb_user_plugin`，不要依赖安装目录名作为 Python 导入包名，也不要依赖 `__name__` 等于源码目录名。

### 13.3 入口导入的副作用

入口在每次调用时都会重新执行。入口顶层只应：

- 导入模块；
- 创建 `Plugin`；
- 注册处理函数；
- 定义轻量常量。

不要在顶层下载模型、扫描大型目录、启动服务或修改用户文件。这些操作会在每次动作和钩子调用时重复，并计入 30 秒超时。

## 14. 打包第三方依赖到 `vendor`

宿主运行插件时不会访问网络、不会执行 `pip install`，也不会使用插件的 `.venv`。新版 SDK 脚手架会创建 `requirements.txt`，并在 `npm run pack` 时使用 Python 3.10 把其中的依赖安装到临时打包目录的 `vendor/`。最终用户拿到的 `.xbplugin` 已经包含依赖。

在 `requirements.txt` 中固定依赖版本：

```powershell
httpx==0.28.1
```

清单同时声明依赖文件：

```ts
.python('plugin.py', { requirements: 'requirements.txt' })
// 混合插件使用 .hybrid('plugin.py', { requirements: 'requirements.txt' })
```

然后正常运行 `npm run validate` 和 `npm run pack`。需要指定打包解释器时设置 `XB_PLUGIN_BUILD_PYTHON`；解释器必须是 Python 3.10，以匹配正式插件运行时。旧项目也可以保留手工生成的 `vendor/`，没有依赖清单时打包器会原样包含它。

运行时 Worker 会把以下位置加入模块搜索路径：

1. 宿主提供的 Python SDK 目录；
2. Python 入口所在目录；
3. 插件根目录；
4. `vendor`；
5. Python 标准库。

Worker 使用隔离模式启动，不读取用户的 `PYTHONPATH`、用户 site-packages 或宿主 AI 环境中的第三方包。因此未进入 `vendor/` 的依赖会在开发机和用户机上一致失败，不会再被开发机全局环境意外掩盖。

因此插件代码可以直接导入：

```python
import httpx
```

### 14.1 依赖规则

- 固定依赖版本，保证构建可复现；
- 不要把 `xb_svcb_plugin` 或 `xb-svcb-plugin-sdk` 写入依赖清单；运行时 SDK 由宿主提供；
- 删除不需要的测试、缓存和文档文件以控制包大小；
- 含 `.pyd` 或其他本机二进制的依赖必须匹配宿主 Python 版本、Windows 架构和平台；
- 不要假定宿主已经安装某个 PyPI 包；标准库之外的依赖都应自行打包；
- 使用网络、进程或环境变量时，在清单中分别声明 `network`、`process`、`environment`。

插件压缩包最大 20 MB，解压后最大 50 MB。大型模型和运行时不适合直接放入插件包；可以由用户明确触发下载并写入 `ctx.data_dir`，但必须声明网络权限、校验下载内容并处理失败和断点恢复。

## 15. 完整的包式后端示例

下面示例同时包含动作、翻唱钩子、生命周期、配置、数据文件和相对导入。

### 15.1 `backend/rules.py`

```python
from typing import Any


def pitch_for_style(style: str) -> int:
    return {
        "natural": 0,
        "bright": 1,
        "deep": -2,
    }.get(style, 0)


def add_safe_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.setdefault("params", {})
    params.setdefault("f0_method", "rmvpe")
    params.setdefault("device", "auto")
    return payload
```

### 15.2 `backend/__init__.py`

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from xb_svcb_plugin import ActionResult, Plugin, PluginContext

from .rules import add_safe_defaults, pitch_for_style


PLUGIN_ID = "com.example.cover-assistant"
plugin = Plugin(PLUGIN_ID)


@plugin.on_enable
def initialise(ctx: PluginContext) -> None:
    ctx.config.setdefault("schema_version", 1)
    ctx.config.setdefault("created_count", 0)
    ctx.save_config()


@plugin.action("build_cover")
async def build_cover(
    ctx: PluginContext,
    values: dict[str, Any],
) -> ActionResult:
    source_path = str(values.get("source_path") or "").strip()
    model_id = str(values.get("model_id") or "").strip()
    if not source_path:
        raise ValueError("请选择源音频")
    if not model_id:
        raise ValueError("请选择模型")

    style = str(values.get("style") or "natural")
    title = str(values.get("title") or "插件翻唱").strip()

    ctx.config["created_count"] = int(ctx.config.get("created_count", 0)) + 1
    ctx.config["last_used_at"] = datetime.now(timezone.utc).isoformat()
    ctx.save_config()

    return ActionResult.create_work(
        {
            "source_path": source_path,
            "model_id": model_id,
            "title": title,
            "workflow": "auto_mix",
            "params": {
                "pitch": pitch_for_style(style),
                "f0_method": "rmvpe",
            },
        }
    )


@plugin.action("status")
def status(ctx: PluginContext, values: dict[str, Any]) -> str:
    count = int(ctx.config.get("created_count", 0))
    return f"插件已创建 {count} 个翻唱任务"


@plugin.before_create
def before_create(
    ctx: PluginContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return add_safe_defaults(payload)


@plugin.on_disable
def record_disable(ctx: PluginContext) -> None:
    ctx.config["last_disabled_at"] = datetime.now(timezone.utc).isoformat()
    ctx.save_config()
```

抛出 `ValueError` 会使动作失败，并把异常消息返回页面。不要把用户输入、令牌或私人路径写入异常消息，因为页面和错误日志都可能显示这些内容。

### 15.3 纯 Python 清单源码 `src/plugin.ts`

这个版本使用宿主声明式表单，不需要自定义前端：

```ts
import { fields, page, plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const startPage = page('start', '翻唱助手', {
  fields: [
    fields.text('source_path', '源音频路径', {
      placeholder: 'D:/Music/song.wav',
    }),
    fields.text('model_id', '模型 ID'),
    fields.text('title', '标题', { default: '插件翻唱' }),
    fields.select(
      'style',
      '声音风格',
      [
        { label: '自然', value: 'natural' },
        { label: '明亮', value: 'bright' },
        { label: '低沉', value: 'deep' },
      ],
      { default: 'natural' },
    ),
  ],
  actions: ['create', 'status'],
})

const app = plugin(
  'com.example.cover-assistant',
  'Python 翻唱助手',
  '1.0.0',
)
  .description('使用 Python 生成翻唱任务。')
  .author('Example')
  .python('backend/__init__.py')
  .permission('filesystem.data')
  .page(startPage)
  .pythonAction('create', '创建翻唱', 'build_cover')
  .pythonAction('status', '查看状态', 'status')

await writeManifest(app, '.')
```

### 15.4 改成混合插件

先用混合脚手架创建工程，或为现有项目增加 Vue/Vite 页面。Python 文件不需要修改，只需把清单构建器改为：

```ts
const app = plugin(
  'com.example.cover-assistant',
  '混合翻唱助手',
  '1.0.0',
)
  .description('Vue 页面与 Python 后端组合。')
  .author('Example')
  .hybrid('backend/__init__.py')
  .frontendEntry('dist/frontend/index.html')
  .permission('filesystem.data')
  .page('start', '翻唱助手', {
    fields: [],
    actions: ['create', 'status'],
  })
  .pythonAction('create', '创建翻唱', 'build_cover')
  .pythonAction('status', '查看状态', 'status')
```

Vue 组件中调用：

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const sourcePath = ref('')
const modelId = ref('')
const title = ref('插件翻唱')
const style = ref('natural')

const { hosted, loading, error, runAction } = usePluginHost()

async function submit() {
  if (!hosted.value) return
  await runAction('create', {
    source_path: sourcePath.value,
    model_id: modelId.value,
    title: title.value,
    style: style.value,
  })
}
</script>
```

`runAction('create', ...)` 中的 `create` 是清单动作 ID，不是 Python 函数名。宿主会根据清单映射到 `build_cover`。

## 16. 单元测试

处理函数本身只是普通 Python 函数。推荐把业务逻辑放在独立模块，并使用标准库 `unittest` 测试，这样测试环境不需要主项目。

### 16.1 测试业务规则

`tests/test_rules.py`：

```python
import unittest

from backend.rules import add_safe_defaults, pitch_for_style


class RuleTests(unittest.TestCase):
    def test_pitch_for_style(self) -> None:
        self.assertEqual(pitch_for_style("bright"), 1)
        self.assertEqual(pitch_for_style("unknown"), 0)

    def test_defaults_do_not_override_user_values(self) -> None:
        payload = {"params": {"f0_method": "harvest"}}
        result = add_safe_defaults(payload)
        self.assertEqual(result["params"]["f0_method"], "harvest")
        self.assertEqual(result["params"]["device"], "auto")


if __name__ == "__main__":
    unittest.main()
```

### 16.2 测试上下文、同步钩子和异步动作

`tests/test_backend.py`：

```python
import tempfile
import unittest
from pathlib import Path

from xb_svcb_plugin import ActionResult, PluginContext

from backend import before_create, build_cover, plugin


class BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.context = PluginContext.create(
            "com.example.cover-assistant",
            str(root / "plugin"),
            str(root / "data"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registered_handlers(self) -> None:
        self.assertEqual(plugin.id, "com.example.cover-assistant")
        self.assertIn("build_cover", plugin.actions)
        self.assertIn("before_create", plugin.hooks)

    def test_before_create(self) -> None:
        payload = {"params": {}}
        result = before_create(self.context, payload)
        self.assertEqual(result["params"]["f0_method"], "rmvpe")

    async def test_build_cover(self) -> None:
        result = await build_cover(
            self.context,
            {
                "source_path": "D:/Music/song.wav",
                "model_id": "model_demo",
                "title": "Demo",
                "style": "bright",
            },
        )
        self.assertIsInstance(result, ActionResult)
        self.assertEqual(result.type, "create_work")
        self.assertEqual(result.payload["params"]["pitch"], 1)

        reloaded = PluginContext.create(
            self.context.plugin_id,
            str(self.context.plugin_dir),
            str(self.context.data_dir),
        )
        self.assertEqual(reloaded.config["created_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

运行：

```powershell
python -m unittest discover -s tests -v
```

### 16.3 单元测试覆盖不到的内容

直接调用函数不会复现以下宿主行为：

- 每次调用重新导入入口；
- `Plugin.id` 与清单 ID 校验；
- `python.entry` 包加载和 `vendor` 路径；
- JSON 序列化；
- 30 秒超时；
- 全局开关和插件启用状态；
- `ActionResult.create_work` 的真实任务创建。

发布前仍需执行一次完整冒烟测试：

```powershell
npm run validate
npm run pack
```

然后在 XB-SVCB 中安装包、启用插件、运行每个动作并创建一次真实测试任务。

## 17. 调试与错误日志

### 17.1 错误如何返回

入口导入或处理函数发生异常时，Worker 返回：

```json
{
  "ok": false,
  "error": "异常消息",
  "traceback": "最多 12 层的 Python traceback"
}
```

页面通常只收到简短的 `error`。宿主把详细 traceback 写到当前插件数据目录：

```text
<plugin-data>/<plugin-id>/error.log
```

在处理函数内部，可以用下面的逻辑定位同一目录：

```python
log_path = ctx.data_dir / "error.log"
```

错误日志最多保留最后 20,000 个字符，每次新的 Worker 错误会覆盖旧文件。需要保留现场时应及时备份。

### 17.2 `print` 的行为

入口导入和处理函数中的 Python `print(...)` 会被重定向到 Worker 的标准错误，避免破坏标准输出上的 JSON 协议。但是：

- 成功调用的标准错误当前不会保存到插件日志；
- 失败时错误日志优先记录 traceback，不能保证包含之前的 `print`；
- 子进程或本机扩展直接写进操作系统标准输出时，仍可能污染 JSON 协议。

因此不要把 `print` 当作持久日志。开发期需要日志时，可以把经过脱敏的内容写入 `ctx.data_dir / "debug.log"`，并自行做大小限制和轮转。插件不要记录令牌、完整环境变量或用户隐私数据。

### 17.3 推荐排查顺序

1. 运行 `python -m unittest discover -s tests -v`；
2. 运行 `npm run validate`，确认清单和入口路径；
3. 解压 `.xbplugin`，确认清单位于包根且入口真实存在；
4. 确认清单 `id` 与 `Plugin(...)` 完全相同；
5. 确认 `python.execute` 已声明；
6. 确认第三方依赖位于根目录 `vendor`；
7. 在插件中心重新安装，并单独启用；
8. 查看插件数据目录中的 `error.log`。

## 18. 执行、安全和资源限制

### 18.1 它不是安全沙箱

Worker 的目标是崩溃隔离和协议隔离，不是限制恶意代码。Python 插件以当前登录用户权限运行，可以：

- 读取或修改当前用户可访问的文件；
- 发起网络请求；
- 读取环境变量；
- 启动子进程；
- 消耗 CPU、内存和磁盘。

只启用可信来源的插件。审查入口、`vendor` 依赖、安装脚本和发布包内容，不要只审查清单。

### 18.2 当前硬限制

| 项目 | 限制 |
| --- | --- |
| 插件压缩包 | 最大 20 MB |
| 解压后全部文件 | 最大 50 MB |
| 清单文件 | 最大 512 KB |
| 单次 Python 调用 | 30 秒 |
| Python 入口 | 插件目录内的相对 `.py` 文件 |
| 插件 ID | 3 到 64 位小写标识符 |
| Worker 输出 | 必须是合法 JSON 响应 |

安装器拒绝压缩包路径穿越。Python 入口在执行前还会再次解析路径，并确认它位于插件根目录内且是现有文件。

### 18.3 数据生命周期

| 操作 | 插件代码目录 | 插件数据目录 | 生命周期 |
| --- | --- | --- | --- |
| 首次安装 | 创建 | 不主动创建，第一次上下文使用时创建 | 插件保持禁用 |
| 重新安装 | 替换 | 保留 | 插件重置为禁用，不保证调用 `on_disable` |
| 禁用 | 保留 | 保留 | 调用 `on_disable`，失败不阻止禁用 |
| 卸载 | 删除 | 删除 | 不保证调用 `on_disable` |

重要配置在版本升级前应兼容旧结构。需要迁移时，在 `on_enable` 中读取 `schema_version` 并做可重复迁移。

### 18.4 进程内状态

以下写法不能用来跨调用计数：

```python
CALLS = 0


@plugin.action("count")
def count(ctx, values):
    global CALLS
    CALLS += 1
    return str(CALLS)
```

下一次动作会启动新 Worker，`CALLS` 通常重新变成 0。应使用 `ctx.config` 或数据文件。

同理，不要启动后台线程、定时任务或常驻网络连接。处理函数返回后 Worker 退出，这些资源不会成为可靠服务。

## 19. Python SDK API 参考

### 19.1 导出成员

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

| 成员 | 类型 | 说明 |
| --- | --- | --- |
| `Plugin` | 类 | 保存动作和钩子注册表，并设置当前活动插件 |
| `PluginContext` | dataclass | 本次调用的插件路径、数据目录和配置 |
| `ActionResult` | dataclass | 消息或创建任务等标准动作结果 |
| `action(name=None)` | 函数 | 在当前活动插件上注册动作 |
| `before_create(func)` | 函数 | 在当前活动插件上注册翻唱创建前钩子 |
| `get_plugin()` | 函数 | 返回当前活动插件；未创建时抛出 `RuntimeError` |

### 19.2 `Plugin`

```python
Plugin(plugin_id: str)
```

| 属性或方法 | 返回值 | 说明 |
| --- | --- | --- |
| `id` | `str` | 创建实例时传入的插件 ID |
| `actions` | `dict[str, Handler]` | 动作注册表 |
| `hooks` | `dict[str, list[Handler]]` | 钩子注册表 |
| `action(name=None)` | 装饰器 | 注册动作；省略名称时使用函数名 |
| `hook(name)` | 装饰器 | 注册任意名称的钩子，允许同名多个 |
| `before_create(func)` | 原函数 | 注册 `before_create` 钩子 |
| `on_enable(func)` | 原函数 | 注册 `on_enable` 生命周期 |
| `on_disable(func)` | 原函数 | 注册 `on_disable` 生命周期 |

### 19.3 处理函数签名

| 类型 | 同步或异步签名 | 有效返回值 |
| --- | --- | --- |
| 动作 | `(ctx, values)` | `ActionResult`、`dict`、`str`、`None` |
| `before_create` | `(ctx, payload)` | `dict` 或 `None` |
| `on_enable` | `(ctx)` | 返回值忽略 |
| `on_disable` | `(ctx)` | 返回值忽略 |
| 通用业务钩子 | `(ctx, payload)` | `dict` 或 `None`，但当前无公开自定义触发入口 |

同步函数返回 awaitable 时 Worker 也会等待它，但建议直接把函数声明成 `async def`，让意图更清楚。

### 19.4 `ActionResult`

构造函数：

```python
ActionResult(
    type: str = "message",
    message: str = "",
    payload: dict[str, Any] | None = None,
)
```

| 方法 | 返回值 | 说明 |
| --- | --- | --- |
| `ActionResult.message_result(message)` | `ActionResult` | 创建 `type="message"` 的消息结果 |
| `ActionResult.create_work(payload)` | `ActionResult` | 创建 `type="create_work"` 的任务结果 |
| `to_dict()` | `dict[str, Any]` | 转成 Worker 可返回的字典 |

`to_dict()` 始终包含 `type`；空字符串 `message` 会被省略；`payload is None` 时会省略 `payload`。

### 19.5 `PluginContext`

| 属性或方法 | 说明 |
| --- | --- |
| `plugin_id` | 当前插件 ID |
| `plugin_dir` | 已解析的插件安装根目录 `Path` |
| `data_dir` | 已解析并确保存在的数据目录 `Path` |
| `config` | 从 `config.json` 读取的字典 |
| `PluginContext.create(plugin_id, plugin_dir, data_dir)` | 创建目录、读取配置并构建上下文 |
| `save_config()` | 通过临时文件原子替换 `config.json` |

插件处理函数不需要自行调用 `PluginContext.create`；宿主会创建并传入。本地单元测试时才需要手工创建。

## 20. 常见错误

### 20.1 “插件入口必须先创建 Plugin(plugin_id)”

原因：入口导入完成后没有活动插件。

检查：

- 是否在模块顶层执行了 `plugin = Plugin("...")`；
- 是否把创建代码放进了 `if __name__ == "__main__"`；
- 是否因条件分支没有执行创建代码。

入口由 Worker 导入，`if __name__ == "__main__"` 中的代码不会运行。

### 20.2 “Python Plugin ID 不匹配”

清单 `id` 与 `Plugin(...)` 不完全一致。修改后重新构建清单、打包并安装。

### 20.3 “未注册 Python 动作”

检查四处：

1. 清单动作 `id` 是页面调用的值；
2. 清单动作 `handler` 是 Python 注册名；
3. `@plugin.action("...")` 名称与 `handler` 相同；
4. 注册代码在入口导入时执行。

### 20.4 插件能安装但不能启用

常见原因：

- `python.entry` 文件没有打进包；
- 入口语法错误或导入失败；
- 缺少 `vendor` 依赖；
- `Plugin.id` 不匹配；
- `on_enable` 抛出异常或超过 30 秒；
- 宿主没有找到 Python 3.10+ 插件运行环境；
- 宿主附带的 Worker 或 SDK 文件缺失。

查看 `error.log`。安装阶段会确认入口文件存在，但不会执行入口；启用成功才代表入口和生命周期能够运行。

### 20.5 “插件返回值必须是 dict、str、ActionResult 或 None”

处理函数返回了列表、数字、布尔值或自定义对象。把结果包进字典，或使用 `ActionResult`。

### 20.6 返回值看起来正确，但显示“Python 插件执行失败”

可能返回字典中含有不能 JSON 序列化的值，例如 `Path`、`bytes`、`set` 或日期对象。先转换成字符串、列表或普通字典。

这类错误可能发生在最终协议序列化阶段，`error.log` 不一定更新，因此应先在单元测试中执行：

```python
import json

json.dumps(result.to_dict() if hasattr(result, "to_dict") else result)
```

### 20.7 相对导入失败

如果入口是普通 `plugin.py`，不能使用 `.helpers`。选择一种方式：

- 保持单文件入口并写 `from helpers import ...`；
- 改为 `backend/__init__.py` 包入口并写 `from .helpers import ...`。

### 20.8 本地能运行，宿主提示缺少模块

本地虚拟环境中的依赖不会自动成为运行时依赖。把固定版本写入 `requirements.txt`：

```powershell
package-name==1.2.3
```

然后运行 `npm run pack`，并检查 `.xbplugin` 内是否存在 `vendor`。Worker 不读取开发机或用户机的全局 site-packages。

### 20.9 配置修改没有保存

修改 `ctx.config` 后漏掉了 `ctx.save_config()`。模块全局变量和内存字典都会随 Worker 退出而丢失。

### 20.10 `before_create` 没有生效

检查：

- 全局插件功能是否开启；
- 插件是否单独启用；
- 运行时是否为 `python` 或 `hybrid`；
- 装饰器是否为 `@plugin.before_create`；
- 是否返回字典或原地修改后返回 `None`；
- `error.log` 是否记录了异常；
- 后执行的其他插件是否又修改了同一字段。

### 20.11 执行超过 30 秒

进程启动、依赖导入和处理函数总计超过限制。可以：

- 把重依赖移出入口顶层初始化；
- 减少包导入开销；
- 把大任务交给宿主已有工作流，而不是在插件动作中完成；
- 将远程请求设置为明显小于 30 秒的连接和读取超时；
- 把缓存写入 `data_dir`，避免每次重新计算。

不能通过插件代码修改宿主的 30 秒限制。

### 20.12 生命周期没有按预期清理资源

`on_disable` 只在明确从启用切换为禁用时调用。重新安装、卸载和异常退出不保证调用。不要用生命周期维持必须常驻的资源，也不要把关键保存延迟到禁用阶段。

## 21. 发布前检查表

- [ ] 清单 ID 与 `Plugin(...)` 完全一致；
- [ ] `runtime` 是 `python` 或 `hybrid`；
- [ ] `python.entry` 是包内相对 `.py` 路径；
- [ ] 已声明 `python.execute` 和实际使用的审计权限；
- [ ] 每个 Python 动作都有合法 `handler`，且入口中已注册；
- [ ] 所有动作返回值都可 JSON 序列化；
- [ ] `before_create` 保留未知字段，不意外覆盖用户选择；
- [ ] 持久数据只写入 `ctx.data_dir`；
- [ ] 修改 `ctx.config` 后调用 `save_config()`；
- [ ] 没有依赖模块全局变量跨调用保存状态；
- [ ] 第三方依赖已放入 `vendor`，没有打包 `xb_svcb_plugin`；
- [ ] 入口顶层没有耗时操作；
- [ ] 单元测试通过；
- [ ] `npm run validate` 通过；
- [ ] `.xbplugin` 压缩后不超过 20 MB、解压后不超过 50 MB；
- [ ] 在真实 XB-SVCB 中完成安装、启用、动作和翻唱创建测试；
- [ ] 检查过 `error.log`，没有被忽略的钩子错误；
- [ ] 发布包不包含令牌、用户路径、测试数据或私人配置。

完成以上检查后，纯 Python 插件和混合插件后端就具备了可安装、可调试、可升级的基本条件。
