[简体中文](../api.md) | **English** | [日本語](../ja/api.md)

# XB-SVCB FastAPI Integration

Applies to XB-SVCB 0.0.32.

## Startup and Security

FastAPI is disabled by default and does not start with XB-SVCB. Open **Library -> API Access**, configure the listening scope and port, and select **Start service**. Closing XB-SVCB or selecting **Stop service** releases the port.

- Local only: listens on `127.0.0.1`, suitable for automation on the same computer.
- LAN: listens on `0.0.0.0`. Devices on the same network use the LAN address shown in the application. You may enter a domain that already resolves to this computer; switching back to local mode clears it.
- Default port: `8760`; choose any free port from `1024` through `65535`.
- Authentication: every request except `GET /health`, `/docs`, `/redoc`, and `/openapi.json` requires `X-API-Key`.
- API keys: manage multiple named keys with expiration and enabled state. Only enabled, unexpired keys authenticate. At least one key is retained. Stop the service before editing, deleting, enabling, or disabling keys. Legacy single-key settings migrate when read.

Use LAN mode only on trusted networks. Domain binding changes the displayed access URL; it does not configure DNS, HTTPS, or public-network security. Allow XB-SVCB on private networks if Windows Firewall prompts. Do not expose the port directly to the public internet.

## Interactive Documentation

After startup:

- Swagger UI: `http://127.0.0.1:8760/docs`
- ReDoc: `http://127.0.0.1:8760/redoc`
- OpenAPI JSON: `http://127.0.0.1:8760/openapi.json`

Replace the port when configured differently. LAN mode may use the domain URL shown in the status page. The in-app connectivity test calls the model endpoint with a currently valid key and returns latency and model count.

## Standard Call Flow

1. Upload source audio with `POST /api/v1/uploads` and retain its `upload_id`.
2. Read models and `default_id` with `GET /api/v1/models`.
3. Create a single- or multi-model task with `POST /api/v1/jobs`; it returns HTTP `202`. Use `POST /api/v1/jobs/batch` for batches.
4. Poll `GET /api/v1/jobs/{job_id}` until `status` is `done` or `failed`.
5. On success, download the result from `result_url`.

Tasks use the same serial inference queue as the UI and are mutually visible. They use the CUDA, ROCm 10, DirectML, or CPU runtime included in the current installation.

## Model Management

Renaming a model changes only its display name, not its ID, weights, configuration, or source record:

```http
PATCH /api/v1/models/{model_id}
Content-Type: application/json

{"name": "New display name"}
```

## PyMSS Vocal Processing

PyMSS catalog entries expose only `vocal_separation` and `dereverb`. List the catalog before downloading a required model:

```http
GET /api/v1/preprocess/pymss/models?purpose=vocal_separation
POST /api/v1/preprocess/pymss/models/UVR-DeEcho-DeReverb.pth/download
DELETE /api/v1/preprocess/pymss/models/UVR-DeEcho-DeReverb.pth
GET /api/v1/preprocess/pymss/downloads
```

Place preprocessing in `preprocess` when creating a cover task. Dereverb runs after vocal separation. Legacy fields `harmony_removal_enabled` and `harmony_model` remain supported:

```json
{
  "preprocess": {
    "enabled": true,
    "engine": "pymss",
    "pymss_model": "bs_roformer_voc_hyperacev2",
    "harmony_removal_enabled": true,
    "harmony_model": "UVR-DeEcho-DeReverb.pth"
  }
}
```

`harmony_removal_enabled` defaults to `false`. Downloads immediately enter the unified transfer center; query `GET /api/v1/preprocess/pymss/downloads`. A task fails with a specific message when the model is absent, PyMSS is unavailable, or the model has an unsupported purpose.

Editor clips use the same preprocessing:

```json
{
  "engine": "pymss",
  "pymss_model": "bs_roformer_voc_hyperacev2.ckpt",
  "harmony_removal_enabled": true,
  "harmony_model": "UVR-DeEcho-DeReverb.pth",
  "mute_source": true,
  "device": "auto"
}
```

Send this to `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/separate`. Projects created from cover works retain the original task's `preprocess` settings.

## Python Example

Install `requests`:

```bash
pip install requests
```

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8760"
HEADERS = {"X-API-Key": "replace with the API key shown in XB-SVCB"}

with open("song.wav", "rb") as audio:
    response = requests.post(
        f"{BASE_URL}/api/v1/uploads",
        headers=HEADERS,
        files={"file": ("song.wav", audio, "audio/wav")},
        timeout=None,
    )
    response.raise_for_status()
    upload = response.json()

models = requests.get(f"{BASE_URL}/api/v1/models", headers=HEADERS, timeout=30)
models.raise_for_status()
model_data = models.json()
model_id = model_data["default_id"] or model_data["items"][0]["id"]

response = requests.post(
    f"{BASE_URL}/api/v1/jobs",
    headers=HEADERS,
    json={
        "source_upload_id": upload["upload_id"],
        "model_id": model_id,
        "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"},
    },
    timeout=30,
)
response.raise_for_status()
job = response.json()

while True:
    response = requests.get(
        f"{BASE_URL}/api/v1/jobs/{job['id']}", headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    current = response.json()
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "Task failed")

response = requests.get(f"{BASE_URL}{current['result_url']}", headers=HEADERS, timeout=None)
response.raise_for_status()
Path("cover.wav").write_bytes(response.content)
```

## SeedVC Tasks

SeedVC also requires target-voice reference audio. Upload source and reference audio separately, then provide `reference_upload_id`:

```json
{
  "source_upload_id": "source audio upload_id",
  "reference_upload_id": "reference audio upload_id",
  "model_id": "SeedVC model ID",
  "params": {"pitch": 0, "device": "auto"}
}
```

## Multi-model Covers

Set `mode` to `multi`, specify independent parameters in `models`, and assign singing ranges through `segments`. Multiple IDs in one segment's `model_ids` create an ensemble:

```json
{
  "source_upload_id": "source audio upload_id",
  "mode": "multi",
  "workflow": "auto_vocal_merge",
  "models": [
    {"model_id": "model_svc", "params": {"pitch": 0, "device": "auto"}},
    {
      "model_id": "model_seedvc",
      "reference_upload_id": "SeedVC reference upload_id",
      "params": {"pitch": 0, "device": "auto"}
    }
  ],
  "segments": [
    {"start": 0, "end": 12.5, "model_ids": ["model_svc"]},
    {"start": 12.5, "end": 24, "model_ids": ["model_svc", "model_seedvc"]}
  ]
}
```

Supported workflows are `auto_mix`, `auto_vocal_merge`, `manual_vocal_merge`, `auto_then_editor`, and `full_manual_editor`. The two vocal-merge workflows do not apply to single-model mode.

`models[].params.auto_high_pitch_guard` controls high-note protection per model and defaults to true. Regions above a reliable range are inferred at a lower pitch and restored afterward. A legacy request may provide the fallback at top-level `params.auto_high_pitch_guard`.

### Complete Python Example

This uses two non-SeedVC models: model A for 0-20 seconds, model B for 20-40, and both for 40-60. Replace the file path, key, model IDs, and ranges.

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8760"
API_KEY = "replace with the API key shown in XB-SVCB"
SOURCE_AUDIO = Path("song.wav")
OUTPUT_AUDIO = Path("multi_model_cover.wav")
MODEL_A_ID = "replace with model A ID"
MODEL_B_ID = "replace with model B ID"

session = requests.Session()
session.headers.update({"X-API-Key": API_KEY})

response = session.get(f"{BASE_URL}/api/v1/models", timeout=30)
response.raise_for_status()
available_models = {item["id"]: item for item in response.json()["items"]}
for model_id in (MODEL_A_ID, MODEL_B_ID):
    if model_id not in available_models:
        choices = ", ".join(
            f"{item['name']}={item['id']}" for item in available_models.values()
        )
        raise RuntimeError(f"Unknown model ID: {model_id}\nAvailable models: {choices}")
    if available_models[model_id].get("framework") == "seed-vc":
        raise RuntimeError("Choose a non-SeedVC model; SeedVC requires reference audio")

with SOURCE_AUDIO.open("rb") as audio:
    response = session.post(
        f"{BASE_URL}/api/v1/uploads",
        files={"file": (SOURCE_AUDIO.name, audio, "application/octet-stream")},
        timeout=None,
    )
response.raise_for_status()
source_upload_id = response.json()["upload_id"]

response = session.post(
    f"{BASE_URL}/api/v1/jobs",
    json={
        "source_upload_id": source_upload_id,
        "title": "Multi-model cover example",
        "mode": "multi",
        "workflow": "auto_mix",
        "models": [
            {"model_id": MODEL_A_ID, "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"}},
            {"model_id": MODEL_B_ID, "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"}},
        ],
        "segments": [
            {"start": 0.0, "end": 20.0, "model_ids": [MODEL_A_ID]},
            {"start": 20.0, "end": 40.0, "model_ids": [MODEL_B_ID]},
            {"start": 40.0, "end": 60.0, "model_ids": [MODEL_A_ID, MODEL_B_ID]},
        ],
    },
    timeout=30,
)
response.raise_for_status()
job = response.json()

while True:
    response = session.get(f"{BASE_URL}/api/v1/jobs/{job['id']}", timeout=30)
    response.raise_for_status()
    current = response.json()
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "Multi-model cover failed")

with session.get(f"{BASE_URL}{current['result_url']}", stream=True, timeout=None) as response:
    response.raise_for_status()
    with OUTPUT_AUDIO.open("wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output.write(chunk)

session.delete(f"{BASE_URL}/api/v1/uploads/{source_upload_id}", timeout=30).raise_for_status()
print("Saved:", OUTPUT_AUDIO.resolve())
```

Segment times are seconds and should cover the required portion of the song. Every `model_ids` entry must appear in the request's `models`. For SeedVC, upload reference audio and add `reference_upload_id` to its model entry.

## Audio Editor Flow

1. Upload local audio and call `POST /api/v1/editor/projects`, or create a project from a cover through `work_id`.
2. Read the timeline with `GET /api/v1/editor/projects/{project_id}`. Clips expose `audio_url` and `waveform_url`, not local `file` paths.
3. Modify volume, fades, channels, envelopes, roles, and effect chains, then save with `PUT /api/v1/editor/projects/{project_id}`. Create new media through clip import, split, separation, or regional re-inference endpoints first.
4. Render project, track, or clip `/audio` endpoints as WAV, MP3, or FLAC.

Clients may modify and resubmit a fetched project. `audio_url`, `waveform_url`, and `render_url` are discarded on save; the server restores real clip files, so requests cannot replace them with arbitrary local paths.

`time_stretch` ranges from `0.25` to `4.0` and defaults to `1.0`. It updates clip duration consistently for waveforms, preview, plugin monitoring, and rendering. Regional re-inference supports `auto_high_pitch_guard: true` by default. With AI vocal enhancement, the server automatically reduces high-frequency coloration.

## Endpoint Summary

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check; no API key |
| `GET` | `/api/v1/system` | Integrated tools and GPU runtime |
| `GET` | `/api/v1/models` | Models and default model |
| `POST` | `/api/v1/models/default` | Set default model |
| `GET/PATCH/DELETE` | `/api/v1/models/{model_id}` | Read, rename, or delete a model |
| `POST` | `/api/v1/models/{model_id}/favorite` | Toggle favorite |
| `POST` | `/api/v1/models/{model_id}/inspect` | Inspect and optionally repair |
| `POST/DELETE` | `/api/v1/uploads[/{upload_id}]` | Stream upload or delete audio |
| `GET` | `/api/v1/jobs`, `/queue`, `/history` | Recent tasks, queue, and history |
| `GET/POST` | `/api/v1/jobs/presets` | List or save presets |
| `DELETE` | `/api/v1/jobs/presets/{preset_id}` | Delete a preset |
| `POST` | `/api/v1/jobs` | Create a single- or multi-model task |
| `POST` | `/api/v1/jobs/batch` | Create up to 50 tasks |
| `GET/PATCH/DELETE` | `/api/v1/jobs/{job_id}` | Read, rename, or delete a task |
| `POST` | `/api/v1/jobs/{job_id}/retry` | Retry a task |
| `GET` | `/api/v1/jobs/{job_id}/audio` | Download `output`, `instrumental`, or `vocals` stem |
| `GET/POST` | `/api/v1/editor/projects` | List or create projects |
| `GET/PUT/DELETE` | `/api/v1/editor/projects/{project_id}` | Read, save, or delete a project |
| `POST` | `/api/v1/editor/projects/{project_id}/undo`, `/redo` | Undo or redo |
| `POST` | `/api/v1/editor/projects/{project_id}/tracks` | Add a track |
| `DELETE` | `/api/v1/editor/projects/{project_id}/tracks/{track_id}` | Delete a track |
| `POST` | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips` | Import a clip by `upload_id` |
| `GET` | Project, track, or clip `/audio` | Render audio |
| `GET` | `/api/v1/editor/projects/{project_id}/clips/{clip_id}/waveform` | Read waveform |
| `POST` | Clip `/split/silence` or `/split/lyrics` | Split by silence or TXT/LRC lyrics |
| `POST` | Clip `/separate` | UVR/PyMSS separation and optional dereverb |
| `POST` | Clip `/rerun` | Regional voice-model re-inference |
| `POST` | Track `/clips/merge` | Render and merge clips |

## Common Status Codes

| Code | Meaning |
| --- | --- |
| `200` | Success |
| `201` | Audio uploaded |
| `202` | Task queued |
| `401` | Missing or invalid API key |
| `404` | Model, task, file, or `upload_id` not found |
| `409` | Result unavailable or operation invalid for current state |
| `415` | Unsupported file format |
| `422` | Invalid fields or parameter combination |

## Files and Cleanup

The API has no configured upload-size limit. It streams fixed-size chunks to disk instead of loading an entire file into memory; capacity is limited by free space in the data directory. Uploads live under `api/uploads` in the current XB-SVCB data directory and move with that directory. Wait for inference to finish before deleting an upload. Generated works remain managed by **My Works**.
