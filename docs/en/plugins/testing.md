[简体中文](../../plugins/testing.md) | **English** | [日本語](../../ja/plugins/testing.md)

# Testing and Debugging Plugins

No single command proves a plugin works. Validate source, build outputs, archive contents, host installation, runtime calls, and real business payloads separately.

## Test Levels

| Level | Proves | Does not prove |
| --- | --- | --- |
| `typecheck` | Vue/TypeScript type consistency | Runtime behavior or manifest validity |
| `build` | Frontend and manifest can be generated | Host installation |
| `xb-plugin validate` | Manifest shape and allowlists | Entry existence, Python import, action registration |
| `pack` | Archive can be produced | All host size limits or absence of secrets |
| Host install | ZIP safety, sizes, manifest, entries | Actions and task payloads work |
| Runtime acceptance | Page, Python, hooks, and task creation | Other hardware/app versions |

Scaffold commands:

```powershell
npm run typecheck
npm run build
npm run validate
npm run pack
```

`validate` runs type checking, builds frontend/manifest, and validates the manifest. `pack` runs validation only through the scaffold script; direct CLI `pack` does not automatically build source. Inspect the final ZIP because `.env`, tests, source maps, and custom caches are not ignored.

## Manifest Unit Tests

Export a function that builds the manifest, then assert runtime, permissions, pages, actions, and validation:

```ts
import { describe, expect, it } from 'vitest'
import { validateManifest } from '@xb-svcb/plugin-sdk'
import { buildPlugin } from '../src/plugin'

describe('manifest', () => {
  it('is valid', () => {
    const manifest = buildPlugin().build()
    expect(validateManifest(manifest)).toEqual({ ok: true, errors: [] })
    expect(manifest.id).toBe('com.example.plugin')
  })
})
```

Do not generate files as an import side effect in modules used by tests; put `writeManifest()` in a dedicated build entry.

## Mock the Page Client

For low-level client tests, create a parent `message` listener that captures request IDs/methods and dispatches the matching response with the injected token. Test success, host rejection, timeout, malformed response, concurrency, and cleanup. Do not mock only `host.runAction()` if protocol behavior matters.

For component tests, mock `@xb-svcb/plugin-sdk/vue` and return refs plus async method spies:

```ts
vi.mock('@xb-svcb/plugin-sdk/vue', () => ({
  usePluginHost: () => ({
    hosted: ref(true), loading: ref(false), error: ref(),
    runAction: vi.fn().mockResolvedValue({ type: 'message', message: 'ok' }),
  }),
}))
```

Verify required-field validation, loading/disabled state, resolved results, rejected promises, browser-preview behavior, narrow layout, keyboard operation, and no duplicate notifications. jsdom cannot prove sandbox, Data URL media, or real host messaging.

## Browser Preview

`npm run dev` validates rendering, local form state, client-side validation, responsive layout, and theme media queries. `isHosted()` is false, so it cannot validate context, actions, storage, resources, fullscreen, host player, or Python.

## Python Unit Tests

Test pure functions separately. Build a temporary context for registered handlers:

```python
from pathlib import Path
from xb_svcb_plugin import PluginContext

ctx = PluginContext(
    plugin_id="com.example.plugin",
    plugin_dir=Path("."),
    data_dir=tmp_path,
    config={},
)
```

Test synchronous and asynchronous actions, `ActionResult` normalization, missing/invalid values, idempotent hooks, unknown-field preservation, configuration persistence, data paths, and exceptions. Run syntax/import tests with the same Python 3.12 architecture as the host. Local SDK tests cannot prove the packaged `vendor/`, entry path, worker timeout, or host's task validation.

## Real Host Acceptance

Fresh install:

1. Pack the final archive and inspect contents and sizes.
2. Install it in Plugin Center and review runtime/permissions.
3. Confirm it starts disabled; enable global and per-plugin switches.
4. Open the page and test every action, resource, storage operation, and error path.
5. For task actions, create a real short test task and verify hooks once.

Same-ID update must replace code, disable the plugin, preserve settings/data, and run an idempotent migration when re-enabled. Uninstall must remove code and plugin data; export anything that must survive first.

## Worker Debugging

Follow this order: `py_compile` -> local import -> handler unit test -> manifest action/handler mapping -> final archive entry/vendor -> enable lifecycle -> installed action -> application logs. Remember every call imports in a fresh process. A local virtual environment hiding an undeclared dependency is a common cause of “works locally, fails in host.”

## Release Gate

Require typecheck, unit tests, validate, archive inspection, fresh install, same-ID update, enable/disable, all actions/hooks, real task creation, negative paths, timeout behavior, size checks, license review, and installation from the actual GitHub Release URL. Record the tested XB-SVCB and SDK versions because the marketplace does not enforce compatibility.
