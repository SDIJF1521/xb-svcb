[简体中文](../../plugins/README.md) | **English** | [日本語](../../ja/plugins/README.md)

# XB-SVCB Plugin Development

These documents cover the manifest SDK, page client, Vue composable, Python SDK, package format, installation behavior, and current runtime limits without requiring the main XB-SVCB source.

## Reading Paths

| Goal | Read | Result |
| --- | --- | --- |
| First plugin | [Quick Start](getting-started.md) -> [Vue Pages](frontend-vue.md) | Installable Vue plugin |
| Cover-parameter tool | [Quick Start](getting-started.md) -> [Manifest](manifest.md) | Declarative form or task action |
| Execute Python | [Python Plugins](python.md) -> [Testing](testing.md) | Python action or workflow hook |
| Vue calls Python | [Hybrid Plugins](hybrid.md) -> [Client API](client-api.md) | Vue + Python plugin |
| Publish | [Packaging and Marketplace](publishing.md) | GitHub Release and `market.json` |

Use [API Reference](reference.md) to find a field or function, and [Testing and Debugging](testing.md) for installation, enablement, or action failures. The [single-file guide](../plugin-development.md) remains available for full-text search.

## Development Flow

```text
Create scaffold -> edit manifest/page/backend -> npm install -> npm run dev
-> npm run typecheck -> npm run validate -> npm run pack
-> install .xbplugin -> enable global plugins -> enable plugin
-> open page, run actions, and create a real test task
```

Validation checks local source and the manifest. A real installation proves package contents, entry points, host communication, Python runtime, and task parameters.

## Plugin Parts

```text
src/plugin.ts ---------------------> xb-svcb-plugin.json
frontend/src/App.vue + components -> dist/frontend/index.html
plugin.py / Python package -------> isolated Python worker
```

| Runtime | Page | Python | Typical use |
| --- | --- | --- | --- |
| `frontend` | Optional | No | Vue tools, declarative forms, messages, task creation |
| `python` | Optional | Yes | Hooks, background parameter processing, configuration |
| `hybrid` | Optional | Yes | Vue pages invoking Python actions |

Installed code is normalized under `<plugins>/<plugin-id>/`. Persistent Python data belongs in `ctx.data_dir`, not the code directory. Pages use `host.getStorage()`, `host.setStorage()`, and `host.removeStorage()` for plugin-isolated JSON settings.

## TypeScript Entry Points

```ts
import { plugin, fields, writeManifest } from '@xb-svcb/plugin-sdk'
import { host, isHosted } from '@xb-svcb/plugin-sdk/client'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

The first runs on the developer machine to build a manifest. The second runs inside a plugin page. The third is its reactive Vue wrapper.

## Security and Limits

- New plugins are disabled; both global and per-plugin switches must be enabled.
- Pages run in `sandbox="allow-scripts"` opaque-origin iframes and cannot access host DOM.
- Host calls use a message token, request IDs, and a 30-second default timeout.
- Python workers isolate crashes, not permissions. Code runs with the current user's rights and is imported in a new worker for every action, hook, or lifecycle call.
- Permissions are declarations for review and prompts, not OS enforcement. Enable only trusted Python/hybrid plugins.
- Package: 20 MB compressed, 50 MB declared extracted size. Manifest: 512 KB. Entry HTML: 2 MB. One `assetUrl()` resource: 10 MB.
- One `frontend.entry` per plugin. Multiple views should live inside the Vue app; the center usually opens only `pages[0]`.
- Marketplace downloads accept only allowed GitHub HTTPS raw/API/release URLs.
- The host player supports only `m3u8.yaohud.cn` URLs with `network` permission, not arbitrary web video.

Important boundaries: `page.actions` controls buttons on declarative pages but does not restrict a custom page from calling top-level actions. `before_create` runs for every real task, including tasks created by a plugin. Reinstalling the same ID replaces code, disables the plugin, and preserves its data directory.
