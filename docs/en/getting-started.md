[简体中文](../getting-started.md) | **English** | [日本語](../ja/getting-started.md)

# Installation, Source Setup, and Troubleshooting

Most users should install the package built for their hardware. Source setup is intended for contributors and users who need to modify an engine.

## Choose a Package

| Hardware | Package | Runtime layout |
| --- | --- | --- |
| No compatible GPU | CPU | Isolated compatibility environments |
| Windows AMD Radeon (preferred) | ROCm 10 | Shared SVC / RVC / Vocal runtime; other components isolated |
| Windows AMD (alternative) | DirectML | Isolated environments; DDSP automatic mode uses CPU |
| NVIDIA RTX 40 series or older | CUDA126 | `core-cu126` + `svc-cu126` shared environments |
| NVIDIA RTX 50 series (Blackwell) | CUDA128 | `core-cu128` + `svc-cu128` shared environments |

The minimum supported CUDA wheel stack is cu126; cu121 is no longer used. Each hardware-specific package includes only its own wheels, while the application, model assets, and engine sources are identical.

The installer does not bundle a complete Python distribution. Select a 64-bit CPython 3.12.x interpreter. If automatic detection chooses the wrong interpreter, select `python.exe` manually. You do not need to install `uv`; the installer bootstraps it from an included wheel.

Download the installer EXE and **all BIN parts with the same filename prefix**, keep them in one directory, and then run the EXE.

## Runtime Layout After Installation

CUDA126 and CUDA128 use shared layers:

| Directory | Components |
| --- | --- |
| `runtimes/core-cu126` / `core-cu128` | UVR, SeedVC, DDSP-SVC |
| `runtimes/svc-cu126` / `svc-cu128` | So-VITS-SVC, RVC, Vocal / DeepFilterNet3 |

CPU uses isolated directories such as `.venv-uvr`, `.venv-svc`, `.venv-rvc`, `.venv-seedvc`, `.venv-ddsp`, and `.venv-vocal`. DirectML is also isolated, with RVC in `.venv-rvc-directml`. ROCm 10 shares SVC, RVC, and Vocal in `runtimes/svc-rocm10` and keeps the other components isolated.

The application reads `runtime.json` to find the actual interpreter. Do not decide whether a component is installed based only on a directory name. See [Shared Runtime and Compatibility Layout](runtime-consolidation.md).

## Requirements for Source Setup

- Windows.
- 64-bit CPython 3.12.x, matching the current `cp312-win_amd64` offline wheels.
- Node.js 20.19+ or 22.12+ for frontend builds.
- Access to PyPI, model providers, and upstream repositories, unless the offline wheelhouse and model assets are already available.
- FFmpeg for source-based audio processing.
- CMake, Visual Studio Build Tools with C++17 support, and JUCE when building the VST3 host.

From the repository root, explicitly select one hardware stack:

```bat
setup_env.bat --cu128
setup_env.bat --cu126
setup_env.bat --cpu
setup_env.bat --rocm10
setup_env.bat --directml
```

CUDA setup uses the two shared runtime layers. ROCm 10 uses the compatible layout with a shared SVC layer. CPU and DirectML use isolated environments. Advanced users may run the underlying entry points directly:

```bat
setup_shared_env.bat --cu128
python install\install.py --cpu
python install\install.py --rocm10
python install\install.py --directml
```

Setup is repeatable. The presence of common component code and legacy compatibility code in `install/install.py` does not mean that a new CUDA installation uses the old isolated layout.

To install or repair selected component groups:

```bat
setup_env.bat --only uvr seedvc ddsp
setup_env.bat --only svc rvc vocal
setup_env.bat --only models
```

UVR, SeedVC, and DDSP are an atomic CUDA core group and must be repaired together. Preserve `assets\wheels` and `install_logs` after a failure. The installer removes offline wheels only after every environment passes final validation.

## Start the Application

Production mode:

```bat
run.bat
```

Equivalent PowerShell command:

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py
```

For frontend development, start Vite in one terminal:

```powershell
Set-Location .\web
npm install
npm run dev
```

Start the Python backend in another terminal:

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py --dev
```

Production mode loads `web/dist/index.html`. Development mode connects to `http://localhost:5173` by default; set `XB_DEV_URL` to use another URL.

## User Data

The default user-data directory is `.xb_svcb`. It stores the model library, works, editor projects, downloads, settings, logs, and caches. Choose a disk with enough free space. Move the directory from the application or set `XB_DATA_DIR`. Application upgrades normally do not overwrite it.

## Troubleshooting

### Python is not found or rejected

The installer accepts a working 64-bit CPython 3.12.x interpreter because the offline wheels target `cp312-win_amd64`. Prefer a standard Python or Conda interpreter, not a virtual environment belonging to another AI project.

### The frontend is missing

Source production mode requires `web/dist/index.html`:

```powershell
Set-Location .\web
npm install
npm run build
```

### Runtime setup fails

Inspect `install_logs` in the installation directory. For online repair, mirrors can be configured before rerunning setup:

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
setup_env.bat
```

The installer writes the selected hardware stack and layout to `installer_env.cmd`. Running setup without arguments from an installed CUDA package therefore retains the shared layout.

### CUDA128 reports an invalid Torch wheel

In v0.0.32, an error such as `The wheel is invalid: Missing .dist-info directory` while installing `torch-2.7.1+cu128` indicates a damaged package file, not a CUDA Toolkit or driver problem. Close XB-SVCB and verify the wheel from PowerShell, replacing the installation path:

```powershell
$root = "E:\XB-SVCB"
$torchWheel = "$root\assets\wheels\py312\cu128\torch-2.7.1+cu128-cp312-cp312-win_amd64.whl"

(Get-Item $torchWheel).Length
(Get-FileHash $torchWheel -Algorithm SHA256).Hash
```

The expected v0.0.32 CUDA128 values are:

```text
Size:   3273024349
SHA256: 2BB8C05D48BA815B316879A18195D53A6472A03E297D971E916753F8E1053D30
```

If either value differs, download the complete CUDA128 package again and verify that the EXE and every matching BIN part are in the same directory. Do not use the damaged wheel to repair the environment.

If both values match, obtain the pinned `XB_PYTHON_EXE` path from the setup log or `installer_env.cmd`, reinstall the bundled `uv`, clear the Torch cache, and retry the shared core group:

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

If all three components succeed but final validation reports `missing: ["exceptiongroup"]`, install the included wheel and validate again:

```powershell
& $uv pip install `
  --python "$root\runtimes\core-cu128\Scripts\python.exe" `
  --no-index --no-build `
  --find-links "$root\assets\wheels\py312\cu128" `
  "exceptiongroup==1.3.1"

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

`hf-xet` is allowed to be absent. DDSP's `Please install tensorboardX` output is also not the cause of this setup failure.

### `pkg_resources` is missing during inference

The SVC environment may require a compatible setuptools version. For a CUDA128 installation, run:

```powershell
uv pip install --python <installation-directory>\runtimes\svc-cu128\Scripts\python.exe "setuptools<81" wheel
```

### FFmpeg is not found

Installer packages include FFmpeg. Source builds require `ffmpeg` on `PATH`, or a complete Windows build placed in `assets/tools/ffmpeg`.

### Frontend changes do not appear

Rebuild `web/dist`, fully exit the application, and restart it. During development, prefer `--dev` with the Vite server.

### Legacy v0.0.31 CUDA128 setup

v0.0.32 already includes `gin-config`. The manual lockfile patch applies only to installations that must remain on v0.0.31. See the [canonical Chinese guide](../getting-started.md#仅旧版-0031rtx-50-安装修复) for that legacy procedure, or upgrade to v0.0.32.
