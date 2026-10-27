[简体中文](../../plugins/client-api.md) | **English** | [日本語](../../ja/plugins/client-api.md)

# Page Client API

Custom pages cannot call the desktop bridge directly. Host capabilities use `postMessage`; the npm client manages tokens, request IDs, response matching, and timeout.

## Import and Host Detection

```ts
import { host, isHosted, request, type PluginHostContext,
  type HostMessageResult, type CreateWorkPayload } from '@xb-svcb/plugin-sdk/client'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

No-build JavaScript may use injected `window.XBSVCB`, but it lacks npm-client types and the 30-second timeout. Prefer the bundled client. `isHosted()` is true only after receiving a host token; do not infer hosting from `window.parent`.

All methods return promises and reject on host failures. The default timeout is 30 seconds. Low-level `request(method, payload, {timeoutMs})` can change it; non-positive disables timeout. There is no cancellation/AbortSignal, arbitrary methods are rejected, and closing the iframe abandons pending calls. Prefer `host.*`.

## Context and Actions

```ts
const context = await host.getContext()
// { plugin: Manifest, page?: Page, theme?: string }
const result = await host.runAction('create', { title: 'Page cover', pitch: 0 })
```

`page` is absent when none is declared. The center normally opens `pages[0]`. `theme` is a snapshot ID such as `cyber`, `anime`, or `custom`, not CSS variables or a change subscription.

`runAction()` returns optional `ok`, `type`, `message`, `payload`, `work`, and `error`. Message actions interpolate and notify; create-work actions interpolate, create a task, notify, and return `work`; Python actions invoke their worker. Successful actions already notify. Catch promise rejection. Custom pages may call every top-level action; `page.actions` controls declarative buttons only.

## Create a Work Directly

```ts
const work = await host.createWork({
  source_path: 'D:/Music/song.wav', model_id: 'model_xxx',
  title: 'Direct cover', workflow: 'auto_mix',
  params: { pitch: 0, f0_method: 'rmvpe' },
})
```

This skips manifest templates but still passes through every enabled plugin's `before_create` hooks and automatically notifies.

`CreateWorkPayload` supports `title`, `model_id`, nullable `source_path`, `params`, `workflow`, optional `vocal_enhancement`, `mode`, `models`, and `segments`. Workflows are `auto_mix`, `auto_then_editor`, `full_manual_editor`, and multi-only `auto_vocal_merge` / `manual_vocal_merge`.

Inference fields include `pitch`, `f0_method`, `index_rate`, `rms_mix`, `uvr_model`, `diffusion_ratio`, `device`, `protect`, `filter_radius`, `rvc_version`, `reference_audio`, `ddsp_infer_steps`, `ddsp_formant_shift`, and `speaker`. Models use only applicable fields; host validation may reject invalid combinations.

Vocal enhancement requires a complete object: `enabled`, `level`, `pitch_correction`, `timing_alignment`, `timbre_focus`, `ai_eq`, `ai_compressor`, `ai_exciter`, `stereo_width`, and `loudness_envelope`; strengths are 0-1.

```ts
const payload: CreateWorkPayload = {
  source_path: 'D:/Music/song.wav', title: 'Ensemble', mode: 'multi',
  workflow: 'auto_vocal_merge',
  models: [
    { model_id: 'model_a', params: { pitch: 0 } },
    { model_id: 'model_b', params: { pitch: 2 } },
  ],
  segments: [
    { start: 0, end: 12.5, model_id: 'model_a' },
    { start: 12.5, end: 24, model_id: 'model_a', model_ids: ['model_a', 'model_b'] },
  ],
}
```

Multiple `model_ids` create an ensemble; `model_id` remains required and usually equals the first. Validate ranges and IDs. `CreatedWork` stably declares `id` and `title`; `model_id`, `source_path`, `status`, and `progress` are optional. Do not rely on undeclared host fields.

## Resources and Notifications

```ts
const url = await host.assetUrl('assets/cover.png')
const asset = await host.assetData('assets/presets.json')
await host.notify('Settings saved', 'success')
```

Asset paths are relative, may not be absolute or contain `..`, and are limited to 10 MB. `assetData()` returns `{ok,name,mime,data,error?}` with `data` as a Base64 Data URL. It cannot read `plugin-data`; failures reject. Notification types are `success`, `warning`, `info`, and `error`. Do not duplicate automatic action/task notifications.

## Persistent Page Storage

```ts
const prefs = await host.getStorage('preferences', { source: 1 })
await host.setStorage('preferences', { source: 3 })
await host.removeStorage('preferences')
```

Keys are 1-80 letters, digits, dots, underscores, or hyphens. Values must be JSON-serializable; `undefined` is rejected. Data is isolated by plugin ID. Missing/corrupt values return the fallback. Same-ID reinstall preserves storage; changing ID creates a namespace. Storage is not encrypted; avoid irreplaceable high-value credentials.

## Fullscreen and Host Player

`togglePluginFullscreen(enabled?)` fills the host workspace and returns `{ok:true,fullscreen}`. The host button or Escape exits; host changes dispatch `xb-svcb-host-event` with `pluginFullscreenChanged`. `toggleWindowFullscreen()` controls the entire application window independently and should not be triggered automatically by ordinary forms.

```ts
window.addEventListener('xb-svcb-host-event', (event) => {
  const detail = (event as CustomEvent).detail
  if (detail?.name === 'pluginFullscreenChanged') console.log(detail.payload?.fullscreen)
})
```

`openYaohuPlayer(url)` requires `network`, accepts only HTTP(S) hostname exactly `m3u8.yaohud.cn`, upgrades HTTP to HTTPS, and opens a host-controlled non-sandboxed player overlay. Plugins cannot inspect its DOM, progress, or responses. It is not a general URL/M3U8 API. Rejects on unsupported older hosts should show an upgrade message.

## Vue `usePluginHost()`

Returns `hosted`, `context`, `plugin`, `page`, `theme`, `loading`, `error`, and wrappers for context, actions, work creation, assets, notifications, storage, fullscreen, player, and `clearError`.

It loads context on mount unless `{loadContext:false}`. In browser preview refresh returns `undefined`. Each operation clears error, writes and rethrows failures, and maintains a concurrent loading counter. Separate components get separate state; use one shared composable/provide-inject for large pages. Vue wrappers use the default timeout and require Vue 3.5 compatibility.

## Not Available

There is no client API for model/work lists, task polling, file pickers, host routing, direct plugin-data access, theme-change subscription, cancellation, arbitrary external players, or custom RPC. Use host storage for normal settings and hybrid Python actions for filesystem/system operations. Extend the formal client contract instead of accessing internal bridge APIs.
