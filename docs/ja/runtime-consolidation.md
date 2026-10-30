[简体中文](../runtime-consolidation.md) | [English](../en/runtime-consolidation.md) | **日本語**

# 共有ランタイムと互換構成

本書は現在のランタイム構成に関する正式な説明です。以前の容量調査、キャッシュ復元、実験的な導入記録はここへ統合し、過去バージョンの動作は`docs/release-notes/`に残します。

## リリース方針

NVIDIA CUDA126 / CUDA128は既定で二つの共有環境を使用します。ROCm 10ではSVC/RVC/Vocalが一つの環境を共有し、他のROCmコンポーネントとCPU/DirectMLは分離環境です。すべて64ビットCPython 3.12.xを使い、cu121は新規作成・配布しません。

| パッケージ | 既定構成 | 主なディレクトリ |
| --- | --- | --- |
| CPU | 分離互換 | `.venv-uvr`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp`、`.venv-vocal` |
| ROCm 10 | SVCグループ共有 | SVC/RVC/Vocalは`runtimes/svc-rocm10`、他はPyMSSを含む`.venv-*` |
| DirectML | 分離互換 | `.venv-*`。DDSPは自動的にCPUを使用し、PyMSSは独立環境でCPUへフォールバック |
| CUDA126 | 二層共有 | `runtimes/core-cu126`、`runtimes/svc-cu126` |
| CUDA128 | 二層共有 | `runtimes/core-cu128`、`runtimes/svc-cu128` |

「共有」は依存関係の構成であり、全コンポーネントを一つのPythonプロセスへ入れる意味ではありません。二層化で新しいNumPy/protobuf/AudioToolsと旧SVC/RVC依存関係の競合を分離します。

ROCm 10構築ではROCmメジャーバージョン、HIP、実GPU演算を検証し、CPU TorchをAMD構築成功とは判定しません。DirectML RVCは`.venv-rvc-directml`に分離し、`runtime.json`の`rvc-directml`routeで選択します。ROCm Torchと同じ環境へ混在させられません。`device=directml`を明示した場合だけ起動し、`device=rocm`と`auto`はROCm routeを使います。

## コンポーネントのルーティング

| 共有層 | コンポーネント | 目的 |
| --- | --- | --- |
| `core-cu126` / `core-cu128` | UVR、SeedVC、DDSP-SVC | 統一された新しいcore配方 |
| `svc-cu126` / `svc-cu128` | So-VITS-SVC、RVC、Vocal/DeepFilterNet3 | 旧モデルフレームワーク互換層 |

アプリは固定ディレクトリ名から構成を推測しません。成功後に`install/runtime_manifest.py`が各コンポーネントの相対Pythonパスを`runtime.json`へ書き、アプリはこれを優先して旧`.venv-*`へfallbackします。

PyMSS、プラグイン、ModelScope Hubは二層共有環境の固定メンバーではありません。独自の実装と依存要件に従い、既存インタープリターの利用によってcore/svcのリリース境界を変更してはいけません。

## 構築エントリ

- `install/install_shared.py`: CUDA126/CUDA128共有構成。検証済み方針だけを公開します。
- `install/install.py`: 共通コンポーネント実装とCPU、ROCm 10、DirectML、旧分離構成の互換エントリです。
- `setup_env.bat`: 利用者向け統一修復入口。`installer_env.cmd`の`XB_RUNTIME_LAYOUT`と`XB_GPU_STACK`に従い、CUDAは二層共有、ROCm 10はSVC共有を維持します。
- `setup_shared_env.bat`: 開発者が共有構成を明示的に検証する入口です。

インストーラー固定引数:

```text
CUDA126: --gpu --cu126 --consolidated
CUDA128: --gpu --cu128 --consolidated --core-profile core-cu128
ROCm 10: --rocm10
DirectML: --directml
CPU:      --cpu
```

DirectML RVC分離環境だけを導入:

```powershell
python install/install.py --directml --only rvc
```

ROCm RVCは既定でrvc-pythonのfp16 GPU経路を維持します。不安定な場合は一時的に`XB_RVC_ROCM_FP32=1`を設定してください。ログの`RVC_COMPONENT_DEVICES`と`RVC_TIMING`にコンポーネントのデバイスとモデル/後処理時間が出ます。

SVC、RVC、SeedVC、DDSP-SVC、UVR、PyMSS、F0、Vocal Workerは品質優先のPyTorch方針を共有します。勾配記録を無効化し、CUDA/ROCmデバイスを固定し、FP32行列演算を最高精度にし、NVIDIA CUDAのTF32を無効化します。CPUは既定で最大8 Torch threadで、`XB_INFERENCE_CPU_THREADS`で変更できます。モデル別FP16/FP32とDirectML fallbackは各Workerが決め、`*_RUNTIME`行へbackend、device、精度方針を記録します。

旧実装は`--consolidated`を認識しますが、リリースでは利用者向け実験機能ではなくCUDA共有構成を意味します。`XB_RUNTIME_LAYOUT`がない旧環境で引数なしの`setup_env.bat`は互換動作を維持し、`--cu126`、`--cu128`、`--consolidated`を明示すると共有入口を選びます。

## 配方とオフライン資産

CUDA128 core固定配方:

- `install/runtime_profiles/core-cu128/requirements.lock`
- `install/runtime_profiles/core-cu128/profile.json`
- `assets/runtime/core-cu128/compat/`
- `assets/runtime/core-cu128/candidate/`
- `assets/runtime/core-cu128/rollback/`

NumPy 2.2.6、protobuf 7.36.0、TensorBoardX 2.6.5、ローカルAudioTools互換wheelを使います。hashと再構築は[core-cu128配方README](../../install/runtime_profiles/core-cu128/README.md)を参照してください。CUDA126は検証済み互換資産を再利用しますが、固有のcu126 Torch wheelとディレクトリを使い、cu121へ戻りません。

`install/prepare_wheelhouse.py`が5スタックのcacheを準備し、`installer/stage_wheelhouse.py`が対象スタック用wheelだけを一時配置します。全環境が検証に成功した場合だけ、導入先の`assets/wheels`を削除します。失敗時はオフライン再試行用に保存します。

CUDAパッケージには`assets/runtime/core-cu128/candidate`と`compat`も必要です。Git管理外のbinaryなので`installer/build.ps1 -RuntimeAssets <バックアップ先>`で渡します。builderがprofile lockと各wheel SHA-256を確認し、`protobuf==7.36.0`不足パッケージの公開を防ぎます。

## 原子的な導入と有効化

1. UVR、SeedVC、DDSPはcoreグループ全体で事前解決し、一部だけ変更して全routeを公開しません。
2. SVC、RVC、Vocalの最終`pip check`は共有層全体の導入完了後に行います。
3. Python、依存関係、Torch/CUDA、主要import、互換probeがすべて成功した場合だけ`runtime.json`を更新します。
4. 失敗した半完成環境を有効とせず、旧`.venv-*`や利用者モデルを自動削除しません。
5. 修復でも同じ構成を維持し、CUDA共有環境を旧分離入口で個別上書きしません。

## 検証コマンド

インストーラーとscriptだけを検証:

```powershell
& .\installer\build.ps1 -ValidateOnly
```

CUDA128 core配方を導入せず解決:

```powershell
& .\setup_shared_env.bat --cu128 --only uvr seedvc ddsp --preflight-only
```

導入済み共有環境を検査:

```powershell
& .\runtimes\core-cu128\Scripts\python.exe -B .\install\audit_runtime.py --root . --require-cuda --timeout 90 --ddsp-timeout 180
& uv pip check --python .\runtimes\core-cu128\Scripts\python.exe
& uv pip check --python .\runtimes\svc-cu128\Scripts\python.exe
```

自動テスト範囲は[テスト](testing.md)を参照してください。配方解決、再導入、drift検出、復元、import、小CUDA tensor、事前検証には回帰テストがありますが、対象GPUでの実モデル・実音声・完全なSetup.exe受け入れを置き換えません。

## 旧環境とクリーンアップ

旧`.venv-*`は互換fallbackで、新CUDA構成の対象ではなく、自動削除しません。ROCm 10の`svc-rocm10`移行時はSVC/RVC/Vocalすべての導入と最終検証後にだけ旧`.venv-svc`と`.venv-vocal`を削除します。`.venv-rvc`はDirectML Torchを含む可能性があるため残します。外部scriptは更新前に`runtime.json`を読むよう変更し、他の旧ディレクトリは参照がないことを確認して個別削除してください。

次はソース清掃対象ではありません。

- `runtimes/`内で使用中のローカル環境。
- `.xb_svcb`またはカスタムデータディレクトリのモデル、作品、編集プロジェクト、ログ。
- 他プロジェクトも使う可能性があるglobal uv cache。
- `assets/runtime/core-cu128`の配方、互換、rollback資産。

`.tmp/`、`build/`、`dist/`、`assets/wheels/`、`assets/tools/python312/`は再生成可能またはローカル生成物で、`.gitignore`対象です。ローカルコピーの削除はソースcommitと分けて判断してください。
