# 清单、页面与动作

`xb-svcb-plugin.json` 是宿主识别插件的唯一入口。推荐始终维护 `src/plugin.ts`，用构建器生成 JSON，而不是长期手工修改构建产物。

## 1. 最小清单

```json
{
  "id": "com.example.hello",
  "name": "Hello Plugin",
  "version": "1.0.0",
  "description": "",
  "author": "",
  "runtime": "frontend",
  "python": {},
  "frontend": {},
  "permissions": [],
  "pages": [],
  "actions": [],
  "workflow": {}
}
```

对应构建代码：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.hello', 'Hello Plugin', '1.0.0')
await writeManifest(app, '.')
```

## 2. 顶层字段

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `id` | `string` | 是 | 3-64 位小写标识符；首位是字母或数字 |
| `name` | `string` | 是 | 插件中心显示名称，宿主保留前 80 字符 |
| `version` | `string` | 是 | 推荐语义化版本；宿主保留前 32 字符 |
| `description` | `string` | 否 | 功能简介，宿主保留前 400 字符 |
| `author` | `string` | 否 | 作者或组织，宿主保留前 80 字符 |
| `runtime` | 枚举 | 是 | `frontend`、`python`、`hybrid` |
| `python` | 对象 | 是 | Python 入口配置；非 Python 插件为空对象 |
| `frontend` | 对象 | 是 | 自定义页面入口配置 |
| `permissions` | 数组 | 是 | 声明的能力 |
| `pages` | 数组 | 是 | 页面元数据和声明式字段 |
| `actions` | 数组 | 是 | 页面可以请求的动作 |
| `workflow` | 对象 | 是 | 静态翻唱流程扩展 |

ID 正则：

```text
^[a-z0-9][a-z0-9._-]{2,63}$
```

合法示例：`com.example.quick-cover`、`io.github.user.plugin_name`。发布后不要修改 ID，否则宿主会把它当作另一个插件。

## 3. 运行类型

```ts
plugin('com.example.frontend', 'Frontend').frontend('dist/frontend/index.html')
plugin('com.example.python', 'Python').python('plugin.py')
plugin('com.example.hybrid', 'Hybrid').hybrid('plugin.py').frontendEntry('dist/frontend/index.html')
```

| Builder | runtime | 副作用 |
| --- | --- | --- |
| `.frontend(config?)` | `frontend` | 清空 Python 配置；字符串会变成 `{ entry }` |
| `.python(entry?)` | `python` | 默认 `plugin.py`；自动加入 `python.execute` |
| `.hybrid(entry?)` | `hybrid` | 默认 `plugin.py`；自动加入 `python.execute` |
| `.frontendEntry(entry, config?)` | 不改变 runtime | 设置或替换 `frontend.entry` |

Python 入口必须是插件目录内的 `.py` 文件，不能是绝对路径，不能包含 `..`。包入口可以写 `my_plugin/__init__.py`。

自定义页面入口必须是插件目录内的 `.html` 或 `.htm`，通常写 `dist/frontend/index.html`。

## 4. 页面

```ts
.page('home', '快速翻唱', {
  description: '填写参数并创建任务。',
  fields: [],
  actions: ['create'],
})
```

页面字段：

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `id` | `string` | 是 | 使用插件 ID 同样的标识符规则 |
| `title` | `string` | 是 | 页面标题 |
| `description` | `string` | 否 | 页面说明 |
| `fields` | `Field[]` | 是 | 声明式页面控件；可以为空 |
| `actions` | `string[]` | 否 | 声明式页面显示的动作 ID |

页面有两种渲染方式：

1. 没有 `frontend.entry`：宿主根据 `fields` 和 `actions` 自动渲染声明式表单。
2. 存在 `frontend.entry`：宿主加载自定义 HTML/Vue 页面，声明式表单完全不显示。

自定义页面仍可从 `getContext()` 读取 `page`，但调用动作时不受 `page.actions` 过滤，只要动作存在于插件顶层 `actions` 即可。

当前插件中心只打开 `pages[0]`，没有完整的多页面导航。自定义 Vue 插件应声明一个入口页面，并在 Vue 内部使用 tabs 或 memory router。

## 5. 声明式字段

```ts
import { fields } from '@xb-svcb/plugin-sdk'

const pageFields = [
  fields.text('title', '标题', { default: '我的翻唱' }),
  fields.textarea('notes', '备注', { placeholder: '可选' }),
  fields.number('pitch', '升降调', { default: 0 }),
  fields.switch('enhance', '自动增强', { default: true }),
  fields.select('device', '设备', [
    { label: '自动', value: 'auto' },
    { label: 'CPU', value: 'cpu' },
  ], { default: 'auto' }),
]
```

公共字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `string` | 提交值中的键 |
| `label` | `string` | 控件标签 |
| `type` | 枚举 | `text`、`textarea`、`number`、`switch`、`select` |
| `default` | 依字段类型 | 初始值 |
| `placeholder` | `string` | 输入提示；switch 不支持 |
| `help` | `string` | 控件下方帮助文字 |

`select` 额外要求非空 `options`：

```ts
type FieldOption = {
  label: string
  value: string | number
}
```

TypeScript 会约束默认值：number 必须是数字，switch 必须是布尔值，select 默认值应与选项值类型一致。

## 6. 动作

### 消息动作

```ts
.message('hello', '打招呼', '你好，{{name}}！')
```

返回 `{ type: 'message', message }`。模板会用页面传入的 values 插值。

### 创建翻唱任务

```ts
.createWork('create', '创建翻唱', {
  source_path: '{{source_path}}',
  model_id: '{{model_id}}',
  title: '{{title}}',
  workflow: 'auto_mix',
  params: { pitch: '{{pitch}}' },
})
```

返回 `{ type: 'create_work', payload }`。宿主页面收到后会调用正式创建任务 API；成功结果还包含 `work`。

### Python 动作

```ts
.pythonAction('analyse', '分析参数', 'analyse_values')
```

`analyse` 是页面调用的 action ID，`analyse_values` 是 Python `@plugin.action()` 注册名。Python 动作只允许 `python` 或 `hybrid` runtime。

动作对象共有 `id`、`label`、`type`。ID 使用 3-64 位小写标识符规则；Python handler 使用 Python 标识符规则，最长 64 位。

## 7. 占位符插值

宿主只识别显式的 `{{fieldId}}`，不会执行 JavaScript、模板表达式或属性访问。

```ts
{
  title: '{{title}}',
  params: {
    pitch: '{{pitch}}',
    note: '用户选择：{{style}}',
  },
}
```

- 整个字符串只有一个占位符时，数字和布尔值保留原类型。
- 占位符嵌在其他文字中时，值会转成字符串。
- 字段名必须以字母开头，只能包含字母、数字和下划线，最长 41 位。
- 缺少值时，原始占位符会保留；插件应在页面提交前校验必填字段。
- 插值递归处理对象和数组。

## 8. 静态 `beforeCreate`

```ts
.beforeCreate({
  f0_method: 'rmvpe',
  pitch: 0,
  device: 'auto',
})
```

静态补丁只填充用户请求中缺少的 `params` 键，不覆盖用户已经选择的值。允许字段：

```text
pitch, f0_method, index_rate, rms_mix, uvr_model, diffusion_ratio,
device, protect, filter_radius, rvc_version, ddsp_infer_steps,
ddsp_formant_shift, speaker
```

需要条件逻辑、修改完整请求或处理批量任务时，使用 Python `before_create` 钩子。

## 9. 权限

```ts
.permission('filesystem.data', 'network')
```

可声明：`python.execute`、`filesystem.plugin`、`filesystem.data`、`network`、`process`、`environment`。

`.python()` 和 `.hybrid()` 自动声明 `python.execute`。权限用于插件中心展示、审计和用户判断，不是操作系统沙箱；Python 代码仍具有当前用户权限。

## 10. Builder 完整方法

```text
plugin(id, name, version?) -> PluginBuilder

.description(text)
.author(name)
.frontend(entryOrConfig?)
.frontendEntry(entry, config?)
.python(entry?)
.hybrid(entry?)
.permission(...permissions)
.page(pageObject)
.page(id, title, configOrFactory?)
.action(actionObject)
.message(id, label, message)
.createWork(id, label, payload, options?)
.pythonAction(id, label, handler?, options?)
.beforeCreate(params)
.build() -> Manifest
```

也可以使用独立工厂：

```ts
import {
  page,
  messageAction,
  createWorkAction,
  pythonAction,
} from '@xb-svcb/plugin-sdk'

app
  .page(page('home', '首页', { fields: [] }))
  .action(messageAction('hello', '问候', '你好'))
```

`.build()` 只返回 JSON 深拷贝，不执行校验。`writeManifest()` 会校验、创建目标目录、写入 `xb-svcb-plugin.json`，并返回文件绝对路径。

JavaScript 使用者不要在 options 中覆盖工厂生成的 `id`、`label`、`type` 或 `options`。TypeScript 类型会阻止大部分错误，但 JavaScript spread 仍可能覆盖对象字段。

## 11. 校验范围

```ts
const result = validateManifest(app)

if (!result.ok) {
  console.error(result.errors)
}
```

SDK 校验会检查：

- 必需元数据和 ID 格式；
- runtime、permission、field type、action type；
- Python 和前端入口路径形状；
- Python runtime 的 `python.execute`；
- select 选项非空；
- Python handler 格式；
- 静态 beforeCreate 参数白名单。

SDK 校验不会检查：

- 入口文件是否存在；
- Python 能否导入；
- Python handler 是否注册；
- ID 是否重复；
- `page.actions` 是否引用真实动作；
- 前端页面能否构建或执行；
- 插件包、清单和资源大小；
- 创建任务 payload 是否满足宿主业务要求。

因此“清单有效”不等于“插件可安装并正常运行”。必须继续执行构建、打包和真实宿主安装测试。

## 12. 容易踩坑的组合

```ts
// 错误：frontend() 会把 hybrid 改回 frontend，并清空 Python 配置
plugin('com.example.bad', 'Bad')
  .hybrid('plugin.py')
  .frontend('dist/frontend/index.html')

// 正确
plugin('com.example.good', 'Good')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
```

```ts
// 错误：类型允许省略 config，但校验要求 fields 是数组
page('home', '首页')

// 正确
page('home', '首页', { fields: [] })
```

字段 ID 可以包含 `.` 或 `-`，但占位符字段名不允许，因此需要插值的字段应只使用字母、数字和下划线。
