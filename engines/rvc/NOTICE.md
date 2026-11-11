# Vendored RVC inference stack

`engines/rvc/infer` is the official RVC inference code from
[RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI),
tag `2.2.231006` (MIT, see `LICENSE`).

The application used to run inference through the third-party `rvc-python`
package. That package is no longer required: this directory is imported by
`app/infrastructure/rvc_worker.py` through `engines/rvc/rvc_session.py`.

## Vendored files (unmodified unless listed below)

| Path | Source |
| --- | --- |
| `infer/lib/infer_pack/{attentions,commons,models,modules,transforms}.py` | official |
| `infer/lib/rmvpe.py` | official |
| `infer/lib/jit/{__init__,get_hubert,get_rmvpe,get_synthesizer}.py` | official |
| `infer/modules/vc/pipeline.py` | official |
| `configs/v1/*.json`, `configs/v2/*.json` | official |

## Local modifications

Only compatibility shims that the desktop runtime needs; inference math is
untouched.

1. **`infer/lib/audio.py`** — the official decoder uses PyAV's legacy
   `av.open(..., "rb"/"wb")` modes and writes `codec_context.channels` /
   `sample_rate`, which PyAV >= 12 rejects. `load_audio` now decodes through
   libsndfile (the application only feeds WAV/FLAC renders) with the official
   `(sample_rate, int16_samples)` tuple fallback preserved; `wav2` keeps PyAV
   for container conversion with the corrected `"r"`/`"w"` modes.
2. **`infer/__init__.py`, `infer/lib/__init__.py`,
   `infer/lib/infer_pack/__init__.py`, `infer/modules/__init__.py`** — added so
   the tree imports as a regular package from `engines/rvc`.
3. **`rvc_session.py`** (project code, not upstream) — the adapter that keeps the
   previous `RvcSession`/`vc_single` surface for the worker and owns device
   selection, fp16/fp32, slicing windows and the HuBERT/RMVPE base-model paths.

## Not vendored

Training code, the Gradio WebUI, UVR/MSST separation and ONNX export are not
included. Only the single-file inference path used by `rvc_worker.py` is
supported.
