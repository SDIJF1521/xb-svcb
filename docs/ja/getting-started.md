[简体中文](../getting-started.md) | [English](../en/getting-started.md) | **日本語**

# インストール、ソース実行、トラブルシューティング

通常の利用では、ハードウェアに対応したインストーラーを推奨します。ソースからの構築は、開発者およびエンジンを変更する利用者向けです。

## パッケージを選ぶ

| ハードウェア | パッケージ | ランタイム構成 |
| --- | --- | --- |
| 対応GPUなし | CPU | 分離された互換環境 |
| Windows AMD Radeon（推奨） | ROCm 10 | SVC / RVC / Vocalを共有、その他は分離 |
| Windows AMD（代替） | DirectML | 分離環境、DDSP自動モードはCPUを使用 |
| NVIDIA RTX 40シリーズ以前 | CUDA126 | `core-cu126` + `svc-cu126`共有環境 |
| NVIDIA RTX 50シリーズ（Blackwell） | CUDA128 | `core-cu128` + `svc-cu128`共有環境 |

対応するCUDA wheelの最小構成はcu126で、cu121は使用しません。各ハードウェア向けパッケージには対応するwheelだけが含まれます。アプリケーション、モデル資産、エンジンのソースは共通です。

インストーラーには完全なPython環境は含まれません。64ビットCPython 3.12.xを選択してください。自動検出が正しくない場合は、`python.exe`を手動で指定します。`uv`の事前インストールは不要で、同梱wheelから自動的に導入されます。

インストーラーのEXEと、**同じファイル名接頭辞を持つすべてのBIN分割ファイル**をダウンロードし、同じディレクトリに置いてからEXEを実行してください。

## インストール後のランタイム構成

CUDA126 / CUDA128は共有層を使用します。

| ディレクトリ | コンポーネント |
| --- | --- |
| `runtimes/core-cu126` / `core-cu128` | UVR、SeedVC、DDSP-SVC |
| `runtimes/svc-cu126` / `svc-cu128` | So-VITS-SVC、RVC、Vocal / DeepFilterNet3 |

CPUでは`.venv-uvr`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp`、`.venv-vocal`などの分離環境を使います。DirectMLも分離構成ですが、RVCは`.venv-rvc-directml`を使います。ROCm 10ではSVC、RVC、Vocalが`runtimes/svc-rocm10`を共有し、その他は分離されます。

アプリケーションは`runtime.json`から実際のインタープリターを取得します。ディレクトリ名だけでインストール済みかどうかを判断しないでください。[共有ランタイムと互換構成](runtime-consolidation.md)を参照してください。

## ソース環境の要件

- Windows。
- 現在の`cp312-win_amd64`オフラインwheelに対応する64ビットCPython 3.12.x。
- フロントエンドのビルドにはNode.js 20.19+または22.12+。
- オフラインwheelhouseとモデル資産がない場合は、PyPI、モデル配布元、上流リポジトリへの接続。
- ソース版の音声処理にはFFmpeg。
- VST3 HostのビルドにはCMake、C++17対応Visual Studio Build Tools、JUCE。

リポジトリのルートでハードウェア構成を明示的に選びます。

```bat
setup_env.bat --cu128
setup_env.bat --cu126
setup_env.bat --cpu
setup_env.bat --rocm10
setup_env.bat --directml
```

CUDAは二つの共有ランタイム層を使用します。ROCm 10はSVC共有層を含む互換構成、CPU / DirectMLは分離環境を使用します。上級者は内部エントリを直接実行できます。

```bat
setup_shared_env.bat --cu128
python install\install.py --cpu
python install\install.py --rocm10
python install\install.py --directml
```

セットアップは繰り返し実行できます。`install/install.py`に共通コンポーネントと旧構成の互換コードが含まれていても、新しいCUDA環境が旧分離構成になるわけではありません。

コンポーネント単位で導入・修復する場合:

```bat
setup_env.bat --only uvr seedvc ddsp
setup_env.bat --only svc rvc vocal
setup_env.bat --only models
```

UVR、SeedVC、DDSPはCUDA coreの一単位なので、まとめて修復してください。失敗時は`assets\wheels`と`install_logs`を保存してください。全環境が最終検証を通過した場合に限り、インストーラーがオフラインwheelを削除します。

## アプリケーションを起動

本番モード:

```bat
run.bat
```

同等のPowerShellコマンド:

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py
```

フロントエンド開発では、一つ目のターミナルでViteを起動します。

```powershell
Set-Location .\web
npm install
npm run dev
```

別のターミナルでPythonバックエンドを起動します。

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py --dev
```

本番モードは`web/dist/index.html`を読み込みます。開発モードは既定で`http://localhost:5173`へ接続し、`XB_DEV_URL`で別のURLを指定できます。

## ユーザーデータ

既定のユーザーデータディレクトリは`.xb_svcb`です。モデルライブラリ、作品、編集プロジェクト、ダウンロード、設定、ログ、キャッシュを保存します。十分な空き容量のあるディスクを選んでください。アプリ内で移動するか、`XB_DATA_DIR`で変更できます。通常、アプリの更新で上書きされることはありません。

## トラブルシューティング

### Pythonが見つからない、または拒否される

オフラインwheelが`cp312-win_amd64`向けのため、インストーラーは動作する64ビットCPython 3.12.xのみを受け付けます。別のAIプロジェクト用仮想環境ではなく、通常のPythonまたはCondaインタープリターを推奨します。

### フロントエンドが見つからない

ソース版の本番モードには`web/dist/index.html`が必要です。

```powershell
Set-Location .\web
npm install
npm run build
```

### ランタイム構築に失敗する

インストール先の`install_logs`を確認してください。オンライン修復では、再実行前にミラーを設定できます。

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
setup_env.bat
```

インストーラーは選択したハードウェア構成を`installer_env.cmd`へ保存します。インストール済みCUDAパッケージから引数なしでセットアップを実行しても、共有構成が維持されます。

### CUDA128でTorch wheelが不正と表示される

v0.0.32で`torch-2.7.1+cu128`の導入時に`The wheel is invalid: Missing .dist-info directory`と表示される場合、CUDA Toolkitやドライバーではなくパッケージファイルの破損です。XB-SVCBを終了し、インストール先を変更してPowerShellでwheelを確認します。

```powershell
$root = "E:\XB-SVCB"
$torchWheel = "$root\assets\wheels\py312\cu128\torch-2.7.1+cu128-cp312-cp312-win_amd64.whl"

(Get-Item $torchWheel).Length
(Get-FileHash $torchWheel -Algorithm SHA256).Hash
```

v0.0.32 CUDA128の正しい値:

```text
サイズ: 3273024349
SHA256: 2BB8C05D48BA815B316879A18195D53A6472A03E297D971E916753F8E1053D30
```

いずれかが異なる場合は、CUDA128パッケージ全体を再ダウンロードし、EXEと対応するすべてのBIN分割ファイルが同じディレクトリにあることを確認してください。破損したwheelで修復を続けないでください。

両方が一致する場合は、セットアップログまたは`installer_env.cmd`から固定された`XB_PYTHON_EXE`を確認し、同梱`uv`の再導入、Torchキャッシュの削除、共有coreグループの再構築を行います。

```powershell
$py = "C:\Path\To\Python312\python.exe"
$uv = "$env:APPDATA\Python\Python312\Scripts\uv.exe"

& $py -m ensurepip --upgrade
& $py -m pip install --user --force-reinstall --no-index `
  --find-links "$root\assets\wheels\bootstrap" "uv==0.12.22"
& $uv --version
& $uv cache clean torch

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

3コンポーネントが成功しても最終検証で`missing: ["exceptiongroup"]`と表示される場合は、同梱wheelを導入して再検証します。

```powershell
& $uv pip install `
  --python "$root\runtimes\core-cu128\Scripts\python.exe" `
  --no-index --no-build `
  --find-links "$root\assets\wheels\py312\cu128" `
  "exceptiongroup==1.3.1"

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

`hf-xet`は欠けていても問題ありません。DDSPの`Please install tensorboardX`も、このセットアップ失敗の原因ではありません。

### 推論時に`pkg_resources`が見つからない

SVC環境に互換バージョンのsetuptoolsが必要な場合があります。CUDA128環境では次を実行します。

```powershell
uv pip install --python <インストール先>\runtimes\svc-cu128\Scripts\python.exe "setuptools<81" wheel
```

### FFmpegが見つからない

インストーラー版にはFFmpegが含まれます。ソース版では`PATH`に`ffmpeg`を追加するか、完全なWindowsビルドを`assets/tools/ffmpeg`へ配置してください。

### フロントエンドの変更が表示されない

`web/dist`を再ビルドし、アプリケーションを完全に終了してから再起動します。開発中はViteサーバーと`--dev`の利用を推奨します。

### 旧v0.0.31 CUDA128のセットアップ

v0.0.32には`gin-config`が含まれています。手動でのlockfile修正は、v0.0.31を維持する必要がある環境だけが対象です。旧版の手順は[正式な中国語ガイド](../getting-started.md#仅旧版-0031rtx-50-安装修复)を参照するか、v0.0.32へ更新してください。
