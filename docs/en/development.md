[简体中文](../development.md) | **English** | [日本語](../ja/development.md)

# Development and Release

## Recommended Workflow

    Install the source environment
      -> Modify app / web
      -> Run Python and frontend tests
      -> Build web/dist
      -> Start the desktop application and verify the bridge
      -> Verify FastAPI, models, and workers
      -> Build the JUCE host when required
      -> Run release validation
      -> Build the Inno Setup installer

## Backend Development

Main-application dependencies are declared in `app/pyproject.toml`; the runtime entry point is `app/main.py`. Start with `app/api/bridge.py` and `app/application/` to follow application calls, then inspect concrete engines and workers in `app/infrastructure/`.

Run tests:

    cd app
    uv run pytest

Important coverage includes model services, inference regressions, device detection, HTTP APIs, real-time conversion, the editor, plugins, and installer runtimes.

## Frontend Development

    cd web
    npm install
    npm run dev
    npm run type-check
    npm run build
    npm run test:unit -- --run

The frontend build is written to `web/dist`, which the production desktop application loads as a bundled resource.

## JUCE VST3 Host

Set the JUCE path and build:

    $env:XB_JUCE_DIR="C:\path\to\JUCE"
    .\native\juce-vst3-host\build.ps1

The output should be `engines/juce-vst3-host/xb-juce-vst3-host.exe`. See the installer documentation for limitations and plugin compatibility.

## Building Installers

Build scripts support `-Help` or `--help` without running preflight checks or packaging.

Lightweight validation:

    .\installer\build.ps1 -ValidateOnly

Build the default CUDA128 shared-runtime package:

    .\installer\build.ps1

Build the CPU, ROCm 10, DirectML, CUDA126, and CUDA128 packages in sequence:

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe

When CUDA shared-core assets are stored outside Git, provide their directory:

    .\installer\build-all-packages.ps1 -Python C:\path\to\python.exe -RuntimeAssets D:\XB-SVCB\assets\runtime\core-cu128

The build process:

1. Validates the application, frontend, version, and critical runtime payloads.
2. Builds the Vue frontend once and reuses it across all five packages.
3. Builds the desktop application and bundled resources with PyInstaller once and reuses them.
4. Builds or reuses the JUCE VST3 host.
5. Filters the offline wheelhouse for the target stack and verifies CUDA candidate/compat assets and runtime payloads.
6. Uses Inno Setup to create a hardware-specific EXE and matching `.bin` parts smaller than 2 GB.

Upload the EXE and every BIN part for a release. See `installer/README.md` for runtime contents and split-archive rules.

## Documentation Conventions

- Keep only the project overview, quick start, and documentation links in the root README.
- Maintain API details only in `docs/api.md` and its translations.
- Prefer `docs/plugins/` for plugin documentation; the legacy single-file guide remains for compatibility and full-text search.
- Store architecture source data in `docs/archify/*.json`; HTML files are deliverable viewing artifacts.
- Keep version notes in `docs/release-notes/release_notes_vXYZ.md`; the README links only the current version.
- Update the corresponding documents when startup behavior, directories, environment names, or API contracts change.
