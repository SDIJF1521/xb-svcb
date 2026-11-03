[简体中文](../../plugins/frontend-vue.md) | [English](../../en/plugins/frontend-vue.md) | **日本語**

# Vue 3 Custom Page

宣言formでは不足する複数step、live state、詳細validation、複数viewにcustom Vue pageを使います。

## ProjectとManifest

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
  .createWork('create', 'カバー作成', {
    source_path: '{{source_path}}', model_id: '{{model_id}}',
    title: '{{title}}', workflow: 'auto_mix', params: { pitch: '{{pitch}}' },
  })
```

`frontend/src/main.ts`が`App.vue`をmountします。Vite single-file pluginでJS/CSSを`dist/frontend/index.html`へinlineしてください。

## Component pattern

`App.vue`はpage shellにし、formと業務処理はcomponentへ分けます。status変更でcontrol sizeが動かないようにし、label、native input/select、disabled/loading state、host通知を使います。

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
const form = reactive({ source_path: '', model_id: '', title: '', pitch: 0 })
const result = ref('')
const { hosted, loading, error, runAction } = usePluginHost()
async function submit() {
  if (!form.source_path || !form.model_id) return
  if (!hosted.value) { result.value = 'Development preview'; return }
  result.value = JSON.stringify(await runAction('create', { ...form }), null, 2)
}
</script>
```

`usePluginHost()`はreactiveな`hosted`、`context`、`loading`、`error`とhost methodを返します。Promise rejectionを処理し、同時actionではshared errorだけに依存しないでください。

## Themeとlayout

iframeからhost DOM/CSS variableは見えません。light/dark tokenを定義し`prefers-color-scheme`へ対応します。responsive grid、bounded width、focus表示、path/resultの`overflow-wrap`を使い、viewport比例fontを避けます。

## 複数viewとlibrary

entryは1つでcenterは通常`pages[0]`だけを開きます。component state、tab、memory routerを使い、server fallbackやbrowser history pathへ依存しません。

PiniaやUI libraryはbundleできますが、すべて2 MB HTML制限へ含まれます。使用component/styleだけをimportします。parent DOM portal、same-origin storage、任意networkを要求するlibraryは失敗する場合があります。

## Plugin resource

read-only fileをpackageへ置き、`host.assetUrl(relativePath)`または`host.assetData(relativePath)`で読みます。pathはplugin内に限定し、単一resourceは10 MBです。`assetUrl()`はData URLを返します。自作object URLだけをrevokeし、Data URLは対象外です。

## Sandbox能力

| 能力 | 状態 |
| --- | --- |
| JavaScript / bundled Vue | Yes |
| Client SDKでhost call | Yes |
| host経由でpackage asset読込 | Yes |
| parent DOM / pywebview API直接接続 | No |
| same-origin cookie/localStorage依存 | No |
| 任意local path | No |
| 任意external siteの安定読込 | No |
| host storageでJSON永続化 | Yes |
| host経由fullscreen | Yes |

third-party playerはopaque origin、CSP/CORS、cookie、frame policy、media制限で失敗しやすいです。専用host playerは`network` permission付き`m3u8.yaohud.cn`だけに使い、それ以外はplugin所有mediaでcontrolを作ります。

## Buildと検証

```powershell
npm run dev
npm run typecheck
npm run build
npm run validate
npm run pack
```

previewはlayoutだけです。XB-SVCBでcontext、action、resource、storage、fullscreen、theme、narrow layout、disabled state、console、plugin/global無効化、実task payloadを確認してください。
