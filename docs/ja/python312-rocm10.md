[简体中文](../python312-rocm10.md) | [English](../en/python312-rocm10.md) | **日本語**

# Python 3.12とAMD ROCm 10

アプリ、プラグイン、全推論環境は**64ビットCPython 3.12.x**を使用します。旧インタープリターを検出すると対応する仮想環境を再構築し、モデルやプロジェクトデータの変換は不要です。オフライン配布では`py312` wheelhouseを作り直し、`cp310-cp310` wheelの改名やコピーはできません。`abi3` wheelは実際の互換tagに従います。

## AMDへの導入

```powershell
./install.ps1 --rocm10
# 導入済みアプリの環境修復
./setup_env.bat --rocm10
```

AMD自動検出とGUIインストーラーは`rocm10`スタックを選び、`--rocm`は別名です。runtime APIのdevice値は`rocm`のままです。ROCm PyTorchは`torch.cuda` interfaceと`cuda:0`を使い、実backendは`torch.version.hip`で判定します。

既定のAMD公式indexは`https://stable.repo.amd.com/rocm/whl-next/`です。

```powershell
python -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-all]==2.13.0+rocm10.0.0" "torchvision[device-all]==0.28.0+rocm10.0.0" "torchaudio==2.11.0.2+rocm10.0.0"
python -m pip install pymss==2.0.18
```

3バージョンすべてにWindows CPython 3.12 wheelがあり、PyMSS 2.0.18との依存解決を検証済みです。`device-all`が導入するAMD各GPU architecture packageもオフラインパッケージに必要です。インストーラーは公式Torch一式、PyMSSの順で導入し、後続でも3バージョンを固定して、依存整合性、PyMSS import、HIP演算を検証します。

Python 3.12 / 現在のOS / ROCm 10 wheelを提供するmirrorも利用できます。

```powershell
$env:XB_TORCH_ROCM_INDEX = 'https://your-mirror.example/rocm10/simple'
$env:XB_ROCM_TORCH_VERSION = '2.13.0+rocm10.0.0'
$env:XB_ROCM_TORCHAUDIO_VERSION = '2.11.0.2+rocm10.0.0'
$env:XB_ROCM_TORCHVISION_VERSION = '<対応する torchvision version>'
./install.ps1 --rocm10
```

Torch、torchvision、torchaudioは固有の公式versionを使い、同じとは限りません。導入後にROCm major 10、HIP、GPU利用可否、実tensor演算を確認し、CPUまたはNVIDIA CUDA TorchをAMD成功とは判定しません。非対応GPU/driverでは`--cpu`を明示してください。Windows native対応はROCm 7.2.1 / Adrenalin 26.2.2 / Python 3.12からですが、ROCm 10の実要件はAMDの最新release noteに従ってください。旧minimumはROCm 10実機検証を意味しません。

オフライン一時配置ではwheel内の`torch/version.py`からROCm 10とHIP markerを確認し、DirectML依存ディレクトリの混入を拒否します。検証済み公式Windows cp312 wheelは`torch.version.rocm == '10.0.0'`、`torch.version.hip == '7.15.26333'`です。数値は異なり、HIP majorをROCm majorの代わりにできません。sourceとversionが不一致ならパッケージ作成を停止します。

PyMSSは独立`.venv-pymss`に同じROCmスタックを導入してAMD高速化します。`auto`はHIPを検出して`rocm`と報告し、明示的`rocm`が利用不能なら失敗します。PyMSSはDirectML非対応です。ROCm 10のSVC/RVC/Vocalは`runtimes/svc-rocm10`を共有します。独立DirectMLパッケージとRVC DirectML環境は選択できますが、ROCm Torchとは混在できません。

## DDSPとSeedVCモデル

DDSPは`model.type`から公式loaderへ振り分けます。Sins、CombSub、CombSubFast、CombSubSuperFast、Diffusion、DiffusionNew、DiffusionFast、RectifiedFlow 6.1 / 6.2 / 6.3に対応します。旧loaderは公式source commitへ固定し、Python 3.12 / fairseq-fixedの`.venv-ddsp-legacy`を使い、6.3と同じハードウェアスタックです。浅拡散は対応するDDSP weightと設定をimportできます。RectifiedFlowは補助network fieldとencoder weight形式からversionを判定し、カスタム設定では`xb_ddsp_version: '6.1'`、`'6.2'`、`'6.3'`を明示できます。

SeedVCは設定からF0 switchを読み、44.1 kHz F0、22.05 kHz非F0、XLSR tiny、上流対応のカスタムencoder/vocoderを扱います。V2は`VoiceConversionWrapper`設定から公式V2推論を選び、主weightはCFM、AR weightは任意です。ない場合は上流download動作に従います。非F0とV2は半音移調に非対応なのでpitch shiftは0にしてください。

import時に設定が参照するlocal encoder、vocoder、Hugging Face modelディレクトリをコピーし、元設定を保ちます。カスタム基本モデル不足時は具体的パスを報告します。variantごとに追加の基本weightが必要な場合があり、既定パッケージには全variantを含みません。CPUはFP32、ROCmはHIPです。SeedVCのWAV保存は新torchaudioに対応し、TorchCodecは不要です。これは読込・実行経路の互換性で、全weightの推論合格を意味しません。

UVRのPyTorchモデルはROCmを使います。Windows ONNX Runtimeは既定でCPU providerで、AMDにNVIDIA CUDA providerは使えません。UVRモデル別に高速化を検証してください。

## 依存関係の移行

SVC/RVC/VocalはNumPy 1.26.4、SciPy 1.13.1、Python 3.12対応依存関係を使います。SVCはWindows cp312 wheelのある`fairseq-fixed==0.12.3.1`を使い、import名は`fairseq`です。

上流RVC 0.1.5は旧fairseq、NumPy、faiss、OmegaConfを固定し、Python 3.12で解決できません。`install/build_rvc_compat.py`が元wheelのRECORDを検証して`rvc-python==0.1.5+xb312`を作ります。変更は4依存関係、Python要件、ローカルpackage versionだけで、上流推論コードとlicenseを維持します。オフライン作成も同じwheelを作り、依存整合性検査を省略しません。

受け入れでは各モデルのimport、短音声の実推論、CPU/CUDA回帰、ROCm 10実機テストが必要です。単体テストやwheel metadata検査では代替できません。
