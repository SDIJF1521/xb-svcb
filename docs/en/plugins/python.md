[简体中文](../../plugins/python.md) | **English** | [日本語](../../ja/plugins/python.md)

# Python Plugin Development

## Execution Model

Python plugins run in a dedicated CPython 3.12 worker. Every lifecycle call, action, or hook starts a fresh worker, imports the entry, executes one request, serializes the result, and exits. This isolates crashes but does not preserve globals and is not a permission sandbox. Code runs with current-user rights.

Use `python` for actions/hooks without a custom page and `hybrid` when Vue calls Python. Both automatically declare `python.execute`.

## Local Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e <XB-SVCB-repository>\plugin-sdk\python
```

The host provides `xb_svcb_plugin`; local tests install it explicitly. Do not import the desktop application's private modules.

## First Plugin

```powershell
npx @xb-svcb/plugin-sdk create python-plugin `
  --id com.example.python-plugin --name "Python Plugin" --type python
cd python-plugin
npm install
```

`src/plugin.ts`:

```ts
const app = plugin('com.example.python-plugin', 'Python Plugin', '1.0.0')
  .python('plugin.py')
  .permission('filesystem.data')
  .page('home', 'Tools', { fields: [], actions: ['analyse'] })
  .pythonAction('analyse', 'Analyse', 'analyse_values')
```

`plugin.py`:

```python
from typing import Any
from xb_svcb_plugin import ActionResult, Plugin, PluginContext

plugin = Plugin("com.example.python-plugin")

@plugin.action("analyse_values")
def analyse_values(ctx: PluginContext, values: dict[str, Any]) -> ActionResult:
    count = int(ctx.config.get("runs", 0)) + 1
    ctx.config["runs"] = count
    ctx.save_config()
    return ActionResult.message_result(f"Run {count}")
```

Validate, package, install, enable global plugins, then enable this plugin:

```powershell
npm run validate
npm run pack
```

## Manifest Rules

`runtime` must be `python` or `hybrid`; `python.entry` is a relative `.py` file inside the package, without absolute paths or `..`. It may be `plugin.py` or `backend/__init__.py`. Manifest action ID is what pages call; `handler` must match the Python decorator. Permissions may declare `filesystem.plugin`, `filesystem.data`, `network`, `process`, and `environment`, but declarations do not enforce OS access.

## Registration and Actions

Create exactly one matching `Plugin(manifest_id)`. Instance decorators are recommended:

```python
@plugin.action("name")
@plugin.before_create
@plugin.on_enable
@plugin.on_disable
@plugin.hook("custom_name")
```

Module-level decorators are supported after creating the plugin. Duplicate registrations overwrite earlier handlers, so keep names unique and registration order obvious.

Action signature is `(ctx: PluginContext, values: dict)`. Sync and async handlers are supported. Valid returns are:

```python
return ActionResult.message_result("Done")
return ActionResult.create_work({"source_path": path, "model_id": model_id})
return "Converted to a message result"
return {"type": "message", "message": "JSON dictionary"}
return None
```

Everything must be JSON-serializable. `Path`, bytes, sets, generators, and arbitrary instances fail during worker output encoding.

## `before_create` Hooks

```python
@plugin.before_create
def before_create(ctx: PluginContext, payload: dict) -> dict:
    payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")
    return payload
```

Preserve unknown fields and make hooks idempotent. Ordering is static manifest patches first, then enabled Python hooks. A hook exception fails task creation instead of silently ignoring policy. Hooks affect UI, HTTP, and plugin-created real tasks. Generic named hooks exist for future host contracts but execute only when the host dispatches that name.

## Lifecycle

`on_enable(ctx)` runs while enabling; failure keeps the plugin disabled. `on_disable(ctx)` runs before disabling; failures are reported but cleanup must tolerate retries. Each callback gets a new process, so persist migration state rather than setting globals. Keep lifecycle work under the 30-second limit and do not start long-lived daemons.

## Context, Configuration, and Files

`PluginContext` provides `plugin_id`, `plugin_dir`, `data_dir`, mutable `config`, and `save_config()`.

```python
ctx.config["schema_version"] = 2
ctx.save_config()

output = ctx.data_dir / "history.json"
output.write_text('{"ok": true}', encoding="utf-8")

template = ctx.plugin_dir / "assets" / "preset.json"
```

Use `data_dir` for mutable files and `plugin_dir` for read-only bundled resources. Do not modify installed code. Configuration changes are not persisted until `save_config()`. Same-ID replacement preserves data; uninstall deletes it.

## Package Entry and Imports

A single-file `plugin.py` is simplest. For packages, point the manifest to `backend/__init__.py` and use relative imports such as `from .rules import normalize`. The worker sets up package import context for an `__init__.py` entry. Avoid expensive or destructive import-time side effects because every call reimports the entry.

## Third-party Dependencies

Pin dependencies in `requirements.txt`:

```text
httpx==0.28.1
```

`npm run pack` installs them into package `vendor/` with Python 3.12. The host prepends `vendor/` to `sys.path` and never installs dependencies online. Do not vendor the whole virtual environment. Audit licenses and compiled-wheel compatibility and stay below 20 MB compressed / 50 MB extracted.

## Testing

Keep business logic in ordinary functions and test without the host. Construct a temporary `PluginContext` to test actions/hooks/configuration, and use `asyncio.run()` for async handlers. Unit tests do not cover manifest-handler matching, final package contents, host interpreter imports, timeout, or real task validation, so perform an installed-host test.

```powershell
python -m py_compile plugin.py
python -m pytest -q
npm run validate
npm run pack
```

## Debugging, Security, and Limits

Worker exceptions are returned as action/hook failures; inspect Plugin Center and application logs. `print()` goes to worker-captured output and is not a stable user interface. Reproduce pure logic locally, then entry import, then manifest mapping, then installed execution.

- Default worker timeout: 30 seconds. There is no background worker, persistent session, or cancellation protocol.
- One request per fresh process; globals and caches do not survive.
- Entry import, handler result, configuration, and IPC must remain JSON/path compatible.
- The worker is not a sandbox. Avoid unrelated files/env credentials, validate subprocess arguments, use HTTPS, and document transmitted data.
- Plugin code directory is replaceable; data directory is persistent until uninstall.

Common failures: create `Plugin(id)` before module decorators; ensure ID equals manifest; map action ID to the registered handler; include the actual entry and `vendor/`; use package-relative imports; call `save_config()`; return the modified payload from `before_create`; keep calls under timeout; and never rely on `on_disable` to clean a long-lived process that cannot exist across workers.

## Python SDK Summary

Exports include `Plugin`, `PluginContext`, `ActionResult`, instance and module-level decorators, and result normalization. Handler signatures are action `(ctx, values)`, hook `(ctx, payload)`, and lifecycle `(ctx)`. `ActionResult` supports message and create-work factories. See [API Reference](reference.md) for the compact signature list and [Testing](testing.md) for host acceptance.
