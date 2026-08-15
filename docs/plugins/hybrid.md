# Vue + Python 混合插件

混合插件适合“页面负责交互，Python 负责计算、配置或系统操作”的场景。Vue 页面通过 `runAction()` 请求宿主，宿主启动独立 Python Worker，执行清单指定的 handler，再把 JSON 结果返回页面。

```text
CoverForm.vue
  -> runAction('create', values)
  -> manifest action id=create, handler=create_cover
  -> @plugin.action('create_cover')
  -> ActionResult.create_work(payload)
  -> 宿主创建任务并返回 work
```

## 1. 创建项目

```powershell
npx @xb-svcb/plugin-sdk create hybrid-cover `
  --id com.example.hybrid-cover `
  --name "混合翻唱助手" `
  --type hybrid

cd hybrid-cover
npm install
```

关键文件：

```text
hybrid-cover/
├─ src/plugin.ts
├─ plugin.py
├─ frontend/src/App.vue
├─ frontend/src/components/GreetingForm.vue
├─ vite.config.ts
└─ xb-svcb-plugin.json
```

## 2. 定义混合清单

`src/plugin.ts`：

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'

const app = plugin('com.example.hybrid-cover', '混合翻唱助手', '1.0.0')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
  .description('Vue 收集参数，Python 生成任务。')
  .author('Your Name')
  .permission('filesystem.data')
  .page('home', '智能翻唱', {
    fields: [],
    actions: ['create'],
  })
  .pythonAction('create', '创建翻唱', 'create_cover')

await writeManifest(app, '.')
```

必须使用 `.hybrid().frontendEntry()`。不要在 `.hybrid()` 后调用 `.frontend()`；后者会把 runtime 改回 `frontend` 并清空 Python 配置。

动作名称有两层：

| 名称 | 示例 | 谁使用 |
| --- | --- | --- |
| action ID | `create` | Vue `runAction('create')` |
| Python handler | `create_cover` | `@plugin.action('create_cover')` |

二者可以相同，也可以不同，但必须分别与页面和 Python 注册保持一致。

## 3. 编写 Python 动作

`plugin.py`：

```python
from __future__ import annotations

from typing import Any

from xb_svcb_plugin import ActionResult, Plugin, PluginContext


plugin = Plugin("com.example.hybrid-cover")


@plugin.action("create_cover")
async def create_cover(
    ctx: PluginContext,
    values: dict[str, Any],
) -> ActionResult:
    source_path = str(values.get("source_path") or "").strip()
    model_id = str(values.get("model_id") or "").strip()
    if not source_path or not model_id:
        return ActionResult.message_result("请填写源音频路径和模型 ID")

    style = str(values.get("style") or "natural")
    pitch = 1 if style == "bright" else 0

    ctx.config["last_style"] = style
    ctx.save_config()

    return ActionResult.create_work(
        {
            "source_path": source_path,
            "model_id": model_id,
            "title": str(values.get("title") or "混合插件翻唱"),
            "workflow": "auto_mix",
            "params": {
                "pitch": pitch,
                "f0_method": "rmvpe",
            },
        }
    )
```

动作签名固定为 `(ctx, values)`。同步 `def` 和异步 `async def` 都支持。返回值必须最终可 JSON 序列化。

## 4. Vue 调用 Python

把脚手架组件替换为 `frontend/src/components/CoverForm.vue`：

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'

import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const form = reactive({
  source_path: '',
  model_id: '',
  title: '混合插件翻唱',
  style: 'natural',
})
const output = ref('')
const { hosted, loading, error, runAction } = usePluginHost()

async function submit() {
  if (!hosted.value) {
    output.value = '浏览器预览不会启动 Python Worker。'
    return
  }

  try {
    const result = await runAction('create', { ...form })
    output.value = JSON.stringify(result, null, 2)
  } catch {
    output.value = error.value?.message || 'Python 动作执行失败'
  }
}
</script>

<template>
  <form @submit.prevent="submit">
    <label>源音频 <input v-model="form.source_path"></label>
    <label>模型 ID <input v-model="form.model_id"></label>
    <label>标题 <input v-model="form.title"></label>
    <label>
      风格
      <select v-model="form.style">
        <option value="natural">自然</option>
        <option value="bright">明亮</option>
      </select>
    </label>
    <button :disabled="loading">
      {{ loading ? 'Python 处理中…' : '创建翻唱' }}
    </button>
    <pre v-if="output">{{ output }}</pre>
  </form>
</template>
```

`runAction()` 成功返回 `create_work` 时，宿主会自动创建任务并显示通知。不要在成功后再调用 `notify()`，否则会重复提示。

## 5. Python 返回协议

支持：

```python
return ActionResult.message_result("操作完成")
return ActionResult.create_work({...})
return "字符串会变成 message 结果"
return {"type": "message", "message": "普通字典"}
return None  # 空结果
```

普通 dict 可以返回自定义 JSON 数据，但页面 SDK 的默认 `HostMessageResult` 只声明 message/create_work 字段。自定义协议时应在页面中定义自己的类型并做运行时校验。

不能返回 Path、set、bytes、任意类实例等不可 JSON 序列化对象。Worker 最终需要把结果编码为 JSON。

## 6. 动作与 `before_create` 的顺序

如果 Python action 返回 `ActionResult.create_work(payload)`：

1. action 先生成 payload；
2. 宿主页面调用正式创建任务 API；
3. 所有已启用插件的静态 `beforeCreate` 补丁执行；
4. 所有已启用 Python/混合插件的 `before_create` 钩子执行；
5. 任务进入正常流程。

这意味着同一个插件的 action 和 `before_create` 都可能处理同一任务。应让钩子保持幂等，例如使用 `setdefault()`，不要每次无条件重复追加数据。

```python
@plugin.before_create
def before_create(ctx: PluginContext, payload: dict) -> dict:
    payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")
    return payload
```
