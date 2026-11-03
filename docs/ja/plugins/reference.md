[简体中文](../../plugins/reference.md) | [English](../../en/plugins/reference.md) | **日本語**

# Plugin API Quick Reference

## Entry point

```ts
import { plugin, fields, page, messageAction, createWorkAction,
  pythonAction, validateManifest, writeManifest } from '@xb-svcb/plugin-sdk'
import { host, isHosted, request } from '@xb-svcb/plugin-sdk/client'
import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'
```

```python
from xb_svcb_plugin import Plugin, PluginContext, ActionResult
```

## CLI

```text
xb-plugin create <dir> --id ID --name NAME
  [--type frontend|python|hybrid] [--language ts|js]
  [--framework vue|vanilla] [--version VERSION] [--author AUTHOR]
xb-plugin validate [dir]
xb-plugin pack [dir] [output.xbplugin]
```

VueはTypeScript必須です。CLI `pack`単体はfrontend/manifestをbuildせず、scaffoldの`npm run pack`が実行します。

## Manifest

必須top-level: `id`、`name`、`version`、`runtime`、`python`、`frontend`、`permissions`、`pages`、`actions`、`workflow`。任意textは`description`、`author`です。

IDは`^[a-z0-9][a-z0-9._-]{2,63}$`。runtimeは`frontend | python | hybrid`。permissionは`python.execute`、`filesystem.plugin`、`filesystem.data`、`network`、`process`、`environment`です。

```text
plugin(id, name, version?) -> PluginBuilder
.description() .author() .frontend() .frontendEntry() .python() .hybrid()
.permission() .page() .action() .message() .createWork() .pythonAction()
.beforeCreate() .build()
```

fieldは`fields.text`、`textarea`、`number`、`switch`、`select`。共通memberは`id`、`label`、`type`、`default`、switch以外の`placeholder`、`help`。selectは空でない`{label,value}`が必要です。

action typeは`message`、`create_work`、`python`で、共通`id`、`label`、`type`、Pythonには`handler`があります。`page.actions`は宣言buttonだけでcustom page permissionではありません。

補間は`{{name}}`だけで、英字開始・英数字/underscoreです。値全体ならprimitive型を保持します。静的`beforeCreate`は不足推論parameterだけを補い、条件・全payloadはPython hookで処理します。

## Page Client

```text
isHosted() / request<T>()
host.getContext() / runAction() / createWork()
host.assetData() / assetUrl() / notify()
host.getStorage() / setStorage() / removeStorage()
host.togglePluginFullscreen() / toggleWindowFullscreen()
host.openYaohuPlayer()
```

失敗はrejectし、既定30秒です。assetは相対pathで10 MB、storage keyは1-80文字の`[A-Za-z0-9._-]`、valueはJSONです。Yaohu playerは`network`と厳密な`m3u8.yaohud.cn` hostnameが必要です。

`PluginHostContext`は`plugin`、任意`page`、任意theme ID。`HostMessageResult`は任意`ok`、`type`、`message`、`payload`、`work`、`error`。`CreatedWork`の保証fieldは`id`と`title`です。

`CreateWorkPayload`は`title`、`model_id`、`source_path`、`params`、`workflow`、`vocal_enhancement`、`mode`、`models`、`segments`。workflowは`auto_mix`、`auto_then_editor`、`full_manual_editor`、multi専用`auto_vocal_merge`、`manual_vocal_merge`です。

`usePluginHost()`は`hosted`、`context`、`plugin`、`page`、`theme`、`loading`、`error` ref、全host wrapper、`clearError`を返します。`{loadContext:false}`以外はmount時に読込し、error更新後もrethrowします。

## Python SDK

```python
plugin = Plugin("com.example.plugin")
@plugin.action("handler")       # (ctx, values)
@plugin.before_create           # (ctx, payload) -> payload
@plugin.on_enable               # (ctx)
@plugin.on_disable              # (ctx)
@plugin.hook("name")            # (ctx, payload)
```

sync/async対応です。returnはJSON serialize可能な`ActionResult`、`dict`、`str`、`None`です。標準factoryは`message_result()`と`create_work()`です。

`PluginContext`は`plugin_id`、`plugin_dir`、`data_dir`、`config`、`save_config()`。mutable dataは`data_dir`、package resourceは`plugin_dir`です。

lifecycle/action/hookごとにfresh workerで再importし、既定timeoutは30秒、globalは保持しません。crashを分離しますがsecurity sandboxではありません。

## Lifecycleと導入

新規導入は無効です。同ID導入はcode置換、enabled reset、data/storage保持です。uninstallはcodeとdataを削除します。上限は圧縮20 MB、展開50 MB、manifest 512 KB、HTML 2 MB、asset 10 MBです。

Marketplaceはvalid `id`と許可GitHub HTTPS `bundle_url`が必要です。署名、hash強制、互換性・依存解決、version比較、自動update、一般rollbackはありません。

## よくある失敗

- runtime誤り、`.hybrid()`後の`.frontend()`。
- build entry不足、handler不一致、不正相対path、vendor依存不足。
- manifest validationがfile/runtimeも確認すると誤解。
- non-JSON return、`save_config()`やhook return忘れ。
- persistent global、same-origin iframe、任意network/player、未提供RPCへの依存。
- timeout/size超過、secret混入。

最低release gateはtypecheck、unit test、build、manifest検証、package確認、fresh host install、同ID更新、page/action/hook/error、実task 1件です。詳細は[Manifest](manifest.md)、[Client API](client-api.md)、[Python](python.md)、[テスト](testing.md)、[公開](publishing.md)。
