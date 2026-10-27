[简体中文](../architecture.md) | [English](../en/architecture.md) | **日本語**

# システムアーキテクチャ

XB-SVCBはローカル優先のデスクトップアプリケーションです。フロントエンドが操作と状態表示、Pythonが処理の調整を担当し、高負荷のモデルと音声ツールは分離Workerで実行されます。

## 全体構成

    デスクトップユーザー -> pywebview + Vue 3 -> API facade -> Application services
    外部クライアント -> FastAPI -----------------------> API facade
                                                            |
                                                 直列推論キュー / ローカルデータ
                                                            |
                                   UVR -> EngineRegistry -> Model worker -> FFmpeg
                                                            |
                                                     オフラインモデル資産

全体の配置と説明は[接続説明付きシステム構成図](../archify/xb-svcb-system.architecture.html)で確認できます。

## 接続の説明

| 接続 | 役割 |
| --- | --- |
| デスクトップユーザー -> pywebview + Vue | 音声、モデル、デバイス、推論パラメーターを選択し、タスク状態を表示します。 |
| 外部クライアント -> FastAPI | HTTPで音声をアップロードし、タスク作成、進捗確認、成果物のダウンロードを行います。既定では無効です。 |
| Vue -> API facade | `window.pywebview.api`を介してPythonメソッドを呼び出します。 |
| FastAPI -> API facade | HTTP層がデスクトップBridgeと同じAPIを再利用し、業務ルールの重複を防ぎます。 |
| API facade -> Application services | UIまたはHTTP要求を作品、モデル、変換、エディターなどのユースケースへ振り分けます。 |
| Application services -> 直列推論キュー | タスクを作成・待機させ、GPUメモリのピークと状態を管理します。 |
| 直列推論キュー -> EngineRegistry | モデルの`framework`からSo-VITS-SVC、RVC、SeedVC、DDSP-SVCアダプターを選択します。 |
| Application services -> UVR worker | ボーカル・伴奏分離、残響除去などの前処理を実行します。 |
| EngineRegistry -> Model worker | 分離Workerを起動または再利用します。checkpointはWorker内で読み込みます。 |
| Model worker -> オフラインモデル資産 | 主モデル、基本モデル、F0、ボコーダー、フレームワーク設定を読み込みます。 |
| Application services -> Vocal enhancement | 設定に応じてボーカル修復、整列、音程補正、マスタリングを行います。 |
| Model worker -> FFmpeg | 推論後に後処理と最終ミックスへ進むことを表し、実際のFFmpeg呼び出しはApplication servicesが行います。 |

## 主なモジュール

### `app/main.py`

デスクトップのエントリです。単一起動、開発/本番モード判定、pywebviewウィンドウ作成、API結合、終了時のバックグラウンドサービス停止と一時ファイル削除を担当します。

### `app/api/`

表示層です。

- `bridge.py`: Vueへ公開するAPIと構成ルート`build_api()`。
- `http_server.py`: 手動で開始・停止するFastAPI/Uvicornサービス。

### `app/application/`

ユースケースと処理調整層です。モデル、作品、音楽ソース、音声編集、リアルタイム変換、プラグイン、変換タスクのサービスを含みます。通常の推論タスクは`conversion_service.py`から直列キューへ入ります。

### `app/domain/`

編集プロジェクト、タスク、モデルのドメインオブジェクトと列挙型を保持し、pywebview、FastAPI、具体的なAIフレームワークへの依存を抑えます。

### `app/infrastructure/`

ファイル保存、パス、FFmpeg、システム音声、UVR、F0、エンジンアダプター、Workerを実装します。`svc_engine.py`、`rvc_engine.py`、`seedvc_engine.py`、`ddsp_engine.py`が各フレームワークの入口です。

### `web/`

Vue 3 + Viteフロントエンドです。`views/`が画面、`stores/`が画面間状態、`src/api/`がpywebview BridgeとHTTP型を管理します。

## 実行境界

- メイン環境にはデスクトップシェル、API、Application servicesだけを置きます。
- NVIDIA CUDA126/CUDA128は既定で二層を共有します。UVR、SeedVC、DDSPは`runtimes/core-*`、So-VITS-SVC、RVC、Vocalは`runtimes/svc-*`です。ROCm 10のSVC/RVC/Vocalは`runtimes/svc-rocm10`を共有し、他のROCmコンポーネントとCPU/DirectMLは分離環境を使います。旧環境は`.venv-*`へフォールバックできます。依存関係、Torch/デバイス、主要モジュール検証の成功後にだけ`runtime.json`へ登録します。[共有ランタイムと互換構成](runtime-consolidation.md)を参照してください。
- Workerは別プロセスですが、Python環境を分けた場合だけ依存関係も分離されます。共有インタープリターの別プロセスは、パッケージ競合を解消せず、OS権限サンドボックスでもありません。
- FastAPIとデスクトップUIは同じタスクキューを共有し、どちらから作成したタスクも同じアプリで確認できます。
- 通常タスクは原則直列です。リアルタイムモードはUVRとモデルWorkerを常駐させ、再読込を減らします。
