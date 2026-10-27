[简体中文](../../plugins/reference.md) | **English** | [日本語](../../ja/plugins/reference.md)

# Plugin API Quick Reference

## Entry Points

```ts
import { plugin, fields, page, messageAction, createWorkAction,
  pythonAction, validateManifest, writeManifest } from '@xb-svcb/plugin-sdk'
import { host, isHosted, request } from '@xb-svcb/plugin-sdk/client'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

```python
from xb_svcb_plugin import Plugin, PluginContext, ActionResult
```

## CLI

```text
xb-plugin create <dir> --id ID --name NAME
  [--type frontend|python|hybrid] [--language ts|js]
  [--framework vue|vanilla] [--version VERSION] [--author AUTHOR]
xb-plugin validate [dir]
xb-plugin pack [dir] [output.xbplugin]
```

Vue requires TypeScript. Direct `pack` does not build frontend/manifest; scaffold `npm run pack` does.

## Manifest

Required top-level fields: `id`, `name`, `version`, `runtime`, `python`, `frontend`, `permissions`, `pages`, `actions`, `workflow`. Optional text fields are `description` and `author`.

ID pattern: `^[a-z0-9][a-z0-9._-]{2,63}$`. Runtime: `frontend | python | hybrid`. Permissions: `python.execute`, `filesystem.plugin`, `filesystem.data`, `network`, `process`, `environment`.

```text
plugin(id, name, version?) -> PluginBuilder
.description(text) .author(name)
.frontend(entryOrConfig?) .frontendEntry(entry, config?)
.python(entry?) .hybrid(entry?)
.permission(...permissions)
.page(pageObject) | .page(id, title, configOrFactory?)
.action(actionObject)
.message(id, label, message)
.createWork(id, label, payload, options?)
.pythonAction(id, label, handler?, options?)
.beforeCreate(params)
.build() -> Manifest
```

Fields: `fields.text`, `fields.textarea`, `fields.number`, `fields.switch`, `fields.select`. Common members: `id`, `label`, `type`, `default`, `placeholder` (except switch), `help`; select requires non-empty `{label,value}` options.

Actions: `message`, `create_work`, and `python`, each with `id`, `label`, and `type`. Python actions also have `handler`. `page.actions` controls declarative buttons, not custom-page permissions.

Interpolation accepts only `{{name}}`; names start with a letter and contain letters/digits/underscores. Whole-value placeholders retain primitive type. Static `beforeCreate` fills missing inference params only; Python hooks handle conditional/full payload changes.

## Page Client

```text
isHosted() -> boolean
request<T>(method, payload?, {timeoutMs?}) -> Promise<T>
host.getContext()
host.runAction(actionId, values?)
host.createWork(payload)
host.assetData(path) / host.assetUrl(path)
host.notify(message, type?)
host.getStorage(key, fallback?) / setStorage(key, value) / removeStorage(key)
host.togglePluginFullscreen(enabled?)
host.toggleWindowFullscreen()
host.openYaohuPlayer(url)
```

Requests reject on failure and default to 30 seconds. Asset paths are relative and one asset is limited to 10 MB. Storage keys are 1-80 `[A-Za-z0-9._-]` characters and values are JSON. The Yaohu player requires `network` and hostname exactly `m3u8.yaohud.cn`.

`PluginHostContext`: `plugin`, optional `page`, optional theme ID. `HostMessageResult`: optional `ok`, `type`, `message`, `payload`, `work`, `error`. `CreatedWork` guarantees `id` and `title`; other fields are optional.

`CreateWorkPayload`: `title`, `model_id`, `source_path`, `params`, `workflow`, `vocal_enhancement`, `mode`, `models`, `segments`. Workflows: `auto_mix`, `auto_then_editor`, `full_manual_editor`, multi-only `auto_vocal_merge`, `manual_vocal_merge`.

`usePluginHost()` exposes refs `hosted`, `context`, `plugin`, `page`, `theme`, `loading`, `error` plus wrappers for every host method and `clearError`. It loads context on mount unless `{loadContext:false}` and rethrows after updating `error`.

## Python SDK

```python
plugin = Plugin("com.example.plugin")

@plugin.action("handler")       # (ctx, values)
@plugin.before_create           # (ctx, payload) -> payload
@plugin.on_enable               # (ctx)
@plugin.on_disable              # (ctx)
@plugin.hook("name")            # (ctx, payload)
```

Sync and async handlers are supported. Returns: `ActionResult`, `dict`, `str`, or `None`, all JSON-serializable. `ActionResult.message_result(message)` and `ActionResult.create_work(payload)` are standard factories.

`PluginContext`: `plugin_id: str`, `plugin_dir: Path`, `data_dir: Path`, `config: dict`, `save_config()`. Mutable data belongs in `data_dir`; packaged resources are read from `plugin_dir`.

Each lifecycle/action/hook starts a new worker and reimports the entry. Default timeout is 30 seconds. Globals do not persist. Workers isolate crashes but are not security sandboxes.

## Lifecycle and Installation

Fresh installs are disabled. Same-ID install replaces code, resets enabled state, and preserves data/storage. Uninstall removes code and plugin data. Package limits: 20 MB compressed, 50 MB extracted, 512 KB manifest, 2 MB HTML, 10 MB asset.

Marketplace records require valid `id` and allowed GitHub HTTPS `bundle_url`. No signatures, hash enforcement, compatibility negotiation, dependency resolution, version comparison, automatic update, or general rollback is provided.

## Common Failures

- Wrong runtime or calling `.frontend()` after `.hybrid()`.
- Missing built entry, handler mismatch, invalid relative path, or undeclared vendored dependency.
- Assuming manifest validation checks files/runtime behavior.
- Returning non-JSON Python objects or forgetting `save_config()` / hook return.
- Depending on persistent globals, same-origin iframe behavior, arbitrary network/player URLs, or unsupported client RPC.
- Exceeding timeout/size limits or packaging secrets.

Minimum release gate: typecheck, unit tests, build, manifest validation, package inspection, fresh host install, same-ID update, page/action/hook/error checks, and one real task. Detailed guides: [Manifest](manifest.md), [Client API](client-api.md), [Python](python.md), [Testing](testing.md), [Publishing](publishing.md).
