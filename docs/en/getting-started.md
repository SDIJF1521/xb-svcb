[简体中文](../getting-started.md) | **English** | [日本語](../ja/getting-started.md)

# Installation, Source Startup, and Repair

Most users should use the online installer, which selects the hardware package automatically. Dedicated offline installers remain available. Running from source is intended for developers and users who need to modify an engine.

## Runtime Prerequisites

- Windows 10 1809 or newer, or Windows 11, 64-bit.
- **Microsoft Visual C++ 2015-2022 x64 Redistributable, latest version**: <https://aka.ms/vs/17/release/vc_redist.x64.exe>. Run it and choose "Repair" even if it is already installed. When it is outdated, or an older `msvcp140.dll` shipped by another application has overwritten it, the `onnxruntime` build that UVR loads crashes while importing (`0xC0000005`) and setup stops at step 4/12 or at the final shared-runtime audit; see [Final install step fails: UVR probes crash](#final-install-step-fails-uvr-probes-crash).
- A GPU driver matching the hardware: CUDA126 for NVIDIA RTX 40-series and older, CUDA128 for RTX 50-series, ROCm 10 as the preferred Windows AMD backend (DirectML optional), CPU when no compatible GPU is available.
- 64-bit CPython 3.12.x: bundled with the installer; source runs need it separately, plus Node.js 20.19+ or 22.12+.

## Online Installation

Download and run the ModelScope edition, `XB-SVCB-Online-Setup-ModelScope.exe`, from GitHub Releases. Choose **Auto detect (recommended)** or select a hardware build manually. The bootstrapper downloads only that complete EXE/BIN set from the ModelScope `v0.1.2` revision, verifies every file with SHA-256, and then starts the localized offline setup. Keep the network connection available and allow access to `www.modelscope.cn`.

GitHub does not publicly provide the fallback `XB-SVCB-Online-Setup.exe`; contact the developer if you need it separately. The bootstrapper does not store repository or OSS credentials on the computer. Verified EXE/BIN files are retained in `XB-SVCB-Downloads\0.1.2\<hardware-stack>\` next to the online installer and launched from there; this directory is not removed when the bootstrapper exits. The folder containing the online installer must be writable. If a download is interrupted or verification fails, run it again. The retained EXE and all same-prefix BIN files can also be kept as a complete offline package.

## Choose an Installer

| Hardware | Installer | Runtime layout |
| --- | --- | --- |
| No compatible GPU | CPU | Isolated compatibility environments |
| Windows AMD Radeon (preferred) | ROCm 10 | SVC / RVC / Vocal shared; other components isolated |
| Windows AMD (optional) | DirectML | Isolated compatibility environments; DDSP automatically uses CPU |
| NVIDIA RTX 40 series or earlier | CUDA126 | Two shared layers: `core-cu126` + `svc-cu126` |
| NVIDIA RTX 50 series Blackwell | CUDA128 | Two shared layers: `core-cu128` + `svc-cu128` |

The minimum CUDA wheel stack is cu126; cu121 is no longer used. Each dedicated package contains only the wheels for its hardware, while the application, models, and engine source code are the same.

The installer includes a complete 64-bit CPython 3.12.x runtime and always uses `tools\python312\python.exe` under the installation directory. Users do not need to install or select Python separately. `uv` does not need to be preinstalled; setup installs it from the bundled bootstrap wheel.

## Runtime Environment After Installation

CUDA126 and CUDA128 share runtimes by default:

| Directory | Components |
| --- | --- |
| `runtimes/core-cu126` / `core-cu128` | UVR, SeedVC, DDSP-SVC |
| `runtimes/svc-cu126` / `svc-cu128` | So-VITS-SVC, RVC, Vocal / DeepFilterNet3 |

CPU uses isolated directories such as `.venv-uvr`, `.venv-svc`, `.venv-rvc`, `.venv-seedvc`, `.venv-ddsp`, and `.venv-vocal`. DirectML is also isolated, but RVC uses `.venv-rvc-directml`. On ROCm 10, SVC / RVC / Vocal share `runtimes/svc-rocm10`, while the other components remain isolated. The application identifies the actual interpreter through `runtime.json`; do not determine whether installation is complete from directory names alone.

RVC inference code ships in `engines/rvc` (an MIT-licensed subset of RVC-Project 2.2.231006); `hubert_base.pt` and `rmvpe.pt` live in `engines/rvc/pretrain` and are seeded by the installer from `assets/models`. The third-party `rvc-python` package is no longer installed.

For the complete layout and compatibility rules for older installations, see [Shared Runtime and Compatibility Layout](runtime-consolidation.md).

## Legacy v0.0.31 Only: RTX 50 Installation Repair

The CUDA128 recipe in v0.0.32 already includes `gin-config`, so the legacy patch below is unnecessary. Use it only when upgrading is temporarily impossible and v0.0.31 fails to install because this dependency is missing. Run the following in PowerShell from the old installation directory:

```powershell
Set-Location 'installation directory'

$lock = Join-Path (Get-Location) 'install\runtime_profiles\core-cu128\requirements.lock'
$profile = Join-Path (Get-Location) 'install\runtime_profiles\core-cu128\profile.json'

if (!(Test-Path -LiteralPath $lock) -or !(Test-Path -LiteralPath $profile)) {
    throw 'The core-cu128 recipe files were not found. Confirm that the current directory is the installation directory.'
}

$utf8 = New-Object System.Text.UTF8Encoding($false)

Copy-Item -LiteralPath $lock -Destination ($lock + '.bak') -Force
Copy-Item -LiteralPath $profile -Destination ($profile + '.bak') -Force

$text = [System.IO.File]::ReadAllText($lock)

if ($text -notmatch '(?m)^gin-config==') {
    $match = [regex]::Match($text, '(?m)^fsspec==[^\r\n]*')
    if (!$match.Success) {
        throw 'The lockfile format is not recognized.'
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

Run "Set up / repair runtime environment" from the Start menu, or execute the following in the installation directory:

```bat
setup_env.bat
```

The installer records the hardware stack and layout in `installer_env.cmd`. Therefore, repairing a CUDA package without arguments still uses shared environments and does not incorrectly create the six legacy isolated environments.

Use `--only` to repair a non-atomic component. The CUDA core components UVR, SeedVC, and DDSP must be repaired as a group:

```bat
setup_env.bat --only uvr seedvc ddsp
setup_env.bat --only svc rvc vocal
setup_env.bat --only models
```

After an installation failure, preserve `assets\wheels` and `install_logs`. The installer removes offline wheels only after every environment passes final validation.

### v0.0.32 CUDA128 Offline Installation Repair

If an RTX 50 series installation reports `The wheel is invalid: Missing .dist-info directory` at `torch-2.7.1+cu128`, this is not a CUDA Toolkit or GPU driver error. Close XB-SVCB, open PowerShell in the installation directory, and verify the Torch wheel extracted by the installer:

```powershell
$root = "E:\XB-SVCB" # Replace with the actual installation directory
$torchWheel = "$root\assets\wheels\py312\cu128\torch-2.7.1+cu128-cp312-cp312-win_amd64.whl"

(Get-Item $torchWheel).Length
(Get-FileHash $torchWheel -Algorithm SHA256).Hash
```

The correct values for the v0.0.32 CUDA128 package are:

```text
Size: 3273024349
SHA256: 2BB8C05D48BA815B316879A18195D53A6472A03E297D971E916753F8E1053D30
```

If the size or hash differs, download the complete CUDA128 installer again and ensure that the installer EXE and every BIN part with the same filename prefix are in one directory. Do not continue repairing the environment with a damaged wheel.

If both values match, obtain the pinned `XB_PYTHON_EXE` path from the installation log or `installer_env.cmd`, then force-reinstall the bundled `uv`, clear the Torch cache, and retry the shared core group:

```powershell
$py = "C:\Path\To\Python312\python.exe" # Replace with XB_PYTHON_EXE
$uv = "$env:APPDATA\Python\Python312\Scripts\uv.exe"

& $py -m ensurepip --upgrade
& $py -m pip install --user --force-reinstall --no-index `
  --find-links "$root\assets\wheels\bootstrap" "uv==0.12.22"
& $uv --version
& $uv cache clean torch

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

If UVR, SeedVC, and DDSP all report success but final validation reports `missing: ["exceptiongroup"]`, Torch and CUDA were installed successfully. Install the local wheel and run the same repair entry point again:

```powershell
& $uv pip install `
  --python "$root\runtimes\core-cu128\Scripts\python.exe" `
  --no-index --no-build `
  --find-links "$root\assets\wheels\py312\cu128" `
  "exceptiongroup==1.3.1"

Set-Location $root
.\setup_env.bat --cu128 --only uvr seedvc ddsp
```

The final output should report that the shared runtime environment is complete and that `runtime.json` was written. `hf-xet` is an optional package that may be absent. DDSP's `Please install tensorboardX` output is also not the cause of this installation failure.

## Source Environment Requirements

- Windows.
- The latest Microsoft Visual C++ 2015-2022 x64 Redistributable (UVR's `onnxruntime` depends on it; see [Runtime Prerequisites](#runtime-prerequisites)).
- Source operation and release builds require 64-bit CPython 3.12.x; normal installations use the bundled runtime.
- Node.js 20.19+ or 22.12+, required only to build the frontend.
- Access to PyPI, model sources, and upstream repositories, or a prepared offline wheelhouse and model assets.
- CMake, Visual C++ Build Tools, and JUCE when building the VST3 Host.

Explicitly select an environment from the source root:

```bat
setup_env.bat --cu128
setup_env.bat --cu126
setup_env.bat --cpu
setup_env.bat --rocm10
setup_env.bat --directml
```

The CUDA arguments invoke the two-layer shared setup. ROCm 10 invokes the compatibility setup with a shared SVC layer. CPU and DirectML invoke isolated setup. Developers may also run the underlying entry points directly:

```bat
setup_shared_env.bat --cu128
python install\install.py --cpu
python install\install.py --rocm10
python install\install.py --directml
```

Every step is repeatable. `install/install.py` still contains shared component implementations and compatibility code for older installations; this does not mean that new CUDA installations use the isolated layout by default.

## Start

Production mode:

```bat
run.bat
```

Equivalent command:

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py
```

Frontend development mode:

```powershell
Set-Location .\web
npm install
npm run dev
```

Then run the following in another terminal:

```powershell
& .\app\.venv\Scripts\python.exe .\app\main.py --dev
```

Production mode loads `web/dist/index.html`. Development mode connects to `http://localhost:5173` by default.

## Data Directory

The default data directory is `.xb_svcb`. It stores the model library, works, editor projects, downloads, settings, logs, and caches. Place it on a disk with sufficient free space. Change its location through the in-app migration feature or `XB_DATA_DIR`.

## Troubleshooting

### Python Cannot Be Found

The offline wheels target `cp312-win_amd64`, so setup always uses its bundled 64-bit CPython 3.12.x runtime. Developers only need to provide Python 3.12 when running from source or producing release packages.

### Frontend Is Missing

Source production mode requires `web/dist/index.html`:

```powershell
Set-Location .\web
npm run build
```

### AI Environment Setup Fails

Inspect `install_logs` in the installation directory. For online repair, configure mirrors first:

```bat
set XB_HF_MIRROR=https://hf-mirror.com
set XB_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
set XB_GH_MIRROR=https://ghfast.top
setup_env.bat
```

### Final install step fails: UVR probes crash

The `uvr_mdx` / `uvr_vr` probes exit with `3221225477` (`0xC0000005`) while `pip check` reports every package as compatible. The cause is the system C++ runtime: the `onnxruntime` pybind extension is statically linked, and when `C:\Windows\System32\msvcp140.dll` is outdated or does not match `msvcp140_1.dll` it faults during initialisation. Windows Event Viewer (Application log, event ID 1000) names `MSVCP140.dll` as the faulting module.

1. Install the latest [Microsoft Visual C++ 2015-2022 x64 Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe); run it and choose "Repair" even if it is already installed.
2. If it still crashes, another application has overwritten `C:\Windows\System32\msvcp140.dll` with an older copy: uninstall the legacy `Microsoft Visual C++ 2015 Redistributable (x64) - 14.0.x` entry under "Apps & features", then repair the 2015-2022 redistributable.
3. All four files must report one version of at least 14.38:

```powershell
foreach ($n in 'msvcp140.dll','msvcp140_1.dll','vcruntime140.dll','vcruntime140_1.dll') {
  "{0} {1}" -f $n, [System.Diagnostics.FileVersionInfo]::GetVersionInfo("$env:SystemRoot\System32\$n").FileVersion
}
```

4. Verify the import, then resume setup:

```bat
runtimes\core-cu126\Scripts\python.exe -c "import onnxruntime; print('ORT_OK')"
setup_env.bat --cu126 --only uvr seedvc ddsp
```

Reinstalling the application, moving the install directory, or rebuilding the Python environment cannot help: the fault is in the system runtime, not in the installation.

### FFmpeg Cannot Be Found

Installer packages include FFmpeg. Running from source requires `ffmpeg` on the system `PATH`, or a complete Windows build placed in `assets/tools/ffmpeg`.

### Startup fails with Failed to resolve Python.Runtime.Loader.Initialize on a non-ASCII path

This is a known pythonnet / clr-loader compatibility issue on Windows paths that contain non-ASCII characters (pythonnet #2141, clr-loader #59): .NET Framework can treat `Python.Runtime.dll` under such a directory as a network location.

At startup the application mirrors the pythonnet runtime and pywebview's WebView2 assemblies to:

```text
%LOCALAPPDATA%\XB-SVCB\clr-mirror
```

and loads them from that ASCII-only path, so the project can stay in a localized directory. If startup still fails, check write access to that directory or move the project to an ASCII-only path.

### Frontend Changes Still Show the Old Page

Rebuild `web/dist`, completely exit the application, and start it again. During development, prefer `--dev` with Vite.
