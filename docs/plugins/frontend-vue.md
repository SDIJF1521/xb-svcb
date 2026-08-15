# Vue 3 自定义页面

Vue 页面是 TypeScript 前端插件的默认方案。页面布局和组件完全由插件作者控制；宿主只负责在沙箱 iframe 中载入构建后的 `dist/frontend/index.html`，并通过 Client SDK 提供有限能力。

本章构建一个可以创建翻唱任务的完整 Vue 插件。所有代码使用同一个动作 ID `create`，可以直接复制到脚手架项目中。

## 1. 创建项目

```powershell
npx @xb-svcb/plugin-sdk create vue-cover `
  --id com.example.vue-cover `
  --name "Vue 翻唱助手" `
  --type frontend

cd vue-cover
npm install
```

默认生成 `App.vue` 和 `components/GreetingForm.vue`。下面把示例组件替换为翻唱表单。

## 2. 定义清单和动作

`src/plugin.ts`：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.vue-cover', 'Vue 翻唱助手', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('使用 Vue 组件创建翻唱任务。')
  .author('Your Name')
  .page('home', '快速翻唱', {
    description: '自定义 Vue 页面入口。',
    fields: [],
    actions: ['create'],
  })
  .createWork('create', '创建翻唱', {
    source_path: '{{source_path}}',
    model_id: '{{model_id}}',
    title: '{{title}}',
    workflow: 'auto_mix',
    params: {
      pitch: '{{pitch}}',
      f0_method: '{{f0_method}}',
    },
  })

await writeManifest(app, '.')
```

这里的 `page.fields` 可以为空，因为 `frontend.entry` 存在时，宿主会显示自定义页面，而不会渲染声明式表单。`page.actions` 仍会出现在上下文中，但自定义页面调用动作时不受它过滤；真正的安全边界是插件清单中的 `actions`。

## 3. Vue 入口

`frontend/src/main.ts`：

```ts
import { createApp } from 'vue'

import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

这就是普通 Vue 3 应用。SDK 不接管 `createApp()`，也不要求特殊根组件。

## 4. 页面布局

`frontend/src/App.vue`：

```vue
<script setup lang="ts">
import CoverForm from './components/CoverForm.vue'
</script>

<template>
  <main class="plugin-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">COVER WORKFLOW</p>
        <h1>Vue 翻唱助手</h1>
        <p>选择源音频、模型和推理参数。</p>
      </div>
    </header>

    <CoverForm />
  </main>
</template>
```

`App.vue` 可以替换为任何布局，也可以继续拆分 header、sidebar、tabs、form 和 preview 组件。宿主不会读取组件名称或 DOM 结构。

## 5. 编写业务组件

创建 `frontend/src/components/CoverForm.vue`：

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'

import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const form = reactive({
  source_path: '',
  model_id: '',
  title: '我的 Vue 翻唱',
  pitch: 0,
  f0_method: 'rmvpe',
})
const output = ref('')

const {
  hosted,
  loading,
  error,
  runAction,
  notify,
} = usePluginHost()

async function submit() {
  if (!hosted.value) {
    output.value = '当前是浏览器预览，真实动作需要安装插件后测试。'
    return
  }

  if (!form.source_path || !form.model_id) {
    await notify('请填写源音频路径和模型 ID', 'warning')
    return
  }

  try {
    const result = await runAction('create', { ...form })
    output.value = JSON.stringify(result, null, 2)
  } catch {
    output.value = error.value?.message || '创建任务失败'
  }
}
</script>

<template>
  <form class="cover-form" @submit.prevent="submit">
    <div class="form-grid">
      <label>
        源音频路径
        <input v-model.trim="form.source_path" placeholder="D:/Music/song.wav">
      </label>

      <label>
        模型 ID
        <input v-model.trim="form.model_id" placeholder="model_xxx">
      </label>

      <label>
        作品标题
        <input v-model.trim="form.title">
      </label>

      <label>
        升降调
        <input v-model.number="form.pitch" type="number">
      </label>

      <label>
        F0 方法
        <select v-model="form.f0_method">
          <option value="rmvpe">RMVPE</option>
          <option value="harvest">Harvest</option>
        </select>
      </label>
    </div>

    <button :disabled="loading">
      {{ loading ? '正在创建…' : '创建翻唱' }}
    </button>
    <pre v-if="output" aria-live="polite">{{ output }}</pre>
  </form>
</template>
```

`runAction('create', values)` 与清单里的 `.createWork('create', ...)` 对应。宿主会插值动作模板、创建真实任务，并把动作结果以及创建后的 `work` 返回给页面。

## 6. `usePluginHost()` 状态

```ts
const pluginHost = usePluginHost({ loadContext: true })
```

| 成员 | 类型 | 行为 |
| --- | --- | --- |
| `hosted` | 只读 `Ref<boolean>` | 当前页面是否有宿主 token |
| `context` | 只读 `Ref<PluginHostContext \| null>` | 插件、当前清单页面和主题 |
| `plugin` | `ComputedRef<Manifest \| undefined>` | 当前插件清单 |
| `page` | `ComputedRef<Page \| undefined>` | 当前页面元数据 |
| `theme` | `ComputedRef<string>` | `cyber`、`anime`、`custom` 或空字符串 |
| `loading` | 只读 `Ref<boolean>` | 至少一个 SDK 请求仍在进行 |
| `error` | 只读 `Ref<Error \| null>` | 最近一次失败；新请求开始时清空 |
| `refreshContext()` | 函数 | 手动重新读取上下文 |
| `runAction()` | 函数 | 调用清单动作 |
| `createWork()` | 函数 | 直接创建翻唱任务 |
| `assetData()` | 函数 | 获取资源元数据和 Data URL |
| `assetUrl()` | 函数 | 只获取资源 Data URL |
| `notify()` | 函数 | 显示宿主通知 |
| `clearError()` | 函数 | 清空错误状态 |

多个请求并发时，`loading` 会等所有请求结束后才变回 `false`。`error` 是共享的“最近错误”，复杂页面可以在自己的 composable 中为不同操作维护独立错误状态。

## 7. 主题适配

当前 `context.theme` 可能是 `cyber`、`anime` 或 `custom`。iframe 不会继承宿主 CSS 变量，自定义主题的具体颜色也没有通过 SDK 暴露；插件只能根据主题名称选择自己定义的颜色。

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const { theme } = usePluginHost()
const themeClass = computed(() => `theme-${theme.value || 'cyber'}`)
</script>

<template>
  <main :class="themeClass">...</main>
</template>
```

```css
.theme-cyber { color: #e8edf2; background: #15191d; }
.theme-anime { color: #253247; background: #f7f9ff; }
.theme-custom { color: #e8edf2; background: #20242a; }
```

主题切换不会主动向已打开的插件页面推送事件。用户重新打开页面时会取得新主题；不要依赖实时同步。

## 8. 多视图与路由

当前插件中心只为插件打开清单中的第一个页面，没有完整的多页面导航 UI，也没有 `navigate()` Client API。推荐只声明一个清单页面，在 Vue 内部实现 tabs 或 memory router：

```ts
import { createRouter, createMemoryHistory } from 'vue-router'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/settings', component: SettingsView },
  ],
})
```

不要使用需要服务器回退的 `createWebHistory()`。插件在 `srcdoc` iframe 中运行，没有正常的网站路径。

## 9. Pinia 和组件库

普通 npm 依赖可以照常安装：

```powershell
npm install pinia vue-router
```

插件不会复用宿主已经加载的 Vue、Element Plus 或样式。需要的依赖必须写入自己的 `package.json` 并进入构建。大型组件库应按需引入；最终单文件入口必须小于 2 MB。

## 10. 插件资源

小图标可以直接 import，让 Vite 内联。较大图片、音频和 JSON 应放在插件根目录，例如：

```text
assets/
├─ cover.png
└─ presets.json
```

Vue 组件中读取：

```ts
const { assetUrl, assetData } = usePluginHost()

const coverUrl = await assetUrl('assets/cover.png')
const presets = await assetData('assets/presets.json')
```

返回的是 Data URL，不是操作系统路径。路径必须相对插件根目录，不能包含 `..`，单个资源最大 10 MB。

## 11. 沙箱能力表

| 需求 | 当前是否支持 | 做法或替代方案 |
| --- | --- | --- |
| 自定义 HTML/CSS/Vue 组件 | 支持 | 正常编写并用 Vite 构建 |
| 调用清单和 Python 动作 | 支持 | `runAction()` |
| 创建翻唱任务 | 支持 | `runAction()` 或 `createWork()` |
| 读取插件包资源 | 支持 | `assetData()` / `assetUrl()` |
| 显示宿主通知 | 支持 | `notify()` |
| 读取宿主 DOM 或 Vue store | 不支持 | 通过公开 Client API 获取上下文 |
| 打开宿主内部路由 | 不支持 | 提示用户从宿主导航 |
| 调用宿主文件选择器 | 不支持 | 当前没有公开 API |
| 查询模型列表或任务列表 | 不支持 | 当前没有公开 API |
| 普通相对脚本和 CSS 文件 | 不可靠 | 使用 singlefile 构建 |
| 外部网络请求 | 取决于 CORS | 目标服务必须允许 opaque origin 请求 |
| localStorage 持久化 | 不应依赖 | 使用混合插件的 `PluginContext.config` |

iframe 使用 opaque origin。即使页面能发出网络请求，也会受浏览器 CORS 约束；前端 `network` 权限声明目前不会改变浏览器策略。

## 12. 构建和验证

```powershell
npm run typecheck
npm run build
npm run validate
npm run pack
```

构建后检查：

- `dist/frontend/index.html` 存在；
- 文件小于 2 MB；
- HTML 中没有依赖 `./assets/*.js` 的外部 bundle；
- `xb-svcb-plugin.json` 的 `frontend.entry` 为 `dist/frontend/index.html`；
- 真实安装后页面能打开并调用 `create` 动作。

完整工程可参考 [`plugin-sdk/examples/hello-plugin`](../../plugin-sdk/examples/hello-plugin)。
