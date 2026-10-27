[简体中文](../../plugins/hybrid.md) | [English](../../en/plugins/hybrid.md) | **日本語**

# Vue + Python Hybrid Plugin

Vueで入力を集め、`runAction()`から分離Python workerへ送り、task payloadを返してhostに作成させます。

## 作成と宣言

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
  .description('Vueでparameterを集め、Pythonでtaskを作成します。')
  .permission('filesystem.data')
  .page('home', 'Smart Cover', { fields: [], actions: ['create'] })
  .pythonAction('create', 'カバー作成', 'create_cover')
await writeManifest(app, '.')
```

`.hybrid().frontendEntry()`を使います。その後の`.frontend()`はruntimeをfrontendへ変えPython設定を消します。Vueはaction ID `create`を呼び、Python登録名はhandler `create_cover`と一致させます。

## Python action

```python
from typing import Any
from xb_svcb_plugin import ActionResult, Plugin, PluginContext

plugin = Plugin("com.example.hybrid-cover")

@plugin.action("create_cover")
async def create_cover(ctx: PluginContext, values: dict[str, Any]) -> ActionResult:
    source_path = str(values.get("source_path") or "").strip()
    model_id = str(values.get("model_id") or "").strip()
    if not source_path or not model_id:
        return ActionResult.message_result("source pathとmodel IDを入力してください")
    style = str(values.get("style") or "natural")
    ctx.config["last_style"] = style
    ctx.save_config()
    return ActionResult.create_work({
        "source_path": source_path, "model_id": model_id,
        "title": str(values.get("title") or "Hybrid cover"),
        "workflow": "auto_mix",
        "params": {"pitch": 1 if style == "bright" else 0, "f0_method": "rmvpe"},
    })
```

handler signatureは`(ctx, values)`固定で、sync/asyncの両方に対応し、結果はJSON serialize可能にします。

## Vue呼出

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
const form = reactive({ source_path: '', model_id: '', title: 'Hybrid cover', style: 'natural' })
const output = ref('')
const { hosted, loading, error, runAction } = usePluginHost()
async function submit() {
  if (!hosted.value) { output.value = 'browser previewではPythonを起動しません'; return }
  try { output.value = JSON.stringify(await runAction('create', { ...form }), null, 2) }
  catch { output.value = error.value?.message || 'Python action失敗' }
}
</script>
```

`create_work`成功時はhostがtaskと通知を作るため、重ねて`notify()`しないでください。

## Returnとhook順序

`ActionResult.message_result()`、`ActionResult.create_work()`、string、JSON dict、`None`を返せます。`Path`、`set`、`bytes`、任意instanceは返せません。

順序はaction payload -> hostの正式task API -> 全pluginの静的`beforeCreate` -> 全Python `before_create` -> 通常queueです。同じpluginが二度処理する可能性があるため、`setdefault()`などでidempotentにしてください。
