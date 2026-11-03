[简体中文](../../plugins/hybrid.md) | **English** | [日本語](../../ja/plugins/hybrid.md)

# Vue + Python Hybrid Plugins

A hybrid plugin collects input in Vue, sends it through `runAction()`, processes it in an isolated Python worker, and may return a task payload for the host to create.

## Create and Declare

```powershell
npx @xb-svcb/plugin-sdk create hybrid-cover --id com.example.hybrid-cover --name "Hybrid Cover Assistant" --type hybrid
cd hybrid-cover
npm install
```

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.hybrid-cover', 'Hybrid Cover Assistant', '1.0.0')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
  .description('Vue collects parameters; Python creates the task.')
  .permission('filesystem.data')
  .page('home', 'Smart Cover', { fields: [], actions: ['create'] })
  .pythonAction('create', 'Create cover', 'create_cover')

await writeManifest(app, '.')
```

Use `.hybrid().frontendEntry()`. Calling `.frontend()` afterward changes runtime to frontend and clears Python configuration. The action ID (`create`) is called by Vue; the handler (`create_cover`) must match Python registration.

## Python Action

```python
from typing import Any
from xb_svcb_plugin import ActionResult, Plugin, PluginContext

plugin = Plugin("com.example.hybrid-cover")

@plugin.action("create_cover")
async def create_cover(ctx: PluginContext, values: dict[str, Any]) -> ActionResult:
    source_path = str(values.get("source_path") or "").strip()
    model_id = str(values.get("model_id") or "").strip()
    if not source_path or not model_id:
        return ActionResult.message_result("Enter a source path and model ID")
    style = str(values.get("style") or "natural")
    ctx.config["last_style"] = style
    ctx.save_config()
    return ActionResult.create_work({
        "source_path": source_path,
        "model_id": model_id,
        "title": str(values.get("title") or "Hybrid cover"),
        "workflow": "auto_mix",
        "params": {"pitch": 1 if style == "bright" else 0, "f0_method": "rmvpe"},
    })
```

Handlers always receive `(ctx, values)`, may be synchronous or asynchronous, and must return JSON-serializable data.

## Vue Call

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const form = reactive({ source_path: '', model_id: '', title: 'Hybrid cover', style: 'natural' })
const output = ref('')
const { hosted, loading, error, runAction } = usePluginHost()

async function submit() {
  if (!hosted.value) { output.value = 'Browser preview does not start Python.'; return }
  try { output.value = JSON.stringify(await runAction('create', { ...form }), null, 2) }
  catch { output.value = error.value?.message || 'Python action failed' }
}
</script>
```

When a `create_work` result succeeds, the host creates the task and displays a notification. Do not notify again.

## Return and Hook Order

Supported returns: `ActionResult.message_result()`, `ActionResult.create_work()`, a string, a JSON dictionary, or `None`. Do not return `Path`, `set`, `bytes`, or arbitrary instances.

For `create_work`: action creates payload -> host calls real task API -> all enabled static `beforeCreate` patches -> all enabled Python `before_create` hooks -> normal task queue. The same plugin may process a task twice, so hooks should be idempotent, for example `payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")`.
