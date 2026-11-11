"""Audio helpers for the vendored official RVC inference stack.

Local compatibility patches (see ``engines/rvc/NOTICE.md``):
* PyAV >= 12 rejects the legacy ``"rb"``/``"wb"`` mode strings and the
  ``codec_context.channels`` / ``sample_rate`` writes used by the original
  ``audio2`` decoder.  ``load_audio`` therefore decodes through libsndfile /
  librosa, which is what the application feeds in (WAV from the pipeline), and
  keeps PyAV only for container conversion in ``wav2``.
* The official ``(sr, samples)`` tuple fallback is preserved.
"""

import librosa
import numpy as np
import av
from io import BytesIO

import soundfile as sf


def wav2(i, o, format):
    inp = av.open(i, "r")
    if format == "m4a":
        format = "mp4"
    out = av.open(o, "w", format=format)
    if format == "ogg":
        format = "libvorbis"
    if format == "mp4":
        format = "aac"

    ostream = out.add_stream(format)

    for frame in inp.decode(audio=0):
        for p in ostream.encode(frame):
            out.mux(p)

    for p in ostream.encode(None):
        out.mux(p)

    out.close()
    inp.close()


def _as_mono(data):
    if data.ndim == 2:
        return np.mean(data, axis=1)
    return data


def load_audio(file, sr):
    try:
        if isinstance(file, tuple):
            audio = _as_mono(np.asarray(file[1], dtype=np.float32) / 32768.0)
            if int(file[0]) == int(sr):
                return audio.astype(np.float32, copy=False)
            return librosa.resample(audio, orig_sr=int(file[0]), target_sr=int(sr))

        path = str(file).strip(" ").strip('"').strip("\n").strip('"').strip(" ")
        data, orig_sr = sf.read(path, dtype="float32", always_2d=True)
        audio = _as_mono(data)
        if int(orig_sr) != int(sr):
            audio = librosa.resample(audio, orig_sr=int(orig_sr), target_sr=int(sr))
        return np.ascontiguousarray(audio, dtype=np.float32)

    except Exception as e:
        raise RuntimeError(f"Failed to load audio: {e}")
