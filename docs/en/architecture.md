[简体中文](../architecture.md) | **English** | [日本語](../ja/architecture.md)

# System Architecture

XB-SVCB is a local-first desktop application. The frontend handles interaction and state display, Python orchestrates application logic, and heavy models and audio tools run in isolated workers.

## Overall Structure

    Desktop user -> pywebview + Vue 3 -> API facade -> Application services
    External client -> FastAPI ----------------------> API facade
                                                           |
                                              Serial inference queue / local data
                                                           |
                                  UVR -> EngineRegistry -> Model worker -> FFmpeg
                                                           |
                                                   Offline model assets

Open the [annotated system architecture diagram](../archify/xb-svcb-system.architecture.html) for the complete layout and explanatory cards.

## Connections

| Connection | Purpose |
| --- | --- |
| Desktop user -> pywebview + Vue | Select audio, models, devices, and inference parameters, and view task state. |
| External client -> FastAPI | Upload audio, create tasks, query progress, and download results over HTTP. The service is disabled by default. |
| Vue -> API facade | The frontend calls Python methods through `window.pywebview.api`. |
| FastAPI -> API facade | The HTTP layer reuses the desktop bridge API instead of duplicating business rules. |
| API facade -> Application services | Dispatch UI or HTTP requests to work, model, conversion, editor, and other use-case services. |
| Application services -> Serial inference queue | Create and queue tasks while controlling peak GPU memory and task state. |
| Serial inference queue -> EngineRegistry | Select the So-VITS-SVC, RVC, SeedVC, or DDSP-SVC adapter from the model's `framework`. |
| Application services -> UVR worker | Run vocal/accompaniment separation, dereverb, and other preprocessing. |
| EngineRegistry -> Model worker | Start or reuse an isolated worker. Checkpoints are loaded inside the worker. |
| Model worker -> Offline model assets | Read the main model, base models, F0 model, vocoder, and framework configuration. |
| Application services -> Vocal enhancement | Optionally repair, align, tune, and master vocals according to task settings. |
| Model worker -> FFmpeg | Indicates that inference output enters post-processing and final mixing; application services make the actual FFmpeg calls. |

## Main Modules

### `app/main.py`

Desktop entry point. It enforces a single instance, resolves development or production mode, creates the pywebview window, binds the API, and stops background services and removes temporary files on exit.

### `app/api/`

Presentation layer:

- `bridge.py` defines the API exposed to Vue and the `build_api()` composition root.
- `http_server.py` creates the FastAPI/Uvicorn service that users start and stop manually.

### `app/application/`

Use-case and orchestration layer. It contains services for models, works, music sources, audio editing, real-time conversion, plugins, and conversion tasks. Normal inference tasks enter the serial queue in `conversion_service.py`.

### `app/domain/`

Contains domain objects and enums for editor projects, tasks, and models, with minimal dependency on pywebview, FastAPI, or concrete AI frameworks.

### `app/infrastructure/`

Implements file storage, paths, FFmpeg, system audio, UVR, F0, engine adapters, and workers. `svc_engine.py`, `rvc_engine.py`, `seedvc_engine.py`, and `ddsp_engine.py` are the framework adapter entry points.

### `web/`

Vue 3 + Vite frontend. `views/` organizes pages, `stores/` manages cross-page state, and `src/api/` defines pywebview bridge and HTTP types.

## Runtime Boundaries

- The main environment contains only the desktop shell, APIs, and application services.
- NVIDIA CUDA126/CUDA128 uses two shared layers by default: UVR, SeedVC, and DDSP in `runtimes/core-*`; So-VITS-SVC, RVC, and Vocal in `runtimes/svc-*`. SVC/RVC/Vocal share `runtimes/svc-rocm10` on ROCm 10. Other ROCm components and CPU/DirectML use isolated environments, while legacy installations may fall back to `.venv-*`. The installer writes interpreters to `runtime.json` only after dependencies, Torch/device checks, and critical imports pass. See [Shared Runtime and Compatibility Layout](runtime-consolidation.md).
- Workers are separate processes; dependencies are isolated only when separate Python environments are used. Separate processes using a shared interpreter do not eliminate package-version conflicts and are not an OS security sandbox.
- FastAPI and the desktop UI share one task queue, so tasks created through either entry point are visible in the same application.
- Normal tasks usually run serially. Real-time mode keeps UVR and model workers alive to reduce repeated loading.
