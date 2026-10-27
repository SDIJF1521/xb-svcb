[简体中文](../../plugins/README.md) | [English](../../en/plugins/README.md) | **日本語**

# XB-SVCBプラグイン開発

メインプロジェクトのソースを読まなくても、manifest SDK、ページClient、Vue composable、Python SDK、package形式、導入動作、実行制限を確認できます。

## 読み方

| 目的 | 順序 | 成果物 |
| --- | --- | --- |
| 初めてのplugin | [Quick Start](getting-started.md) -> [Vueページ](frontend-vue.md) | 導入可能なVue plugin |
| カバー設定tool | [Quick Start](getting-started.md) -> [Manifest](manifest.md) | 宣言formまたはtask action |
| Python実行 | [Python plugin](python.md) -> [テスト](testing.md) | Python action / workflow hook |
| VueからPython | [Hybrid plugin](hybrid.md) -> [Client API](client-api.md) | Vue + Python plugin |
| 公開 | [PackageとMarketplace](publishing.md) | GitHub Releaseと`market.json` |

fieldや関数は[API Reference](reference.md)、導入・有効化・action失敗は[テストとdebug](testing.md)を参照してください。[単一ファイルguide](../plugin-development.md)も全文検索用に残しています。

## 開発フロー

```text
scaffold作成 -> manifest/page/backend編集 -> npm install -> npm run dev
-> npm run typecheck -> npm run validate -> npm run pack
-> .xbplugin導入 -> global plugin有効化 -> plugin有効化
-> page、action、実taskを検証
```

validateはlocal sourceとmanifestを検査します。実導入でpackage内容、entry、host通信、Python runtime、業務parameterを確認してください。

## 構成

```text
src/plugin.ts ---------------------> xb-svcb-plugin.json
frontend/src/App.vue + components -> dist/frontend/index.html
plugin.py / Python package -------> 分離Python worker
```

| Runtime | Page | Python | 用途 |
| --- | --- | --- | --- |
| `frontend` | 任意 | なし | Vue tool、宣言form、message、task作成 |
| `python` | 任意 | あり | hook、parameter処理、設定 |
| `hybrid` | 任意 | あり | VueからPython actionを呼出 |

codeは`<plugins>/<plugin-id>/`へ導入されます。永続Python dataはcode directoryではなく`ctx.data_dir`へ置きます。ページは`host.getStorage()`、`host.setStorage()`、`host.removeStorage()`でplugin単位のJSONを保存します。

## TypeScript entry

```ts
import { plugin, fields, writeManifest } from '@xb-svcb/plugin-sdk'
import { host, isHosted } from '@xb-svcb/plugin-sdk/client'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

1つ目は開発機でmanifestを生成し、2つ目はplugin page内、3つ目はVue向けreactive wrapperです。

## セキュリティと制限

- 新規pluginは無効です。globalと個別switchの両方が必要です。
- pageは`sandbox="allow-scripts"` opaque-origin iframeで動き、host DOMへ接続できません。
- host callはmessage token、request ID、既定30秒timeoutを使います。
- Python workerはcrashを分離しますが権限sandboxではありません。現在user権限で動き、action/hook/lifecycleごとに新workerで再importします。
- permissionは監査・表示用でOS access controlではありません。信頼できるPython/hybridだけを有効化してください。
- package 20 MB、展開宣言50 MB、manifest 512 KB、entry HTML 2 MB、単一asset 10 MBです。
- `frontend.entry`は1つです。複数viewはVue内部へ置き、centerは通常`pages[0]`だけを開きます。
- Marketplaceは許可されたGitHub HTTPS URLだけを利用します。
- host playerは`network` permission付き`m3u8.yaohud.cn`だけを扱い、任意web videoには対応しません。

`page.actions`は宣言pageのbuttonだけを制御し、custom pageのtop-level action呼出を制限しません。`before_create`はpluginが作ったtaskを含む全taskへ適用されます。同一ID再導入ではcodeを置換してpluginを無効化し、data directoryを保持します。
