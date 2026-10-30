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

v0.1.0の履歴はcommit `fc8d214e068457a273929e80c108b33f55b4e9e8`から始まり、このcommit自体もv0.1.0に含まれます。release commit一覧は次の範囲で生成します。

    git log --reverse fc8d214e068457a273929e80c108b33f55b4e9e8^..HEAD

監査でも同じ包括範囲を使用してください。`fc8d214e068457a273929e80c108b33f55b4e9e8..HEAD`では開始commitが除外されるため使用しません。

簡易検証:

    .\installer\build.ps1 -ValidateOnly

既定のCUDA128共有ランタイムパッケージ:

    .\installer\build.ps1

CPU、ROCm 10、DirectML、CUDA126、CUDA128を順番に作成:

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe

package作成前に各stackの共有groupと必須component groupを検査し、不足stackだけを自動準備します。完成済みcacheは再downloadしません。

初回ビルド、依存関係の変更後、またはダウンロード中断後は、5スタックのwheelhouseを増分で補完します。

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe -RebuildWheelhouse

`-RebuildWheelhouse`は既存wheelを再利用します。`-CleanWheelhouse`はcache破損を確認した場合だけ追加してください。全スタックを削除して最初からdownloadします。CPUとROCmが完了し、後続stackだけ不足する場合:

    C:\path\to\python.exe .\install\prepare_wheelhouse.py --root . --stack directml --stack cu126 --stack cu128

CPUのSVC/RVC groupはROCmより前に準備され、ROCm component groupは共有ROCm wheelを再利用します。`ResolutionImpossible`より前に`ProxyError`またはTLS handshake timeoutがある場合、完了済みcacheを削除せず、proxyとpackage sourceを確認してください。正確な再開commandはinstaller資料を参照してください。

CUDA共有core資産をGit外に保存している場合:

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe -RuntimeAssets D:\XB-SVCB\assets\runtime\core-cu128

ビルド処理:

1. アプリ、フロントエンド、バージョン、主要ランタイム資産を検証します。
2. Vueフロントエンドを一度ビルドし、5パッケージで再利用します。
3. PyInstallerでデスクトップアプリと内蔵資産を一度作成し、再利用します。
4. JUCE VST3 Hostを作成または再利用します。
5. 対象スタック用のオフラインwheelhouseを選別し、CUDA candidate/compat資産とランタイム内容を検証します。

`assets/wheels/wheelhouse.json` には各スタックの依存計画署名、wheelのパス、サイズを含む完了プロファイルが保存されます。パッケージ化前に全ファイルを検証するため、古いマニフェストや中断したダウンロードは小さいインストーラーとして出力されず拒否されます。`-SkipWheelhouse` で回避しないでください。単一スタックの確認:

    C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py --root . --check --stack directml
6. Inno Setupでハードウェア別EXEと2 GB未満の同名`.bin`分割ファイルを生成します。

リリース時はEXEとすべてのBINをアップロードしてください。ランタイム一覧と分割規則は`installer/README.md`を参照してください。

## ドキュメント保守規約

- ルートREADMEは概要、クイックスタート、文書リンクだけにします。
- API詳細は`docs/api.md`と各翻訳だけで管理します。
- プラグイン資料は`docs/plugins/`を優先し、旧単一ファイルは互換性と全文検索用に残します。
- アーキテクチャ元データは`docs/archify/*.json`、HTMLは閲覧用成果物です。
- バージョン情報は`docs/release-notes/`に置き、READMEは現行版だけをリンクします。v0.1.0以降は、簡体字中国語の主ファイル、`.en.md`、`.ja.md`の同内容リリースノートを各版で同時に保守します。
- 起動処理、ディレクトリ、環境名、API契約を変更したら対応文書も更新します。
