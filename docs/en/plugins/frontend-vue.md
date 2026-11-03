[简体中文](../../plugins/frontend-vue.md) | **English** | [日本語](../../ja/plugins/frontend-vue.md)

# Vue 3 Custom Pages

Use a custom Vue page when a declarative form is insufficient for multi-step flows, live state, rich validation, or multiple views.

## Project and Manifest

```powershell
npx @xb-svcb/plugin-sdk create vue-tool --id com.example.vue-tool --name "Vue Tool" --type frontend
cd vue-tool
npm install
```

```ts
const app = plugin('com.example.vue-tool', 'Vue Tool', '1.0.0')
  .frontend('dist/frontend/index.html')
  .page('home', 'Vue Tool', { fields: [], actions: ['preview', 'create'] })
  .message('preview', 'Preview', 'Title: {{title}}')
  .createWork('create', 'Create cover', {
    source_path: '{{source_path}}', model_id: '{{model_id}}',
    title: '{{title}}', workflow: 'auto_mix', params: { pitch: '{{pitch}}' },
  })
```

`frontend/src/main.ts` mounts `App.vue`; the Vite single-file plugin must inline JS and CSS into `dist/frontend/index.html`.

## Component Pattern

Keep `App.vue` as a quiet page shell and move form/business behavior into components. Stable controls should not resize when status text changes. Use semantic labels, native inputs/selects, disabled/loading states, and host notifications for commands.

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const form = reactive({ source_path: '', model_id: '', title: '', pitch: 0 })
const result = ref('')
const { hosted, loading, error, runAction, notify } = usePluginHost()

async function submit() {
  if (!form.source_path || !form.model_id) return
  if (!hosted.value) { result.value = 'Development preview'; return }
  const value = await runAction('create', { ...form })
  result.value = JSON.stringify(value, null, 2)
}
</script>
```

`usePluginHost()` exposes reactive `hosted`, `context`, `loading`, and `error`, plus host methods. Catch rejected promises; do not rely only on the shared error state when concurrent actions are possible.

## Theme and Layout

The iframe does not expose host DOM or CSS variables. Define both light and dark page tokens and respond to `prefers-color-scheme`. Avoid assuming the host page background. Use responsive grids, bounded widths, visible focus states, and `overflow-wrap` for paths/results. Do not use viewport-scaled type.

## Multiple Views and Libraries

One plugin has one entry and the center normally opens `pages[0]`. Implement views with component state, tabs, or an in-memory router. Do not depend on server fallback or browser history paths inside the sandbox.

Pinia and UI libraries may be bundled, but everything counts toward the 2 MB entry HTML limit. Import only used components and styles. Libraries requiring portals into parent DOM, same-origin storage, or unrestricted network access may fail.

## Plugin Resources

Place read-only files under the package and load them through `host.assetUrl(relativePath)` or `host.assetData(relativePath)`. Paths must remain inside the plugin, and each resource is limited to 10 MB. `assetUrl()` returns a Data URL suitable for `<img>`/`<audio>`; revoke only object URLs you create yourself, not Data URLs.

## Sandbox Capability Matrix

| Capability | Status |
| --- | --- |
| Run JavaScript and bundled Vue | Yes |
| Call host through Client SDK | Yes |
| Read packaged assets through host | Yes |
| Access parent DOM or pywebview API directly | No |
| Depend on same-origin cookies/localStorage | No |
| Open arbitrary local paths | No |
| Load arbitrary external sites reliably | No |
| Persist JSON through host storage | Yes |
| Request page fullscreen through host | Yes |

Third-party player pages commonly fail because opaque-origin iframes, CSP/CORS, cookies, frame policies, or nested media restrictions apply. Use the dedicated host player only for allowed `m3u8.yaohud.cn` URLs and declare `network`; otherwise build controls around media resources the plugin owns.

## Build and Validate

```powershell
npm run dev
npm run typecheck
npm run build
npm run validate
npm run pack
```

Preview tests layout only. In XB-SVCB verify context, action calls, resources, storage, fullscreen, theme, narrow layouts, disabled states, console errors, plugin/global disable behavior, and a real task payload.
