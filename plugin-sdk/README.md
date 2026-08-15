# XB-SVCB Plugin SDK

用于开发 XB-SVCB 的纯前端、纯 Python 与前端 + Python 插件。SDK 包含清单构建器、页面端 TypeScript Client、Python API、CLI 脚手架、校验器和打包器，插件开发者不需要阅读主项目源码。

推荐从分章节文档开始：[插件开发文档](../docs/plugins/README.md)。旧版单文件指南仍保留在[插件开发完整指南](../docs/plugin-development.md)，适合全文搜索。

## 创建第一个插件

```powershell
npx @xb-svcb/plugin-sdk create my-plugin `
  --id com.example.my-plugin `
  --name "我的插件" `
  --type frontend

cd my-plugin
npm install
npm run dev
```

脚手架默认生成 TypeScript 工程。`--type` 支持：

- `frontend`：自定义 TypeScript 页面或声明式页面；
- `python`：无页面的 Python 动作与翻唱钩子；
- `hybrid`：TypeScript 页面 + Python 动作。

TypeScript 前端默认使用 Vue 3。使用原生 TypeScript 页面时传 `--framework vanilla`；需要无构建 JavaScript 模板时使用 `--language js`。

## Vue 3 工程结构

```text
my-plugin/
├─ src/plugin.ts                清单定义
├─ frontend/index.html          页面 HTML
├─ frontend/src/main.ts         创建 Vue 应用
├─ frontend/src/App.vue         页面布局，可完全修改
├─ frontend/src/components/     用户自定义组件
├─ frontend/src/style.css       页面样式
├─ vite.config.ts               单文件页面构建
├─ plugin.py                    Python/混合插件可选
├─ dist/frontend/index.html     页面构建结果
└─ xb-svcb-plugin.json          清单构建结果
```

常用命令：

```powershell
npm run dev        # 浏览器预览页面布局
npm run typecheck  # 检查清单、页面和构建配置的 TypeScript
npm run build      # 构建页面与插件清单
npm run validate   # 类型检查、完整构建、清单校验
npm run pack       # 生成 .xbplugin
```

## 定义插件清单

`src/plugin.ts`：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.quick-cover', '快速翻唱', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('用自定义页面创建翻唱任务。')
  .author('Your Name')
  .page('home', '快速翻唱', { fields: [], actions: ['create'] })
  .createWork('create', '创建翻唱', {
    source_path: '{{source_path}}',
    model_id: '{{model_id}}',
    title: '{{title}}',
    workflow: 'auto_mix',
    params: { pitch: '{{pitch}}' },
  })

await writeManifest(app, '.')
```

`@xb-svcb/plugin-sdk` 负责清单、字段、动作、校验和打包。它只在开发机上运行。

## 编写自定义 Vue 页面

`frontend/src/App.vue` 可以使用任意 Vue 布局和子组件。组件通过 Vue SDK 调用宿主：

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const name = ref('朋友')
const output = ref('')
const { hosted, loading, error, runAction } = usePluginHost()

async function submit() {
  if (!hosted.value) return
  try {
    output.value = JSON.stringify(
      await runAction('hello', { name: name.value }),
      null,
      2,
    )
  } catch {
    output.value = error.value?.message || '执行失败'
  }
}
</script>

<template>
  <section class="my-layout">
    <input v-model="name">
    <button :disabled="loading" @click="submit">运行</button>
    <pre>{{ output }}</pre>
  </section>
</template>
```

`@xb-svcb/plugin-sdk/vue` 提供 `usePluginHost()`，可在任意 Vue 组件中使用。也可以直接从 `@xb-svcb/plugin-sdk/client` 导入无框架 Client。

页面 Client 提供：

- `host.getContext()`：当前插件、页面和主题；
- `host.runAction()`：运行清单动作或 Python 动作；
- `host.createWork()`：使用强类型参数直接创建翻唱任务；
- `host.assetData()` / `host.assetUrl()`：读取插件包内资源；
- `host.notify()`：显示宿主通知；
- `isHosted()`：区分浏览器预览和真实插件宿主。

Client 同时导出 `CreateWorkPayload`、`InferenceParams`、`CreatedWork`、`BlendModel` 等类型。请求默认 30 秒超时。

## 三种完整示例

```text
examples/hello-plugin       Vue 3 组件页面 + 前端动作
examples/python-preset      纯 Python 翻唱钩子
examples/hybrid-assistant   Vanilla TypeScript 页面 + Python 动作
```

运行示例：

```powershell
cd plugin-sdk\examples\hybrid-assistant
npm install
npm run validate
npm run pack
```

## SDK 组成

- `index.mjs` / `index.d.ts`：清单构建器、字段工厂、校验与打包；
- `client.mjs` / `client.d.ts`：自定义页面宿主 API 与业务类型；
- `vue.mjs` / `vue.d.ts`：Vue 3 `usePluginHost()` composable；
- `bin/xb-plugin.mjs`：`create`、`validate`、`pack` CLI；
- `python/xb_svcb_plugin`：Python 动作、钩子、上下文与配置；
- `examples/`：三类可构建、可安装的完整工程。

详细签名表见 [API 速查](../docs/plugins/reference.md)。

## 运行边界

自定义页面在 `sandbox="allow-scripts"` iframe 中运行，不能访问宿主 DOM。构建器使用 Vite 将 JavaScript 和 CSS 内联到单文件 HTML；入口 HTML 上限为 2 MB，大型资源应放入插件包并通过 `host.assetUrl()` 读取。

Python 插件会执行真实代码，并拥有当前用户权限。独立 Worker 只提供崩溃隔离，不是安全沙箱，只应启用可信来源。
安装和执行的当前硬限制：

| 项目 | 限制 |
| --- | --- |
| 插件包 | 最大 20 MB |
| 解压后全部文件 | 最大 50 MB |
| 清单文件 | 最大 512 KB |
| 自定义页面入口 HTML | 最大 2 MB |
| 单个插件资源 | 最大 10 MB |
| 页面 Client 请求 | 默认 30 秒超时 |
| Python Worker 调用 | 30 秒 |
