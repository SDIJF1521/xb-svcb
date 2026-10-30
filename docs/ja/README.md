[简体中文](../README.md) | [English](../en/README.md) | **日本語**

# XB-SVCB ドキュメント

利用者、開発者、プラグイン作者向けの資料をまとめています。プロジェクトの日本語概要は[ルートREADME](../../README.ja.md)を参照してください。

`docs/`配下の現行Markdownには日本語版があります。v0.0.32以前のリリースノートは中国語のみですが、v0.1.0以降は英語版と日本語版も提供します。`docs/`外のpackage資料は、中国語のままの場合に明記しています。

## 利用者向け

- [インストール、ソース実行、トラブルシューティング](getting-started.md): ハードウェア別パッケージ、ランタイム構成、起動モード、データディレクトリ、一般的な修復方法。
- [Python 3.12とROCm 10への移行](python312-rocm10.md): AMD環境、モデル互換性、依存関係の移行。
- [FastAPI連携](api.md): サービス起動、認証、タスクAPI、アップロード、ダウンロード、呼び出し例。
- [API管理の変更](api-management.md): ドメイン設定と複数API Key管理。
- モデルの重み、マニフェスト、設定は外部モデルコミュニティで管理されます。リリースビルド前にローカルの `assets/models/` へ完全に同期してください。

## 開発者向け

- [システムアーキテクチャ](architecture.md): Pythonバックエンド、Vueフロントエンド、Worker、キュー、モデル、音声ツールの責務と接続。
- [起動と推論の流れ](startup-chain.md): アプリ起動、通常タスク、リアルタイム処理。
- [開発とリリース](development.md): リポジトリ構成、テスト、フロントエンドビルド、JUCE Host、インストーラー作成。
- [テストと受け入れ](testing.md): 自動テスト分類、package統合、hardware受け入れ範囲。
- [インストーラーガイド](../../installer/README.md) **中国語**: PyInstaller、ランタイム、オフラインwheelhouse、Inno Setup分割アーカイブ。
- [共有ランタイムと互換構成](runtime-consolidation.md): CUDA共有層、ROCm 10共有環境、CPU / DirectML互換構成、修復範囲。
- [コントリビューションガイド](../../CONTRIBUTING.md) **中国語**: Issue、開発環境、テスト、Pull Requestの要件。

## プラグイン作者向け

- [プラグイン開発概要](plugins/README.md)
- [プラグイン開発完全ガイド](plugin-development.md)
- [Plugin SDK README](../../plugin-sdk/README.md) **中国語**

## アーキテクチャ資料

- [システムアーキテクチャ図](../archify/xb-svcb-system.architecture.html)
- [システムアーキテクチャJSON](../archify/xb-svcb-system.architecture.json)
- [起動・推論シーケンス図](../archify/xb-svcb-startup-inference.sequence.html)

## リリースノート

全バージョンの履歴は[`docs/release-notes`](../release-notes/)にあります。v0.1.0以降のリリースノートは簡体字中国語、英語、日本語で公開します。

- [v0.1.0](../release-notes/release_notes_v0_1_0.ja.md): 作成と推論、オーディオエディター、多言語UIとインストーラー、オンラインセットアップ、モデルリポジトリ変更。
- [v0.0.32](../release-notes/release_notes_v032.md): Python 3.12、ROCm 10、DirectML推論の修正。
- [v0.0.31](../release-notes/release_notes_v031.md): 共有ランタイム、初回ガイド、高音・ベルティングの安定性。
