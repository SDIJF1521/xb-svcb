[简体中文](../testing.md) | **English** | [日本語](../ja/testing.md)

# Test Groups and Acceptance Boundaries

Run commands from the repository root. `uv` overlays the test tools and SciPy without installing Torch into the main application environment:

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest app/tests -q -rs
```

Add `--offline` after the cache is populated. `-rs` displays every skip reason. A successful test exit does not mean that real inference or release acceptance has passed.

## Groups

| Marker | Contents | Selection |
| --- | --- | --- |
| `runtime` | Recipes, routing, workers, and audio helpers; not complete model inference | `-m runtime` |
| `installer` | Python detection and install/repair safeguards | `-m installer` |
| `packaging` | Offline package plans and packaging rules | `-m packaging` |
| `packaging_integration` | Package-plan checks using actual engine requirements | `-m packaging_integration` |
| `model_inference` | Reserved for real weights/audio acceptance; disabled by default | `-m model_inference --run-model-inference` |

The last group currently has no automated acceptance cases; an empty selection is not a pass. Manual real-inference acceptance is currently deferred. Other application/API tests remain in the full suite instead of being forced into runtime or installer groups.

For example, run only packaging unit tests:

```powershell
uv run --project app --with pytest --with scipy==1.13.1 pytest -m "packaging and not packaging_integration" -q -rs
```

## Resolution of Four Previous Failures

- Two Python detection tests: removed the unreliable `if exist "python.exe\"` directory check, which could incorrectly match a valid Python on drive C. Detection now executes a version probe; directories and non-Python programs are rejected. Existing positive and stale-path fallback cases remain, with a new negative case for a directory named `python.exe`.
- Two packaging assertions moved to `test_wheelhouse_plan.py`. They use temporary engine requirements and retain version/isolation assertions. Generated intermediate requirements stay under the test root and do not modify upstream files.
- A real-source integration check lists component names and absolute paths and skips when SVC/SeedVC/DDSP requirements are missing. Missing inputs are not reported as model dependency failures, and coverage is not deleted.

Release checks must require all inputs:

```powershell
uv run --project app --with pytest pytest -m packaging_integration --require-packaging-inputs -q
```

Missing files fail in this mode instead of producing a green release through skips. This still validates only the packaging plan, not Inno compilation or a clean installation.

## Release Acceptance Order

Passing-test counts change as tests are added, so they are not fixed in documentation. For every release:

1. Run the full Python suite and review all skip reasons.
2. Force `packaging_integration`; do not allow missing requirements to skip it.
3. Run `installer/build.ps1 -ValidateOnly` to check all five Inno configurations and shared entry points.
4. Build each target package and, in a clean directory, complete Setup.exe installation, runtime creation, and final Torch validation.
5. Run real-model and short-audio acceptance on CPU, ROCm 10, DirectML, CUDA126, and CUDA128 hardware. Listen to experimental DDSP DirectML output as well.

See [Shared Runtime and Compatibility Layout](runtime-consolidation.md) for recipe resolution, atomic activation, repair, and rollback boundaries. Automated success proves only the asserted code and packaging behavior, not real-model inference or acceptance on all five hardware classes.
