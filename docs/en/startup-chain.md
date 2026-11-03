[简体中文](../startup-chain.md) | **English** | [日本語](../ja/startup-chain.md)

# Startup and Model Inference Flow

This document describes the actual startup relationship between the Python backend and model runtimes. See the [startup and inference sequence diagram](../archify/xb-svcb-startup-inference.sequence.html) for the detailed sequence.

## 1. Desktop Startup

    run.bat
      -> app/.venv/Scripts/python.exe app/main.py
      -> app/main.py
      -> resolve_url()
      -> build_api()
      -> pywebview.create_window(..., js_api=api)
      -> webview.start()

Production mode loads `web/dist/index.html` through the built-in static HTTP server. `--dev` loads the Vite URL. Startup does not load every model checkpoint into the main process.

## 2. Backend Composition

`build_api()` is the composition root. It connects paths, storage, model services, work services, conversion services, editor services, real-time services, and plugin services to the API facade. Calls to `window.pywebview.api.*` ultimately reach these application services.

FastAPI is optional. After a user starts it in the application, Uvicorn listens from a background thread in the GUI process. HTTP routes call the same API and services instead of creating a second application core.

Model worker interpreters are routed through `runtime.json`. CUDA126/CUDA128 routes UVR, SeedVC, and DDSP to `runtimes/core-*`, and SVC, RVC, and Vocal to `runtimes/svc-*`. CPU, ROCm 10, and legacy installations may route to `.venv-*`. Process isolation is not dependency isolation; components in a shared layer use the same validated dependencies.

## 3. Normal Cover Task

    Select audio and model
      -> API facade
      -> Application services
      -> Create task record
      -> Enter serial inference queue
      -> UVR worker: vocal separation / dereverb
      -> EngineRegistry: route by framework
      -> Model worker: load checkpoint and infer
      -> Vocal enhancement when enabled
      -> FFmpeg: mix, transcode, and output
      -> Save work and task state
      -> Frontend polling/push displays the result

“Model worker -> FFmpeg” describes processing order; the model worker does not directly execute FFmpeg. Application services coordinate stages, temporary files, and task state.

## 4. Multi-model and Editor Tasks

- Multi-model tasks first parse lyrics or a timeline and assign segments to one or more models.
- Each model generates vocals in its own engine environment. Application services merge and crossfade them on the timeline.
- Regional editor re-inference processes only the target segment, then refreshes waveforms, caches, and undo history.
- VST3 effects connect to Python audio services through `native/juce-vst3-host`; they do not enter dry model inference.

## 5. Real-time Tasks

The main difference from normal tasks is worker lifetime:

    Start real-time session
      -> Persistent UVR worker
      -> Persistent RVC / SeedVC worker
      -> Read a song file or WASAPI/VB-CABLE audio blocks
      -> Prebuffer and overlap context
      -> Convert vocals
      -> Equal-power crossfade
      -> Preserve accompaniment and play in real time

System-audio mode is limited to one model to keep fixed-block processing and latency predictable. File mode can register a work and export the result.

## 6. Shutdown

The `finally` block in `app/main.py` stops the API and background services, clears temporary content under the active user-data directory, and releases the single-instance handle. Normal shutdown does not remove persistent models or works.

See [Shared Runtime and Compatibility Layout](runtime-consolidation.md) for runtime directories, setup entry points, and repair boundaries.
