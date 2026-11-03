[简体中文](../../plugins/python.md) | [English](../../en/plugins/python.md) | **日本語**

# Python Plugin開発

## 実行model

専用CPython 3.12 workerで動きます。lifecycle、action、hookごとに新workerを起動し、entryをimportし、1 requestを実行・JSON化して終了します。crashを分離しますがglobal stateを保持せず、権限sandboxでもありません。現在user権限で実行します。

custom pageなしのaction/hookは`python`、Vueから呼ぶ場合は`hybrid`を使います。どちらも`python.execute`を自動宣言します。

## Local環境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e <XB-SVCB-repository>\plugin-sdk\python
```

hostは`xb_svcb_plugin`を提供し、local testだけ明示導入します。desktop appのprivate moduleをimportしないでください。

## 最初のplugin

```powershell
npx @xb-svcb/plugin-sdk create python-plugin --id com.example.python-plugin --name "Python Plugin" --type python
cd python-plugin
npm install
```

```ts
const app = plugin('com.example.python-plugin', 'Python Plugin', '1.0.0')
  .python('plugin.py').permission('filesystem.data')
  .page('home', 'Tools', { fields: [], actions: ['analyse'] })
  .pythonAction('analyse', '解析', 'analyse_values')
```

```python
from typing import Any
from xb_svcb_plugin import ActionResult, Plugin, PluginContext
plugin = Plugin("com.example.python-plugin")

@plugin.action("analyse_values")
def analyse_values(ctx: PluginContext, values: dict[str, Any]) -> ActionResult:
    count = int(ctx.config.get("runs", 0)) + 1
    ctx.config["runs"] = count
    ctx.save_config()
    return ActionResult.message_result(f"実行 {count}")
```

`npm run validate`、`npm run pack`後、実hostへ導入しglobalと個別pluginを有効化します。

## Manifest規則

`runtime`は`python`または`hybrid`、`python.entry`はpackage内の相対`.py`でabsolute/`..`は禁止です。`plugin.py`または`backend/__init__.py`を使えます。pageがaction IDを呼び、manifestの`handler`をPython decorator名と一致させます。permission宣言はOS accessを強制しません。

## 登録とaction

manifest IDと一致する`Plugin()`を1つ作り、instance decoratorを推奨します。

```python
@plugin.action("name")
@plugin.before_create
@plugin.on_enable
@plugin.on_disable
@plugin.hook("custom_name")
```

module-level decoratorもPlugin作成後に利用できます。同名登録は前handlerを上書きするため名前と順序を明確にします。

action signatureは`(ctx, values)`でsync/async対応です。有効returnは`ActionResult.message_result()`、`ActionResult.create_work()`、string、JSON dict、`None`です。`Path`、bytes、set、generator、任意instanceはJSON encodeに失敗します。

## `before_create`

```python
@plugin.before_create
def before_create(ctx: PluginContext, payload: dict) -> dict:
    payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")
    return payload
```

unknown fieldを保持し、idempotentにします。静的manifest patchの後に全有効Python hookが動きます。exceptionはtask作成を失敗させます。UI、HTTP、plugin作成taskすべてが対象です。generic hookはhostが名前をdispatchした場合だけ動きます。

## Lifecycle

`on_enable(ctx)`失敗時は有効化しません。`on_disable(ctx)`は無効化前に実行しますが、cleanupはretry可能にします。毎回別processなのでmigration状態はconfigへ保存し、30秒以内に終え、long-lived daemonを起動しません。

## Context、設定、file

`PluginContext`は`plugin_id`、`plugin_dir`、`data_dir`、mutable `config`、`save_config()`を提供します。

```python
ctx.config["schema_version"] = 2
ctx.save_config()
output = ctx.data_dir / "history.json"
output.write_text('{"ok": true}', encoding="utf-8")
template = ctx.plugin_dir / "assets" / "preset.json"
```

mutable fileは`data_dir`、同梱read-only resourceは`plugin_dir`です。導入codeを変更しません。configは`save_config()`まで永続化されません。同ID置換でdataを保持し、uninstallで削除します。

## Package entryとimport

単一`plugin.py`が最も簡単です。packageではmanifestを`backend/__init__.py`へ向け、`from .rules import normalize`のような相対importを使います。毎回再importするため、高負荷・破壊的なimport side effectを避けます。

## Third-party依存

```text
httpx==0.28.1
```

`requirements.txt`へ固定し、`npm run pack`がPython 3.12で`vendor/`へ導入します。hostは`vendor/`を`sys.path`先頭へ置き、online installしません。`.venv`全体をvendor化せず、license、compiled wheel互換性、20 MB/50 MB制限を確認します。

## Test

業務処理を通常functionへ分け、temporary `PluginContext`でaction/hook/configをtestし、asyncは`asyncio.run()`を使います。unit testではmanifest-handler対応、final package、host interpreter import、timeout、実task validationを確認できないためhost導入testも必要です。

```powershell
python -m py_compile plugin.py
python -m pytest -q
npm run validate
npm run pack
```

## Debug、安全、制限

exceptionはaction/hook失敗として返るためPlugin Centerとapp logを確認します。`print()`はworker outputで、user UIには使いません。純logic、entry import、manifest mapping、導入実行の順で切り分けます。

- worker timeoutは既定30秒。background worker、persistent session、cancel protocolはありません。
- 1 requestごとに新processでglobal/cacheは保持しません。
- workerはsandboxではありません。無関係file/env credentialを避け、subprocess引数を検証し、HTTPSと送信dataを説明します。
- code directoryは置換対象、data directoryはuninstallまで永続です。

よくある問題は、module decorator前の`Plugin(id)`不足、manifest ID不一致、handler mapping不一致、entry/vendor不足、relative import誤り、`save_config()`忘れ、`before_create`のreturn忘れ、timeout、process間global依存です。

## SDK概要

`Plugin`、`PluginContext`、`ActionResult`、instance/module decorator、result normalizationをexportします。signatureはaction `(ctx, values)`、hook `(ctx, payload)`、lifecycle `(ctx)`です。詳細一覧は[API Reference](reference.md)、host受け入れは[テスト](testing.md)を参照してください。
