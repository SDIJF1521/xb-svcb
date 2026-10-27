[简体中文](../../plugins/manifest.md) | [English](../../en/plugins/manifest.md) | **日本語**

# Manifest、Page、Action

`xb-svcb-plugin.json`はhostがpluginを認識するentryです。生成JSONを手動編集せず、`src/plugin.ts`から生成してください。

## 最小manifest

```json
{"id":"com.example.hello","name":"Hello Plugin","version":"1.0.0","description":"","author":"","runtime":"frontend","python":{},"frontend":{},"permissions":[],"pages":[],"actions":[],"workflow":{}}
```

```ts
import { plugin, writeManifest } from '@xb-svcb/plugin-sdk'
const app = plugin('com.example.hello', 'Hello Plugin', '1.0.0')
await writeManifest(app, '.')
```

## Top-level field

| Field | 必須 | 内容 |
| --- | --- | --- |
| `id` | Yes | `^[a-z0-9][a-z0-9._-]{2,63}$`に一致する3-64文字 |
| `name` / `version` | Yes | 表示名80文字 / version 32文字 |
| `description` / `author` | No | 400 / 80文字 |
| `runtime` | Yes | `frontend`、`python`、`hybrid` |
| `python` / `frontend` | Yes | runtime entry設定 |
| `permissions` | Yes | 宣言する能力 |
| `pages` / `actions` | Yes | UI metadataとaction |
| `workflow` | Yes | 静的cover workflow拡張 |

公開後のIDは変更しないでください。Python entryは`..`を含まない相対`.py`、frontend entryは相対`.html`/`.htm`で、通常`dist/frontend/index.html`です。

## Runtime builder

```ts
plugin('com.example.frontend', 'Frontend').frontend('dist/frontend/index.html')
plugin('com.example.python', 'Python').python('plugin.py')
plugin('com.example.hybrid', 'Hybrid').hybrid('plugin.py').frontendEntry('dist/frontend/index.html')
```

`.frontend()`はfrontend runtimeへ変更してPython設定を消します。`.python()`と`.hybrid()`は既定`plugin.py`と`python.execute`を追加します。`.frontendEntry()`はpage entryだけを変更します。

## Pageとfield

```ts
.page('home', 'Quick Cover', {
  description: 'parameterを入力してtaskを作成します。',
  fields: [], actions: ['create'],
})
```

`frontend.entry`がなければhostが`fields`と`actions`を描画し、あればcustom pageを読み込んで宣言formを非表示にします。custom pageは`context.page`を取得でき、`page.actions`に関係なくtop-level actionを呼べます。centerは通常`pages[0]`だけを開くため、複数viewはVue内部のtabまたはmemory routerで実装します。

```ts
import { fields } from '@xb-svcb/plugin-sdk'
const pageFields = [
  fields.text('title', 'タイトル', { default: 'My cover' }),
  fields.textarea('notes', 'メモ', { placeholder: '任意' }),
  fields.number('pitch', 'Pitch', { default: 0 }),
  fields.switch('enhance', '強化', { default: true }),
  fields.select('device', 'Device', [
    { label: '自動', value: 'auto' }, { label: 'CPU', value: 'cpu' },
  ], { default: 'auto' }),
]
```

fieldは`id`、`label`、`type`、任意`default`/`help`を持ち、switch以外は`placeholder`を使えます。selectは空でない`{label,value}`が必要です。TypeScriptがnumber、boolean、option-compatible defaultを検査します。

## Action

```ts
.message('hello', '挨拶', 'こんにちは、{{name}}!')
.createWork('create', 'カバー作成', {
  source_path: '{{source_path}}', model_id: '{{model_id}}',
  title: '{{title}}', workflow: 'auto_mix', params: { pitch: '{{pitch}}' },
})
.pythonAction('analyse', '解析', 'analyse_values')
```

messageは`{type:'message',message}`、create-workは`{type:'create_work',payload}`を返し、hostが実task APIを呼びます。Python actionではpageがaction IDを呼び、handlerは`@plugin.action()`名と一致させます。Python/hybrid runtimeだけで利用できます。

actionには`id`、`label`、`type`があります。IDはplugin ID規則、handlerは最大64文字のPython identifierです。

## Placeholder

明示的`{{fieldId}}`だけを処理します。文字列全体がplaceholderならnumber/boolean型を保持し、他文字と混ざるとstringになります。名前は英字から始まり、英数字とunderscoreだけで最大41文字です。値不足ではplaceholderを残し、object/arrayを再帰処理します。送信前に必須値を検証してください。

## 静的`beforeCreate`

```ts
.beforeCreate({ f0_method: 'rmvpe', pitch: 0, device: 'auto' })
```

user値を上書きせず、不足`params`だけを補います。許可keyは`pitch`、`f0_method`、`index_rate`、`rms_mix`、`uvr_model`、`diffusion_ratio`、`device`、`protect`、`filter_radius`、`rvc_version`、`ddsp_infer_steps`、`ddsp_formant_shift`、`speaker`です。条件処理、request全体、batchにはPython `before_create`を使います。

## PermissionとBuilder API

`python.execute`、`filesystem.plugin`、`filesystem.data`、`network`、`process`、`environment`を宣言できます。Python/hybridは`python.execute`を自動追加します。これは表示・監査用でOS sandboxではありません。

```text
plugin(id, name, version?) -> PluginBuilder
.description() .author() .frontend() .frontendEntry() .python() .hybrid()
.permission() .page() .action() .message() .createWork() .pythonAction()
.beforeCreate() .build()
```

独立factoryは`page`、`messageAction`、`createWorkAction`、`pythonAction`です。`.build()`は検証なしのdeep JSON copy、`writeManifest()`は検証、directory作成、書込を行い絶対pathを返します。

## 検証範囲

SDKはmetadata、ID、enum、field/action type、path形式、`python.execute`、select option、handler形式、静的patch allowlistを検査します。file存在、Python import、handler登録、重複ID、page action参照、frontend実行、package size、host業務条件は検査しません。実hostでbuild、package、導入してください。

`.hybrid()`後に`.frontend()`を使わず`.frontendEntry()`を使います。空pageも`{fields: []}`を渡します。`.`や`-`を含むfield IDはplaceholder名にできません。
