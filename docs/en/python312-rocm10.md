[简体中文](../python312-rocm10.md) | **English** | [日本語](../ja/python312-rocm10.md)

# Python 3.12 and AMD ROCm 10

The application, plugins, and all inference environments use **64-bit CPython 3.12.x**. When the installer finds an older interpreter it rebuilds the corresponding virtual environments; models and project data require no conversion. Offline releases must rebuild a `py312` wheelhouse rather than renaming or copying `cp310-cp310` wheels. Wheels tagged `abi3` follow their actual compatibility tags.

## AMD Installation

```powershell
./install.ps1 --rocm10
# Repair an installed application
./setup_env.bat --rocm10
```

AMD auto-detection and graphical installers select the `rocm10` stack; `--rocm` is an alias. The runtime API device value remains `rocm`. ROCm PyTorch uses the `torch.cuda` interface and device name `cuda:0`; the application detects the actual backend through `torch.version.hip`.

The default official AMD index is `https://stable.repo.amd.com/rocm/whl-next/`:

```powershell
python -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-all]==2.13.0+rocm10.0.0" "torchvision[device-all]==0.28.0+rocm10.0.0" "torchaudio==2.11.0.2+rocm10.0.0"
python -m pip install pymss==2.0.18
```

All three versions have verified Windows CPython 3.12 wheels and resolve with PyMSS 2.0.18. `device-all` installs AMD architecture packages, which must also be included in offline packages. The installer installs official Torch first and PyMSS second, pins all three Torch-family versions during subsequent steps, then checks dependency consistency, PyMSS import, and a HIP operation.

You may use a mirror that provides Python 3.12 / current-OS / ROCm 10 wheels and pin matching packages:

```powershell
$env:XB_TORCH_ROCM_INDEX = 'https://your-mirror.example/rocm10/simple'
$env:XB_ROCM_TORCH_VERSION = '2.13.0+rocm10.0.0'
$env:XB_ROCM_TORCHAUDIO_VERSION = '2.11.0.2+rocm10.0.0'
$env:XB_ROCM_TORCHVISION_VERSION = '<matching torchvision version>'
./install.ps1 --rocm10
```

Torch, torchvision, and torchaudio use their own official version numbers; do not assume they match. Setup must validate ROCm major version 10, HIP presence, GPU availability, and an actual tensor operation. CPU or NVIDIA CUDA Torch is not accepted as successful AMD setup. Unsupported GPUs or drivers must explicitly use `--cpu`. Native Windows support began with ROCm 7.2.1 / Adrenalin 26.2.2 / Python 3.12, but use AMD's current release notes for actual ROCm 10 GPU and driver requirements; the earlier minimum does not prove ROCm 10 hardware acceptance.

Offline staging reads `torch/version.py` inside the wheel, verifies the ROCm 10 and HIP markers, and rejects DirectML dependencies. The verified official Windows cp312 wheel reports `torch.version.rocm == '10.0.0'` and `torch.version.hip == '7.15.26333'`. These numbers differ; the HIP major version cannot replace the ROCm major version. Packaging stops when sources and versions do not match.

## Offline Release Cache and Network Recovery

Release-side `-RebuildWheelhouse` incrementally completes the cache. Only the explicit `-CleanWheelhouse` option deletes all CPU, ROCm, DirectML, and CUDA caches. CPU SVC/RVC groups are prepared before ROCm so an AMD-index failure cannot leave an unpackageable partial CPU stack. ROCm PyMSS and DDSP component groups hardlink the shared ROCm Torch/SDK wheels, and staging deduplicates them by filename instead of downloading or packaging the large runtime repeatedly.

Resume an interrupted ROCm DDSP batch with:

```powershell
& C:\python3.12.9\python.exe .\install\prepare_wheelhouse.py `
  --root . --stack rocm10 --from-batch "ddsp legacy rocm10 torch"
```

When `ProxyError('Cannot connect to proxy')` or a TLS handshake timeout appears before `ResolutionImpossible`, the latter is usually a secondary pip error caused by an unreadable index, not a real conflict between the pinned versions. Check `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `XB_TORCH_ROCM_INDEX` in the current PowerShell session. After fixing network access, rerun the incremental command without deleting completed ROCm wheels.

PyMSS installs the same ROCm stack in a separate `.venv-pymss` for AMD acceleration. `auto` detects HIP and reports `rocm`; explicit `rocm` fails when unavailable. PyMSS does not use a DirectML backend: the DirectML package carries an isolated CPU Torch 2.7.1 wheel set and runs PyMSS on CPU, avoiding a conflict with the Torch 2.4.1 pin required by `torch-directml`. SVC/RVC/Vocal share `runtimes/svc-rocm10`; a separate DirectML package and RVC DirectML environment remain optional but cannot mix with ROCm Torch.

## DDSP and SeedVC Models

DDSP routes by `model.type` to official loaders: Sins, CombSub, CombSubFast, CombSubSuperFast, Diffusion, DiffusionNew, DiffusionFast, and RectifiedFlow 6.1 / 6.2 / 6.3. The legacy loader is pinned to an official source commit and uses the Python 3.12 / fairseq-fixed `.venv-ddsp-legacy` environment with the same hardware stack as 6.3. Shallow diffusion can import matching DDSP weights and configuration. RectifiedFlow infers its version from auxiliary-network fields and encoder weight format; custom configs may set `xb_ddsp_version: '6.1'`, `'6.2'`, or `'6.3'` explicitly.

SeedVC reads the F0 switch from configuration and supports 44.1 kHz F0, 22.05 kHz non-F0, XLSR tiny, and upstream custom encoder/vocoder combinations. V2 selects official V2 inference from `VoiceConversionWrapper`; CFM is the main weight and AR weights are optional, with upstream download behavior used when absent. Non-F0 and V2 models do not support semitone transposition, so pitch shift must be zero.

Import copies locally referenced encoders, vocoders, and Hugging Face model directories while preserving the model's original configuration. Missing custom base models report their exact path. Variants may require architecture-specific base models not included in the default package. CPU uses FP32 and ROCm uses HIP. SeedVC WAV output supports current torchaudio without TorchCodec. These are loading/runtime compatibility claims, not inference acceptance for every weight.

UVR PyTorch models use ROCm. Windows ONNX Runtime still defaults to its CPU provider; an NVIDIA CUDA provider cannot be used for AMD. Validate acceleration separately for each UVR model.

## Dependency Migration

SVC/RVC/Vocal use NumPy 1.26.4, SciPy 1.13.1, and Python 3.12-compatible dependencies. SVC uses `fairseq-fixed==0.12.3.1`, which provides Windows cp312 wheels and still imports as `fairseq`.

Upstream RVC 0.1.5 pins old fairseq, NumPy, faiss, and OmegaConf versions that cannot resolve on Python 3.12. `install/build_rvc_compat.py` verifies the original wheel RECORD, then creates `rvc-python==0.1.5+xb312`, changing only those four dependencies, the Python requirement, and local package version while preserving upstream inference code and its license. Offline packaging builds the same wheel and does not bypass dependency checks.

Acceptance must cover imports, real short-audio inference, CPU/CUDA regression, and ROCm 10 hardware. Unit tests and wheel metadata checks cannot replace these tests.
