[简体中文](../../plugins/publishing.md) | [English](../../en/plugins/publishing.md) | **日本語**

# Package、公開、Marketplace

pluginは`.xbplugin` ZIPとして配布します。MarketplaceはGitHub release assetをdownloadするJSON indexだけです。署名、hash、互換性・依存解決、version比較、自動更新、有効化後rollbackはありません。

## Package作成

```powershell
npm install
npm run pack
```

scaffoldはtypecheck -> frontend build -> manifest build -> validate -> ZIPを実行します。直接`xb-plugin pack . .\release\my-plugin-1.0.0.xbplugin`を呼ぶ場合、Vite、`tsx`、typecheckは先に動きません。

archiveにはmanifestと参照する`dist/frontend/index.html`、`plugin.py`、任意`vendor/`が必要です。source、test、READMEはruntimeに不要ですが、除外されなければ含まれます。

自動除外は`node_modules/`、`.git/`、`.venv/`、`__pycache__/`、`.pytest_cache/`、`*.xbplugin`です。`tests/`、`.env`、source map、lockfile、画像、`vendor/`、custom cacheは除外されません。`.xbpluginignore`はないため、secret、private audio、log、旧packageを手動確認します。

## Host制限

| 対象 | 上限 |
| --- | --- |
| 圧縮`.xbplugin` | 20 MB |
| 展開宣言size | 50 MB |
| Manifest | 512 KB |
| Entry HTML | 2 MB |
| 単一`assetData()` / `assetUrl()` | 10 MB |
| Python worker call | 30秒 |
| Page request | 既定30秒 |

SDKはpack前に全sizeを検査しません。大型UI libraryも2 MB HTMLへ含まれます。画像・音声はpackage resourceとして`assetUrl()`で読み、model、dataset、大型audioは配布しないでください。

## ManifestとPython依存

`npm run validate`を実行し、安定ID、version更新、正しいruntime、最小permission、build済みfrontend entry、相対Python entry、page action、Python handlerを確認します。hostはversionをstring表示するだけでSemVer比較しません。

Python 3.12 hostが保証するのはstandard libraryと`xb_svcb_plugin`だけです。他は`requirements.txt`へ固定し、`npm run pack`でvendor化します。hostはonline `pip install`を行いません。伝達licenseを監査し、`.venv`全体をcopyせず、size制限を守ります。

## GitHub Release

公開repositoryを使い、READMEへscreenshot、ID/version/runtime、手動検証したXB-SVCB version、各permission理由、現在user権限でのPython実行、network/file/process、設定data、依存license、導入・更新・削除、uninstall時の`plugin-data/<id>`削除、既知制限を記載します。

1. version更新、clean dependency、validate、全test。
2. final archiveを実hostへ導入。
3. 同version tagとReleaseを作り、version付きassetをupload。
4. Releaseからdownloadして再導入。
5. 最後に`market.json`更新。同URL内容を黙って置換せず旧releaseを残します。

## Marketplace index

```json
{
  "plugins": [{
    "id": "com.example.hybrid-cover",
    "name": "Hybrid Cover Assistant",
    "version": "1.0.0",
    "description": "Vueで入力しPythonでtaskを作成します。",
    "author": "Your Name",
    "bundle_url": "https://github.com/OWNER/REPO/releases/download/v1.0.0/hybrid-cover-1.0.0.xbplugin"
  }]
}
```

`id`と`bundle_url`は必須で、不正recordはskipします。他fieldは表示用でunknown fieldは無視されます。download packageのmanifestが正式値で、indexのID/name/versionとのcross-checkはありません。

`https://raw.githubusercontent.com/OWNER/REPO/main/market.json`のような公開URLを使います。開始・redirect後URLはHTTPSの`github.com`、`api.github.com`、そのsubdomain、`githubusercontent.com`、そのsubdomainに限定します。index timeoutは20秒、bundleは30秒です。GitHub credentialを送らないためprivate repositoryは非対応です。

## 現在ない機能

- GPG、Sigstore、attestation、publisher identity検証。
- hostが認識する`sha256`。Release checksumは手動確認だけです。
- `min_app_version`、`max_app_version`、SDK/schema交渉、非互換install阻止。
- version比較、update badge、background download、自動更新。
- npm、Python、system tool、plugin間依存の導入。
- file/entry検証中の置換失敗は旧codeを復元しますが、有効化後のerrorは新releaseが必要です。

同一ID導入はcodeを置換し、pluginを無効化し、`plugin-data/<id>`を保持します。version比較と自動data移行はありません。idempotent migrationを`on_enable`で行い、完了を`ctx.config`へ保存し、破壊的変更前にbackupしてください。uninstallはcodeとdataを削除します。

## Securityとrelease gate

Pythonは現在user権限で動きます。必要permissionだけを説明付きで宣言し、無関係file/credentialを読まず、実行fileを黙ってdownloadせず、secretをsource/package/indexへ入れず、送信dataを説明し、外部process引数を検証し、`vendor/`とlicenseを監査し、sourceを公開してください。

公開前にclean build/test、browserとhost UI、Python成功/error、fresh installと同ID置換、manifest 1件、entry存在、cache/secretなし、size、third-party license、tag/release/manifest/index version、Release URL導入、未実装security/update機能の明記を確認します。[テスト](testing.md)も参照してください。
