"""Small child-process entry point for PyMSS separation and model downloads."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


_AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aiff", ".aif"}


def _audio_files(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES),
        key=lambda p: (p.stat().st_mtime_ns, str(p).casefold()),
    )


def _audio_stats(path: Path) -> tuple[float, float, int]:
    """Return (rms, peak, samples) without relying on a particular output codec."""
    import numpy as np

    from pymss import load_audio

    audio, _ = load_audio(str(path), sr=44100, mono=False)
    values = np.asarray(audio, dtype=np.float32)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or values.size == 0 or not np.isfinite(values).all():
        return 0.0, 0.0, 0
    flat = values.reshape(-1)
    return (
        float(np.sqrt(np.mean(np.square(flat), dtype=np.float64))),
        float(np.max(np.abs(flat))),
        int(flat.size),
    )


def _name_score(path: Path, purpose: str, preferred_stem: str = "") -> int:
    """Prefer explicit PyMSS stem names over arbitrary filesystem order."""
    name = path.stem.casefold().replace("_", " ").replace("-", " ")
    preferred = str(preferred_stem or "").casefold().replace("_", " ").replace("-", " ").strip()
    if purpose == "dereverb":
        positive = ("no reverb", "noreverb", "no echo", "no noise", "dry", "clean", "dereverb", "deecho")
        negative = ("reverb", "wet", "echo", "noise", "instrument", "accompan")
    else:
        positive = ("vocal", "vocals", "voice", "singing", "lead")
        negative = ("instrument", "accompan", "karaoke", "music", "other", "reverb")
    preferred_clean = purpose != "dereverb" or any(
        token in preferred for token in ("no ", "dry", "clean", "vocals", "vocal")
    )
    score = (500 if preferred_clean and preferred and preferred in name else 0) + sum(
        100 for token in positive if token in name
    )
    # ``no noise``/``no echo`` contain the removed-stem word, so protect the
    # clean label before applying the generic penalty.
    clean_label = any(token in name for token in ("no noise", "no echo", "no reverb"))
    score -= sum(120 for token in negative if token in name and not (clean_label and token in {"noise", "echo", "reverb"}))
    return score


def _select_stem(
    root: Path,
    purpose: str,
    reference_rms: float = 0.0,
    preferred_stem: str = "",
) -> Path | None:
    """Select a usable stem and reject silent/wrong-purpose outputs.

    PyMSS model versions use different output names.  The old implementation
    selected whichever filename containing ``vocal`` had the newest mtime,
    which made ``(Reverb)`` win nondeterministically over ``(No Reverb)``.
    """
    candidates: list[tuple[int, float, float, Path]] = []
    minimum_rms = max(1.0e-6, reference_rms * 1.0e-4)
    for path in _audio_files(root):
        try:
            rms, peak, samples = _audio_stats(path)
        except Exception:  # noqa: BLE001 - one malformed stem must not hide valid stems
            continue
        if samples <= 0 or peak < 1.0e-5 or rms < minimum_rms:
            continue
        candidates.append((_name_score(path, purpose, preferred_stem), rms, peak, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2], str(item[3]).casefold()), reverse=True)
    return candidates[0][3]


def _find_stem(root: Path, stem: str) -> Path | None:
    """Backward-compatible filename lookup used by older integrations."""
    matches = [p for p in _audio_files(root) if stem.casefold() in p.stem.casefold()]
    return max(matches, key=lambda p: p.stat().st_mtime_ns) if matches else None


def _subtract_audio(source: Path, removed: Path, destination: Path) -> None:
    """Remove a separated backing-vocal stem from the original vocal mix."""
    import numpy as np

    from pymss import load_audio, save_audio

    source_audio, source_rate = load_audio(str(source), sr=44100, mono=False)
    removed_audio, _ = load_audio(str(removed), sr=source_rate, mono=False)
    source_audio = np.asarray(source_audio, dtype=np.float32)
    removed_audio = np.asarray(removed_audio, dtype=np.float32)
    if source_audio.ndim == 1:
        source_audio = source_audio[None, :]
    if removed_audio.ndim == 1:
        removed_audio = removed_audio[None, :]
    channels = max(source_audio.shape[0], removed_audio.shape[0])
    if source_audio.shape[0] == 1 and channels > 1:
        source_audio = np.repeat(source_audio, channels, axis=0)
    if removed_audio.shape[0] == 1 and channels > 1:
        removed_audio = np.repeat(removed_audio, channels, axis=0)
    length = max(source_audio.shape[1], removed_audio.shape[1])
    source_audio = np.pad(source_audio[:channels], ((0, 0), (0, length - source_audio.shape[1])))
    removed_audio = np.pad(removed_audio[:channels], ((0, 0), (0, length - removed_audio.shape[1])))
    lead = np.clip(source_audio - removed_audio, -1.0, 1.0).T
    destination.parent.mkdir(parents=True, exist_ok=True)
    save_audio(str(destination), lead, int(source_rate), "wav", {"wav_bit_depth": "FLOAT"})


def _resolve_device(requested: str) -> tuple[str, str]:
    """Resolve devices inside the PyMSS environment, never the app process."""
    requested = str(requested or "auto").strip().lower()
    requested = {"amd": "rocm", "hip": "rocm", "rocm10": "rocm"}.get(requested, requested)
    if requested == "mlx":
        return "mlx", "mlx"
    import torch

    if requested in {"", "auto", "gpu"}:
        if bool(torch.cuda.is_available()):
            return "cuda", "rocm" if getattr(torch.version, "hip", None) else "cuda"
        return "cpu", "cpu"
    if requested in {"cuda", "rocm"}:
        if not bool(torch.cuda.is_available()):
            raise RuntimeError(f"已选择 {requested.upper()}，但 PyMSS 环境中对应 GPU 不可用；AMD 需要 ROCm Torch")
        backend = "rocm" if getattr(torch.version, "hip", None) else "cuda"
        if requested == "rocm" and backend != "rocm":
            raise RuntimeError("已选择 ROCm，但 PyMSS 环境不是 ROCm Torch")
        if requested == "cuda" and backend != "cuda":
            raise RuntimeError("已选择 NVIDIA CUDA，但 PyMSS 环境安装的是 AMD ROCm Torch")
        return "cuda", backend
    if requested in {"directml", "dml"}:
        raise RuntimeError("PyMSS 不支持 DirectML；AMD 显卡请安装 ROCm 环境并选择 rocm")
    if requested == "cpu":
        return "cpu", "cpu"
    return requested, requested


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--input")
    parser.add_argument("--out-dir")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--purpose",
        choices=("vocal_separation", "dereverb", "harmony_removal"),
        default="vocal_separation",
        help="处理用途：人声分离或去混响/人声净化",
    )
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    from pymss import MSSeparator, download_model

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    if args.download:
        result = download_model(args.model, model_dir=str(model_dir), source="modelscope")
        print(json.dumps({"ok": True, "model": args.model, "files": result.get("downloaded", [])}, ensure_ascii=False))
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = Path(args.input)
    # Keep all stems in a private directory, then normalize the two names consumed by XB-SVCB.
    raw_dir = out_dir / "pymss-output"
    # A retry or editor re-run can reuse the same work directory.  Never let a
    # previous model's stems participate in the current result selection.
    if raw_dir.exists():
        shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for stale in (out_dir / "pymss_vocals.wav", out_dir / "pymss_instrumental.wav", out_dir / "pymss_result.json"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        import torch

        device_name, device_backend = _resolve_device(args.device)
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(f"PyMSS 设备初始化失败: {exc}") from exc
    try:
        reference_rms, _, _ = _audio_stats(source)
    except Exception:
        reference_rms = 0.0
    separator = MSSeparator.from_model_name(
        args.model,
        model_dir=str(model_dir),
        download=False,
        device=device_name,
        device_ids=[0],
        output_format="wav",
        store_dirs=str(raw_dir),
        save_as_folder=False,
        inference_params={"normalize": False},
    )
    configured_stems = getattr(getattr(separator, "config", None), "training", {})
    if hasattr(configured_stems, "get"):
        configured_stems = configured_stems.get("instruments", ())
    primary_stem = str(configured_stems[0] if configured_stems else "")
    try:
        separator.process_folder(str(source))
    finally:
        close = getattr(separator, "close", None)
        if callable(close):
            close()

    vocal = _select_stem(
        raw_dir,
        args.purpose,
        reference_rms,
        primary_stem,
    )
    instrumental = _find_stem(raw_dir, "instrumental") or _find_stem(raw_dir, "accompaniment") or _find_stem(raw_dir, "other")
    if vocal is None:
        raise RuntimeError("PyMSS 未生成有效人声音轨（输出为空或近似静音）")
    vocals_dest = out_dir / "pymss_vocals.wav"
    removed_harmony = None
    if args.purpose == "harmony_removal":
        # UVR-BVE marks its isolated backing-vocal stem as "Vocals".  It must
        # be treated as a clean vocal output for compatibility with old jobs.
        shutil.copyfile(vocal, vocals_dest)
    else:
        shutil.copyfile(vocal, vocals_dest)
    instrumental_dest = None
    if instrumental and instrumental != vocal:
        instrumental_dest = out_dir / "pymss_instrumental.wav"
        shutil.copyfile(instrumental, instrumental_dest)
    (out_dir / "pymss_result.json").write_text(
        json.dumps(
            {
                "vocals": str(vocals_dest),
                "instrumental": str(instrumental_dest) if instrumental_dest else None,
                "removed_harmony": str(removed_harmony) if removed_harmony else None,
                "device": device_backend,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "vocals": str(vocals_dest), "instrumental": str(instrumental_dest) if instrumental_dest else None, "removed_harmony": str(removed_harmony) if removed_harmony else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
