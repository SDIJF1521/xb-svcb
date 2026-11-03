[简体中文](../README.md) | **English** | [日本語](../ja/README.md)

# XB-SVCB Documentation

This index groups documentation for users, contributors, and plugin authors. The English project overview is available in the [root README](../../README.en.md).

All current Markdown documentation under `docs/` is available in English. Release notes through v0.0.32 remain Chinese-only; releases from v0.1.0 onward include English and Japanese. Package-level documents outside `docs/` are marked when they remain Chinese.

## Users

- [Installation, source setup, and troubleshooting](getting-started.md): hardware packages, runtime layout, startup modes, data directories, and common repairs.
- [Python 3.12 and ROCm 10 migration](python312-rocm10.md): AMD installation, model compatibility, and dependency migration.
- [FastAPI integration](api.md): server startup, authentication, task endpoints, uploads, downloads, and examples.
- [API management changes](api-management.md): domain binding and multiple API key support.
- Model weights, manifests, and configurations are maintained in the external model community and must be synchronized to local `assets/models/` before a release build.

## Contributors

- [System architecture](architecture.md): responsibilities and connections between the Python backend, Vue frontend, workers, queues, models, and audio tools.
- [Startup and inference flow](startup-chain.md): application startup, normal jobs, and real-time processing.
- [Development and release](development.md): repository layout, tests, frontend builds, JUCE host, and installer builds.
- [Testing and acceptance](testing.md): automated groups, packaging integration, and hardware acceptance boundaries.
- [Installer guide](../../installer/README.md) **Chinese**: PyInstaller, runtimes, the offline wheelhouse, and Inno Setup split archives.
- [Shared runtime and compatibility layout](runtime-consolidation.md): CUDA shared layers, ROCm 10 sharing, CPU / DirectML compatibility, and repair boundaries.
- [Contributing guide](../../CONTRIBUTING.md) **Chinese**: issue reports, development setup, testing, and pull-request expectations.

## Plugin Authors

- [Plugin development overview](plugins/README.md)
- [Complete plugin development guide](plugin-development.md)
- [Plugin SDK README](../../plugin-sdk/README.md) **Chinese**

## Architecture Artifacts

- [System architecture diagram](../archify/xb-svcb-system.architecture.html)
- [System architecture JSON](../archify/xb-svcb-system.architecture.json)
- [Startup and inference sequence diagram](../archify/xb-svcb-startup-inference.sequence.html)

## Release Notes

Release history is kept in [`docs/release-notes`](../release-notes/). Starting with v0.1.0, release notes are published in Simplified Chinese, English, and Japanese.

- [v0.1.0](../release-notes/release_notes_v0_1_0.en.md): creation and inference, audio editor, multilingual UI and installer, online setup, and model-repository changes.
- [v0.0.32](../release-notes/release_notes_v032.md): Python 3.12, ROCm 10, and DirectML inference fixes.
- [v0.0.31](../release-notes/release_notes_v031.md): shared runtimes, first-run onboarding, and high-note / belting stability.
