# XB-SVCB 插件开发指南

XB-SVCB 插件可以扩展翻唱流程、提供声明式工具页面，或运行自定义 Python 逻辑。本指南只使用公开 SDK；开发插件不需要阅读 XB-SVCB 主项目源码。

本文的学习顺序借鉴 [NoneBot2 官方指南](https://nonebot.dev/docs/next/tutorial/create-plugin)：先建立插件概念，用脚手架完成一个能运行的插件，再逐步学习元数据、动作、钩子、配置、测试和发布。两套插件系统的 API 并不兼容，请以本文和 XB-SVCB SDK 的类型定义为准。

> **阅读提示**
>
> 第一次开发建议依次阅读“插件是什么”到“第一个纯前端插件”。需要修改翻唱参数时继续阅读 Python 插件和流程钩子；准备公开发布时再阅读权限、依赖、打包和市场章节。

## 阅读路线

| 目标                   | 建议章节                                                                                               | 完成后得到                        |
| ---------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------- |
| 先跑通一个插件         | [插件是什么](#1-插件是什么) -> [脚手架](#4-使用脚手架创建插件) -> [纯前端插件](#5-第一个纯前端插件)       | 可安装的`.xbplugin`             |
| 修改翻唱默认参数       | [纯 Python 插件](#6-第一个纯-python-插件) -> [Python SDK](#10-python-sdk) -> [流程钩子](#11-翻唱流程钩子) | `before_create` 钩子插件        |
| 做带页面的 Python 工具 | [混合插件](#7-第一个混合插件) -> [清单与元数据](#8-清单与元数据) -> [权限与安全](#13-权限与安全)          | 页面与 Python 动作协作的插件      |
| 发布插件               | [测试与调试](#15-测试与调试) -> [打包与安装](#16-打包与安装) -> [GitHub 市场发布](#17-github-市场发布)    | 可供用户安装的 Release 与市场索引 |

## 目录

- [1. 插件是什么](#1-插件是什么)
- [2. 选择插件类型](#2-选择插件类型)
- [3. 环境准备](#3-环境准备)
- [4. 使用脚手架创建插件](#4-使用脚手架创建插件)
- [5. 第一个纯前端插件](#5-第一个纯前端插件)
- [6. 第一个纯 Python 插件](#6-第一个纯-python-插件)
- [7. 第一个混合插件](#7-第一个混合插件)
- [8. 清单与元数据](#8-清单与元数据)
- [9. TypeScript/JavaScript SDK](#9-typescriptjavascript-sdk)
- [10. Python SDK](#10-python-sdk)
- [11. 翻唱流程钩子](#11-翻唱流程钩子)
- [12. 配置与数据目录](#12-配置与数据目录)
- [13. 权限与安全](#13-权限与安全)
- [14. 第三方依赖](#14-第三方依赖)
- [15. 测试与调试](#15-测试与调试)
- [16. 打包与安装](#16-打包与安装)
- [17. GitHub 市场发布](#17-github-市场发布)
- [18. API 参考](#18-api-参考)
- [19. 常见问题](#19-常见问题)

## 1. 插件是什么

一个插件是包含 `xb-svcb-plugin.json` 的目录或 `.xbplugin` 压缩包。清单保存插件元数据、运行类型、页面、动作、Python 入口和权限声明。

```text
src/plugin.ts -----------> xb-svcb-plugin.json -----> 插件元数据、页面与动作
frontend/src/main.ts ---> dist/frontend/index.html -> 沙箱 iframe 中的自定义页面
plugin.py ------------------------------------------> 独立 Worker 中的动作、钩子与生命周期
```

这里有两种 TypeScript：`src/plugin.ts` 是构建清单的开发脚本，不会被宿主执行；`frontend/src/main.ts` 是自定义页面代码，会由 Vite 编译并内联到 `dist/frontend/index.html`，安装后在沙箱 iframe 中执行。纯 Python 插件可以没有前端目录。

推荐插件工程结构：

```text
my-plugin/
├─ package.json
├─ tsconfig.json              # TypeScript 严格检查配置
├─ src/
│  └─ plugin.ts               # 使用 SDK 生成清单（脚手架默认）
├─ frontend/                  # 纯前端/混合插件的页面源码
│  ├─ index.html
│  └─ src/
│     ├─ main.ts              # 页面端 TypeScript
│     ├─ App.vue              # 默认 Vue 页面布局
│     ├─ components/          # 用户自定义 Vue 组件
│     └─ style.css
├─ dist/frontend/index.html   # Vite 生成的单文件页面，清单指向这里
├─ vite.config.ts             # 单文件页面构建配置
├─ plugin.py                  # Python/混合插件入口，可选
├─ vendor/                    # Python 第三方依赖，可选
├─ README.md
└─ xb-svcb-plugin.json        # SDK 生成
```

`xb-svcb-plugin.json` 和 `dist/` 都是构建产物。前者来自 `src/plugin.ts`，后者来自 `frontend/`。不要手工维护构建产物。纯 JavaScript 插件可以使用 `--language js`，脚手架会生成 `build.mjs` 和无需构建的 `frontend/index.html`。

Python 入口既可以是单文件，也可以是包：

```text
# 单文件插件
plugin.py

# 包插件
my_plugin/
├─ __init__.py
├─ config.py
└─ handlers.py
```

包插件声明 `.python('my_plugin/__init__.py')` 或 `.hybrid('my_plugin/__init__.py')`，可以正常使用 `from .config import Config` 等相对导入。

安装插件并不等于运行插件。插件新安装后默认关闭，用户还需要开启插件总开关和单插件开关。

## 2. 选择插件类型

XB-SVCB 支持三种插件类型：

| 类型          | 适合场景                                   | 页面   | Python | 清单运行类型 |
| ------------- | ------------------------------------------ | ------ | ------ | ------------ |
| 纯前端        | 参数表单、预设页面、创建翻唱任务、提示工具 | 支持   | 不执行 | `frontend` |
| 纯 Python     | 自动修改翻唱任务、记录数据、无页面后台逻辑 | 可省略 | 支持   | `python`   |
| 前端 + Python | 页面收集输入，Python 计算、校验或生成任务  | 支持   | 支持   | `hybrid`   |

纯前端插件使用宿主提供的声明式控件，不是任意 HTML/Vue 页面。Python 和混合插件会执行真实 Python 代码。

建议：

- 只需要表单和固定参数时选择纯前端，安装风险最低；
- 只需要修改翻唱流程时选择纯 Python；
- 页面按钮需要复杂计算、配置读写或异步逻辑时选择混合插件。

## 3. 环境准备

使用 XB-SVCB Plugin SDK 开发插件需要 Node.js 20 或更高版本，用于脚手架、清单校验和打包：

```powershell
node --version
npm --version
```

Python/混合插件还建议安装 Python 3.10 或更高版本，用于本地类型检查和测试：

```powershell
python --version
```

插件在 XB-SVCB 内运行时，由宿主提供 Python SDK。开发机上为了让编辑器识别类型，可以安装仓库中的 SDK：

```powershell
pip install -e plugin-sdk\python
```

## 4. 使用脚手架创建插件

在 XB-SVCB 仓库中可直接使用本地 CLI：

```powershell
node plugin-sdk\bin\xb-plugin.mjs create my-plugin `
  --id com.example.my-plugin `
  --name "我的插件" `
  --type frontend `
  --author "Your Name"
```

`--type` 可选：

```text
frontend   纯前端插件，默认值
python     纯 Python 插件
hybrid     前端 + Python 插件
```

如果 SDK 已经发布到 npm，也可以使用：

```powershell
npx @xb-svcb/plugin-sdk create my-plugin --id com.example.my-plugin --name "我的插件" --type hybrid
```

脚手架默认生成 Vue 3 + TypeScript 工程。使用不带 Vue 的原生 TypeScript 页面：

```powershell
npx @xb-svcb/plugin-sdk create my-plugin --id com.example.my-plugin --name "我的插件" --framework vanilla
```

想使用无构建 JavaScript 时显式传入语言：

```powershell
npx @xb-svcb/plugin-sdk create my-plugin --id com.example.my-plugin --name "我的插件" --language js
```

创建后：

```powershell
cd my-plugin
npm install
npm run typecheck
npm run build
npm run validate
npm run pack
```

脚手架会生成可运行代码，不需要从空白文件开始。各命令的职责如下：

| 命令                  | 作用                         | 是否生成文件    |
| --------------------- | ---------------------------- | --------------- |
| `npm run typecheck` | 检查 TypeScript 类型         | 否              |
| `npm run dev`       | 在浏览器预览自定义前端页面   | 否              |
| `npm run build`     | 构建页面并执行清单脚本       | `dist/`、清单 |
| `npm run validate`  | 类型检查、完整构建并校验清单 | 更新页面与清单  |
| `npm run pack`      | 校验后打包                   | `.xbplugin`   |

打包成功后，在 XB-SVCB 中打开“插件中心”，先开启插件总开关，再选择“安装本地插件包”并选中生成的 `.xbplugin`。新安装的插件默认关闭；检查名称、版本和权限后，还需要单独启用它。

> **注意**
>
> 安装 Python 或混合插件时不会执行 Python。第一次启用插件才会加载入口并调用 `on_enable`；因此启用失败通常表示 Python 入口、插件 ID 或依赖有问题。

插件 ID 只能使用小写字母、数字、`.`、`_`、`-`，长度为 3 到 64 个字符。推荐反向域名：

```text
com.example.quick-cover
io.github.username.my-plugin
```

## 5. 第一个纯前端插件

纯前端插件适合创建参数页面和固定动作。完整示例位于：

```text
plugin-sdk/examples/hello-plugin
```

### 5.1 `src/plugin.ts`

```ts
import { fields, plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.hello', '问候插件', '1.0.0')
  .frontend()
  .description('一个不执行 Python 的简单页面插件。')
  .author('Your Name')
  .page('home', '欢迎页面', {
    description: '输入名称并显示问候。',
    fields: [
      fields.text('name', '你的名字', {
        default: '朋友',
        placeholder: '请输入名字',
      }),
    ],
    actions: ['hello'],
  })
  .message('hello', '打招呼', '你好，{{name}}！')

await writeManifest(app, '.')
```

### 5.2 构建和打包

```powershell
npm install
npm run typecheck
npm run build
npm run validate
npm run pack
```

生成的 `.xbplugin` 可以在插件中心直接安装。这个插件只使用声明式页面和消息动作，不执行第三方代码。

### 5.3 创建翻唱任务

把消息动作换成 `createWork`：

```ts
const app = plugin('com.example.quick-cover', '快速翻唱', '1.0.0')
  .frontend()
  .page('start', '快速翻唱', {
    fields: [
      fields.text('source_path', '源音频路径'),
      fields.text('model_id', '模型 ID'),
      fields.text('title', '作品标题', { default: '我的翻唱' }),
      fields.number('pitch', '升降调', { default: 0 }),
    ],
    actions: ['create'],
  })
  .createWork('create', '开始翻唱', {
    source_path: '{{source_path}}',
    model_id: '{{model_id}}',
    title: '{{title}}',
    workflow: 'auto_mix',
    params: { pitch: '{{pitch}}' },
  })
```

`{{fieldId}}` 会替换为页面值。如果整个值只有一个占位符，数字和布尔值会保留原始类型。

### 5.4 声明式页面：不写页面代码

如果你的需求是“做一个自己的参数页面，点击按钮创建翻唱”，可以从纯前端插件开始：

```ts
import { fields, plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.my-cover-page', '我的翻唱页面', '1.0.0')
  .frontend()
  .description('使用自定义参数页面创建翻唱任务。')
  .author('Your Name')
  .page('home', '快速翻唱', {
    description: '填写参数后创建一首翻唱。',
    fields: [
      fields.text('source_path', '源音频路径', {
        placeholder: 'D:/Music/song.wav',
        help: '填写本机音频文件的完整路径。',
      }),
      fields.text('model_id', '模型 ID', {
        placeholder: 'model_xxx',
      }),
      fields.text('title', '作品标题', {
        default: '我的翻唱',
      }),
      fields.select('device', '推理设备', [
        { label: '自动', value: 'auto' },
        { label: 'CPU', value: 'cpu' },
      ], { default: 'auto' }),
      fields.number('pitch', '升降调', { default: 0 }),
      fields.switch('enhance', '自动增强', { default: true }),
    ],
    actions: ['create'],
  })
  .createWork('create', '开始翻唱', {
    source_path: '{{source_path}}',
    model_id: '{{model_id}}',
    title: '{{title}}',
    workflow: 'auto_mix',
    params: {
      device: '{{device}}',
      pitch: '{{pitch}}',
    },
    vocal_enhancement: { enabled: '{{enhance}}', level: 'basic' },
  })

await writeManifest(app, '.')
```

这里有三层对应关系：

1. `fields.*()` 定义页面控件，提交后组成 `values`；
2. `page(..., { actions: ['create'] })` 决定页面显示哪个动作；
3. `.createWork('create', ...)` 使用同名动作 ID，把 `{{fieldId}}` 替换成用户输入。

声明式页面只能使用 `text`、`number`、`select`、`switch` 和 `textarea`，优点是代码少、样式自动跟随宿主。如果需要自由布局、复杂交互、图表、图片或异步状态，请使用下一节的自定义 TypeScript 页面。需要执行 Python 时再选择混合插件。

保存为 `src/plugin.ts` 后，在插件目录执行：

```powershell
npm install
npm run validate
npm run pack
```

再到 XB-SVCB 的“插件中心”开启插件总开关，安装生成的 `.xbplugin`，并单独启用该插件即可看到页面。

### 5.5 Vue 3 自定义页面：推荐方式

TypeScript 前端插件默认使用 Vue 3。宿主不限制组件结构：`App.vue` 可以定义任意布局，也可以拆分任意数量的 `.vue` 组件、composable 和普通 TypeScript 模块。最终只需要由 Vite 输出 `dist/frontend/index.html`。

#### 5.5.1 创建 Vue 插件

```powershell
npx @xb-svcb/plugin-sdk create my-vue-plugin `
  --id com.example.my-vue-plugin `
  --name "我的 Vue 插件" `
  --type frontend

cd my-vue-plugin
npm install
npm run dev
```

不需要额外传 `--framework vue`，Vue 是 TypeScript 前端和混合插件的默认框架。显式写法也有效：

```powershell
xb-plugin create my-vue-plugin `
  --id com.example.my-vue-plugin `
  --name "我的 Vue 插件" `
  --framework vue
```

生成结构：

```text
my-vue-plugin/
├─ src/plugin.ts
├─ frontend/
│  ├─ index.html
│  └─ src/
│     ├─ main.ts
│     ├─ App.vue
│     ├─ style.css
│     ├─ env.d.ts
│     └─ components/
│        └─ GreetingForm.vue
├─ vite.config.ts
├─ tsconfig.json
├─ package.json
├─ dist/frontend/index.html
└─ xb-svcb-plugin.json
```

`frontend/src/` 完全属于插件作者。可以删除示例组件、创建自己的目录、使用 CSS Modules，或者加入 Pinia、Vue Router 和其他 Vue 组件库。

#### 5.5.2 清单与 Vue 页面入口

`src/plugin.ts`：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.my-vue-plugin', '我的 Vue 插件', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('一个完全自定义布局的 Vue 页面。')
  .author('Your Name')
  .page('home', '插件首页', {
    fields: [],
    actions: ['hello'],
  })
  .message('hello', '打招呼', '你好，{{name}}！')

await writeManifest(app, '.')
```

清单只负责告诉宿主“页面在哪里、有哪些页面路由和动作”。Vue 组件树、布局、表单状态和交互逻辑不会写入清单。

#### 5.5.3 Vue 应用入口

`frontend/src/main.ts`：

```ts
import { createApp } from 'vue'

import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

这是普通 Vue 3 应用入口。SDK 没有包装或替换 `createApp()`。

#### 5.5.4 自定义页面布局

`frontend/src/App.vue`：

```vue
<script setup lang="ts">
import CoverForm from './components/CoverForm.vue'
import TaskSummary from './components/TaskSummary.vue'
</script>

<template>
  <main class="workspace">
    <header class="toolbar">
      <div>
        <h1>智能翻唱工作台</h1>
        <p>选择模型并设置翻唱参数</p>
      </div>
    </header>

    <div class="content-grid">
      <CoverForm />
      <TaskSummary />
    </div>
  </main>
</template>

<style scoped>
.workspace {
  width: min(960px, 100%);
  margin: 0 auto;
  padding: 24px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr);
  gap: 16px;
}

@media (max-width: 720px) {
  .content-grid { grid-template-columns: 1fr; }
}
</style>
```

布局没有固定模板。示例中的 header、grid 和组件都可以删除或重写；宿主只提供一个宽度为 100% 的 iframe 页面区域。

#### 5.5.5 在 Vue 组件中调用宿主

`frontend/src/components/CoverForm.vue`：

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'

import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const form = reactive({
  source_path: '',
  model_id: '',
  title: '我的 Vue 翻唱',
  pitch: 0,
})
const output = ref('')

const {
  hosted,
  context,
  page,
  theme,
  loading,
  error,
  runAction,
  notify,
} = usePluginHost()

async function submit() {
  if (!hosted.value) {
    output.value = '浏览器预览模式不会创建真实任务。'
    return
  }

  try {
    const result = await runAction('create', { ...form })
    output.value = JSON.stringify(result, null, 2)
    await notify('任务已提交', 'success')
  } catch {
    output.value = error.value?.message || '提交失败'
  }
}
</script>

<template>
  <form class="cover-form" @submit.prevent="submit">
    <label>源音频 <input v-model="form.source_path"></label>
    <label>模型 ID <input v-model="form.model_id"></label>
    <label>标题 <input v-model="form.title"></label>
    <label>升降调 <input v-model.number="form.pitch" type="number"></label>

    <button :disabled="loading">
      {{ loading ? '提交中…' : '创建翻唱' }}
    </button>
    <pre v-if="output">{{ output }}</pre>
  </form>
</template>
```

`usePluginHost()` 返回响应式状态和方法：

| 成员 | Vue 类型 | 说明 |
| --- | --- | --- |
| `hosted` | 只读 `Ref<boolean>` | 是否运行在真实插件宿主中 |
| `context` | 只读 `Ref<PluginHostContext \| null>` | 插件、页面和主题上下文 |
| `plugin` | `ComputedRef<Manifest \| undefined>` | 当前插件清单 |
| `page` | `ComputedRef<Page \| undefined>` | 当前页面路由 |
| `theme` | `ComputedRef<string>` | 当前宿主主题 |
| `loading` | 只读 `Ref<boolean>` | SDK 调用是否执行中 |
| `error` | 只读 `Ref<Error \| null>` | 最近一次调用错误 |
| `refreshContext()` | 异步函数 | 重新读取宿主上下文 |
| `runAction()` | 异步函数 | 调用清单动作或 Python 动作 |
| `createWork()` | 异步函数 | 直接创建翻唱任务 |
| `assetUrl()` | 异步函数 | 获取插件包内资源 Data URL |
| `notify()` | 异步函数 | 显示宿主通知 |

composable 默认在组件挂载时加载上下文。只想手动加载时使用：

```ts
const pluginHost = usePluginHost({ loadContext: false })
await pluginHost.refreshContext()
```

#### 5.5.6 创建和复用自己的组件

组件不必直接调用 SDK。推荐把宿主调用放在页面级组件或自定义 composable 中，再通过 props 和 emits 连接纯 UI 组件：

```vue
<!-- frontend/src/components/PitchControl.vue -->
<script setup lang="ts">
defineProps<{ modelValue: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()
</script>

<template>
  <label>
    升降调
    <input
      type="number"
      :value="modelValue"
      @input="emit('update:modelValue', Number(($event.target as HTMLInputElement).value))"
    >
  </label>
</template>
```

使用方式与普通 Vue 项目完全一致：

```vue
<PitchControl v-model="form.pitch" />
```

#### 5.5.7 使用 Pinia、Vue Router 和组件库

可以安装普通 npm 依赖：

```powershell
npm install pinia vue-router
```

注意以下宿主约束：

- 插件运行于 `srcdoc` iframe，Vue Router 应使用 `createMemoryHistory()`；不要依赖服务器端路由回退。
- 插件不会复用宿主的 Vue、Element Plus 或 CSS，所需依赖必须由插件自己声明并构建。
- 最终入口 HTML 上限为 2 MB。大型组件库应按需引入，图片和音频使用 `assetUrl()`，避免全部内联。
- 不要尝试访问 `window.parent.document`；沙箱会阻止宿主 DOM 访问。

#### 5.5.8 Vue 构建配置

脚手架生成的 `vite.config.ts`：

```ts
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

export default defineConfig({
  root: 'frontend',
  plugins: [vue(), viteSingleFile()],
  build: {
    outDir: '../dist/frontend',
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
  },
})
```

`vue-tsc --noEmit` 检查 `.ts` 和 `.vue` 文件；Vite 把 Vue runtime、组件、CSS 与页面 SDK 打入单文件 HTML。

### 5.6 原生 TypeScript 页面：完整示例

自定义页面不是声明式表单。你可以编写普通 HTML、CSS 和 TypeScript，自由决定布局与交互，再通过页面 SDK 请求宿主执行受支持的操作。宿主会在带有 `sandbox="allow-scripts"` 的 iframe 中运行最终 HTML。

先创建项目：

```powershell
npx @xb-svcb/plugin-sdk create my-cover-page `
  --id com.example.my-cover-page `
  --name "我的翻唱页面" `
  --type frontend `
  --framework vanilla
cd my-cover-page
npm install
```

脚手架生成的关键文件：

```text
my-cover-page/
├─ src/plugin.ts                # 清单定义
├─ frontend/index.html          # 页面 HTML 入口
├─ frontend/src/main.ts         # 页面逻辑，真正的 TypeScript 前端代码
├─ frontend/src/style.css       # 页面样式
├─ vite.config.ts               # 输出单文件 HTML
├─ dist/frontend/index.html     # 构建结果
└─ xb-svcb-plugin.json          # 清单构建结果
```

#### 5.6.1 在清单中声明自定义页面

`src/plugin.ts`：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.my-cover-page', '我的翻唱页面', '1.0.0')
  .frontend('dist/frontend/index.html')
  .description('使用 TypeScript 编写的翻唱参数页面。')
  .author('Your Name')
  .page('home', '快速翻唱', {
    description: '自定义页面的导航名称和说明。',
    fields: [],
    actions: ['create'],
  })
  .createWork('create', '创建翻唱', {
    source_path: '{{source_path}}',
    model_id: '{{model_id}}',
    title: '{{title}}',
    workflow: 'auto_mix',
    params: { pitch: '{{pitch}}' },
  })

await writeManifest(app, '.')
```

关键点：

1. `.frontend('dist/frontend/index.html')` 必须指向构建结果，不是 `frontend/index.html` 源文件。
2. `.page()` 仍负责插件中心里的页面名称和路由；自定义页面可以把 `fields` 留空。
3. `.createWork()` 注册宿主动作；页面端通过同一个动作 ID `create` 调用。
4. 纯前端插件不能注册 `pythonAction()`。需要 Python 动作时使用 `.hybrid('plugin.py')`。

#### 5.6.2 编写 HTML

`frontend/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>我的翻唱页面</title>
</head>
<body>
  <main>
    <label>源音频 <input id="source_path"></label>
    <label>模型 ID <input id="model_id"></label>
    <label>标题 <input id="title"></label>
    <label>升降调 <input id="pitch" type="number" value="0"></label>
    <button id="create">创建翻唱</button>
    <pre id="output" aria-live="polite"></pre>
  </main>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

这里的 `/src/main.ts` 只用于 Vite 开发和构建。安装后的单文件 HTML 不会保留这个绝对路径。

#### 5.6.3 用 TypeScript 调用宿主

`frontend/src/main.ts`：

```ts
import { host, isHosted, type HostMessageResult } from '@xb-svcb/plugin-sdk/client'
import './style.css'

function input(id: string): HTMLInputElement {
  const value = document.querySelector<HTMLInputElement>(`#${id}`)
  if (!value) throw new Error(`缺少输入框：${id}`)
  return value
}

const button = document.querySelector<HTMLButtonElement>('#create')
const output = document.querySelector<HTMLPreElement>('#output')
if (!button || !output) throw new Error('页面结构不完整')

button.addEventListener('click', async () => {
  if (!isHosted()) {
    output.textContent = '浏览器预览不会创建真实任务，请安装插件后测试。'
    return
  }

  button.disabled = true
  try {
    const result: HostMessageResult = await host.runAction('create', {
      source_path: input('source_path').value,
      model_id: input('model_id').value,
      title: input('title').value,
      pitch: Number(input('pitch').value || 0),
    })
    output.textContent = JSON.stringify(result, null, 2)
  } catch (error) {
    output.textContent = error instanceof Error ? error.message : String(error)
  } finally {
    button.disabled = false
  }
})
```

`host.runAction('create', values)` 会找到清单里的 `create` 动作。若动作返回 `create_work`，宿主会创建真实翻唱任务，并把动作结果和创建后的 `work` 返回给页面。

页面也可以跳过清单动作，直接创建任务：

```ts
import { host, type CreateWorkPayload, type CreatedWork } from '@xb-svcb/plugin-sdk/client'

const payload: CreateWorkPayload = {
  source_path: 'D:/Music/song.wav',
  model_id: 'model_xxx',
  title: '我的翻唱',
  workflow: 'auto_mix',
  params: { pitch: 0, f0_method: 'rmvpe' },
}

const work: CreatedWork = await host.createWork(payload)
console.log(work.id, work.title)
```

推荐优先使用 `runAction()`：动作会集中记录在清单中，声明式页面和自定义页面也能复用。只有完全由页面动态生成任务时，才直接使用 `createWork()`。

#### 5.6.4 开发、构建与安装

```powershell
# 浏览器预览布局；宿主动作不会真实执行
npm run dev

# 检查清单 TS、页面 TS 和 Vite 配置
npm run typecheck

# 构建 dist/frontend/index.html 和 xb-svcb-plugin.json
npm run build

# 类型检查 + 完整构建 + 清单校验
npm run validate

# 校验后生成 .xbplugin
npm run pack
```

构建使用 `vite-plugin-singlefile`，会把页面 JavaScript 和 CSS 内联到一个 HTML 中。这是必要的：插件页面通过 `srcdoc` 加载，普通的 `./assets/main.js` 相对路径无法可靠解析。

宿主目前限制入口 HTML 不超过 2 MB。较大的图片、音频或数据文件不要导入页面 bundle，应放在插件目录中，再使用 `host.assetUrl('assets/banner.png')` 读取；单个资源不得超过 10 MB。

#### 5.6.5 多页面插件

一个插件只有一个 `frontend.entry`，但可以声明多个 `pages`。所有路由加载同一份 HTML，页面代码通过上下文决定显示内容：

```ts
const context = await host.getContext()

switch (context.page?.id) {
  case 'create':
    renderCreatePage()
    break
  case 'history':
    renderHistoryPage()
    break
  default:
    renderHomePage()
}
```

#### 5.6.6 页面运行限制

- iframe 只有 `allow-scripts`，不能取得宿主 DOM、文件系统对象或 Python 对象。
- 页面通过 `postMessage` 与宿主通信，SDK 默认 30 秒超时。
- 页面刷新或关闭后，内存状态会丢失；需要持久化配置时使用混合插件的 Python `PluginContext.config`。
- `npm run dev` 只能预览页面布局。涉及真实模型、任务和 Python 的调用必须打包安装后验证。
- `XBSVCB` 全局对象保留给无构建 JavaScript 页面；TypeScript 项目应导入 `@xb-svcb/plugin-sdk/client`。

## 6. 第一个纯 Python 插件

纯 Python 插件可以没有页面。下面的插件会在创建翻唱任务前补充默认参数，并记录运行次数。

完整示例：

```text
plugin-sdk/examples/python-preset
```

### 6.1 `src/plugin.ts`

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.python-preset', 'Python 翻唱预设', '1.0.0')
  .python('plugin.py')
  .description('为翻唱任务设置默认 F0 和设备。')
  .author('Your Name')
  .permission('filesystem.data')

await writeManifest(app, '.')
```

`.python('plugin.py')` 声明这是纯 Python 插件，入口为插件目录内的 `plugin.py`。SDK 会自动加入 `python.execute` 权限声明。

项目较大时可将入口改成 `.python('my_plugin/__init__.py')`，再按普通 Python 包拆分模块。

### 6.2 `plugin.py`

```python
from xb_svcb_plugin import Plugin, PluginContext


plugin = Plugin("com.example.python-preset")


@plugin.on_enable
def on_enable(ctx: PluginContext) -> None:
    ctx.config.setdefault("runs", 0)
    ctx.save_config()


@plugin.before_create
def before_create(ctx: PluginContext, payload: dict) -> dict:
    params = payload.setdefault("params", {})
    params.setdefault("f0_method", "rmvpe")
    params.setdefault("device", "auto")

    ctx.config["runs"] = int(ctx.config.get("runs", 0)) + 1
    ctx.save_config()
    return payload
```

入口模块必须创建一个 `Plugin` 实例，并且 ID 必须与清单 ID 一致。

Python 插件入口会在每次动作或钩子调用时重新加载，不应依赖模块全局变量保存状态。需要持久化时使用 `ctx.config`。

## 7. 第一个混合插件

混合插件用前端页面收集输入，用 Python 完成计算或生成任务。页面可以是声明式页面，也可以是第 5.5 节介绍的自定义 TypeScript 页面。

完整示例：

```text
plugin-sdk/examples/hybrid-assistant
```

### 7.1 `src/plugin.ts`

```ts
import { fields, plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.hybrid-cover', '混合翻唱助手', '1.0.0')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
  .description('前端收集参数，Python 生成翻唱任务。')
  .author('Your Name')
  .permission('filesystem.data')
  .page('start', '智能翻唱', {
    fields: [
      fields.text('source_path', '源音频路径'),
      fields.text('model_id', '模型 ID'),
      fields.select('style', '风格', [
        { label: '自然', value: 'natural' },
        { label: '明亮', value: 'bright' },
      ], { default: 'natural' }),
    ],
    actions: ['create'],
  })
  .pythonAction('create', '创建翻唱', 'create_cover')

await writeManifest(app, '.')
```

Vue 页面组件调用 `runAction('create', values)`，vanilla 页面调用 `host.runAction('create', values)`；宿主随后把 `values` 交给清单中的 `create` Python 动作。如果不需要自定义布局，可以删掉 `.frontendEntry()` 并保留声明式字段，宿主会自动渲染表单。

### 7.2 `plugin.py`

```python
from xb_svcb_plugin import ActionResult, Plugin, PluginContext


plugin = Plugin("com.example.hybrid-cover")


@plugin.action("create_cover")
async def create_cover(ctx: PluginContext, values: dict) -> ActionResult:
    pitch = 1 if values.get("style") == "bright" else 0
    return ActionResult.create_work(
        {
            "source_path": values.get("source_path", ""),
            "model_id": values.get("model_id", ""),
            "title": "混合插件翻唱",
            "workflow": "auto_mix",
            "params": {"pitch": pitch, "f0_method": "rmvpe"},
        }
    )
```

Python 动作可以是同步函数或 `async def`。参数：

- `ctx`：当前插件上下文；
- `values`：页面字段组成的字典。

## 8. 清单与元数据

`xb-svcb-plugin.json` 是宿主识别插件的唯一入口。推荐把 `src/plugin.ts` 作为可维护的源文件，让 `writeManifest()` 生成 JSON。宿主不会执行清单构建脚本 `src/plugin.ts` 或 `build.mjs`；当清单声明 `frontend.entry` 时，会在沙箱 iframe 中执行构建后的页面 JavaScript。

清单顶层字段：

| 字段               | 必需            | 说明                                                |
| ------------------ | --------------- | --------------------------------------------------- |
| `id`             | 是              | 插件稳定标识；发布后不要更改                        |
| `name`           | 是              | 插件中心显示的人类可读名称                          |
| `version`        | 是              | 版本字符串，推荐使用语义化版本                      |
| `description`    | 否              | 功能简介，最多保留 400 个字符                       |
| `author`         | 否              | 作者或组织名，最多保留 80 个字符                    |
| `runtime`        | 是              | `frontend`、`python` 或 `hybrid`              |
| `python.entry`   | Python/混合必需 | 插件目录内的`.py` 入口，不能使用绝对路径或 `..` |
| `frontend.entry` | 自定义页面必需  | 构建后的 HTML，相对插件根目录                       |
| `permissions`    | 是              | 权限声明；Python/混合插件必须包含`python.execute` |
| `pages`          | 是              | 页面导航与声明式字段数组，可以为空                  |
| `actions`        | 是              | 页面可触发的动作数组，可以为空                      |
| `workflow`       | 是              | 翻唱流程扩展；当前支持静态`before_create.params`  |

`.python()` 和 `.hybrid()` 会自动设置运行类型、入口和 `python.execute` 权限；其他字段由构建器方法生成。SDK 会在写入和打包前校验清单，但宿主安装时仍会再次校验，不能依赖手工修改绕过限制。

### 8.1 页面、字段与动作

页面只描述宿主可以安全渲染的表单，不包含 HTML、Vue 组件或任意脚本：

```text
Page
├─ fields[]     用户输入，提交时组成 values
└─ actions[]    当前页面显示的动作 ID
       │
       └──────> Manifest.actions[] 中同 ID 的动作
```

`page.actions` 是动作 ID 列表。提供非空列表时，页面只显示列出的动作；省略或使用空列表时，页面显示插件的全部动作。字段和动作 ID 在同一插件内应保持唯一。

用于 `{{fieldId}}` 占位符的字段 ID 建议采用小写字母开头、只含字母数字和下划线的形式，例如 `source_path`。这样可以同时满足清单校验与插值规则。

### 8.2 动作类型

| 类型            | 构建器              | 结果                                                  |
| --------------- | ------------------- | ----------------------------------------------------- |
| `message`     | `.message()`      | 插值后在页面显示一条消息                              |
| `create_work` | `.createWork()`   | 插值后交给正式作品服务创建翻唱任务                    |
| `python`      | `.pythonAction()` | 在独立 Worker 中调用`@plugin.action()` 注册的处理器 |

插值会递归处理对象、数组和字符串。整个值只有一个占位符时会保留数字或布尔类型；占位符嵌在其他文本中时会转换为字符串。未提供的字段不会被猜测或执行为表达式。

> **注意**
>
> `python` 动作只应出现在 Python 或混合插件中，并且 `handler` 必须与 Python 入口中注册的动作名称一致。

## 9. TypeScript/JavaScript SDK

SDK 有两个 TypeScript 入口：`@xb-svcb/plugin-sdk` 用于生成清单，`@xb-svcb/plugin-sdk/client` 用于自定义页面调用宿主。脚手架已经准备好 `tsx`、Vite、单文件构建和严格 `tsconfig.json`，不需要复制主项目源码或手工声明宿主接口。

### 9.1 TypeScript 快速写法

```ts
import {
  fields,
  plugin,
  writeManifest,
  type BeforeCreateParams,
  type PluginPermission,
} from '@xb-svcb/plugin-sdk'

const permissions = ['filesystem.data'] satisfies PluginPermission[]
const defaults = { f0_method: 'rmvpe', pitch: 0 } satisfies BeforeCreateParams

const app = plugin('com.example.typed-cover', '类型安全翻唱', '1.0.0')
  .frontend()
  .permission(permissions)
  .beforeCreate(defaults)
  .page('home', '快速翻唱', {
    fields: [
      fields.text('title', '标题', { default: '我的翻唱' }),
      fields.number('pitch', '升降调', { default: 0 }),
      fields.switch('enhance', '自动增强', { default: true }),
      fields.select('device', '推理设备', [
        { label: '自动', value: 'auto' },
        { label: 'CPU', value: 'cpu' },
      ], { default: 'auto' }),
    ],
    actions: ['create'],
  })
  .createWork('create', '创建翻唱', {
    title: '{{title}}',
    params: { pitch: '{{pitch}}', device: '{{device}}' },
    vocal_enhancement: { enabled: '{{enhance}}', level: 'basic' },
  })

await writeManifest(app, '.')
```

运行以下命令即可检查并生成清单：

```powershell
npm run typecheck  # 只做 TypeScript 检查，不写入文件
npm run build      # 构建页面并生成 xb-svcb-plugin.json
npm run validate   # 类型检查 + 构建 + 清单校验
npm run pack       # 校验后生成 .xbplugin
```

类型定义会约束字段默认值、下拉选项、权限名称、运行类型和动作形状。编辑器输入错误值时会直接标红；`satisfies` 可以检查对象又保留更精确的字面量类型。

### 9.2 插件构建器

```ts
plugin(id, name, version)
  .description(text)
  .author(name)
  .frontend()
  .python(entry)
  .hybrid(entry)
  .permission(...permissions)
  .page(id, title, options)
  .message(id, label, text)
  .createWork(id, label, payload)
  .pythonAction(id, label, handler)
  .beforeCreate(params)
```

构建器支持链式调用，最终通过 `.build()` 取得普通清单对象。

### 9.3 页面字段

```ts
fields.text('title', '标题', {
  default: '我的翻唱',
  placeholder: '请输入标题',
  help: '显示在作品库中',
})

fields.number('pitch', '升降调', { default: 0 })

fields.select('device', '设备', [
  { label: '自动', value: 'auto' },
  { label: 'CPU', value: 'cpu' },
], { default: 'auto' })

fields.switch('enhance', '自动增强', { default: true })
fields.textarea('notes', '备注', { placeholder: '可选' })
```

支持类型：`text`、`number`、`select`、`switch`、`textarea`。

### 9.4 清单工具

```ts
import {
  validateManifest,
  writeManifest,
  packPlugin,
} from '@xb-svcb/plugin-sdk'

const result = validateManifest(app)
if (!result.ok) console.error(result.errors)

await writeManifest(app, '.')
await packPlugin('.', './my-plugin.xbplugin')
```

打包器会忽略 `node_modules`、`.git`、`.venv`、`__pycache__`、`.pytest_cache` 和旧 `.xbplugin` 文件。

### 9.5 自定义页面 Client API

导入方式：

```ts
import {
  host,
  isHosted,
  request,
  type PluginHostContext,
  type CreateWorkPayload,
  type CreatedWork,
} from '@xb-svcb/plugin-sdk/client'
```

| API                                   | 返回值                | 用途                                           |
| ------------------------------------- | --------------------- | ---------------------------------------------- |
| `isHosted()`                        | `boolean`           | 判断页面是在普通浏览器预览还是插件宿主中       |
| `host.getContext()`                 | `PluginHostContext` | 取得当前插件、当前页面和主题                   |
| `host.runAction(id, values)`        | `HostMessageResult` | 调用清单动作，包括消息、创建任务和 Python 动作 |
| `host.createWork(payload)`          | `CreatedWork`       | 直接创建翻唱任务                               |
| `host.assetData(path)`              | `HostAssetResult`   | 读取插件包内资源及其 Data URL                  |
| `host.assetUrl(path)`               | `string`            | 直接取得资源 Data URL                          |
| `host.notify(message, type)`        | `true`              | 显示宿主通知                                   |
| `request(method, payload, options)` | 泛型 Promise          | 低层通信；通常不需要直接使用                   |

#### `host.getContext()`

```ts
const context = await host.getContext()

console.log(context.plugin.id)
console.log(context.plugin.version)
console.log(context.page?.id)
console.log(context.theme)
```

`context.plugin` 是规范化后的完整清单；`context.page` 是当前路由对应的页面，多页面插件可以用它切换视图。

#### `host.runAction()`

```ts
const result = await host.runAction('create', {
  source_path: 'D:/Music/song.wav',
  model_id: 'model_xxx',
  pitch: 2,
})

if (result.type === 'message') console.log(result.message)
if (result.type === 'create_work') console.log(result.work?.id)
```

动作 ID 必须存在于清单 `actions` 中。纯前端插件可以调用 `message` 和 `create_work`；`python` 动作只允许 Python 或混合插件。

#### `host.createWork()`

```ts
const payload: CreateWorkPayload = {
  title: 'SDK 创建的任务',
  source_path: 'D:/Music/song.wav',
  model_id: 'model_xxx',
  workflow: 'auto_mix',
  params: {
    pitch: 0,
    f0_method: 'rmvpe',
    device: 'auto',
  },
}

const work: CreatedWork = await host.createWork(payload)
```

SDK 同时导出 `CreateWorkflow`、`InferenceParams`、`VocalEnhancementOptions`、`BlendModel` 和 `BlendSegment`，用于单模型、多模型与美声增强任务。

#### 插件资源

```ts
const image = document.querySelector<HTMLImageElement>('#cover')
if (image) image.src = await host.assetUrl('assets/cover.png')

const asset = await host.assetData('assets/config.json')
console.log(asset.name, asset.mime, asset.data)
```

路径相对于插件根目录，不能使用绝对路径或 `..`。返回的是 Data URL，不是本机文件路径。

#### 通知和错误

```ts
try {
  await host.notify('参数已保存', 'success')
  await host.runAction('refresh')
} catch (error) {
  const message = error instanceof Error ? error.message : String(error)
  await host.notify(message, 'error')
}
```

通知类型为 `success`、`warning`、`info`、`error`。Client 请求默认 30 秒超时；使用低层 `request()` 时可以传 `{ timeoutMs: 10_000 }`，传 `0` 表示关闭超时。

## 10. Python SDK

### 10.1 `Plugin`

```python
plugin = Plugin("com.example.plugin")
```

注册接口：

```python
@plugin.action("handler_name")
def action_handler(ctx, values): ...

@plugin.before_create
def before_create(ctx, payload): ...

@plugin.on_enable
def on_enable(ctx): ...

@plugin.on_disable
def on_disable(ctx): ...
```

### 10.2 动作返回值

显示消息：

```python
return "操作完成"
```

或：

```python
return ActionResult.message_result("操作完成")
```

创建翻唱任务：

```python
return ActionResult.create_work({
    "source_path": "D:/Music/song.wav",
    "model_id": "model_xxx",
    "params": {"pitch": 0},
})
```

也可以直接返回协议字典：

```python
return {"type": "message", "message": "完成"}
```

支持返回：`str`、`dict`、`ActionResult`、`None`。其他类型会被视为错误。

### 10.3 `PluginContext`

```python
ctx.plugin_id     # 插件 ID
ctx.plugin_dir    # 插件安装目录，只读约定但不是系统强制只读
ctx.data_dir      # 插件持久化数据目录
ctx.config        # 从 data_dir/config.json 加载的字典
ctx.save_config() # 原子写回 config.json
```

不要把用户配置写进 `plugin_dir`，插件升级会替换该目录。使用 `ctx.data_dir` 和 `ctx.config`。

### 10.4 生命周期与执行模型

Python 插件不是常驻进程。每次生命周期、动作或钩子调用都会启动一个独立 Worker，重新导入入口，构造新的 `PluginContext`，完成后退出：

```text
安装插件（不执行 Python）
        |
        v
插件关闭 --单独启用--> 导入入口 -> on_enable -> 插件开启
                                      |
                      +---------------+---------------+
                      |                               |
                 页面 Python 动作                before_create
                 每次一个新 Worker              每次一个新 Worker
                      |                               |
                      +---------------+---------------+
                                      |
                         单独停用 -> on_disable（尽力执行）
                                      |
                              卸载 -> 删除代码和数据
```

这带来几个约束：

- 模块全局变量不会跨调用保留；持久状态必须写入 `ctx.config` 或 `ctx.data_dir`；
- `on_enable` 失败时插件保持关闭；
- 关闭插件总开关只暂停所有插件，不会逐个调用 `on_disable`；
- 更新同 ID 插件会替换插件目录并将它设为关闭，但保留现有 `plugin-data`；
- 直接卸载会删除插件目录和数据，不应依赖 `on_disable` 完成关键数据保存。

同步函数和 `async def` 都受支持。单次 Worker 最长运行 30 秒，不适合长期后台服务、常驻监听器或无限循环。

## 11. 翻唱流程钩子

当前提供一个 Python 钩子：`before_create`。

```python
@plugin.before_create
def before_create(ctx: PluginContext, payload: dict) -> dict:
    payload.setdefault("params", {}).setdefault("pitch", 0)
    return payload
```

钩子在单任务和批量任务进入作品服务前执行。批量创建时对整份批量请求调用一次，不会为其中每个 `source_path` 重复调用。多个插件按插件目录名称顺序运行；后一个插件会收到前一个插件返回的结果。

钩子必须返回 `dict` 或 `None`：

- 返回 `dict`：把返回值传给下一个插件或任务服务；
- 返回 `None`：保持当前 payload 不变；
- 抛出异常或超时：本次插件钩子失败，宿主保留此前 payload 并继续任务流程。

纯前端插件也可以通过构建器提供静态默认值：

```ts
app.beforeCreate({
  f0_method: 'rmvpe',
  device: 'auto',
})
```

静态参数只填补缺失值，不覆盖用户值。白名单：

```text
pitch, f0_method, index_rate, rms_mix, uvr_model, diffusion_ratio,
device, protect, filter_radius, rvc_version, ddsp_infer_steps,
ddsp_formant_shift, speaker
```

白名单只限制清单中的静态补丁。Python `before_create` 会收到完整请求并可以修改其他字段，因此插件必须保留不认识的字段、校验自己新增的数据，并尽量只改动负责的部分。

当前尚未提供 `after_create`、`task_completed`、`editor_opened` 等其他钩子。

## 12. 配置与数据目录

Python 插件使用宿主提供的 JSON 配置：

```python
@plugin.action("save")
def save(ctx: PluginContext, values: dict):
    ctx.config["preset"] = values
    ctx.save_config()
    return "设置已保存"
```

配置保存在：

```text
<XB-SVCB 数据目录>/plugin-data/<plugin-id>/config.json
```

`ctx.config` 在每次 Worker 启动时读取，`save_config()` 会把整个字典原子替换回文件。两个并发调用仍可能发生“后写覆盖先写”，因此它适合小型、低频设置，不适合并发计数或任务队列。需要并发更新时，可以在 `ctx.data_dir` 中使用 SQLite 等具备事务能力的存储。

卸载插件时，当前实现会同时删除该插件的 `plugin-data`。重要数据应提供导出方式，或者在 README 中明确卸载行为。

## 13. 权限与安全

权限声明：

```ts
app.permission(
  'filesystem.data',
  'network',
)
```

可声明权限：

| 权限                  | 含义                                                |
| --------------------- | --------------------------------------------------- |
| `python.execute`    | 执行 Python，`.python()` / `.hybrid()` 自动加入 |
| `filesystem.plugin` | 需要访问插件安装目录                                |
| `filesystem.data`   | 使用插件数据目录                                    |
| `network`           | 发起网络请求                                        |
| `process`           | 启动外部进程                                        |
| `environment`       | 读取环境变量                                        |

重要：当前权限是**声明、审计和用户提示机制，不是操作系统沙箱**。Python 插件进程继承当前用户权限，技术上可能访问声明之外的资源。独立 Worker 只隔离崩溃，不提供安全隔离。

因此：

- 只启用可信来源的 Python 插件；
- 发布源码和依赖清单，方便用户审查；
- 不读取无关文件、凭据、Cookie、API Key 或环境变量；
- 不静默下载和运行程序；
- 安装插件时不会执行 Python；用户明确启用后才执行生命周期和钩子。

每次 Worker 调用默认超时 30 秒。超时后进程会被终止并返回错误。

## 14. 第三方依赖

宿主只保证 Python 3.10+ 标准库和 `xb_svcb_plugin` SDK。不要假设用户安装了 `requests`、`numpy` 等包。

当前推荐把依赖安装进插件的 `vendor/`：

```powershell
python -m pip install httpx -t .\vendor
```

插件入口可以直接导入：

```python
import httpx
```

Worker 会自动把 `vendor/` 加入 `sys.path`。打包时 `vendor/` 会包含在插件包中。

发布要求：

- 记录第三方依赖和版本范围；
- 保留依赖许可证；
- 不打包平台不兼容的二进制包；
- 不使用安装时自动执行 `pip install` 的脚本。

## 15. 测试与调试

### 15.1 清单校验

```powershell
npm run validate
```

如果正在 XB-SVCB 仓库内开发，也可以从仓库根目录直接调用本地 CLI：

```powershell
node plugin-sdk\bin\xb-plugin.mjs validate .\my-plugin
```

### 15.2 Python 语法检查

```powershell
python -m py_compile plugin.py
```

本地安装 Python SDK 后，可以直接导入插件入口：

```powershell
pip install -e path\to\plugin-sdk\python
python -c "import plugin"
```

导入成功只能证明入口可以加载。钩子和动作还应测试输入、输出和配置持久化。下面使用 Python 标准库测试 `before_create`，不要求插件安装 `pytest`：

```python
# tests/test_plugin.py
import unittest
from tempfile import TemporaryDirectory

from xb_svcb_plugin import PluginContext
from plugin import plugin


class TestPreset(unittest.TestCase):
    def test_adds_missing_f0_method(self) -> None:
        with TemporaryDirectory() as data_dir:
            ctx = PluginContext.create(plugin.id, ".", data_dir)
            handler = plugin.hooks["before_create"][0]
            result = handler(ctx, {"params": {}})

        self.assertEqual(result["params"]["f0_method"], "rmvpe")


if __name__ == "__main__":
    unittest.main()
```

```powershell
python -m unittest discover -s tests -t .
```

异步动作可以使用 `unittest.IsolatedAsyncioTestCase` 并在测试中 `await` 处理器。

### 15.3 在 XB-SVCB 中调试

1. 执行 `npm run pack`；
2. 在插件中心卸载旧版本；
3. 安装新 `.xbplugin`；
4. 启用插件；
5. 打开页面或创建翻唱任务。

开发目录支持直接放置未压缩目录，但修改 Python 文件后仍建议先停用再启用插件，确保生命周期与配置状态清晰。

Python 异常会由 Worker 转换为错误消息，不会直接终止桌面进程。普通 `print()` 会被重定向到 Worker 的 stderr，以免破坏 stdout 上的 JSON 协议；成功调用的 stderr 不会显示在插件页面。正式插件如需持续日志，应给标准 `logging` 配置写入 `ctx.data_dir` 的文件处理器。

宿主会把最近一次 Python 错误写入插件数据目录的 `error.log`。每次调用使用独立进程，不共享内存；耗时初始化应通过磁盘缓存优化，不能依赖常驻对象。

## 16. 打包与安装

```powershell
npm run build
npm run validate
npm run pack
```

或：

```powershell
node plugin-sdk\bin\xb-plugin.mjs pack .\my-plugin .\my-plugin.xbplugin
```

上面的本地 CLI 命令需要在 XB-SVCB 仓库根目录执行。脚手架生成的 `npm run pack` 可以在插件目录直接执行；未指定输出路径时，压缩包默认生成在插件目录旁边。

限制：

- 压缩包最大 20 MB；
- 解压后最大 50 MB；
- 清单最大 512 KB；
- 清单名必须是 `xb-svcb-plugin.json`；
- 包内不能使用 `../` 路径穿越；
- Python 入口必须是插件目录内的 `.py` 文件。

插件中心安装后默认关闭。Python 代码不会在安装阶段执行。

### 16.1 安装后的状态

插件中心有两层开关：

| 开关           | 关闭时                                  | 开启时                           |
| -------------- | --------------------------------------- | -------------------------------- |
| 插件功能总开关 | 所有插件页面、动作和流程钩子暂停        | 允许已安装插件参与工作流         |
| 单个插件开关   | 当前插件不显示可用页面，也不执行 Python | 运行该插件声明的页面、动作和钩子 |

开发目录会显示在插件中心的“开发目录”一栏。把每个插件放在这个目录的独立子目录中，并确保根目录包含 `xb-svcb-plugin.json`，即可在列表中检查；修改清单后重新打开插件中心或刷新列表。Python 代码每次调用都会重新导入，修改后建议先停用再启用，以便重新执行生命周期初始化。

卸载会删除插件目录和 `plugin-data/<plugin-id>`；更新同 ID 插件会替换代码但保留数据目录，并把插件重新设为关闭。

## 17. GitHub 市场发布

建议项目名使用：

```text
xb-svcb-plugin-<name>
```

仓库至少包含：

```text
README.md
LICENSE
package.json
src/plugin.ts（或 build.mjs）
tsconfig.json（TypeScript 插件）
frontend/index.html（自定义页面源码）
frontend/src/main.ts（页面端 TypeScript）
frontend/src/App.vue（Vue 页面布局）
frontend/src/components/（Vue 自定义组件）
vite.config.ts（自定义页面构建配置）
dist/frontend/index.html（自定义页面构建结果）
plugin.py（如有）
xb-svcb-plugin.json
```

README 应说明：

- 插件功能和截图；
- 插件类型；
- 权限和数据访问；
- 安装方法；
- 配置项；
- 第三方依赖；
- 支持的 XB-SVCB 版本；
- 卸载是否删除数据。

把 `.xbplugin` 上传到 GitHub Release，并维护 `market.json`：

```json
{
  "plugins": [
    {
      "id": "com.example.hybrid-cover",
      "name": "混合翻唱助手",
      "version": "1.0.0",
      "description": "前端表单与 Python 翻唱逻辑。",
      "author": "Your Name",
      "bundle_url": "https://github.com/OWNER/REPO/releases/download/v1.0.0/hybrid-cover.xbplugin"
    }
  ]
}
```

插件中心填写 Raw 地址：

```text
https://raw.githubusercontent.com/OWNER/REPO/main/market.json
```

市场索引和插件包地址必须使用 GitHub HTTPS。GitHub Release 跳转到官方 `githubusercontent.com` 资产域是允许的，跳转到其他域名会被拒绝。

### 17.1 发布前检查

提交 Release 前逐项确认：

- `id` 在后续版本中保持不变，`version` 已递增；
- `npm run validate` 和 Python 单元测试在干净环境通过；
- `.xbplugin` 中没有 `node_modules`、`.venv`、缓存或密钥文件；
- README 写明运行类型、权限、数据目录、依赖、支持版本和卸载行为；
- Python/混合插件已经人工审查入口代码和 `vendor/` 依赖，确认没有静默网络下载或外部进程；
- Release 资产名称与 `bundle_url` 完全一致，市场索引已经指向新版本；
- 用一个没有旧插件数据的测试用户完成安装、启用、动作、停用和卸载流程。

## 18. API 参考

### TypeScript/JavaScript SDK

TypeScript 项目可以从 `@xb-svcb/plugin-sdk` 导入 `Field`、`Page`、`Action`、`Manifest`、`PluginBuilder`、`PluginPermission` 和 `BeforeCreateParams` 等类型；JavaScript 项目直接使用同一组运行时函数。类型检查只发生在开发机，宿主安装时仍会执行运行时校验。

```text
plugin(id, name, version?) -> PluginBuilder
fields.text(id, label, options?)
fields.number(id, label, options?)
fields.select(id, label, options, config?)
fields.switch(id, label, options?)
fields.textarea(id, label, options?)
page(id, title, options?)
messageAction(id, label, message)
createWorkAction(id, label, payload, options?)
pythonAction(id, label, handler?, options?)
validateManifest(manifestOrBuilder)
writeManifest(manifestOrBuilder, directory)
packPlugin(directory, output?)
createPlugin(options)
allowedParams
```

`createPlugin()` 是创建最小清单的底层辅助函数，通常优先使用 `xb-plugin create`；`allowedParams` 是静态 `beforeCreate()` 参数名的只读集合。

常用返回值：

| API                                 | 返回值                        | 说明                              |
| ----------------------------------- | ----------------------------- | --------------------------------- |
| `validateManifest(input)`         | `{ ok, errors, manifest? }` | `input` 可以是清单对象或构建器  |
| `writeManifest(input, directory)` | `Promise<string>`           | 校验后写入`xb-svcb-plugin.json` |
| `packPlugin(directory, output?)`  | `Promise<string>`           | 校验清单并创建`.xbplugin`       |
| `plugin(id, name, version?)`      | `PluginBuilder`             | 创建链式构建器                    |
| `fields.*`                        | `Field`                     | 创建宿主支持的声明式字段          |

### 自定义页面 Client SDK

从 `@xb-svcb/plugin-sdk/client` 导入。页面端不需要接触主项目 API、宿主 Vue 组件或桌面 Bridge。

```text
isHosted() -> boolean
host.getContext() -> Promise<PluginHostContext>
host.runAction(actionId, values?) -> Promise<HostMessageResult>
host.createWork(payload) -> Promise<CreatedWork>
host.assetData(path) -> Promise<HostAssetResult>
host.assetUrl(path) -> Promise<string>
host.notify(message, type?) -> Promise<true>
request(method, payload?, options?) -> Promise<T>
```

页面端导出的主要类型：

```text
PluginHost
PluginHostContext
HostMessageResult
HostAssetResult
NotifyType
RequestOptions
CreateWorkflow
InferenceParams
CreateWorkPayload
CreatedWork
VocalEnhancementOptions
BlendModel
BlendSegment
```

Client SDK 只在带有宿主 token 的插件 iframe 中执行真实调用。浏览器开发预览应先使用 `isHosted()` 判断环境。

### Vue 3 SDK

从 `@xb-svcb/plugin-sdk/vue` 导入。它在无框架 Client 上提供 Vue 响应式状态：

```text
usePluginHost(options?) -> UsePluginHostResult
```

主要类型：

```text
UsePluginHostOptions
UsePluginHostResult
```

`usePluginHost()` 只能在 Vue 组件 `setup()`、`<script setup>` 或其他 composable 中使用。默认在 `onMounted()` 时加载宿主上下文；`loadContext: false` 可关闭自动加载。

### Python SDK

```text
Plugin(plugin_id)
Plugin.action(name?)
Plugin.hook(name)
Plugin.before_create(handler)
Plugin.on_enable(handler)
Plugin.on_disable(handler)
get_plugin()
action(name?)
before_create(handler)
PluginContext.create(plugin_id, plugin_dir, data_dir)
PluginContext.plugin_id
PluginContext.plugin_dir
PluginContext.data_dir
PluginContext.config
PluginContext.save_config()
ActionResult.message_result(message)
ActionResult.create_work(payload)
```

顶层 `action()` 和 `before_create()` 装饰器会使用当前已创建的 `Plugin` 实例，因此入口必须先执行 `plugin = Plugin("...")`。显式写成 `@plugin.action()` 和 `@plugin.before_create` 更便于阅读，也更适合大型插件。

### Worker 行为

- 每次动作或钩子使用独立 Python 子进程；
- 同步与异步处理器均支持；
- 调用超时 30 秒；
- Python 入口每次重新导入；
- 动作、钩子和生命周期每次调用使用独立进程，不共享内存；
- `vendor/` 自动加入模块路径；
- 配置通过 `config.json` 持久化；
- Worker 不是安全沙箱。

## 19. 常见问题

### 插件不显示

运行 `xb-plugin validate .`。检查 ID、运行类型、入口、页面和动作。开发目录中每个插件需要独立子目录。

### Python 插件无法启用

确认 XB-SVCB 能找到 Python 3.10+，插件包内存在清单声明的入口，例如 `plugin.py`，且入口中的 `Plugin()` ID 与清单一致。

### 页面按钮提示“未注册 Python 动作”

`pythonAction` 的 handler 必须和 `@plugin.action()` 名称一致：

```ts
.pythonAction('create', '创建', 'create_cover')
```

```python
@plugin.action("create_cover")
def create_cover(ctx, values): ...
```

### 配置重启后丢失

修改 `ctx.config` 后必须调用 `ctx.save_config()`。

### 全局变量不保留

这是预期行为。每次 Worker 调用会重新加载插件入口。使用 `ctx.config` 或 `ctx.data_dir` 保存状态。

### Python 依赖导入失败

把依赖安装进插件根目录的 `vendor/`，然后重新打包。

### 页面中的占位符没有替换

确认页面字段 ID 与占位符完全一致，例如字段 `source_path` 对应 `{{source_path}}`。占位符只支持字段名，不支持表达式、函数调用或点号路径；嵌入其他文本时会按字符串替换。

### 页面或动作没有显示

确认插件功能总开关和单插件开关都已开启。若页面配置了非空的 `actions`，其中每个 ID 都必须能在清单的 `actions` 数组中找到；纯 Python 插件可以没有页面，因此不会出现“打开”按钮。

### 打包后文件过大

打包器会忽略 `node_modules`、`.venv`、缓存目录和旧 `.xbplugin`，但 `vendor/` 会被完整打包。删除不需要的依赖、调试输出和模型文件，并确认压缩包小于 20 MB、解压后小于 50 MB。

### 静态默认值覆盖不了用户设置

这是预期行为。`beforeCreate()` 生成的静态参数只会填补用户请求中缺失的键；需要有条件地修改完整请求时使用 Python `before_create`，同时保留其他插件和用户字段。

### GitHub 市场中没有插件

市场地址必须是 GitHub HTTPS 的 Raw/API 地址，响应必须是包含 `plugins` 数组的 JSON。每条记录的 `id` 和 `bundle_url` 都必须有效，且下载地址只能跳转到 GitHub 官方域名。

### 更新插件后配置还在吗

通过安装同 ID 的新包更新时，插件代码会替换、开关会重置为关闭，但 `plugin-data/<plugin-id>` 会保留。卸载再安装则会删除旧数据；重要配置应提供导出和恢复动作。

### 钩子修改没有生效

确认总开关和插件开关都打开，函数使用 `@plugin.before_create` 注册，并返回修改后的字典。

### Python 插件是否安全

不能仅凭插件格式判断安全。Python 插件具有当前用户权限。请查看源码、作者、权限声明和依赖，只启用可信插件。

## 下一步

- 先运行 `plugin-sdk/examples/hello-plugin` 理解纯前端插件；
- 再运行 `plugin-sdk/examples/python-preset` 理解流程钩子；
- 最后运行 `plugin-sdk/examples/hybrid-assistant` 理解页面与 Python 动作协作。

SDK 快速入口：[plugin-sdk/README.md](../plugin-sdk/README.md)。
