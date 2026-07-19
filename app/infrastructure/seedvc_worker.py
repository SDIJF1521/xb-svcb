"""SeedVC 推理 worker（运行于 ``.venv-seedvc`` 中，调用官方 Seed-VC inference.py）。

成功时打印 ``SEEDVC_OK <output_path>``；失败时打印 ``SEEDVC_ERR <message>``。
官方脚本输出到目录且自动生成文件名，本 worker 负责把最新生成的 wav 复制到主程序
指定的输出路径，便于复用 XB-SVCB 的统一流水线。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

import numpy as np

try:
    from inference_device import (
        patch_directml_no_half,
        patch_directml_rmvpe_cpu,
        patch_directml_seedvc_f0_coarse,
        resolve_torch_device,
    )
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_device import (
        patch_directml_no_half,
        patch_directml_rmvpe_cpu,
        patch_directml_seedvc_f0_coarse,
        resolve_torch_device,
    )
from typing import Any, Callable


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _patch_whisper_sampling_rate(feature_extractor_class: Any) -> None:
    """Tell SeedVC's Whisper extractor that its resampled input is 16 kHz.

    Upstream already resamples every waveform to 16 kHz, but omits the explicit
    argument when calling WhisperFeatureExtractor. Recent Transformers versions
    warn once per chunk and may apply an incorrect frontend for custom configs.
    """
    if getattr(feature_extractor_class, "_xb_seedvc_sampling_rate_patch", False):
        return
    original_call = feature_extractor_class.__call__

    def call_with_sampling_rate(self: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("sampling_rate", 16000)
        return original_call(self, *args, **kwargs)

    feature_extractor_class.__call__ = call_with_sampling_rate
    feature_extractor_class._xb_seedvc_sampling_rate_patch = True


def _patch_seedvc_directml_audio_preprocessing(
    audio_module: Any,
    kaldi_module: Any,
) -> None:
    """Keep SeedVC's real-valued Mel/FBank features stable on DirectML.

    DirectML's audio FFT and reflect-padding paths can raise an empty
    ``RuntimeError`` or terminate while constructing ComplexFloat tensors.
    Mel and Kaldi FBank are deterministic preprocessing stages, so calculate
    each complete feature on CPU and immediately return its small real-valued
    result to the original DirectML device. The neural models remain on GPU.
    """
    if not getattr(audio_module, "_xb_seedvc_cpu_mel", False):
        original_mel_spectrogram = audio_module.mel_spectrogram

        def directml_safe_mel(y: Any, *args: Any, **kwargs: Any) -> Any:
            if not str(getattr(y, "device", "")).startswith("privateuseone"):
                return original_mel_spectrogram(y, *args, **kwargs)
            target_device = y.device
            return original_mel_spectrogram(y.cpu(), *args, **kwargs).to(target_device)

        audio_module.mel_spectrogram = directml_safe_mel
        audio_module._xb_seedvc_cpu_mel = True

    if not getattr(kaldi_module, "_xb_seedvc_cpu_fbank", False):
        original_fbank = kaldi_module.fbank

        def directml_safe_fbank(waveform: Any, *args: Any, **kwargs: Any) -> Any:
            if not str(getattr(waveform, "device", "")).startswith("privateuseone"):
                return original_fbank(waveform, *args, **kwargs)
            target_device = waveform.device
            return original_fbank(waveform.cpu(), *args, **kwargs).to(target_device)

        kaldi_module.fbank = directml_safe_fbank
        kaldi_module._xb_seedvc_cpu_fbank = True


def _patch_seedvc_directml_f0_postprocessing(torch: Any, rmvpe_module: Any) -> None:
    """Keep RMVPE's small F0 statistics on CPU until embedding lookup.

    SeedVC converts RMVPE's NumPy result to the global model device before
    applying log/median/exp. Several Radeon DirectML drivers raise an empty
    ``RuntimeError`` for that elementwise chain. Mark only arrays returned by
    RMVPE and defer their requested DirectML transfer; the length regulator's
    patched coarse quantizer moves the final real-valued bins to the GPU.
    """
    if getattr(rmvpe_module, "_xb_seedvc_cpu_f0_postprocessing", False):
        return

    class SeedVCF0Array(np.ndarray):
        pass

    class DeferredF0Tensor:
        def __init__(self, tensor: Any) -> None:
            self.tensor = tensor

        def to(self, device: Any, *args: Any, **kwargs: Any) -> Any:
            if str(device).startswith("privateuseone"):
                return self.tensor.cpu()
            return self.tensor.to(device, *args, **kwargs)

    original_rmvpe = rmvpe_module.RMVPE
    original_from_numpy = torch.from_numpy

    def seedvc_rmvpe(*args: Any, **kwargs: Any) -> Any:
        instance = original_rmvpe(*args, **kwargs)
        if getattr(instance, "_xb_seedvc_cpu_f0_output", False):
            return instance
        original_infer = instance.infer_from_audio

        def infer_from_audio(*infer_args: Any, **infer_kwargs: Any) -> Any:
            result = original_infer(*infer_args, **infer_kwargs)
            return np.asarray(result).view(SeedVCF0Array)

        instance.infer_from_audio = infer_from_audio
        instance._xb_seedvc_cpu_f0_output = True
        return instance

    def from_numpy(array: Any) -> Any:
        tensor = original_from_numpy(array)
        if isinstance(array, SeedVCF0Array):
            return DeferredF0Tensor(tensor)
        return tensor

    rmvpe_module.RMVPE = seedvc_rmvpe
    rmvpe_module._xb_seedvc_cpu_f0_postprocessing = True
    torch.from_numpy = from_numpy


def _latest_wav(folder: Path) -> Path | None:
    wavs = [p for p in folder.glob("*.wav") if p.is_file()]
    if not wavs:
        return None
    return max(wavs, key=lambda p: p.stat().st_mtime)


def _valid_file(path: Path, minimum_size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= minimum_size
    except OSError:
        return False


def _valid_model_dir(path: Path, required: dict[str, int]) -> bool:
    return path.is_dir() and all(
        _valid_file(path / name, minimum_size)
        for name, minimum_size in required.items()
    )


def _installation_root() -> Path:
    worker = Path(__file__).resolve()
    for parent in worker.parents:
        if (parent / "assets" / "models").is_dir():
            return parent
    return worker.parents[2]


def _discover_local_assets(repo: Path, install_root: Path | None = None) -> dict[str, Path]:
    root = install_root or _installation_root()
    bundled = root / "assets" / "models"
    checkpoints = repo / "checkpoints"
    found: dict[str, Path] = {}

    for candidate in (
        bundled / "pretrain" / "rmvpe.pt",
        checkpoints / "rmvpe.pt",
    ):
        if _valid_file(candidate, 300 * 1024 * 1024):
            found["rmvpe"] = candidate.resolve()
            break

    for candidate in (
        bundled / "seedvc" / "campplus_cn_common.bin",
        checkpoints / "campplus_cn_common.bin",
        repo / "campplus_cn_common.bin",
    ):
        if _valid_file(candidate, 20 * 1024 * 1024):
            found["campplus"] = candidate.resolve()
            break

    whisper_required = {
        "config.json": 1024,
        "preprocessor_config.json": 1024,
        "model.safetensors": 900 * 1024 * 1024,
    }
    for candidate in (
        bundled / "seedvc" / "whisper-small",
        checkpoints / "local_whisper_small",
    ):
        if _valid_model_dir(candidate, whisper_required):
            found["whisper"] = candidate.resolve()
            break

    bigvgan_required = {
        "config.json": 1024,
        "bigvgan_generator.pt": 400 * 1024 * 1024,
    }
    for candidate in (
        bundled / "seedvc" / "bigvgan_v2_44khz_128band_512x",
        checkpoints / "local_bigvgan_v2_44khz_128band_512x",
    ):
        if _valid_model_dir(candidate, bigvgan_required):
            found["bigvgan"] = candidate.resolve()
            break

    return found


def _normalized_seedvc_rmvpe(source: Path, repo: Path) -> Path:
    destination = repo / "checkpoints" / "rmvpe.pt"
    marker = destination.with_name(destination.name + ".xb-normalized")
    if _valid_file(destination, 300 * 1024 * 1024) and marker.is_file():
        return destination.resolve()

    import torch

    try:
        obj = torch.load(source, map_location="cpu", weights_only=False)
    except TypeError:
        obj = torch.load(source, map_location="cpu")
    wrapped = False
    state = obj.get("model") if isinstance(obj, dict) else None
    if isinstance(state, dict):
        obj = state
        wrapped = True
    if isinstance(obj, dict):
        cleaned = {key: value for key, value in obj.items() if not key.startswith("unet.tf.")}
        if len(cleaned) != len(obj):
            obj = cleaned
            wrapped = True
    expected = ("unet.encoder.bn.weight", "cnn.weight", "fc.1.bias")
    if not isinstance(obj, dict) or not any(key in obj for key in expected):
        raise RuntimeError(f"自带 RMVPE 格式不兼容: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve() or wrapped:
        temporary = destination.with_name(destination.name + ".xbtmp")
        temporary.unlink(missing_ok=True)
        torch.save(obj, temporary)
        temporary.replace(destination)
    marker.write_text("xb-svcb seedvc rmvpe v1\n", encoding="ascii")
    return destination.resolve()


def _local_hf_loader(
    original: Callable[..., Any],
    assets: dict[str, Path],
) -> Callable[..., Any]:
    local_files = {
        ("lj1995/voiceconversionwebui", "rmvpe.pt"): assets.get("rmvpe"),
        ("funasr/campplus", "campplus_cn_common.bin"): assets.get("campplus"),
    }

    def load(repo_id: str, model_filename: str = "pytorch_model.bin", config_filename: str | None = None):
        key = (str(repo_id).lower(), str(model_filename).replace("\\", "/"))
        local_model = local_files.get(key)
        if config_filename is None and local_model and local_model.exists():
            return str(local_model)
        return original(repo_id, model_filename, config_filename)

    return load


def _apply_local_model_paths(data: dict[str, Any], assets: dict[str, Path]) -> bool:
    model_params = data.get("model_params")
    if not isinstance(model_params, dict):
        return False
    changed = False

    vocoder = model_params.get("vocoder")
    if isinstance(vocoder, dict):
        name = str(vocoder.get("name") or "").strip().lower()
        if name == "nvidia/bigvgan_v2_44khz_128band_512x" and assets.get("bigvgan"):
            vocoder["name"] = str(assets["bigvgan"])
            changed = True

    tokenizer = model_params.get("speech_tokenizer")
    if isinstance(tokenizer, dict):
        name = str(tokenizer.get("name") or "").strip().lower()
        if name == "openai/whisper-small" and assets.get("whisper"):
            tokenizer["name"] = str(assets["whisper"])
            changed = True
    return changed


def _localized_config(config: Path, folder: Path, assets: dict[str, Path]) -> Path:
    if not assets.get("whisper") and not assets.get("bigvgan"):
        return config
    try:
        import yaml

        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not _apply_local_model_paths(data, assets):
            return config
        output = folder / "seedvc_local_config.yml"
        output.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return output
    except Exception as exc:  # noqa: BLE001 - invalid optional local config falls back safely
        print(f"SEEDVC_INFO 本地模型配置生成失败，将使用原配置: {exc}", flush=True)
        return config


def main() -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB SeedVC inference worker")
    parser.add_argument("--repo", required=True, help="Seed-VC 仓库根目录")
    parser.add_argument("--checkpoint", required=True, help="SeedVC checkpoint .pth 路径")
    parser.add_argument("--config", required=True, help="SeedVC config .yml/.yaml 路径")
    parser.add_argument("--reference", required=True, help="目标音色参考音频路径")
    parser.add_argument("--input", required=True, help="待转换人声 wav")
    parser.add_argument("--output", required=True, help="输出 wav 路径")
    parser.add_argument(
        "--device",
        default="auto",
        help="auto / cuda / rocm / directml / cpu",
    )
    parser.add_argument("--pitch", type=int, default=0, help="半音变调")
    parser.add_argument("--diffusion-steps", type=int, default=30)
    parser.add_argument("--length-adjust", type=float, default=1.0)
    parser.add_argument("--cfg-rate", type=float, default=0.7)
    parser.add_argument("--fp16", type=_parse_bool, default=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    checkpoint = Path(args.checkpoint).resolve()
    config = Path(args.config).resolve()
    reference = Path(args.reference).resolve()
    source = Path(args.input).resolve()
    out_path = Path(args.output).resolve()

    for label, path in (
        ("仓库", repo),
        ("模型", checkpoint),
        ("配置", config),
        ("参考音频", reference),
        ("输入音频", source),
    ):
        if not path.exists():
            print(f"SEEDVC_ERR {label}不存在: {path}", flush=True)
            return 2
    if not (repo / "inference.py").exists():
        print(f"SEEDVC_ERR Seed-VC inference.py 不存在: {repo}", flush=True)
        return 2

    if str(args.device or "").lower() == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        fp16 = False
    else:
        fp16 = bool(args.fp16)

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    hf_mirror = (
        os.environ.get("XB_HF_MIRROR")
        or os.environ.get("HF_ENDPOINT")
        or "https://hf-mirror.com"
    ).strip().rstrip("/")
    os.environ.setdefault("XB_HF_MIRROR", hf_mirror)
    os.environ.setdefault("HF_ENDPOINT", hf_mirror)
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", hf_mirror)

    old_cwd = Path.cwd()
    sys.path.insert(0, str(repo))
    try:
        os.chdir(repo)
        try:
            import torch

            resolved_device = resolve_torch_device(args.device, torch)
            if resolved_device.backend == "directml":
                patch_directml_no_half(torch)
                fp16 = False
        except Exception as exc:  # noqa: BLE001
            print(f"SEEDVC_ERR 设备初始化失败: {exc}", flush=True)
            return 3
        local_assets = _discover_local_assets(repo)
        if local_assets.get("rmvpe"):
            try:
                local_assets["rmvpe"] = _normalized_seedvc_rmvpe(
                    local_assets["rmvpe"],
                    repo,
                )
            except Exception as exc:  # noqa: BLE001 - emit a stable worker error
                print(f"SEEDVC_ERR SeedVC RMVPE 底模准备失败: {exc}", flush=True)
                return 3
        try:
            import inference as seedvc_inference  # type: ignore

            seedvc_inference.load_custom_model_from_hf = _local_hf_loader(
                seedvc_inference.load_custom_model_from_hf,
                local_assets,
            )
            seedvc_inference.device = resolved_device.device
            if resolved_device.backend == "directml":
                import modules.audio as seedvc_audio  # type: ignore
                import modules.length_regulator as seedvc_length_regulator  # type: ignore
                import modules.rmvpe as seedvc_rmvpe  # type: ignore
                import torchaudio.compliance.kaldi as seedvc_kaldi
                from transformers import WhisperFeatureExtractor, WhisperModel

                _patch_seedvc_directml_audio_preprocessing(seedvc_audio, seedvc_kaldi)
                patch_directml_rmvpe_cpu(seedvc_rmvpe)
                _patch_seedvc_directml_f0_postprocessing(torch, seedvc_rmvpe)
                patch_directml_seedvc_f0_coarse(
                    seedvc_length_regulator,
                    resolved_device.device,
                )
                _patch_whisper_sampling_rate(WhisperFeatureExtractor)
                print(
                    "XB: SeedVC Mel/FBank/F0 后处理使用 DirectML 安全路径；"
                    "RMVPE 使用 CPU 稳定路径，"
                    "主模型继续使用 AMD DirectML",
                    flush=True,
                )
                original_from_pretrained = WhisperModel.from_pretrained

                def directml_from_pretrained(cls, *model_args, **model_kwargs):  # noqa: ANN001, ANN202
                    model_kwargs["torch_dtype"] = torch.float32
                    return original_from_pretrained(*model_args, **model_kwargs)

                WhisperModel.from_pretrained = classmethod(directml_from_pretrained)
            seedvc_main = seedvc_inference.main
        except Exception as exc:  # noqa: BLE001
            print(f"SEEDVC_ERR SeedVC 依赖导入失败: {exc}", flush=True)
            return 3

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xb_seedvc_") as td:
            out_dir = Path(td)
            inference_config = _localized_config(config, out_dir, local_assets)
            ns = SimpleNamespace(
                source=str(source),
                target=str(reference),
                output=str(out_dir),
                diffusion_steps=max(1, int(args.diffusion_steps)),
                length_adjust=float(args.length_adjust),
                inference_cfg_rate=float(args.cfg_rate),
                f0_condition=True,
                auto_f0_adjust=False,
                semi_tone_shift=int(args.pitch),
                checkpoint=str(checkpoint),
                config=str(inference_config),
                fp16=fp16,
            )
            try:
                seedvc_main(ns)
            except Exception as exc:  # noqa: BLE001
                message = str(exc).strip() or type(exc).__name__
                print(f"SEEDVC_ERR SeedVC 推理失败: {message}", flush=True)
                traceback.print_exc()
                return 4
            generated = _latest_wav(out_dir)
            if not generated or not generated.exists():
                print("SEEDVC_ERR SeedVC 未生成 wav 输出", flush=True)
                return 5
            try:
                shutil.copy2(generated, out_path)
            except OSError as exc:
                print(f"SEEDVC_ERR 写出失败: {exc}", flush=True)
                return 6
    finally:
        try:
            os.chdir(old_cwd)
        except OSError:
            pass
    print(f"SEEDVC_DEVICE {resolved_device.backend} {resolved_device.name}", flush=True)
    print(f"SEEDVC_OK {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
