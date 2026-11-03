[简体中文](../startup-chain.md) | [English](../en/startup-chain.md) | **日本語**

# 起動とモデル推論の流れ

Pythonバックエンドとモデルランタイムの実際の起動関係を説明します。詳細は[起動・推論シーケンス図](../archify/xb-svcb-startup-inference.sequence.html)を参照してください。

## 1. デスクトップアプリの起動

    run.bat
      -> app/.venv/Scripts/python.exe app/main.py
      -> app/main.py
      -> resolve_url()
      -> build_api()
      -> pywebview.create_window(..., js_api=api)
      -> webview.start()

本番モードでは内蔵HTTP serverから`web/dist/index.html`を読み、`--dev`ではVite URLを読みます。起動時にすべてのmodel checkpointをメインプロセスへ読み込むことはありません。

## 2. バックエンドの構成

`build_api()`は構成ルートです。パス、保存、モデル、作品、変換、エディター、リアルタイム、プラグインサービスをAPI facadeへ接続します。`window.pywebview.api.*`の呼び出しは最終的にこれらのApplication servicesへ届きます。

FastAPIは任意機能です。アプリ内で開始すると、UvicornがGUIプロセスのバックグラウンドスレッドで待ち受けます。HTTP routeは同じAPIとサービスを呼び、別の業務コアを作りません。

Model workerのPythonは`runtime.json`で選択します。CUDA126/CUDA128ではUVR、SeedVC、DDSPを`runtimes/core-*`、SVC、RVC、Vocalを`runtimes/svc-*`へ振り分けます。CPU、ROCm 10、旧環境は`.venv-*`も利用できます。プロセス分離は依存関係分離ではなく、共有層のコンポーネントは同じ検証済み依存関係を使います。

## 3. 通常カバータスク

    音声とモデルを選択
      -> API facade
      -> Application services
      -> タスク記録を作成
      -> 直列推論キュー
      -> UVR worker: ボーカル分離 / 残響除去
      -> EngineRegistry: frameworkで選択
      -> Model worker: checkpoint読込と推論
      -> 必要に応じてVocal enhancement
      -> FFmpeg: ミックス、変換、出力
      -> 作品とタスク状態を保存
      -> フロントエンドのpolling/pushで結果表示

「Model worker -> FFmpeg」は処理順を示し、Workerが直接FFmpegを実行する意味ではありません。Application servicesが段階、一時ファイル、タスク状態を調整します。

## 4. 複数モデルとエディタータスク

- 複数モデルタスクは歌詞またはタイムラインを解析し、セグメントへ一つ以上のモデルを割り当てます。
- 各モデルは自身のエンジン環境でボーカルを生成し、Application servicesがタイムライン上で結合・crossfadeします。
- エディターの範囲再推論は対象セグメントだけを処理し、波形、キャッシュ、undo履歴を更新します。
- VST3エフェクトは`native/juce-vst3-host`を通じてPython音声サービスへ接続し、モデルのdry推論には入りません。

## 5. リアルタイムタスク

通常タスクとの主な違いはWorkerの寿命です。

    リアルタイムセッション開始
      -> UVR workerを常駐
      -> RVC / SeedVC workerを常駐
      -> 楽曲ファイルまたはWASAPI/VB-CABLEブロックを読込
      -> prebufferとoverlap context
      -> ボーカル変換
      -> 等電力crossfade
      -> 伴奏を保持してリアルタイム再生

システム音声モードは固定ブロック処理と遅延を安定させるため単一モデルに制限します。ファイルモードは作品登録と書き出しができます。

## 6. 終了処理

`app/main.py`の`finally`がAPIとバックグラウンドサービスを停止し、現在のユーザーデータ配下の一時内容を消去し、単一起動handleを解放します。通常終了で永続モデルや作品は削除しません。

ランタイムディレクトリ、構築エントリ、修復範囲は[共有ランタイムと互換構成](runtime-consolidation.md)を参照してください。
