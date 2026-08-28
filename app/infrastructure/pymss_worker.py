"""Small child-process entry point for PyMSS separation and model downloads."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _find_stem(root: Path, stem: str) -> Path | None:
    matches = [p for p in root.rglob("*") if p.is_file() and stem in p.stem.lower()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime_ns)


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
    if requested == "mlx":
        return "mlx", "mlx"
    import torch

    if requested in {"", "auto", "gpu"}:
        if bool(torch.cuda.is_available()):
            return "cuda", "cuda"
        try:
            from inference_device import _directml_device  # type: ignore

            resolved = _directml_device(torch)
            if resolved is not None:
                return str(resolved.device), "directml"
        except (ImportError, AttributeError):
            pass
        return "cpu", "cpu"
    if requested in {"cuda", "rocm"}:
        if not bool(torch.cuda.is_available()):
            raise RuntimeError(f"已选择 {requested.upper()}，但 PyMSS 环境中 CUDA 不可用")
        backend = "rocm" if getattr(torch.version, "hip", None) else "cuda"
        if requested == "rocm" and backend != "rocm":
            raise RuntimeError("已选择 ROCm，但 PyMSS 环境不是 ROCm Torch")
        return "cuda", backend
    if requested in {"directml", "dml"}:
        from inference_device import _directml_device  # type: ignore

        resolved = _directml_device(torch)
        if resolved is None:
            raise RuntimeError("已选择 DirectML，但 PyMSS 环境或驱动不可用")
        return str(resolved.device), "directml"
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
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        import torch

        device_name, device_backend = _resolve_device(args.device)
        if device_backend == "directml":
            from inference_device import patch_directml_float32  # type: ignore

            patch_directml_float32(torch)
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(f"PyMSS 设备初始化失败: {exc}") from exc
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
    try:
        separator.process_folder(str(source))
    finally:
        close = getattr(separator, "close", None)
        if callable(close):
            close()

    vocal = _find_stem(raw_dir, "vocal")
    instrumental = _find_stem(raw_dir, "instrumental") or _find_stem(raw_dir, "other")
    if vocal is None:
        # Catalog models may use target_stem names; preserve a useful fallback for a
        # two-stem output while refusing arbitrary non-audio files.
        candidates = [p for p in raw_dir.rglob("*.wav") if p.is_file()]
        if candidates:
            vocal = candidates[0]
            if len(candidates) > 1:
                instrumental = candidates[1]
    if vocal is None:
        raise RuntimeError("PyMSS 未生成 vocals 音轨")
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
