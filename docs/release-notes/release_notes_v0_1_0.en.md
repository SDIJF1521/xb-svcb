# XB-SVCB v0.1.0 Release Notes

[简体中文](release_notes_v0_1_0.md) | **English** | [日本語](release_notes_v0_1_0.ja.md)

`0.1.0` is the first XB-SVCB release to provide the application UI, installer, and release notes in Simplified Chinese, English, and Japanese. This release focuses on the creation workflow, audio editor, inference safeguards, theme system, and distribution process, and aligns all application and installer versions at `0.1.0`.

The release range starts at and includes commit `fc8d214e068457a273929e80c108b33f55b4e9e8` ("replace the full-parameter speaker text field with a selector"). Use the following range when generating commit lists or auditing changes:

```text
fc8d214e068457a273929e80c108b33f55b4e9e8^..HEAD
```

Starting with `0.1.0`, every new release must publish matching Simplified Chinese, English, and Japanese release notes covering the same release scope and compatibility requirements.

## Interface and languages

- Added Simplified Chinese, English, and Japanese UI switching. The choice is persisted and applied before Vue pages and Element Plus components initialize, reducing language flashes during startup.
- Added English and Japanese text for the home, creation, editor, works, models, plugins, vocal enhancement, and API management workflows.
- Adjusted buttons, selectors, forms, and editor panels for longer English and Japanese labels so translated text does not clip or cover adjacent controls.
- Consolidated the first-use guide from 37 fragmented steps into 10 workflow-oriented steps while retaining model preparation, task creation, and editor export guidance.
- Fixed horizontal layout movement during theme changes and improved synchronization between theme transitions and the native window background.

## Creation and inference

- Replaced free-form speaker input in full-parameter mode with model-provided options. So-VITS-SVC reads speaker names from model configuration, while DDSP-SVC generates numeric choices from the model's declared speaker count.
- Invalid model configuration, unreasonable speaker counts, or missing speaker metadata now fall back to an empty selection instead of producing unusable option lists.
- Normal conversion now lets the system manage high-pitch protection when full-parameter mode is enabled and the retry count is `0`. Real-time conversion retains the existing meaning of `0`: no protection retry.
- High-pitch protection first lowers extreme regions while preserving formants, then restores the original pitch and compensates loudness after inference. Retries adjust the internal protection boundary based on detected dropouts.
- Added RVC v1/v2 structure detection and compatibility warnings. When a model cannot be identified reliably, the existing compatibility setting is retained instead of being silently rewritten.
- Updated API documentation for high-pitch protection, full-parameter controls, and editor partial re-inference, including ranges, defaults, and normal versus real-time behavior.

## Audio editor

- Added context menus for empty timeline areas, tracks, and clips, making common clip, track, and effect actions available at the current pointer location.
- Split effects into independent clip, track, and role scopes. Each scope can enable, bypass, configure, and remove its own effects while preserving routing boundaries during rendering.
- Expanded built-in processing and plugin workflows with scoped effect buses, plugin editor synchronization, monitored preview, and automatic dry-signal bypass for invalid plugin output.
- Added stage progress, status details, and continuously appended logs for partial re-inference. Model validation, inference, and clip replacement can be inspected while the task is still running.
- Applicable clip effects are retained after re-inference. Plugin effects that cannot safely be reapplied are recorded in project metadata instead of being applied twice without notice.
- Improved editor panels, timeline selection, project lists, playback interactions, and responsive layouts.

## Themes and assets

- Added and revised built-in themes and replaced the default brand assets. The application and installer now use `web/public/favicon.ico` as their common icon source.
- Custom backgrounds support JPG, PNG, WebP, GIF, AVIF, HEIC/HEIF, and MP4. Media is stored in the application theme directory and is no longer constrained by browser local-storage limits.
- Large still images are automatically resized and converted through FFmpeg to reduce startup memory and configuration size. Theme media operations are confined to the theme directory to avoid deleting external files.
- Custom themes support overlay strength, image/video type, and particle controls, and synchronize native window chrome after theme changes.

## Installer and online setup

- The offline installer supports Simplified Chinese, English, and Japanese. It preselects the Windows UI language and always lets the user change it.
- The wizard, dependency checks, hardware selection, bundled-Python validation, data directory selection, progress, errors, runtime validation, completion page, and shortcuts use one synchronized set of translated message keys.
- All five offline installers now include a clean 64-bit CPython 3.12.x runtime and complete FFmpeg/ffprobe payload. Installation and later repairs use these bundled runtimes instead of depending on global Python or FFmpeg installations.
- Fixed false CUDA shared-runtime failures on slower GPUs or first cold starts where DDSP import exceeded 45 seconds. Shared setup now allows 90 seconds for ordinary imports and 180 seconds for DDSP cold start; timeouts remain explicit failures and never activate an incomplete `runtime.json`.
- Simplified Chinese and Japanese Inno Setup language files are stored in the repository, so builds do not depend on optional language packs installed on the build machine.
- Added a lightweight online installer that detects CPU, NVIDIA CUDA 12.6/12.8, and AMD ROCm 10, with an explicit DirectML compatibility option. It downloads only the selected offline installer family.
- Restored `pymss/py312/cpu` in the DirectML package. PyMSS uses CPU Torch 2.7.1 in its isolated `.venv-pymss` instead of mixing with the Torch 2.4.1 runtime pinned by `torch-directml`.
- The online manifest pins the size and SHA-256 of every EXE/BIN file, while the online bootstrapper pins the manifest SHA-256. The offline installer starts only after all checks pass.
- The public OSS HTTPS URL is injected at build time. No AccessKey, secret, or long-lived signed URL is embedded in the installer.
- Five-stack wheelhouse preparation is now incremental. Only `-CleanWheelhouse` deletes cached wheels, and interrupted downloads can resume at a named batch.
- CPU SVC/RVC components are prepared before ROCm batches so an AMD source failure cannot leave the CPU package apparently present but incomplete.
- ROCm component groups reuse shared Torch/SDK wheels through hardlinks, reducing repeated downloads and disk use for PyMSS, DDSP, and related components.

## Models and repository

- The Git repository no longer tracks model weights, manifests, or configuration under `assets/models/`. Models are maintained by the external model community and must be synchronized locally before a release build.
- Offline installers can still include a complete locally prepared `assets/models/` directory. Repository ignore rules do not prevent the installer from reading those local files.
- Models, works, editor projects, themes, API settings, and plugin data continue to use the existing data directory. An in-place upgrade does not intentionally delete user data.

## Development and documentation

- Root READMEs, user guides, development guides, API documentation, and plugin documentation now provide Simplified Chinese, English, and Japanese entry points.
- Added type annotations across Python services, infrastructure, installation scripts, and wheelhouse tools, together with Pyright configuration to catch interface drift before release.
- Added checks for translation-key parity, installer messages in all three languages, RVC model detection, inference devices, theme media, editor effect scopes, and installer runtime plans.
- Aligned the backend, Python package and lock file, frontend and lock file, PyInstaller resources, and installer version at `0.1.0`.

## Compatibility and upgrade notes

- Python 3.12 and hardware-specific runtime layouts remain in use. Installer profiles are available for CPU, ROCm 10, DirectML, CUDA 12.6, and CUDA 12.8.
- DirectML is primarily a compatibility path. DDSP automatic device selection still prefers CPU; explicitly selected experimental DirectML output should be auditioned before use.
- The online installer requires access to the configured OSS/HTTPS endpoint. For fully offline deployment, download the EXE and every matching BIN part for the selected hardware stack.
- Back up the user data directory before upgrading from an older version. The installer does not migrate or remove existing models, works, or editor projects, but external model storage remains the publisher's or user's responsibility.

See [Installation and startup](../en/getting-started.md) for setup and repair, and the [installer documentation](../../installer/README.md) for builds, online publishing, and OSS configuration.
