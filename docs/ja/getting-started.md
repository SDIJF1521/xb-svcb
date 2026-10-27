[简体中文](../getting-started.md) | [English](../en/getting-started.md) | **日本語**

# インストール、ソース起動、修復

通常の利用者は、ハードウェアに対応する専用インストーラーをダウンロードしてください。ソースからの起動は、開発者およびエンジンを変更する必要がある利用者向けです。

## インストーラーを選ぶ

| ハードウェア | インストーラー | ランタイム構成 |
| --- | --- | --- |
| 対応 GPU なし | CPU | 分離された互換環境 |
| Windows AMD Radeon（推奨） | ROCm 10 | SVC / RVC / Vocal を共有、その他は分離 |
| Windows AMD（任意） | DirectML | 分離された互換環境、DDSP は自動的に CPU を使用 |
| NVIDIA RTX 40 シリーズ以前 | CUDA126 | `core-cu126` + `svc-cu126` の 2 層共有環境 |
| NVIDIA RTX 50 シリーズ Blackwell | CUDA128 | `core-cu128` + `svc-cu128` の 2 層共有環境 |

CUDA wheel スタックの最小構成は cu126 で、cu121 は使用しません。各専用パッケージには対象ハードウェア用の wheel だけが含まれ、アプリケーション、モデル、エンジンのソースコードは共通です。

インストーラーには完全な Python は含まれません。64 ビット CPython 3.12.x を選択してください。自動検出が正しくない場合は、インストールウィザードで `python.exe` を手動指定できます。`uv` を事前にインストールする必要はなく、同梱の起動用 wheel からインストールされます。

## インストール後のランタイム環境

CUDA126 / CUDA128 は既定でランタイムを共有します。

| ディレクトリ | コンポーネント |
| --- | --- |
| `runtimes/core-cu126` / `core-cu128` | UVR、SeedVC、DDSP-SVC |
| `runtimes/svc-cu126` / `svc-cu128` | So-VITS-SVC、RVC、Vocal / DeepFilterNet3 |

CPU では `.venv-uvr`、`.venv-svc`、`.venv-rvc`、`.venv-seedvc`、`.venv-ddsp`、`.venv-vocal` などの分離ディレクトリを使用します。DirectML も分離構成ですが、RVC は `.venv-rvc-directml` を使用します。ROCm 10 では SVC / RVC / Vocal が `runtimes/svc-rocm10` を共有し、その他のコンポーネントは分離されます。アプリケーションは `runtime.json` から実際のインタープリターを特定します。ディレクトリ名だけでインストール完了を判断しないでください。

完全な構成と旧インストールとの互換規則については、[共有ランタイムと互換構成](runtime-consolidation.md)を参照してください。

## 旧バージョン 0.0.31 のみ：RTX 50 インストール修復

0.0.32 の CUDA128 レシピにはすでに `gin-config` が含まれているため、以下の旧版パッチは不要です。アップグレードできず、0.0.31 がこの依存関係の不足によってインストールに失敗する場合に限り、旧インストールディレクトリで PowerShell から実行してください。

```powershell
Set-Location 'インストールディレクトリ'

$lock = Join-Path (Get-Location) 'install\runtime_profiles\core-cu128\requirements.lock'
$profile = Join-Path (Get-Location) 'install\runtime_profiles\core-cu128\profile.json'

if (!(Test-Path -LiteralPath $lock) -or !(Test-Path -LiteralPath $profile)) {
    throw 'core-cu128 のレシピファイルが見つかりません。現在のディレクトリがインストール先であることを確認してください。'
}

$utf8 = New-Object System.Text.UTF8Encoding($false)

Copy-Item -LiteralPath $lock -Destination ($lock + '.bak') -Force
Copy-Item -LiteralPath $profile -Destination ($profile + '.bak') -Force

$text = [System.IO.File]::ReadAllText($lock)

if ($text -notmatch '(?m)^gin-config==') {
    $match = [regex]::Match($text, '(?m)^fsspec==[^\r\n]*')
    if (!$match.Success) {
        throw 'ロックファイルの形式が想定と異なります。'
    }

    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $text = $text.Insert(
        $match.Index + $match.Length,
        $newline + 'gin-config==0.5.0'
    )

    [System.IO.File]::WriteAllText($lock, $text, $utf8)
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $lock).Hash.ToLowerInvariant()
$json = [System.IO.File]::ReadAllText($profile) | ConvertFrom-Json
$json.lock_sha256 = $hash

[System.IO.File]::WriteAllText(
    $profile,
    ($json | ConvertTo-Json -Depth 10),
    $utf8
)

.\setup_env.bat
```

スタートメニューから「実行環境の構築 / 修復」を実行するか、インストールディレクトリで次を実行します。

```bat
setup_env.bat
```

インストーラーはハードウェアスタックと構成を `installer_env.cmd` に記録します。そのため、CUDA パッケージで引数なしの修復を実行しても共有環境が使用され、旧式の 6 個の分離環境が誤って作成されることはありません。

非アトミックなコンポーネントだけを修復する場合は `--only` を使用できます。CUDA core の UVR、SeedVC、DDSP は必ず一組として修復してください。

```bat
setup_env.bat --only uvr seedvc ddsp
setup_env.bat --only svc rvc vocal
setup_env.bat --only models
```

インストールに失敗した場合は、`assets\wheels` と `install_logs` を保持してください。すべての環境が最終検証に合格した場合に限り、インストーラーがオフライン wheel を自動削除します。

### v0.0.32 CUDA128 オフラインインストール修復

RTX 50 シリーズへのインストール中、`torch-2.7.1+cu128` で `The wheel is invalid: Missing .dist-info directory` と表示された場合、CUDA Toolkit や GPU ドライバーの問題ではありません。XB-SVCB を終了し、インストールディレクトリで PowerShell を開いて、インストーラーが展開した Torch wheel を確認してください。

```powershell
$root = "E:\XB-SVCB" # 実際のインストールディレクトリに置き換える
$torchWheel = "$root\assets\wheels\py312\cu128\torch-2.7.1+cu128-cp312-cp312-win_amd64.whl"

(Get-Item $torchWheel).Length
(Get-FileHash $torchWheel -Algorithm SHA256).Hash
```

v0.0.32 CUDA128 パッケージの正しい値は次のとおりです。

```text
サイズ: 3273024349
SHA256: 2BB8C05D48BA815B316879A18195D53A6472A03E297D971E916753F8E1053D30
```

サイズまたはハッシュが異なる場合は、完全な CUDA128 インストーラーを再度ダウンロードし、インストーラー EXE と同じファイル名接頭辞を持つすべての BIN 分割ファイルを同じディレクトリに置いてください。破損した wheel を使って環境の修復を続けないでください。

サイズとハッシュが一致する場合は、インストールログまたは `installer_env.cmd` から固定された `XB_PYTHON_EXE` のパスを取得します。その後、同梱の `uv` を強制的に再インストールし、Torch キャッシュを削除して、共有 core グループを再試行します。

```powershell
$py = "C:\Path\To\Python312\python.exe" # XB_PYTHON_EXE に置き換える
$uv = "$env:APPDATA\Python\Python312\Scripts\uv.exe"

& $py -m ensurepip --upgrade
& $py -m pip install --user --force-reinstall --no-index `
  --find-links "$root\assets\wheels\bootstrap" "uv==0.12.22"
& $uv --version
& $uv cache clean torch

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

UVR、SeedVC、DDSP がすべて成功しても、最終検証で `missing: ["exceptiongroup"]` と報告される場合、Torch と CUDA のインストールは成功しています。ローカル wheel を追加してから、同じ修復エントリをもう一度実行してください。

```powershell
& $uv pip install `
  --python "$root\runtimes\core-cu128\Scripts\python.exe" `
  --no-index --no-build `
  --find-links "$root\assets\wheels\py312\cu128" `
  "exceptiongroup==1.3.1"

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

最終出力では、共有ランタイム環境の構築完了と `runtime.json` の書き込みが表示されます。`hf-xet` は不足が許容される任意パッケージです。DDSP が出力する `Please install tensorboardX` も、今回のインストール失敗の原因ではありません。

## ソース環境の要件

- Windows。
- インストーラーと現在のオフライン wheel に使用する 64 ビット CPython 3.12.x。
- フロントエンドのビルドにのみ必要な Node.js 20.19+ または 22.12+。
- PyPI、モデル配布元、上流リポジトリへの接続、または準備済みのオフライン wheelhouse とモデル資産。
- VST3 Host のビルドには CMake、Visual C++ Build Tools、JUCE。

ソースルートで環境を明示的に選択します。

```bat
setup_env.bat --cu128
setup_env.bat --cu126
setup_env.bat --cpu
setup_env.bat --rocm10
setup_env.bat --directml
```

CUDA 引数は 2 層の共有セットアップを呼び出します。ROCm 10 は SVC 共有層を含む互換セットアップを呼び出し、CPU / DirectML は分離セットアップを呼び出します。開発者は内部エントリを直接実行することもできます。

```bat
setup_shared_env.bat --cu128
python install\install.py --cpu
python install\install.py --rocm10
python install\install.py --directml
```

各手順は繰り返し実行できます。`install/install.py` には共通コンポーネントの実装と旧インストール用の互換コードが残っていますが、新しい CUDA インストールが既定で分離構成を使用するという意味ではありません。

## 起動

本番モード:

```bat
run.bat
```

同等のコマンド:

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py
```

フロントエンド開発モード:

```powershell
Set-Location .\web
npm install
npm run dev
```

続いて、別のターミナルで次を実行します。

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py --dev
```

本番モードは `web/dist/index.html` を読み込みます。開発モードは既定で `http://localhost:5173` に接続します。

## データディレクトリ

既定のデータディレクトリは `.xb_svcb` です。モデルライブラリ、作品、編集プロジェクト、ダウンロード、設定、ログ、キャッシュを保存します。十分な空き容量のあるディスクに配置してください。アプリ内の移行機能または `XB_DATA_DIR` で場所を変更できます。

## よくある問題

### Python が見つからない

オフライン wheel が `cp312-win_amd64` 向けであるため、インストーラーは実行可能な 64 ビット CPython 3.12.x のみを受け付けます。別の AI プロジェクトの `.venv` ではなく、通常の Python または Conda インタープリターを選んでください。

### フロントエンドがない

ソース版の本番モードには `web/dist/index.html` が必要です。

```powershell
Set-Location .\web
npm run build
```

### AI 環境の構築に失敗する

インストールディレクトリの `install_logs` を確認してください。オンライン修復では、先にミラーを設定できます。

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
setup_env.bat
```

### FFmpeg が見つからない

インストーラーパッケージには FFmpeg が含まれます。ソースから実行する場合は、システムの `PATH` に `ffmpeg` を追加するか、完全な Windows ビルドを `assets/tools/ffmpeg` に配置してください。

### フロントエンドを変更しても古いページが表示される

`web/dist` を再ビルドし、アプリケーションを完全に終了してから起動してください。開発中は Vite に接続する `--dev` を推奨します。
