[简体中文](../plugin-development.md) | [English](../en/plugin-development.md) | **日本語**

# XB-SVCB Plugin開発Guide

単一page互換guideです。保守する日本語資料は、API詳細、security境界、exampleを重複せず更新できるよう章ごとに分割しています。

## 読む順序

1. [Plugin概要](plugins/README.md)でruntime modelと制限。
2. [Quick Start](plugins/getting-started.md)で最初のpluginを作成・導入。
3. runtimeに応じて[Vue page](plugins/frontend-vue.md)または[Python plugin](plugins/python.md)。
4. [Manifest](plugins/manifest.md)、[Client API](plugins/client-api.md)、[Hybrid](plugins/hybrid.md)で統合。
5. 公開前に[テスト](plugins/testing.md)、[公開](plugins/publishing.md)、[API Reference](plugins/reference.md)。

## Plugin model

```text
src/plugin.ts -> xb-svcb-plugin.json -> host metadata、page、action、permission
frontend/     -> dist/frontend/index.html -> sandbox iframe
plugin.py     -> fresh Python 3.12 worker -> action/hook/lifecycle result
```

Pythonなしの宣言/custom pageは`frontend`、action/hookは`python`、custom pageからPythonを呼ぶ場合は`hybrid`です。新規導入は無効です。pageは`sandbox="allow-scripts"`、Pythonは現在user権限で動きsecurity sandboxではありません。

## 作成とbuild

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

TypeScript Vueを推奨し、Vanilla TypeScriptとno-build JavaScriptも利用できます。Python/hybridにはPython 3.12.xが必要です。

公開後のmanifest IDは固定です。`src/plugin.ts`からmanifestを生成し、`xb-svcb-plugin.json`や`dist/`を手動保守しません。

## 最小Hybrid example

```ts
const app = plugin('com.example.my-plugin', 'My Plugin', '1.0.0')
  .hybrid('plugin.py')
  .frontendEntry('dist/frontend/index.html')
  .page('home', 'Home', { fields: [], actions: ['create'] })
  .pythonAction('create', 'カバー作成', 'create_cover')
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

manifest action ID、Python handler、decorator登録名を正しく対応させます。`.hybrid().frontendEntry()`を使い、`.hybrid().frontend()`は使いません。

## Data、hook、依存

通常JSON preferenceはpage host storageを使います。Pythonは同梱resourceを`ctx.plugin_dir`、mutable fileを`ctx.data_dir`で扱い、`ctx.config`変更後に`ctx.save_config()`を呼びます。

静的`.beforeCreate()`は不足する推論defaultを補い、Python `before_create`は条件・全payloadを扱います。unknown fieldを保持しidempotentにし、UI、HTTP、plugin作成taskすべてへ適用されることを考慮します。

非standard Python 3.12依存は`requirements.txt`へ固定し、package時に`vendor/`へ入れます。hostはonline installしません。licenseとcompiled wheelを監査します。

## Securityと制限

- package 20 MB / 展開50 MB、manifest 512 KB、HTML 2 MB、asset 10 MB。
- page/Python callは既定30秒。cancelとpersistent workerはありません。
- permissionは宣言でOS enforcementではありません。
- pageはparent DOM、内部Bridge、任意local path、same-origin storageへ依存できません。
- PythonはOSが許すuser resourceへ接続できます。信頼できるsourceだけを有効化します。
- MarketplaceはGitHub HTTPS限定で、署名、hash強制、互換性・依存解決、自動更新はありません。

## 受け入れと問題調査

validateだけではentry、Python import、handler、size、task規則を保証しません。archiveを確認し、実hostへ導入し、両switchを有効化し、全action/errorと短い実taskを確認します。同ID置換時のdata保持とuninstall削除もtestします。

失敗時はmanifest/runtime/ID、entry path、final package、handler mapping、Python 3.12 importと`vendor/`、JSON return、`save_config()`、hook return、timeout、Plugin Center、app logを順に確認します。実行例は[テストとdebug](plugins/testing.md)を参照してください。
