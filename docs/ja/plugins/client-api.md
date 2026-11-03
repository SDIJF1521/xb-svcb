[简体中文](../../plugins/client-api.md) | [English](../../en/plugins/client-api.md) | **日本語**

# Page Client API

custom pageはdesktop Bridgeを直接呼べません。host能力は`postMessage`で公開され、npm clientがtoken、request ID、response対応、timeoutを管理します。

## Importとhost判定

```ts
import { host, isHosted, request, type PluginHostContext,
  type HostMessageResult, type CreateWorkPayload } from '@xb-svcb/plugin-sdk/client'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

no-build JavaScriptは`window.XBSVCB`を使えますが、型と30秒timeoutがありません。`isHosted()`はhost token受信後だけtrueです。`window.parent`で推測しないでください。

全methodはPromiseで、host失敗時はrejectします。既定timeoutは30秒です。低level `request(method,payload,{timeoutMs})`で変更でき、0以下は無制限です。cancel/AbortSignalはなく、未定義methodは拒否され、iframe終了時のpending callは結果を受けません。通常は`host.*`を使います。

## Contextとaction

```ts
const context = await host.getContext()
const result = await host.runAction('create', { title: 'Page cover', pitch: 0 })
```

contextは`plugin`、任意`page`、任意`theme`を返します。centerは通常`pages[0]`、themeは`cyber`、`anime`、`custom`などのsnapshot IDでCSS variableや変更eventではありません。

`runAction()`結果は`ok`、`type`、`message`、`payload`、`work`、`error`を持ち得ます。messageは補間と通知、create-workは補間・task作成・通知・`work`返却、Pythonはworkerを実行します。成功後の通知は重複させず、rejectをcatchしてください。custom pageは全top-level actionを呼べ、`page.actions`は宣言buttonだけを制御します。

## 直接作品を作成

```ts
const work = await host.createWork({
  source_path: 'D:/Music/song.wav', model_id: 'model_xxx',
  title: 'Direct cover', workflow: 'auto_mix',
  params: { pitch: 0, f0_method: 'rmvpe' },
})
```

manifest templateを使いませんが、全有効pluginの`before_create`を通り、自動通知します。

`CreateWorkPayload`は`title`、`model_id`、nullable `source_path`、`params`、`workflow`、任意`vocal_enhancement`、`mode`、`models`、`segments`を持ちます。workflowは`auto_mix`、`auto_then_editor`、`full_manual_editor`、multi専用`auto_vocal_merge` / `manual_vocal_merge`です。

推論fieldは`pitch`、`f0_method`、`index_rate`、`rms_mix`、`uvr_model`、`diffusion_ratio`、`device`、`protect`、`filter_radius`、`rvc_version`、`reference_audio`、`ddsp_infer_steps`、`ddsp_formant_shift`、`speaker`です。modelに不適切な組合せは拒否されます。

美声objectには`enabled`、`level`、`pitch_correction`、`timing_alignment`、`timbre_focus`、`ai_eq`、`ai_compressor`、`ai_exciter`、`stereo_width`、`loudness_envelope`をすべて指定し、強度は0-1です。

```ts
const payload: CreateWorkPayload = {
  source_path: 'D:/Music/song.wav', title: 'Ensemble', mode: 'multi',
  workflow: 'auto_vocal_merge',
  models: [
    { model_id: 'model_a', params: { pitch: 0 } },
    { model_id: 'model_b', params: { pitch: 2 } },
  ],
  segments: [
    { start: 0, end: 12.5, model_id: 'model_a' },
    { start: 12.5, end: 24, model_id: 'model_a', model_ids: ['model_a', 'model_b'] },
  ],
}
```

複数`model_ids`は合唱です。`model_id`も必要で通常は先頭です。範囲とIDを検証してください。`CreatedWork`の安定fieldは`id`と`title`、任意fieldは`model_id`、`source_path`、`status`、`progress`です。

## Resourceと通知

```ts
const url = await host.assetUrl('assets/cover.png')
const asset = await host.assetData('assets/presets.json')
await host.notify('設定を保存しました', 'success')
```

asset pathは相対で、absolute/`..`は禁止、10 MB上限です。`assetData()`は`{ok,name,mime,data,error?}`を返し、`data`はBase64 Data URLです。`plugin-data`は読めず、失敗はrejectします。通知typeは`success`、`warning`、`info`、`error`です。

## Page storage

```ts
const prefs = await host.getStorage('preferences', { source: 1 })
await host.setStorage('preferences', { source: 3 })
await host.removeStorage('preferences')
```

keyは1-80文字の英数字、dot、underscore、hyphenです。valueはJSON serialize可能で`undefined`は禁止です。plugin IDで分離し、不足・破損時はfallbackを返します。同ID再導入で保持し、ID変更で別namespaceになります。暗号化storageではないため高価値credentialを避けます。

## Fullscreenとhost player

`togglePluginFullscreen(enabled?)`はpluginをhost workspace全体へ広げ、`{ok:true,fullscreen}`を返します。host button/Escapeで終了し、変更は`xb-svcb-host-event`の`pluginFullscreenChanged`で通知されます。`toggleWindowFullscreen()`はアプリwindow全体を独立制御するため、通常formで自動実行しないでください。

`openYaohuPlayer(url)`は`network` permissionが必要で、hostnameが厳密に`m3u8.yaohud.cn`のHTTP(S)だけを受け付け、HTTPをHTTPSへ上げます。host管理overlayで動き、pluginはDOM、進捗、responseを読めません。一般URL/M3U8 APIではありません。旧hostのreject時はupgrade案内を表示します。

## Vue `usePluginHost()`

`hosted`、`context`、`plugin`、`page`、`theme`、`loading`、`error`と、context/action/work/asset/notify/storage/fullscreen/player wrapper、`clearError`を返します。

`{loadContext:false}`でなければmount時にcontextを読みます。browser previewでは`undefined`です。各操作はerrorをclearし、失敗を書いて再throwし、並行loading countを管理します。componentごとにstateが別なので、大型pageではshared composableまたはprovide/injectを使います。既定timeoutとVue 3.5互換が必要です。

## 未提供API

model/work一覧、task poll、file picker、host route、plugin-data直接access、theme change subscription、cancel、任意external player、custom RPCはありません。通常設定はhost storage、filesystem/system処理はhybrid Python actionを使い、内部Bridgeへ接続せず正式Client契約を拡張してください。
