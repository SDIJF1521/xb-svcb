# 页面 Client API

自定义 HTML/Vue 页面不能直接调用桌面 Bridge。所有宿主能力通过 `postMessage` 协议暴露，npm Client 负责 token、请求 ID、响应匹配和超时。

## 1. 导入

TypeScript 或打包页面：

```ts
import {
  host,
  isHosted,
  request,
  type PluginHostContext,
  type HostMessageResult,
  type CreateWorkPayload,
} from '@xb-svcb/plugin-sdk/client'
```

Vue 组件：

```ts
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

无构建 JavaScript 页面可以使用宿主注入的 `window.XBSVCB`。该兼容全局没有 npm Client 的 30 秒超时和 TypeScript 类型，推荐新项目使用打包 Client。

## 2. 宿主检测

```ts
if (!isHosted()) {
  console.log('当前是普通浏览器预览')
}
```

只有页面收到宿主注入 token 时才返回 `true`。不要通过 `window.parent !== window` 猜测环境。

## 3. 请求规则

- API 返回 Promise。
- 宿主返回失败时 Promise 会 reject；不要只检查 resolved value 的 `error` 字段。
- npm Client 默认 30 秒超时。
- 低层 `request(method, payload, { timeoutMs })` 可以修改超时；`0` 或负数表示不设超时。
- 当前没有 AbortSignal 或取消 API。
- `request()` 不是开放扩展协议，宿主只接受本文列出的固定 method。
- iframe 关闭时未完成调用不会得到业务结果。

低层调用示例：

```ts
const context = await request<PluginHostContext>(
  'getContext',
  {},
  { timeoutMs: 10_000 },
)
```

通常应使用 `host.*`，避免手写 method 名和 payload。

## 4. `host.getContext()`

签名：

```ts
getContext(): Promise<PluginHostContext>
```

返回：

```ts
interface PluginHostContext {
  plugin: Manifest
  page?: Page
  theme?: string
}
```

```ts
const context = await host.getContext()
console.log(context.plugin.id)
console.log(context.page?.id)
console.log(context.theme)
```

注意：

- 自定义页面没有声明 pages 时，`page` 为 `undefined`。
- 当前插件中心通常只打开 `pages[0]`。
- `theme` 是读取时的一次主题 ID 快照，值通常为 `cyber`、`anime`、`custom`。
- 上下文不包含宿主 CSS 变量、自定义主题颜色或主题变化事件。

## 5. `host.runAction()`

签名：

```ts
runAction(
  actionId: string,
  values?: Record<string, unknown>,
): Promise<HostMessageResult>
```

```ts
const result = await host.runAction('create', {
  source_path: 'D:/Music/song.wav',
  model_id: 'model_xxx',
  title: '页面创建的翻唱',
  pitch: 0,
})
```

结果形状：

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

宿主行为：

- `message`：插值后返回消息，并自动显示成功通知。
- `create_work`：插值 payload、创建真实任务、自动显示成功通知，并返回 `work`。
- `python`：启动 Worker，调用 handler，再按返回结果处理。

页面不需要在成功后再次 `notify()`，否则用户会看到重复提示。失败会 reject：

```ts
try {
  const result = await host.runAction('create', values)
  console.log(result.work?.id)
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
}
```

自定义页面可以调用插件顶层清单中的任意 action，`page.actions` 只控制声明式表单显示，不是权限边界。

## 6. `host.createWork()`

签名：

```ts
createWork(payload: CreateWorkPayload): Promise<CreatedWork>
```

直接创建任务并自动显示成功通知。与 `runAction(create_work)` 相比，它不使用清单模板；适合 payload 完全由页面动态产生的场景。

```ts
const work = await host.createWork({
  source_path: 'D:/Music/song.wav',
  model_id: 'model_xxx',
  title: '直接创建的翻唱',
  workflow: 'auto_mix',
  params: {
    pitch: 0,
    f0_method: 'rmvpe',
  },
})
```

创建任务仍会经过所有已启用插件的 `before_create`。如果当前混合插件先用 Python action 返回 `create_work`，它自己的 `before_create` 也会在正式创建时再执行一次。

### `CreateWorkPayload`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | `string` | 作品标题 |
| `model_id` | `string` | 单模型 ID |
| `source_path` | `string \| null` | 本机源音频路径 |
| `params` | `InferenceParams` | 推理参数 |
| `workflow` | `CreateWorkflow` | 工作流 |
| `vocal_enhancement` | `VocalEnhancementOptions` | 可选美声增强 |
| `mode` | `'single' \| 'multi'` | 单模型或多模型 |
| `models` | `BlendModel[]` | 多模型配置 |
| `segments` | `BlendSegment[]` | 片段模型指派 |

### 工作流

| 值 | 模式 | 说明 |
| --- | --- | --- |
| `auto_mix` | single/multi | 自动完成分离、转换和伴奏混音 |
| `auto_then_editor` | single/multi | 自动生成后允许进入编辑器 |
| `full_manual_editor` | single/multi | 创建全手动编辑流程 |
| `auto_vocal_merge` | 仅 multi | 多模型自动人声合并 |
| `manual_vocal_merge` | 仅 multi | 多模型手动人声合并 |

不传时宿主通常使用 `auto_mix`。人声合并工作流用于 `single` 会失败。

### 推理参数

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pitch` | `number` | 半音升降调 |
| `f0_method` | `string` | F0 提取方法，例如 `rmvpe` |
| `index_rate` | `number` | 索引混合比例 |
| `rms_mix` | `number` | RMS 包络混合比例 |
| `uvr_model` | `string` | 人声分离模型 |
| `diffusion_ratio` | `number` | 扩散混合比例 |
| `device` | `string` | 推理设备，例如 `auto`、`cpu` |
| `protect` | `number` | RVC 清辅音/呼吸保护，通常 0-0.5 |
| `filter_radius` | `number` | RVC F0 中值滤波半径，通常 0-7 |
| `rvc_version` | `string` | RVC `v1` 或 `v2` |
| `reference_audio` | `string` | SeedVC 目标音色参考音频路径 |
| `ddsp_infer_steps` | `number` | DDSP-SVC 采样步数 |
| `ddsp_formant_shift` | `number` | DDSP-SVC 共振峰偏移，通常 -2 到 2 |
| `speaker` | `string \| number` | So-VITS/DDSP 目标说话人 |

并非每种模型都使用所有字段。宿主业务校验和模型运行时仍可能拒绝不适用的组合。

### 美声增强

设置 `vocal_enhancement` 时，TypeScript 类型要求提供全部字段：

```ts
const enhancement: VocalEnhancementOptions = {
  enabled: true,
  level: 'basic',
  pitch_correction: 0.3,
  timing_alignment: 0.2,
  timbre_focus: 0.2,
  ai_eq: 0.3,
  ai_compressor: 0.3,
  ai_exciter: 0.1,
  stereo_width: 0.2,
  loudness_envelope: 0.2,
}
```

强度字段使用 0-1。插件应提供明确默认值，不要假设宿主会补全局部对象。

### 多模型任务

```ts
const payload: CreateWorkPayload = {
  source_path: 'D:/Music/song.wav',
  title: '多人合唱',
  mode: 'multi',
  workflow: 'auto_vocal_merge',
  models: [
    { model_id: 'model_a', params: { pitch: 0 } },
    { model_id: 'model_b', params: { pitch: 2 } },
  ],
  segments: [
    { start: 0, end: 12.5, model_id: 'model_a' },
    {
      start: 12.5,
      end: 24,
      model_id: 'model_a',
      model_ids: ['model_a', 'model_b'],
    },
  ],
}
```

`model_ids` 包含多个 ID 时表示该片段合唱；`model_id` 仍需填写，通常使用列表首个模型。插件应确保时间区间、模型 ID 和宿主已有模型一致。

### `CreatedWork`

SDK 稳定声明 `id` 和 `title`；`model_id`、`source_path`、`status`、`progress` 是可选字段。对象可能包含其他宿主数据，不要依赖未在类型中声明的字段长期稳定。

## 7. 插件资源

```ts
assetData(path: string): Promise<HostAssetResult>
assetUrl(path: string): Promise<string>
```

```ts
const image = document.querySelector<HTMLImageElement>('#cover')
if (image) image.src = await host.assetUrl('assets/cover.png')

const asset = await host.assetData('assets/presets.json')
console.log(asset.name, asset.mime, asset.data)
```

结果：

```ts
interface HostAssetResult {
  ok: boolean
  name: string
  mime: string
  data: string
  error?: string
}
```

- 路径相对插件安装根目录。
- 不能使用绝对路径或 `..`。
- 单个资源最大 10 MB。
- `data` 是 Base64 Data URL。
- API 不能读取 `plugin-data` 配置目录。
- 失败时 Promise reject，不会 resolve 一个 `ok: false` 让页面继续处理。

## 8. 通知

```ts
notify(
  message: string,
  type?: 'success' | 'warning' | 'info' | 'error',
): Promise<true>
```

```ts
await host.notify('配置已保存', 'success')
```

`runAction(message)`、`runAction(create_work)` 和 `createWork()` 已自动通知，通常不用再次调用。

## 9. 页面持久化

页面 iframe 使用 opaque origin，不要直接依赖 `window.localStorage`。宿主提供按插件 ID 隔离的 JSON 存储：

```ts
getStorage<T = unknown>(key: string, fallback?: T): Promise<T>
setStorage(key: string, value: unknown): Promise<true>
removeStorage(key: string): Promise<true>
```

```ts
interface AnimePreferences {
  apiKey: string
  source: number
}

const preferences = await host.getStorage<AnimePreferences>('anime-preferences', {
  apiKey: '',
  source: 1,
})

await host.setStorage('anime-preferences', {
  apiKey: preferences.apiKey,
  source: 3,
})

await host.removeStorage('anime-preferences')
```

规则：

- `key` 只能包含字母、数字、点、下划线和连字符，长度为 1 到 80。
- 数据使用插件 ID 隔离，同名 key 不会在不同插件之间共享。
- `value` 必须可以 JSON 序列化；`undefined` 会被拒绝。
- key 不存在、保存内容损坏或无法解析时，`getStorage()` 返回 `fallback`。
- 重新安装同 ID 插件会保留宿主存储；更换插件 ID 会得到新的存储命名空间。
- 存储不是加密保险箱。可以保存普通 API key 和用户偏好，但不要保存无法撤销的高价值凭据。

Vue composable 暴露同名方法，调用期间会更新共享 `loading` 和 `error`。

## 10. 全屏控制

```ts
interface PluginFullscreenResult {
  ok: true
  fullscreen: boolean
}

interface WindowFullscreenResult {
  ok: boolean
  fullscreen?: boolean
  error?: string
}

togglePluginFullscreen(enabled?: boolean): Promise<PluginFullscreenResult>
toggleWindowFullscreen(): Promise<WindowFullscreenResult>
```

`togglePluginFullscreen()` 只让当前插件内容占满宿主工作区，不切换操作系统窗口。传 `true` 或 `false` 可显式设置；省略参数时切换当前状态。

```ts
const result = await host.togglePluginFullscreen(true)
console.log(result.fullscreen)
```

宿主的退出按钮或 `Escape` 可以结束插件全屏。宿主主动改变状态时，会向页面派发事件：

```ts
window.addEventListener('xb-svcb-host-event', (event) => {
  const detail = (event as CustomEvent).detail
  if (detail?.name === 'pluginFullscreenChanged') {
    console.log(Boolean(detail.payload?.fullscreen))
  }
})
```

`toggleWindowFullscreen()` 切换整个 XB-SVCB 窗口，适合播放器或演示工具。它和插件全屏是两种独立状态，普通表单页不应自动切换软件窗口。

## 11. 妖狐 M3U8 播放器

第三方播放器页面不应直接嵌套在插件 iframe 中。插件 iframe 继承 `sandbox="allow-scripts"` 和 opaque origin，依赖自身 origin、localStorage 或复杂跨域请求的播放器可能一直停在初始化状态。

宿主为妖狐播放器提供受限的顶层播放弹层：

```ts
interface YaohuPlayerResult {
  opened: true
  url: string
}

openYaohuPlayer(url: string): Promise<YaohuPlayerResult>
```

```ts
await host.openYaohuPlayer(
  'http://m3u8.yaohud.cn/?url=https://cdn.example.com/video/index.m3u8',
)
```

宿主行为和限制：

- 插件清单必须声明 `network` 权限。
- 只接受主机名严格等于 `m3u8.yaohud.cn` 的 HTTP 或 HTTPS URL。
- HTTP 地址会在打开前升级为 HTTPS。
- 播放器在宿主控制的非沙箱跨域 iframe 中运行，插件仍不能读取播放器 DOM、播放进度或媒体响应。
- 关闭按钮和 `Escape` 会卸载播放器 iframe 并停止播放。
- 这不是通用外部网址或任意 M3U8 打开 API，其他域名会被拒绝。
- 旧版宿主不认识该 method 时 Promise 会 reject，插件应显示明确的升级提示。

## 12. Vue `usePluginHost()`

```ts
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
  getStorage,
  setStorage,
  removeStorage,
  togglePluginFullscreen,
  toggleWindowFullscreen,
  openYaohuPlayer,
  clearError,
} = usePluginHost()
```

行为细节：

- 默认在 `onMounted()` 自动调用 `refreshContext()`。
- `{ loadContext: false }` 会关闭自动加载。
- 浏览器预览中 `refreshContext()` 返回 `undefined`，不会请求宿主。
- 每个方法开始时清空共享 `error`。
- 失败会写入 `error`，然后继续 throw，调用方仍需 try/catch。
- `loading` 使用并发计数，有请求未完成时保持 `true`。
- 多个组件分别调用会得到独立状态；大型页面建议封装一个共享 composable 或 provide/inject。
- Vue SDK 不提供单独 timeout 参数，使用 npm Client 默认 30 秒。
- 项目必须安装 Vue 3.5 兼容版本。

共享实例示例：

```ts
// frontend/src/composables/pluginHost.ts
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

let instance: ReturnType<typeof usePluginHost> | undefined

export function useSharedPluginHost() {
  instance ??= usePluginHost()
  return instance
}
```

注意：只有第一次调用发生在组件 setup 中时，`onMounted()` 才能正确注册。也可以传 `loadContext: false`，由根组件显式刷新。

## 13. 当前没有的页面 API

Client 目前不提供：模型列表、作品列表、任务状态查询、文件选择器、宿主路由跳转、插件数据目录直接读写、主题变化订阅、请求取消、通用外部网址播放器和任意自定义 RPC。

普通配置使用宿主存储；需要插件数据目录、复杂系统操作或加密凭据管理时使用混合插件的 Python 动作。需要宿主新能力时，应先扩展正式 Client 契约，而不是访问内部 Bridge。
