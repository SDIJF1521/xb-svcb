[简体中文](../runtime-consolidation.md) | **English** | [日本語](../ja/runtime-consolidation.md)

# Shared Runtime and Compatibility Layout

This is the canonical description of the current runtime layout. Earlier storage surveys, cache recovery notes, and experimental installation records have been consolidated here. Historical behavior remains in `docs/release-notes/`.

## Release Policy

NVIDIA CUDA126 and CUDA128 use two shared environments by default. SVC/RVC/Vocal share one environment on ROCm 10; other ROCm components and CPU/DirectML use isolated environments. Every component uses 64-bit CPython 3.12.x. New releases no longer ship or create a cu121 stack.

| Package | Default layout | Main directories |
| --- | --- | --- |
| CPU | Isolated compatibility | `.venv-uvr`, `.venv-svc`, `.venv-rvc`, `.venv-seedvc`, `.venv-ddsp`, `.venv-vocal` |
| ROCm 10 | Shared SVC group | `runtimes/svc-rocm10` for SVC/RVC/Vocal; `.venv-*` for other components, including separate PyMSS |
| DirectML | Isolated compatibility | `.venv-*`; DDSP automatically uses CPU, and PyMSS falls back to CPU in its isolated environment |
| CUDA126 | Two shared layers | `runtimes/core-cu126`, `runtimes/svc-cu126` |
| CUDA128 | Two shared layers | `runtimes/core-cu128`, `runtimes/svc-cu128` |

“Shared” describes dependency layout, not one Python process for every component. The two layers separate modern NumPy/protobuf/AudioTools dependencies from older SVC/RVC constraints.

ROCm 10 setup validates the ROCm major version, HIP, and an actual GPU operation, so CPU Torch cannot be reported as a successful AMD setup. DirectML RVC must remain in `.venv-rvc-directml` and is selected by the `rvc-directml` route in `runtime.json`; it cannot share an environment with ROCm Torch. Only an explicit `device=directml` starts that interpreter. `device=rocm` and `auto` continue to use the ROCm route.

## Component Routing

| Shared layer | Components | Purpose |
| --- | --- | --- |
| `core-cu126` / `core-cu128` | UVR, SeedVC, DDSP-SVC | Unified modern core recipe |
| `svc-cu126` / `svc-cu128` | So-VITS-SVC, RVC, Vocal/DeepFilterNet3 | Shared compatibility layer for older frameworks |

The application no longer infers the layout from fixed directory names. After successful setup, `install/runtime_manifest.py` writes each component's relative Python path to `runtime.json`. The application reads this file first and then falls back to legacy `.venv-*` directories for upgrades.

PyMSS, plugins, and ModelScope Hub are not fixed members of the two AI shared layers. They follow their own implementations and dependency requirements; using an existing interpreter must not change the core/svc release boundary.

## Setup Entry Points

- `install/install_shared.py`: shared orchestrator for CUDA126/CUDA128; exposes only validated sharing policies.
- `install/install.py`: common component setup plus compatibility entry points for CPU, ROCm 10, DirectML, and legacy isolated installs.
- `setup_env.bat`: unified user repair entry point. `installer_env.cmd` records `XB_RUNTIME_LAYOUT` and `XB_GPU_STACK`; CUDA repairs retain the two shared layers and ROCm 10 retains its shared SVC layer.
- `setup_shared_env.bat`: explicit developer entry point for shared-layout testing.

Pinned installer arguments:

```text
CUDA126: --gpu --cu126 --consolidated
CUDA128: --gpu --cu128 --consolidated --core-profile core-cu128
ROCm 10: --rocm10
DirectML: --directml
CPU:      --cpu
```

Install only the separate DirectML RVC environment:

```powershell
python install/install.py --directml --only rvc
```

ROCm RVC retains rvc-python's fp16 GPU path by default. If a driver or model is unstable in fp16, temporarily set `XB_RVC_ROCM_FP32=1`. Worker log entries `RVC_COMPONENT_DEVICES` and `RVC_TIMING` show component devices and model/post-processing time.

SVC, RVC, SeedVC, DDSP-SVC, UVR, PyMSS, F0, and Vocal workers share a quality-first PyTorch policy: disable gradient recording, pin the active CUDA/ROCm device, use highest-precision FP32 matrix operations, and disable TF32 on NVIDIA CUDA. CPU inference uses at most eight Torch threads by default; override with `XB_INFERENCE_CPU_THREADS`. Each worker still chooses FP16/FP32 and DirectML fallback according to its own stability requirements and logs a `*_RUNTIME` line with the backend, device, and precision policy.

The legacy implementation still recognizes `--consolidated`, but releases use it to mean the CUDA shared layout, not a user-facing experiment. Without `XB_RUNTIME_LAYOUT`, running `setup_env.bat` without arguments preserves legacy behavior. Explicit `--cu126`, `--cu128`, or `--consolidated` selects the shared entry point.

## Recipes and Offline Assets

The pinned CUDA128 core recipe is stored in:

- `install/runtime_profiles/core-cu128/requirements.lock`
- `install/runtime_profiles/core-cu128/profile.json`
- `assets/runtime/core-cu128/compat/`
- `assets/runtime/core-cu128/candidate/`
- `assets/runtime/core-cu128/rollback/`

It uses NumPy 2.2.6, protobuf 7.36.0, TensorBoardX 2.6.5, and a local AudioTools compatibility wheel. Hashes and rebuild steps are in the [core-cu128 recipe README](../../install/runtime_profiles/core-cu128/README.md). CUDA126 reuses validated compatibility assets with its own cu126 Torch wheels and runtime directory; it never falls back to cu121.

`install/prepare_wheelhouse.py` prepares caches for five stacks. `installer/stage_wheelhouse.py` stages only the wheels required for a package's target stack. The installer deletes `assets/wheels` from the installed application only after every runtime passes validation; it preserves the directory after failures for offline retries.

CUDA packages must also contain `assets/runtime/core-cu128/candidate` and `compat`. These binaries are not committed to Git. Supply them with `installer/build.ps1 -RuntimeAssets <backup-directory>`. The builder validates the profile lock and every wheel SHA-256 to prevent a package without `protobuf==7.36.0` from being released.

## Atomic Installation and Activation

Shared setup follows these boundaries:

1. UVR, SeedVC, and DDSP are resolved as one core group; do not publish routing for all three after changing only part of the group.
2. Final `pip check` for SVC, RVC, and Vocal is deferred until the complete shared layer is installed.
3. `runtime.json` is updated only after the Python executable, dependencies, Torch/CUDA, critical imports, and compatibility probes all pass.
4. A failure does not declare a partial environment usable or remove legacy `.venv-*` directories or user models.
5. Repairs must keep the same layout. A shared CUDA installation must not use legacy isolated entry points to overwrite packages component by component.

## Validation Commands

Validate installer scripts only:

```powershell
& .\installer\build.ps1 -ValidateOnly
```

Resolve the CUDA128 core recipe without installing:

```powershell
& .\setup_shared_env.bat --cu128 --only uvr seedvc ddsp --preflight-only
```

Audit installed shared environments:

```powershell
& .\runtimes\core-cu128\Scripts\python.exe -B .\install\audit_runtime.py --root . --require-cuda --timeout 90 --ddsp-timeout 180
& uv pip check --python .\runtimes\core-cu128\Scripts\python.exe
& uv pip check --python .\runtimes\svc-cu128\Scripts\python.exe
```

See [Testing](testing.md) for automation boundaries and commands. Recipe resolution, repeated installation, drift detection, recovery, imports, small CUDA tensors, and installer preflight have regression coverage. They do not replace real models, real audio, and complete Setup.exe acceptance on target GPUs.

## Legacy Installs and Cleanup

Legacy `.venv-*` directories are compatibility fallbacks, not targets for new CUDA installs, and CUDA setup does not remove them. When ROCm 10 migrates to `svc-rocm10`, it removes legacy `.venv-svc` and `.venv-vocal` only after SVC/RVC/Vocal all install and pass final dependency validation. Legacy `.venv-rvc` may contain separate DirectML Torch and is retained. External scripts should read `runtime.json` before upgrading; remove other legacy directories only after confirming nothing references them.

Do not treat these as source cleanup targets:

- Active local environments under `runtimes/`.
- Models, works, editor projects, and logs in `.xb_svcb` or a custom data directory.
- The global uv cache, which other projects may reuse.
- Recipe, compatibility, and rollback assets under `assets/runtime/core-cu128`.

Repository paths `.tmp/`, `build/`, `dist/`, `assets/wheels/`, and `assets/tools/python312/` are rebuildable or machine-generated and excluded through `.gitignore`. Decide whether to remove local copies separately from source commits.
