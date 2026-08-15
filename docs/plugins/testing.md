# 测试与调试

插件测试需要分层进行。TypeScript 通过、清单有效或成功生成 `.xbplugin`，都不能单独证明插件能在 XB-SVCB 中运行。发布前至少要完成静态检查、插件单元测试和一次真实宿主安装检查。

本章只描述当前 SDK 和宿主已经实现的检查能力，不把尚未提供的模拟宿主、自动兼容性检查或端到端测试框架当作现成功能。

## 1. 测试层次

| 层次 | 典型命令或操作 | 能发现 | 不能证明 |
| --- | --- | --- | --- |
| TypeScript 检查 | `npm run typecheck` | `.ts`、`.vue` 和 Vite 配置的类型错误 | 清单文件有效、宿主调用成功 |
| 构建 | `npm run build` | Vue/Vite 编译错误、页面 bundle 生成错误、清单脚本执行错误 | 包大小合规、Python 能加载 |
| 清单校验 | `npm run validate` | 类型、构建和 SDK 已实现的清单形状错误 | 入口文件存在、handler 已注册、业务参数有效 |
| 插件单元测试 | `npm test`、`python -m unittest` | 动作、组件、插值输入和 Python 处理逻辑回归 | 真实桌面 Bridge 和宿主服务行为 |
| 打包 | `npm run pack` | 当前目录可压缩，现有清单能通过 SDK 校验 | 包符合宿主全部大小限制、可以启用 |
| 宿主安装 | 插件中心安装 `.xbplugin` | ZIP、清单、路径、前端入口及安装大小问题 | Python handler 和所有页面动作都正确 |
| 宿主启用和调用 | 启用、打开页面、执行动作 | Worker 导入、插件 ID、生命周期、动作、真实任务数据错误 | 所有用户环境均兼容 |

不要用后面的检查替代前面的检查。真实安装很重要，但它不应成为发现普通 TypeScript 拼写错误的第一道检查。

## 2. 脚手架命令实际执行什么

默认 Vue 或混合工程生成以下脚本：

```powershell
npm run typecheck
npm run build:frontend
npm run build:manifest
npm run build
npm run validate
npm run pack
```

它们之间的调用关系是：

```text
typecheck -------------------------------> vue-tsc --noEmit
build:frontend --------------------------> dist/frontend/index.html
build:manifest --------------------------> xb-svcb-plugin.json
build = build:frontend + build:manifest
validate = typecheck + build + xb-plugin validate .
pack = validate + xb-plugin pack .
```

纯 Python TypeScript 工程没有 `build:frontend` 和 `dev`；无构建 JavaScript 工程没有 `typecheck`。以脚手架生成的 `package.json` 为准，不要给不存在的脚本补写测试结论。

提交前通常执行：

```powershell
npm run validate
```

准备交付时执行：

```powershell
npm run pack
```

`npm run pack` 已经通过脚本调用 `validate`，不需要先手工重复运行 `build` 和 `validate`。在排错时分开运行这些命令，能更快确定失败属于哪一层。

## 3. 每一层的真实边界

### 3.1 `typecheck`

Vue 工程使用 `vue-tsc --noEmit`，原生 TypeScript 和纯 Python 清单工程使用 `tsc --noEmit`。它会检查：

- `src/plugin.ts` 的 SDK 类型；
- `frontend/**/*.ts`；
- Vue 工程的 `frontend/**/*.vue`；
- `vite.config.ts`。

它不会执行清单构建器，不会读取 `plugin.py`，也不会联系 XB-SVCB。`Record<string, unknown>` 仍可能包含宿主业务不接受的值；TypeScript 通过不等于创建翻唱任务一定成功。

### 3.2 `build`

前端构建使用 Vite 和 `vite-plugin-singlefile`，把 JavaScript、Vue runtime 与 CSS 内联到 `dist/frontend/index.html`。清单构建使用 `tsx` 执行 `src/plugin.ts` 并写入 `xb-svcb-plugin.json`。

构建完成后至少确认两个文件存在：

```powershell
Test-Path .\dist\frontend\index.html
Test-Path .\xb-svcb-plugin.json
```

纯 Python 插件没有前端入口，只需要第二项。

### 3.3 `xb-plugin validate`

CLI 校验读取已经生成的 `xb-svcb-plugin.json`。当前 SDK 会检查：

- `id`、`name`、`version` 是否存在；
- 插件、页面、字段和动作 ID 的基本格式；
- `runtime`、字段类型、动作类型和权限是否在允许集合中；
- Python/混合插件是否声明相对 `.py` 入口和 `python.execute`；
- `frontend.entry` 是否是插件内相对 HTML 路径；
- `select` 是否有非空选项；
- `create_work` 是否有对象形式的 `payload`；
- Python handler 名称格式；
- 纯前端插件是否错误声明 Python 动作；
- 静态 `before_create.params` 是否只使用允许字段。

当前 CLI 校验不会检查：

- `frontend.entry` 指向的文件是否存在；
- Python 入口文件是否存在或可以导入；
- `pythonAction()` 的 handler 是否在 `plugin.py` 中注册；
- 页面引用的动作 ID 是否实际存在；
- 页面、字段或动作 ID 是否重复；
- `create_work` 的业务字段组合是否能被作品服务接受；
- 最终压缩包、解压目录、HTML 或资源是否超过宿主限制；
- Vue 页面是否能通过真实 Bridge 调用宿主。

因此，看到“清单有效”只表示清单通过了当前结构校验。

### 3.4 `xb-plugin pack`

SDK 打包器会再次读取并校验现有清单，然后复制插件目录并创建 ZIP 格式的 `.xbplugin`。它默认忽略：

```text
node_modules/
.git/
.venv/
__pycache__/
.pytest_cache/
*.xbplugin
```

测试文件、源代码、README、`package-lock.json`、`dist/` 和 `vendor/` 不在忽略列表中，会被打入包内。当前没有 `.xbpluginignore`。

`xb-plugin pack` 本身不会重新构建页面或清单；脚手架生成的 `npm run pack` 才会先执行 `validate`。直接运行下面的 CLI 时，要先自行保证构建产物是最新的：

```powershell
xb-plugin pack .
```

打包器也不会预先执行宿主的 20 MB/50 MB 大小检查。这些限制必须另外检查，并在真实安装时再次确认。

### 3.5 宿主安装

插件中心安装包时，当前宿主会检查：

- 压缩包不超过 20 MB；
- 所有 ZIP 成员声明的解压后大小总和不超过 50 MB；
- 包内只有一个名称以 `xb-svcb-plugin.json` 结尾的清单；
- 清单 UTF-8 JSON 不超过 512 KB，并能通过宿主清单解析；
- ZIP 成员不能通过 `..` 等路径逃出安装目录；
- 已声明的 `frontend.entry` 文件存在、位于插件目录内且扩展名为 `.html` 或 `.htm`。

安装阶段不会执行 Python，也不会确认 Python 入口存在、handler 已注册或依赖可以导入。新安装或同 ID 替换安装后，插件都会处于关闭状态。

### 3.6 打开页面、启用 Python 和执行动作

页面第一次打开时，宿主才会读取入口 HTML，并拒绝超过 2 MB 的入口。`host.assetData()` 或 `host.assetUrl()` 每次读取资源时，宿主才会执行单个资源 10 MB 限制。

Python 或混合插件第一次启用时，宿主会启动独立 Worker，并检查：

- 宿主 Python 3.10+ 运行环境和 Python SDK 可用；
- 清单入口可以导入；
- 入口创建了 `Plugin`；
- `Plugin` ID 与清单 ID 一致；
- `on_enable` 能在 30 秒内完成。

动作或钩子实际执行时，才会发现 handler 未注册、返回值不能 JSON 序列化、真实任务参数错误或单次 Worker 超过 30 秒等问题。

## 4. 清单逻辑单元测试

可以使用 Node.js 内置测试运行器，不需要额外测试框架。先在 `package.json` 增加：

```json
{
  "scripts": {
    "test:manifest": "node --test tests/manifest.test.mjs"
  }
}
```

`tests/manifest.test.mjs`：

```js
import assert from 'node:assert/strict'
import test from 'node:test'

import { plugin, validateManifest } from '@xb-svcb/plugin-sdk'

test('有效的 Vue 前端清单可以通过校验', () => {
  const definition = plugin('com.example.cover', '翻唱助手', '1.0.0')
    .frontend('dist/frontend/index.html')
    .page('home', '首页', { fields: [], actions: ['create'] })
    .createWork('create', '创建翻唱', {
      source_path: '{{source_path}}',
      model_id: '{{model_id}}',
      workflow: 'auto_mix',
    })

  const result = validateManifest(definition)
  assert.equal(result.ok, true, result.errors.join('\n'))
})

test('纯前端插件不能声明 Python 动作', () => {
  const definition = plugin('com.example.cover', '翻唱助手', '1.0.0')
    .frontend()
    .pythonAction('run', '运行 Python', 'run')

  const result = validateManifest(definition)
  assert.equal(result.ok, false)
  assert.match(result.errors.join('\n'), /Python 动作只能用于/)
})
```

对清单测试以下内容最有价值：稳定 ID、运行类型、入口路径、权限、页面动作映射、静态工作流参数和最终构建出的动作 ID。SDK 当前不会检查重复 ID 和页面动作引用，因此可以在项目测试中自行断言：

```js
const manifest = definition.build()
const actionIds = manifest.actions.map((item) => item.id)
assert.equal(new Set(actionIds).size, actionIds.length, '动作 ID 不能重复')

for (const page of manifest.pages) {
  for (const actionId of page.actions || []) {
    assert.ok(actionIds.includes(actionId), `页面引用了不存在的动作：${actionId}`)
  }
}
```

## 5. 模拟页面 Client

当前 SDK 没有单独发布模拟宿主包。单元测试应在项目内 mock `@xb-svcb/plugin-sdk/client`，把页面业务逻辑与真实 `postMessage` Bridge 分开测试。

推荐先把宿主调用提取成普通模块。

`frontend/src/services/cover.ts`：

```ts
import { host, type HostMessageResult } from '@xb-svcb/plugin-sdk/client'

export interface CoverFormValues {
  source_path: string
  model_id: string
  title: string
  pitch: number
}

export function createCover(values: CoverFormValues): Promise<HostMessageResult> {
  return host.runAction('create', values)
}
```

安装 Vitest：

```powershell
npm install --save-dev vitest
```

`tests/cover.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hostMock = vi.hoisted(() => ({
  getContext: vi.fn(),
  runAction: vi.fn(),
  createWork: vi.fn(),
  assetData: vi.fn(),
  assetUrl: vi.fn(),
  notify: vi.fn(),
}))

vi.mock('@xb-svcb/plugin-sdk/client', () => ({
  host: hostMock,
  isHosted: () => true,
  request: vi.fn(),
}))

import { createCover } from '../frontend/src/services/cover'

describe('createCover', () => {
  beforeEach(() => vi.clearAllMocks())

  it('把表单值交给 create 动作', async () => {
    hostMock.runAction.mockResolvedValue({
      ok: true,
      type: 'create_work',
      work: { id: 'work_1', title: '测试翻唱' },
    })

    const values = {
      source_path: 'D:/Music/song.wav',
      model_id: 'model_xxx',
      title: '测试翻唱',
      pitch: 2,
    }

    await expect(createCover(values)).resolves.toMatchObject({ type: 'create_work' })
    expect(hostMock.runAction).toHaveBeenCalledWith('create', values)
  })

  it('保留宿主错误', async () => {
    hostMock.runAction.mockRejectedValue(new Error('插件动作不存在'))
    await expect(createCover({
      source_path: '',
      model_id: '',
      title: '',
      pitch: 0,
    })).rejects.toThrow('插件动作不存在')
  })
})
```

这个 mock 能验证页面传给宿主的动作 ID 和载荷，但不能验证真实 Bridge token、消息来源检查、超时或作品服务。对应行为仍要在宿主安装检查中覆盖。

## 6. Vue 组件测试

Vue 组件可以直接 mock `@xb-svcb/plugin-sdk/vue`。不要只 mock Client 后继续使用真实 `usePluginHost()`；Vue SDK 内部通过包内相对路径导入 Client，不保证测试框架能用包入口 mock 替换它。

安装测试依赖：

```powershell
npm install --save-dev vitest @vue/test-utils jsdom
```

增加独立配置 `vitest.config.ts`：

```ts
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    clearMocks: true,
  },
})
```

在 `package.json` 增加：

```json
{
  "scripts": {
    "test": "vitest run"
  }
}
```

下面以脚手架的表单组件为例。测试文件先提供响应式宿主状态，再导入组件。

`tests/GreetingForm.test.ts`：

```ts
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'

const runActionMock = vi.hoisted(() => vi.fn())

vi.mock('@xb-svcb/plugin-sdk/vue', async () => {
  const { computed, readonly, ref } = await import('vue')
  const hosted = ref(true)
  const context = ref(null)
  const loading = ref(false)
  const error = ref<Error | null>(null)

  return {
    usePluginHost: () => ({
      hosted: readonly(hosted),
      context: readonly(context),
      plugin: computed(() => undefined),
      page: computed(() => undefined),
      theme: computed(() => 'cyber'),
      loading: readonly(loading),
      error: readonly(error),
      refreshContext: vi.fn(),
      runAction: runActionMock,
      createWork: vi.fn(),
      assetData: vi.fn(),
      assetUrl: vi.fn(),
      notify: vi.fn(),
      clearError: () => { error.value = null },
    }),
  }
})

import GreetingForm from '../frontend/src/components/GreetingForm.vue'

beforeEach(() => {
  vi.clearAllMocks()
  runActionMock.mockResolvedValue({ type: 'message', message: '你好！' })
})

it('提交名字并显示动作结果', async () => {
  const wrapper = mount(GreetingForm)
  await wrapper.get('input').setValue('小明')
  await wrapper.get('button').trigger('click')
  await vi.waitFor(() => expect(runActionMock).toHaveBeenCalled())

  expect(runActionMock).toHaveBeenCalledWith('hello', { name: '小明' })
  expect(wrapper.text()).toContain('你好')
})
```

实际项目还应覆盖：

- `hosted` 为 `false` 时显示开发预览状态且不调用动作；
- `loading` 为 `true` 时禁止重复提交；
- `runAction()` 拒绝时显示 `error`；
- 空值、数字转换和组件 emits；
- `theme` 的每个当前主题值；
- 响应式窄宽布局中没有关键内容溢出。

组件测试不加载真实 iframe，也不会继承宿主 CSS。主题和布局最终仍要在 XB-SVCB 中人工检查。

## 7. 浏览器开发预览

```powershell
npm run dev
```

开发预览适合检查：

- Vue 组件是否渲染；
- 本地表单和状态切换；
- 响应式布局；
- 资源被 Vite 正确导入；
- 页面在未托管状态下给出清晰提示。

普通浏览器预览没有宿主注入的 token，`isHosted()` 返回 `false`。它不能验证 `runAction()`、`createWork()`、`assetUrl()`、Python 动作或真实模型数据。测试代码不应伪造全局 token 后声称完成了宿主集成测试。

## 8. Python 单元测试

宿主运行时会提供 `xb_svcb_plugin`。当前本地源码开发方式需要从 XB-SVCB 源码树安装 Python SDK：

```powershell
python -m pip install -e <XB-SVCB源码目录>\plugin-sdk\python
```

这条命令只用于本地测试环境。插件包中不要复制或打包宿主 SDK。

先做语法检查：

```powershell
python -m py_compile plugin.py
```

下面的测试同时覆盖同步或异步 handler、动作返回和配置持久化。

`tests/test_plugin.py`：

```python
import inspect
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from xb_svcb_plugin import ActionResult, PluginContext

from plugin import plugin


async def call(handler, *args):
    result = handler(*args)
    if inspect.isawaitable(result):
        result = await result
    return result


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_action(self) -> None:
        with TemporaryDirectory() as data_dir:
            ctx = PluginContext.create(plugin.id, ".", data_dir)
            handler = plugin.actions["create_cover"]
            result = await call(handler, ctx, {
                "source_path": "D:/Music/song.wav",
                "model_id": "model_xxx",
                "style": "bright",
            })

        self.assertIsInstance(result, ActionResult)
        self.assertEqual(result.type, "create_work")
        self.assertEqual(result.payload["params"]["pitch"], 1)
        json.dumps(result.to_dict(), ensure_ascii=False)

    async def test_before_create_preserves_existing_value(self) -> None:
        with TemporaryDirectory() as data_dir:
            ctx = PluginContext.create(plugin.id, ".", data_dir)
            payload = {"params": {"f0_method": "harvest"}}
            handler = plugin.hooks["before_create"][0]
            result = await call(handler, ctx, payload)

        self.assertEqual(result["params"]["f0_method"], "harvest")

    async def test_config_is_persisted(self) -> None:
        with TemporaryDirectory() as data_dir:
            first = PluginContext.create(plugin.id, ".", data_dir)
            first.config["preset"] = "bright"
            first.save_config()

            second = PluginContext.create(plugin.id, ".", data_dir)
            self.assertEqual(second.config["preset"], "bright")
            self.assertTrue(Path(data_dir, "config.json").is_file())


if __name__ == "__main__":
    unittest.main()
```

运行：

```powershell
python -m unittest discover -s tests -t .
```

Python 测试应特别覆盖：

- 清单中的 handler 名称与 `plugin.actions` 键一致；
- `Plugin` ID 与清单 ID 一致；
- 不覆盖用户已经设置的参数；
- 钩子保留不认识的 payload 字段；
- 返回值只包含 JSON 可序列化对象；
- 空输入、非法输入和依赖失败；
- 配置保存后可由新的 `PluginContext` 读取；
- 异步处理器不会启动永久后台任务。

直接调用 handler 不会模拟 Worker 的 30 秒超时、重新导入模块和 stderr 重定向。它是业务单元测试，不是 Worker 集成测试。

## 9. 真实宿主安装检查

发布前使用最终 `.xbplugin`，不要用源码目录或开发服务器代替最终包。

### 9.1 全新安装

1. 执行 `npm run pack`。
2. 在插件中心开启插件功能总开关。
3. 安装生成的 `.xbplugin`。
4. 确认插件卡片显示的 ID、名称、版本、运行类型、作者和权限正确。
5. 确认新插件默认关闭。
6. 启用插件；Python/混合插件应显示信任确认，并成功运行 `on_enable`。
7. 打开页面，检查无空白、无明显溢出，并执行每个对外动作。
8. 对 `create_work` 动作确认作品真实创建，标题、模型、源音频和参数正确。
9. 禁用插件，确认动作不可继续使用；再关闭总开关，确认所有插件暂停。

### 9.2 同 ID 更新

不要先卸载旧版本。直接安装同 ID 的新包：

1. 先在旧版本写入一项测试配置。
2. 安装版本号已更新的新包。
3. 确认插件代码和清单被替换。
4. 确认插件重新变为关闭状态。
5. 重新启用并确认 `plugin-data/<plugin-id>` 中的配置仍在。

卸载会删除插件代码和 `plugin-data/<plugin-id>`，不能用“卸载再安装”验证保留数据的升级路径。

### 9.3 卸载

卸载测试应使用可丢弃数据：

1. 停用插件。
2. 执行卸载。
3. 确认插件卡片消失。
4. 确认插件数据也被删除。

当前卸载不提供回收站或恢复操作。

## 10. 调试 Python Worker

Python 动作、钩子或生命周期失败时，页面只会收到错误消息。宿主会把最近一次失败详情写到：

```text
<XB-SVCB 数据目录>/plugin-data/<plugin-id>/error.log
```

每次失败会覆盖该文件，只保留最近错误详情的尾部。成功调用中的 `print()` 被重定向到 Worker stderr，但不会自动显示在插件页面，也不会作为持久日志保存。

需要长期日志时，在插件自己的 `ctx.data_dir` 中配置 `logging.FileHandler`。不要写入 `plugin_dir`，因为同 ID 更新会替换插件代码目录。

常见启用错误：

| 现象 | 首先检查 |
| --- | --- |
| 启用后立即恢复关闭 | `plugin.py` 是否存在、能否导入、`Plugin` ID 是否一致、`on_enable` 是否报错 |
| “未注册 Python 动作” | 清单 handler 与 `@plugin.action()` 名称 |
| “执行超过 30 秒” | 网络请求、模型加载、死循环或长时间同步任务 |
| 依赖导入失败 | 依赖是否位于包根目录 `vendor/`，是否兼容目标 Python/Windows |
| 配置重启后丢失 | 修改 `ctx.config` 后是否调用 `ctx.save_config()` |

## 11. 发布前测试门槛

至少满足以下条件再创建 GitHub Release：

- TypeScript/Vue 类型检查通过；
- 前端和清单从干净依赖安装后可以重新构建；
- 清单单元测试通过；
- 前端业务模块或关键 Vue 组件有成功和失败路径测试；
- Python 语法与单元测试通过；
- 最终包满足当前大小限制；
- 使用最终包完成一次全新安装、启用、动作、停用和卸载；
- 使用同 ID 新版本完成一次保留数据的替换安装；
- Python/混合插件人工审查了权限声明、入口和 `vendor/`；
- 已知未覆盖行为写入插件 README。

下一步：[打包、发布与市场](publishing.md)。
