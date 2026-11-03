[简体中文](../api-management.md) | [English](../en/api-management.md) | **日本語**

# XB-SVCB API管理とビルド資産の変更

> 0.0.32のcommit `5616756`に関する実装記録です。現在の利用方法は[FastAPI連携](api.md)を参照してください。

## 対象範囲

ドメイン結合と複数API Key管理の実装を記録します。検証結果は当時のcommitだけを対象とし、現在のリリース受け入れ結果ではありません。

## 変更内容

### APIサービス設定

- 既定portを`8765`から`8760`へ変更しました。
- ローカルモードは`127.0.0.1`、LANモードは`0.0.0.0`で待ち受け、LANではドメインを結合できます。
- ドメインはLANモードだけで利用でき、ローカルへ戻すと消去します。
- ドメインを正規化・検証し、Swagger、ReDoc、状態表示は結合ドメインURLを優先します。

### API Key管理

- 単一Keyを名前付きKey一覧へ拡張しました。
- 自動生成、有効期限、有効/無効、編集、削除に対応します。
- 生成Keyは`XB-SVCB-`接頭辞を使います。
- ボタンまたはKey文字列でコピーし、平文表示を切り替えられます。
- 有効かつ期限内のKeyだけを認証し、最低1件を残します。
- サービス実行中はKeyを変更できません。旧単一Keyは既定Keyへ移行します。

### フロントエンド構成

- Keyをresponsive cardで表示し、広い画面は複数列、狭い画面は1列です。
- ドメイン入力は内容に合わせ最大幅まで伸縮し、ローカルモードでは説明付きで無効になります。

## 変更パス

### バックエンド

`app/api/http_server.py`に`DEFAULT_HTTP_PORT = 8760`、`API_KEY_PREFIX = "XB-SVCB-"`、複数Key recordとCRUD、旧設定移行、有効・期限判定、ドメイン検証と正規化、ドメイン状態URL、実行中変更保護を追加しました。

`app/api/bridge.py`の追加メソッド:

- `list_http_api_keys`
- `create_http_api_key`
- `update_http_api_key`
- `delete_http_api_key`

### フロントエンドAPIと型

`web/src/api/types.ts`に`HttpApiKey`、`HttpApiKeyResult`を追加し、`HttpApiStatus`へ`domain`、`domain_url`、`api_keys`、設定・起動引数へ`scope`、`port`、`domain`を追加しました。

`web/src/api/index.ts`はドメイン設定を渡し、`listHttpApiKeys`、`createHttpApiKey`、`updateHttpApiKey`、`deleteHttpApiKey`を公開します。

`web/src/api/mock.ts`はport `8760`、ドメインURL、複数Key CRUD、有効・期限判定、`XB-SVCB-`接頭辞を再現します。

### API画面

`web/src/views/api/api.vue`にドメイン設定と状態、ローカル時の入力無効化、responsive幅、独立API Key領域、作成・編集・有効化・無効化・削除・コピー・表示切替、長いKeyの省略、responsive card、実行状態による操作保護を追加しました。

`web/src/types/components.d.ts`と`web/src/types/auto-imports.d.ts`は自動生成宣言で、API Keyの業務処理は含みません。

## 当時の検証記録

バックエンド構文・単体テスト:

```powershell
$python = (Resolve-Path '.venv-svc\Scripts\python.exe').Path
& $python -m py_compile app/api/http_server.py app/api/bridge.py
& $python -m unittest app.tests.test_http_api -q
```

記録結果は`Ran 15 tests in 3.269s`、`OK`で、Starlette/httpxのdeprecated warningだけでした。

フロントエンド:

```powershell
Set-Location web
npm.cmd run type-check
npm.cmd run build
```

当時はいずれも成功しました。

## `test.juzidc.cn:8760`手動確認

1. LANモードで`test.juzidc.cn`を結合し、port `8760`を設定してAPIを開始します。
2. DNS A recordをXB-SVCB hostへ向け、Windows FirewallでTCP `8760` inboundを許可します。
3. DNSと接続を確認します。

```powershell
Resolve-DnsName test.juzidc.cn
Test-NetConnection test.juzidc.cn -Port 8760
```

4. 有効かつ期限内のKeyで呼び出します。

```powershell
curl.exe -H "X-API-Key: XB-SVCB-..." http://test.juzidc.cn:8760/api/v1/models
```

5. `http://test.juzidc.cn:8760/docs`と`http://test.juzidc.cn:8760/redoc`を確認します。

DNS解決後もportへ接続できない場合は、サービス状態、Windows Firewall、router port forwarding、解決先hostを確認してください。コードとローカル検査だけでは公開ドメイン接続を保証しません。
