[简体中文](../development.md) | [English](../en/development.md) | **日本語**

# 開発とリリース

## 推奨ワークフロー

    ソース環境を構築
      -> app / webを変更
      -> Pythonとフロントエンドのテスト
      -> web/distをビルド
      -> デスクトップアプリでBridgeを検証
      -> FastAPI、モデル、Workerを検証
      -> 必要に応じてJUCE Hostをビルド
      -> リリース検証
      -> Inno Setupインストーラーをビルド

## バックエンド開発

メインアプリの依存関係は`app/pyproject.toml`、実行エントリは`app/main.py`です。`app/api/bridge.py`と`app/application/`から処理を追い、具体的なエンジンとWorkerは`app/infrastructure/`を確認してください。

テスト:

    cd app
    uv run pytest

モデルサービス、推論回帰、デバイス検出、HTTP API、リアルタイム変換、エディター、プラグイン、インストーラーランタイムが重要な範囲です。

## フロントエンド開発

    cd web
    npm install
    npm run dev
    npm run type-check
    npm run build
    npm run test:unit -- --run

成果物は`web/dist`へ出力され、本番デスクトップアプリが内蔵リソースとして読み込みます。

## JUCE VST3 Host

JUCEのパスを設定してビルドします。

    $env:XB_JUCE_DIR="C:\path\to\JUCE"
    .\native\juce-vst3-host\build.ps1

成果物は`engines/juce-vst3-host/xb-juce-vst3-host.exe`です。制限とプラグイン互換性はインストーラー資料を参照してください。

## インストーラーのビルド

`-Help`または`--help`では事前検証やパッケージ作成を実行せずに引数を確認できます。

簡易検証:

    .\installer\build.ps1 -ValidateOnly

既定のCUDA128共有ランタイムパッケージ:

    .\installer\build.ps1

CPU、ROCm 10、DirectML、CUDA126、CUDA128を順番に作成:

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe

CUDA共有core資産をGit外に保存している場合:

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe -RuntimeAssets D:\XB-SVCB\assets\runtime\core-cu128

ビルド処理:

1. アプリ、フロントエンド、バージョン、主要ランタイム資産を検証します。
2. Vueフロントエンドを一度ビルドし、5パッケージで再利用します。
3. PyInstallerでデスクトップアプリと内蔵資産を一度作成し、再利用します。
4. JUCE VST3 Hostを作成または再利用します。
5. 対象スタック用のオフラインwheelhouseを選別し、CUDA candidate/compat資産とランタイム内容を検証します。
6. Inno Setupでハードウェア別EXEと2 GB未満の同名`.bin`分割ファイルを生成します。

リリース時はEXEとすべてのBINをアップロードしてください。ランタイム一覧と分割規則は`installer/README.md`を参照してください。

## ドキュメント保守規約

- ルートREADMEは概要、クイックスタート、文書リンクだけにします。
- API詳細は`docs/api.md`と各翻訳だけで管理します。
- プラグイン資料は`docs/plugins/`を優先し、旧単一ファイルは互換性と全文検索用に残します。
- アーキテクチャ元データは`docs/archify/*.json`、HTMLは閲覧用成果物です。
- バージョン情報は`docs/release-notes/release_notes_vXYZ.md`に置き、READMEは現行版だけをリンクします。
- 起動処理、ディレクトリ、環境名、API契約を変更したら対応文書も更新します。
