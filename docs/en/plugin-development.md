[简体中文](../plugin-development.md) | **English** | [日本語](../ja/plugin-development.md)

# XB-SVCB Plugin Development Guide

This is the single-page compatibility guide. The maintained English documentation is split into focused chapters so API details, security boundaries, and examples can be updated without duplicating one large file.

## Reading Route

1. [Plugin overview](plugins/README.md) for the runtime model and limits.
2. [Quick start](plugins/getting-started.md) to scaffold and install a first plugin.
3. [Vue pages](plugins/frontend-vue.md) or [Python plugins](plugins/python.md) for the chosen runtime.
4. [Manifest](plugins/manifest.md), [Client API](plugins/client-api.md), and [hybrid plugins](plugins/hybrid.md) for integration details.
5. [Testing](plugins/testing.md), [publishing](plugins/publishing.md), and [API reference](plugins/reference.md) before release.

## Plugin Model

```text
src/plugin.ts -> xb-svcb-plugin.json -> host metadata, pages, actions, permissions
frontend/     -> dist/frontend/index.html -> sandboxed iframe
plugin.py     -> fresh Python 3.12 worker -> action/hook/lifecycle result
```

Choose `frontend` for declarative/custom pages without Python, `python` for actions/hooks, and `hybrid` for a custom page that invokes Python. New installs are disabled. Pages run with `sandbox="allow-scripts"`; Python workers run with current-user rights and are not security sandboxes.

## Create and Build

```powershell
npx @xb-svcb/plugin-sdk create my-plugin `
  --id com.example.my-plugin --name "My Plugin" --type hybrid
cd my-plugin
npm install
npm run dev
npm run typecheck
npm run validate
npm run pack
```

TypeScript Vue is the recommended frontend. Vanilla TypeScript and no-build JavaScript are also available. Python/hybrid development requires Python 3.12.x.

The manifest ID is permanent after publication. Generate `xb-svcb-plugin.json` from `src/plugin.ts`; do not maintain it or `dist/` manually.

## Minimal Hybrid Example

```ts
const app = plugin('com.example.my-plugin', 'My Plugin', '1.0.0')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
  .page('home', 'Home', { fields: [], actions: ['create'] })
  .pythonAction('create', 'Create cover', 'create_cover')
```

```python
from xb_svcb_plugin import ActionResult, Plugin, PluginContext
plugin = Plugin("com.example.my-plugin")

@plugin.action("create_cover")
def create_cover(ctx: PluginContext, values: dict) -> ActionResult:
    return ActionResult.create_work({
        "source_path": values["source_path"],
        "model_id": values["model_id"],
        "workflow": "auto_mix",
        "params": {"pitch": 0, "f0_method": "rmvpe"},
    })
```

```ts
const { hosted, loading, error, runAction } = usePluginHost()
const result = await runAction('create', { source_path, model_id })
```

Manifest action ID, Python handler, and decorator registration are distinct names that must map correctly. Use `.hybrid().frontendEntry()`, not `.hybrid().frontend()`.

## Data, Hooks, and Dependencies

Use page host storage for ordinary JSON preferences. Python reads packaged resources through `ctx.plugin_dir`, writes mutable files under `ctx.data_dir`, changes `ctx.config`, and calls `ctx.save_config()`.

Static `.beforeCreate()` fills missing inference defaults. Python `before_create` handles conditional/full payload changes and must preserve unknown fields and remain idempotent. It runs for UI, HTTP, and plugin-created tasks.

Pin non-standard Python 3.12 dependencies in `requirements.txt`; packaging places them in `vendor/`. The host never installs them online. Audit licenses and compiled-wheel support.

## Security and Runtime Limits

- Package 20 MB compressed / 50 MB extracted; manifest 512 KB; HTML 2 MB; one asset 10 MB.
- Page and Python calls default to 30 seconds. No cancellation or persistent worker exists.
- Permissions are declarations, not OS enforcement.
- Pages cannot access parent DOM, internal bridge, arbitrary local paths, or reliable same-origin storage.
- Python code can access user resources permitted by the OS; enable only trusted sources.
- Marketplace downloads are GitHub HTTPS only and provide no signatures, hash enforcement, compatibility resolution, dependencies, or automatic upgrades.

## Acceptance and Troubleshooting

Validation does not prove entry files, Python imports, handler registration, package size, or task rules. Inspect the archive, install it in a real host, enable both switches, exercise every action and error path, and create a real short task. Test same-ID replacement and data preservation as well as uninstall deletion.

For failures, check manifest/runtime and IDs, entry paths, final package contents, handler mapping, Python 3.12 imports and `vendor/`, JSON-serializable returns, `save_config()`, hook return, timeout, Plugin Center output, and application logs. See [Testing and Debugging](plugins/testing.md) for executable patterns.
