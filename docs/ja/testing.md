[简体中文](../testing.md) | [English](../en/testing.md) | **日本語**

# テスト分類と受け入れ範囲

リポジトリのルートで実行します。`uv`がテストツールとSciPyを一時追加し、メインアプリ環境へTorchを導入しません。

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs
```

キャッシュ準備後は`--offline`を追加できます。`-rs`は各skip理由を表示します。テスト成功は実モデル推論やリリース受け入れの成功を意味しません。

## 分類

| マーカー | 内容 | 選択方法 |
| --- | --- | --- |
| `runtime` | 配方、ルーティング、Worker、音声補助処理。完全なモデル推論ではない | `-m runtime` |
| `installer` | Python検出、導入・修復保護 | `-m installer` |
| `packaging` | オフラインパッケージ計画と規則 | `-m packaging` |
| `packaging_integration` | 実際のエンジンrequirementsを使う計画検査 | `-m packaging_integration` |
| `model_inference` | 実weight・音声の受け入れ用。既定では無効 | `-m model_inference --run-model-inference` |

最後の分類には現在自動受け入れケースがなく、空集合は合格ではありません。手動の実推論検証は現在保留です。他の業務/APIテストは全体テストに残し、runtimeやinstallerへ強制分類しません。

パッケージ単体テストだけを実行する例:

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest -m "packaging and not packaging_integration" -q -rs
```

## 以前の4件の失敗への対応

- Python検出2件: 正常なCドライブPythonにも誤一致する`if exist "python.exe\"`判定を削除しました。現在はバージョンprobeを実行し、ディレクトリやPython以外のプログラムを拒否します。既存の正常・無効パスfallbackテストを残し、`python.exe`というディレクトリの反例を追加しました。
- パッケージassertion 2件を`test_wheelhouse_plan.py`へ移し、一時requirementsを利用します。バージョン/分離assertionを維持し、中間requirementsはテストルート内に置いて上流ファイルを変更しません。
- 実ソース統合検査では、SVC/SeedVC/DDSP requirements不足時にコンポーネントと絶対パスを列挙してskipします。入力不足をモデル依存失敗として扱わず、対象範囲も削除しません。

リリース検査では入力を必須にします。

```powershell
uv run --project app --with pytest pytest -m packaging_integration --require-packaging-inputs -q
```

このモードでは不足ファイルは失敗し、skipでリリース合格にはできません。ただしInnoコンパイルや新規インストールではなく、パッケージ計画だけの検証です。

## リリース受け入れ順序

テスト追加で件数が変わるため、固定値は記載しません。各リリースで次を実行します。

1. Python全テストを実行し、全skip理由を確認します。
2. `packaging_integration`を強制実行し、requirements不足によるskipを禁止します。
3. `installer/build.ps1 -ValidateOnly`で5種のInno設定と共有エントリを確認します。
4. 対象パッケージを作成し、新規ディレクトリでSetup.exe、ランタイム作成、最終Torch検証を完了します。
5. CPU、ROCm 10、DirectML、CUDA126、CUDA128実機で実モデル・短音声を検証し、DDSP DirectML実験出力も試聴します。

配方解決、原子的有効化、修復、rollback境界は[共有ランタイムと互換構成](runtime-consolidation.md)を参照してください。自動テスト成功はassertion対象のコードとパッケージ規則だけを保証し、実モデルや5種ハードウェアの受け入れを保証しません。
