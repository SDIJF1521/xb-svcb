"""Small child-process entry point for PyMSS separation and model downloads."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

try:
    from inference_device import ResolvedDevice, configure_torch_inference
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_device import (
        ResolvedDevice,
        configure_torch_inference,
    )


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


def _normalized_name(path: Path) -> str:
    return path.stem.casefold().replace("_", " ").replace("-", " ")


def _has_token(name: str, token: str) -> bool:
    """整词匹配，避免 primary_stem="male" 也命中 "female"。"""
    token = str(token or "").strip()
    if not token:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", name) is not None


def _match_configured_stem(filename_stem: str, configured_names: list[str]) -> str | None:
    """把输出文件名映射到模型声明的音轨名（整词匹配）。

    之前用子串 ``name in output_key`` 匹配，``male`` 会命中 ``female``，
    导致「男/女声分离」模型两路输出都标成 ``male``（第二路退化成 ``male_2``），
    前端按声明音轨（male / female）连的线就对不上。这里改成整词匹配。
    """
    output_key = str(filename_stem or "").casefold().replace("_", " ").replace("-", " ")
    for name in configured_names:
        token = str(name or "").casefold().replace("_", " ").replace("-", " ").strip()
        if _has_token(output_key, token):
            return str(name)
    return None


def _name_score(path: Path, purpose: str, preferred_stem: str = "") -> int:
    """Prefer explicit PyMSS stem names over arbitrary filesystem order."""
    name = _normalized_name(path)
    preferred = str(preferred_stem or "").casefold().replace("_", " ").replace("-", " ").strip()
    if purpose == "dereverb":
        positive = ("no reverb", "noreverb", "no echo", "no noise", "dry", "clean", "dereverb", "deecho")
        negative = ("reverb", "wet", "echo", "noise", "instrument", "accompan")
    elif purpose == "generic":
        # Generic PyMSS models may target drums, bass, restoration, or any
        # other catalog stem. The catalog target is applied through the
        # preferred name instead of assuming every output is vocal.
        positive = ()
        negative = ()
    else:
        positive = ("vocal", "vocals", "voice", "singing", "lead")
        negative = ("instrument", "accompan", "karaoke", "music", "other", "reverb")
    preferred_clean = purpose not in {"dereverb", "generic"} or any(
        token in preferred for token in ("no ", "dry", "clean", "vocals", "vocal")
    )
    score = (1000 if preferred and preferred in name else 0) + (500 if preferred_clean and preferred and preferred in name else 0) + sum(
        100 for token in positive if token in name
    )
    if purpose == "generic" and _has_token(name, preferred):
        # 工作流里明确指定的「主音轨」：整词命中优先，避免 male 命中 female。
        score += 3000
    # ``no noise``/``no echo`` contain the removed-stem word, so protect the
    # clean label before applying the generic penalty.
    clean_label = any(token in name for token in ("no noise", "no echo", "no reverb"))
    score -= sum(120 for token in negative if token in name and not (clean_label and token in {"noise", "echo", "reverb"}))
    if purpose == "generic":
        # 自定义工作流用 generic 跑任意 PyMSS 模型：同一模型若同时输出干声与湿声
        # （如去混响模型的「(No Reverb)」「(Reverb)」），主输出应取干声。
        score += sum(
            80
            for token in ("no reverb", "noreverb", "no echo", "no noise", "dry", "clean", "dereverb", "deecho")
            if token in name
        )
        score -= sum(
            60
            for token in ("reverb", "wet", "echo", "noise")
            if token in name
            and not any(
                clean in name
                for clean in ("no reverb", "noreverb", "no echo", "no noise", "dry", "clean", "dereverb", "deecho")
            )
        )
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


def _pick_server_stems(
    results: dict[str, object],
    purpose: str,
    primary_stem: str,
) -> tuple[object | None, object | None]:
    """Select vocal/instrumental arrays from one PyMSS result mapping."""
    if not results:
        return None, None
    keys = list(results)

    def norm(value: object) -> str:
        return str(value).casefold().replace("_", " ").replace("-", " ")

    instrumental_key = None
    for key in keys:
        name = norm(key)
        if any(
            token in name
            for token in ("instrumental", "accompaniment", "karaoke", "music", "other")
        ):
            instrumental_key = key
            break

    vocal_key = None
    preferred = norm(primary_stem).strip()
    if preferred:
        for key in keys:
            name = norm(key)
            if name == preferred or preferred in name:
                vocal_key = key
                break
    if vocal_key is None:
        positive = (
            ("no reverb", "noreverb", "no echo", "dry", "clean", "vocal", "voice")
            if str(purpose or "").lower() == "dereverb"
            else ("vocal", "vocals", "voice", "singing", "lead")
        )
        for key in keys:
            if key == instrumental_key:
                continue
            if any(token in norm(key) for token in positive):
                vocal_key = key
                break
    if vocal_key is None:
        for key in keys:
            if key != instrumental_key:
                vocal_key = key
                break
    if vocal_key is None and len(keys) == 1:
        vocal_key = keys[0]

    vocal = results.get(vocal_key) if vocal_key is not None else None
    instrumental = (
        results.get(instrumental_key)
        if instrumental_key is not None and instrumental_key != vocal_key
        else None
    )
    return vocal, instrumental


def _write_server_stem(path: str, audio: object, sample_rate: int) -> None:
    import numpy as np

    from pymss import save_audio

    data = np.asarray(audio, dtype=np.float32)
    # PyMSS results are sample-major, but accept channel-first inputs too.
    if data.ndim == 2 and data.shape[0] <= 8 and data.shape[1] > data.shape[0]:
        data = data.T
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    save_audio(
        str(destination),
        data,
        int(sample_rate),
        "wav",
        {"wav_bit_depth": "PCM_16"},
    )


def _run_server(args) -> int:  # noqa: ANN001
    """Keep one PyMSS model resident and separate one block per JSON line."""
    import traceback

    from pymss import MSSeparator, load_audio

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out_dir) if args.out_dir else model_dir / ".xb-realtime"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import torch

        device_name, device_backend = _resolve_device(args.device)
        if device_backend != "mlx":
            resolved_device = ResolvedDevice(
                torch.device(device_name),
                device_backend,
                device_backend.upper(),
            )
            runtime_profile = configure_torch_inference(torch, resolved_device)
            print(f"PYMSS_RUNTIME {runtime_profile.summary}", flush=True)
        separator = MSSeparator.from_model_name(
            args.model,
            model_dir=str(model_dir),
            download=False,
            device=device_name,
            device_ids=[0],
            output_format="wav",
            store_dirs=str(out_dir),
            save_as_folder=False,
            inference_params={"normalize": False},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"PYMSS_ERR PyMSS 实时分离初始化失败: {exc}", flush=True)
        traceback.print_exc()
        return 4

    configured_stems = getattr(getattr(separator, "config", None), "training", {})
    if hasattr(configured_stems, "get"):
        configured_stems = configured_stems.get("instruments", ())
    if isinstance(configured_stems, str):
        configured_stems = (configured_stems,)
    elif not isinstance(configured_stems, (list, tuple)):
        configured_stems = ()
    primary_stem = str(
        args.primary_stem
        or args.target_stem
        or (configured_stems[0] if configured_stems else "")
    )
    try:
        import numpy as np

        sample_rate = 44100
        timeline = np.arange(sample_rate, dtype=np.float32) / sample_rate
        warmup = (0.01 * np.sin(2.0 * np.pi * 220.0 * timeline)).astype(np.float32)
        separator.separate(np.stack((warmup, warmup), axis=0), pbar=False)
        print("XB: PyMSS 实时组件预热完成", flush=True)
    except Exception as exc:  # noqa: BLE001 - first real block may still succeed
        print(f"XB: PyMSS 实时预热失败（继续启动）: {exc}", flush=True)
    print("PYMSS_SERVER_READY", flush=True)

    try:
        for raw in sys.stdin:
            try:
                request = json.loads(raw)
                if request.get("command") == "close":
                    break
                source = str(request.get("input") or "")
                output = str(request.get("output") or "")
                instrumental_output = str(request.get("instrumental") or "")
                if not source or not output:
                    raise ValueError("输入或输出路径为空")
                # The vocal models used by the app operate at 44.1 kHz; VR
                # stems are resampled to 44.1 kHz internally as well. Keep one
                # rate for both outputs so the realtime mixer stays aligned.
                audio, _ = load_audio(source, sr=44100, mono=False)
                results = separator.separate(audio, pbar=False)
                vocal, instrumental = _pick_server_stems(
                    results,
                    args.purpose,
                    primary_stem,
                )
                if vocal is None:
                    raise RuntimeError("PyMSS 未生成有效人声音轨")
                _write_server_stem(output, vocal, 44100)
                if instrumental_output and instrumental is not None:
                    _write_server_stem(instrumental_output, instrumental, 44100)
                result = {
                    "ok": True,
                    "output": output,
                    "instrumental": (
                        instrumental_output
                        if instrumental_output and instrumental is not None
                        else None
                    ),
                }
            except Exception as exc:  # noqa: BLE001 - keep serving after one bad block
                result = {"ok": False, "error": str(exc)}
            print(
                "PYMSS_SERVER_RESULT\t" + json.dumps(result, ensure_ascii=False),
                flush=True,
            )
    finally:
        close = getattr(separator, "close", None)
        if callable(close):
            close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--input")
    parser.add_argument("--out-dir")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--purpose",
        choices=("vocal_separation", "dereverb", "harmony_removal", "generic"),
        default="vocal_separation",
        help="处理用途：人声分离、去混响或通用 PyMSS 分离",
    )
    parser.add_argument("--target-stem", default="")
    parser.add_argument("--primary-stem", default="", help="用户指定的主音轨（覆盖模型默认目标音轨）")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--server", action="store_true", help="常驻进程，逐行接收实时分离块")
    args = parser.parse_args()

    if args.server:
        return _run_server(args)

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
        if device_backend != "mlx":
            resolved_device = ResolvedDevice(
                torch.device(device_name),
                device_backend,
                device_backend.upper(),
            )
            runtime_profile = configure_torch_inference(torch, resolved_device)
            print(f"PYMSS_RUNTIME {runtime_profile.summary}", flush=True)
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
    if isinstance(configured_stems, str):
        configured_stems = (configured_stems,)
    elif not isinstance(configured_stems, (list, tuple)):
        configured_stems = ()
    primary_stem = str(args.primary_stem or args.target_stem or (configured_stems[0] if configured_stems else ""))
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
        if args.purpose == "generic":
            raise RuntimeError("PyMSS 未生成有效分离音轨（输出为空或近似静音）")
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
    stem_outputs = []
    raw_outputs = _audio_files(raw_dir)
    configured_names = [str(value) for value in configured_stems or () if str(value).strip()]
    for index, output in enumerate(raw_outputs):
        label = _match_configured_stem(output.stem, configured_names) or output.stem
        if output == vocal:
            destination = vocals_dest
        elif instrumental and output == instrumental and instrumental_dest:
            destination = instrumental_dest
        else:
            destination = out_dir / f"pymss_stem_{index + 1:02d}{output.suffix.lower()}"
            shutil.copyfile(output, destination)
        stem_outputs.append({"name": label, "path": str(destination)})
    (out_dir / "pymss_result.json").write_text(
        json.dumps(
            {
                "vocals": str(vocals_dest),
                "instrumental": str(instrumental_dest) if instrumental_dest else None,
                "removed_harmony": str(removed_harmony) if removed_harmony else None,
                "device": device_backend,
                "target_stem": primary_stem,
                "stems": stem_outputs,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "vocals": str(vocals_dest), "instrumental": str(instrumental_dest) if instrumental_dest else None, "removed_harmony": str(removed_harmony) if removed_harmony else None, "stems": stem_outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
