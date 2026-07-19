"""DDSP-SVC worker running inside ``.venv-ddsp``.

The upstream loader requires a file named ``config.yaml`` beside the checkpoint.
This worker stages that pair without modifying the imported model and resolves bundled
pretrained-model paths before executing upstream ``main_reflow.py``.
"""

from __future__ import annotations

import argparse
import os
import runpy
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

try:
    from inference_device import ResolvedDevice, resolve_torch_device
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_device import ResolvedDevice, resolve_torch_device
from typing import Any


def _resolve_model_path(raw: Any, config_dir: Path, fallback: Path) -> str:
    value = str(raw or "").strip()
    if value:
        path = Path(value).expanduser()
        if path.is_absolute() and path.exists():
            return str(path.resolve())
        beside_config = (config_dir / path).resolve()
        if beside_config.exists():
            return str(beside_config)
    return str(fallback.resolve())


def _localized_config(source: Path, destination: Path, repo: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("配置文件内容不是 YAML 对象")
    data_section = data.setdefault("data", {})
    vocoder = data.setdefault("vocoder", {})
    if not isinstance(data_section, dict) or not isinstance(vocoder, dict):
        raise ValueError("配置缺少 data/vocoder 对象")
    data_section["encoder_ckpt"] = _resolve_model_path(
        data_section.get("encoder_ckpt"),
        source.parent,
        repo / "pretrain" / "contentvec" / "pytorch_model.bin",
    )
    vocoder["ckpt"] = _resolve_model_path(
        vocoder.get("ckpt"),
        source.parent,
        repo / "pretrain" / "nsf_hifigan" / "model",
    )
    destination.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return data


def _effective_ddsp_infer_steps(config: dict[str, Any], requested: int) -> tuple[int, int]:
    """Never run below the model author's recommended Flow step count."""
    infer = config.get("infer") if isinstance(config, dict) else None
    try:
        recommended = int((infer or {}).get("infer_step", 50))
    except (TypeError, ValueError, AttributeError):
        recommended = 50
    recommended = max(1, recommended)
    return max(recommended, max(1, int(requested))), recommended


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _patch_torch_load(force_cpu_map: bool = False, torch_module: Any = None) -> None:
    if torch_module is None:
        import torch as torch_module

    original = torch_module.load

    def compatible_load(*args: Any, **kwargs: Any):
        positional = list(args)
        kwargs.setdefault("weights_only", False)
        if force_cpu_map:
            # DDSP/RMVPE checkpoints may have been saved from CUDA and some
            # upstream loaders omit map_location entirely. Always deserialize
            # storage on CPU for DirectML; every inference loader subsequently
            # moves the initialized module to the selected AMD device.
            if len(positional) >= 2:
                positional[1] = "cpu"
                kwargs.pop("map_location", None)
            else:
                kwargs["map_location"] = "cpu"
        try:
            return original(*positional, **kwargs)
        except TypeError:
            kwargs.pop("weights_only", None)
            return original(*positional, **kwargs)

    torch_module.load = compatible_load


def _patch_directml_ddsp_rmvpe_cpu(rmvpe_class: Any) -> None:
    """Run DDSP's unsupported RMVPE GRU wholly on CPU for DirectML."""
    if getattr(rmvpe_class, "_xb_directml_cpu_patch", False):
        return
    original_rmvpe_infer = rmvpe_class.infer_from_audio

    def cpu_rmvpe_infer(self, audio, sample_rate=16000, device=None, *args, **kwargs):
        del device
        return original_rmvpe_infer(
            self,
            audio,
            sample_rate,
            "cpu",
            *args,
            **kwargs,
        )

    rmvpe_class.infer_from_audio = cpu_rmvpe_infer
    rmvpe_class._xb_directml_cpu_patch = True


def _patch_directml_ddsp_sinusoidal_cpu(embedding_class: Any) -> None:
    """Compute DDSP Flow's tiny sin/cos timestep embedding on CPU."""
    if getattr(embedding_class, "_xb_directml_cpu_patch", False):
        return
    original_forward = embedding_class.forward

    def cpu_sinusoidal_forward(self, x):
        if not str(getattr(x, "device", "")).startswith("privateuseone"):
            return original_forward(self, x)
        target_device = x.device
        return original_forward(self, x.float().cpu()).to(target_device)

    embedding_class.forward = cpu_sinusoidal_forward
    embedding_class._xb_directml_cpu_patch = True


def _patch_directml_ddsp_vocoder_cpu(vocoder_class: Any) -> None:
    """Decode the final DDSP mel with NSF-HiFiGAN on the stable CPU path."""
    if getattr(vocoder_class, "_xb_directml_cpu_patch", False):
        return
    original_infer = vocoder_class.infer

    def cpu_vocoder_infer(self, mel, f0):
        if not str(getattr(mel, "device", "")).startswith("privateuseone"):
            return original_infer(self, mel, f0)
        target_device = mel.device
        decoder = self.vocoder
        decoder.device = "cpu"
        if getattr(decoder, "model", None) is not None:
            decoder.model = decoder.model.float().cpu()
        audio = original_infer(self, mel.float().cpu(), f0.float().cpu())
        return audio.to(target_device)

    vocoder_class.infer = cpu_vocoder_infer
    vocoder_class._xb_directml_cpu_patch = True


def _patch_ddsp_float_wav(soundfile_module: Any) -> None:
    """Preserve quiet DDSP samples until post-inference level validation."""
    if getattr(soundfile_module, "_xb_ddsp_float_wav_patch", False):
        return
    original_write = soundfile_module.write

    def float_wav_write(file, data, samplerate, *args, **kwargs):
        if (
            str(file).lower().endswith(".wav")
            and not args
            and kwargs.get("subtype") is None
        ):
            kwargs["subtype"] = "FLOAT"
        return original_write(file, data, samplerate, *args, **kwargs)

    soundfile_module.write = float_wav_write
    soundfile_module._xb_ddsp_float_wav_patch = True


def _ddsp_output_levels(rendered: Any, reference: Any) -> tuple[Any, dict[str, float]]:
    import numpy as np

    if rendered.size == 0:
        raise RuntimeError("DDSP 输出为空")
    finite = np.isfinite(rendered)
    finite_ratio = float(finite.mean())
    if finite_ratio < 1.0:
        raise RuntimeError(
            f"DDSP 输出包含 NaN/Inf（有效采样 {finite_ratio:.2%}），已拒绝写入作品"
        )

    rendered_rms = float(np.sqrt(np.mean(np.square(rendered, dtype=np.float64))))
    rendered_peak = float(np.max(np.abs(rendered)))
    reference_rms = (
        float(np.sqrt(np.mean(np.square(reference, dtype=np.float64))))
        if reference.size
        else 0.0
    )
    if rendered_peak < 1e-4 or rendered_rms < 1e-5:
        raise RuntimeError(
            f"DDSP 输出近似静音（peak={rendered_peak:.6f}, rms={rendered_rms:.6f}）"
        )

    gain = 1.0
    if reference_rms > 1e-5 and rendered_rms < reference_rms * 0.7:
        gain = min(reference_rms / rendered_rms, 8.0, 0.98 / rendered_peak)
        if gain > 1.05:
            rendered = np.clip(rendered * gain, -0.98, 0.98)
            rendered_rms = float(
                np.sqrt(np.mean(np.square(rendered, dtype=np.float64)))
            )
            rendered_peak = float(np.max(np.abs(rendered)))
        else:
            gain = 1.0

    return rendered, {
        "peak": rendered_peak,
        "rms": rendered_rms,
        "reference_rms": reference_rms,
        "gain": float(gain),
        "finite_ratio": finite_ratio,
    }


def _finalize_ddsp_output(source: Path, output: Path) -> dict[str, float]:
    """Reject invalid/near-silent output and safely restore a low vocal level."""
    import numpy as np
    import soundfile as sf

    rendered, sample_rate = sf.read(
        str(output),
        dtype="float32",
        always_2d=True,
    )
    reference, _ = sf.read(
        str(source),
        dtype="float32",
        always_2d=True,
    )
    rendered, stats = _ddsp_output_levels(rendered, reference)
    if stats["gain"] > 1.0:
        info = sf.info(str(output))
        subtype = info.subtype if info.subtype and info.subtype != "UNKNOWN" else "FLOAT"
        sf.write(str(output), rendered, sample_rate, subtype=subtype)
    return stats


def _patch_ddsp_directml() -> None:
    """Keep DDSP neural controls on DML and synthesize complex spectra on CPU."""
    import numpy as np
    import torch
    try:
        from ddsp.vocoder import CombSubSuperFast
        from reflow.vocoder import Vocoder
    except ImportError as exc:
        if "DTensor" in str(exc) and "torch.distributed.tensor" in str(exc):
            raise RuntimeError(
                "DDSP 依赖版本不兼容：当前 Transformers 要求新版 Torch DTensor，"
                "请运行“搭建/修复运行环境”的 DDSP-SVC 修复，将 Transformers "
                "恢复为 4.46.3"
            ) from exc
        raise
    from encoder.rmvpe.inference import RMVPE
    from reflow.lynxnet2 import SinusoidalPosEmb

    _patch_directml_ddsp_rmvpe_cpu(RMVPE)
    _patch_directml_ddsp_sinusoidal_cpu(SinusoidalPosEmb)
    _patch_directml_ddsp_vocoder_cpu(Vocoder)

    def directml_forward(
        self,
        units_frames,
        f0_frames,
        volume_frames,
        spk_id=None,
        spk_mix_dict=None,
        aug_shift=None,
        initial_phase=None,
        infer=True,
        **kwargs,
    ):
        del initial_phase, infer, kwargs
        combtooth = self.fast_source_gen(f0_frames)
        block_size = int(self.block_size.detach().cpu().item())
        win_length = int(self.win_length.detach().cpu().item())
        combtooth_frames = combtooth.unfold(1, block_size, block_size)
        noise = torch.randn_like(combtooth)
        noise_frames = noise.unfold(1, block_size, block_size)
        ctrls, hidden = self.unit2ctrl(
            units_frames,
            combtooth_frames,
            noise_frames,
            volume_frames,
            spk_id=spk_id,
            spk_mix_dict=spk_mix_dict,
            aug_shift=aug_shift,
        )

        harmonic_magnitude = ctrls["harmonic_magnitude"].float().cpu()
        harmonic_phase = ctrls["harmonic_phase"].float().cpu() * np.pi
        noise_magnitude = ctrls["noise_magnitude"].float().cpu()
        noise_phase = ctrls["noise_phase"].float().cpu() * np.pi
        src_filter = torch.polar(torch.exp(harmonic_magnitude), harmonic_phase)
        noise_filter = torch.polar(torch.exp(noise_magnitude), noise_phase) / 128
        src_filter = torch.cat((src_filter, src_filter[:, -1:, :]), 1)
        noise_filter = torch.cat((noise_filter, noise_filter[:, -1:, :]), 1)

        combtooth_cpu = combtooth.float().cpu()
        noise_cpu = noise.float().cpu()
        window = self.window.float().cpu()
        pad_mode = "reflect" if combtooth_cpu.shape[-1] > win_length // 2 else "constant"
        combtooth_stft = torch.stft(
            combtooth_cpu,
            n_fft=win_length,
            win_length=win_length,
            hop_length=block_size,
            window=window,
            center=True,
            return_complex=True,
            pad_mode=pad_mode,
        )
        noise_stft = torch.stft(
            noise_cpu,
            n_fft=win_length,
            win_length=win_length,
            hop_length=block_size,
            window=window,
            center=True,
            return_complex=True,
            pad_mode=pad_mode,
        )
        signal_stft = (
            combtooth_stft * src_filter.permute(0, 2, 1)
            + noise_stft * noise_filter.permute(0, 2, 1)
        )
        signal = torch.istft(
            signal_stft,
            n_fft=win_length,
            win_length=win_length,
            hop_length=block_size,
            window=window,
            center=True,
        )
        return signal.to(units_frames.device), hidden

    CombSubSuperFast.forward = directml_forward


def main() -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB DDSP-SVC inference worker")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--f0", default="rmvpe")
    parser.add_argument("--infer-steps", type=int, default=50)
    parser.add_argument("--formant-shift", type=float, default=0.0)
    parser.add_argument("--speaker", default="1")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    model = Path(args.model).resolve()
    config = Path(args.config).resolve()
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    upstream = repo / "main_reflow.py"
    for label, path in (
        ("DDSP-SVC 仓库", repo),
        ("上游推理脚本", upstream),
        ("模型", model),
        ("配置", config),
        ("输入音频", source),
    ):
        if not path.exists():
            print(f"DDSP_ERR {label}不存在: {path}", flush=True)
            return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    f0_method = str(args.f0 or "rmvpe").lower()
    if f0_method == "pm":
        f0_method = "parselmouth"
    if f0_method not in {"rmvpe", "fcpe", "crepe", "harvest", "dio", "parselmouth"}:
        print(f"DDSP_ERR 不支持的 F0 提取器: {f0_method}", flush=True)
        return 2

    if str(args.device).lower() == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    try:
        import torch
        import soundfile

        detected_device = resolve_torch_device(args.device, torch)
        _patch_ddsp_float_wav(soundfile)
        if detected_device.backend == "directml":
            # The full DDSP/Rectified-Flow graph can finish on DirectML while
            # silently producing low-level electrical noise. A successful
            # return code is therefore not a sufficient correctness signal.
            # Prefer deterministic CPU inference until the upstream graph is
            # numerically validated on DirectML end-to-end. UVR and the other
            # model families remain free to use the AMD adapter.
            resolved_device = ResolvedDevice(
                torch.device("cpu"),
                "cpu",
                f"CPU 稳定路径（检测到 {detected_device.name}）",
            )
            print(
                "XB: DDSP-SVC DirectML 实机会产生小声/静音/电流杂音，"
                "已切换完整 CPU 稳定推理；UVR 与其他模型的 AMD 加速不受影响",
                flush=True,
            )
        else:
            resolved_device = detected_device
    except Exception as exc:  # noqa: BLE001
        print(f"DDSP_ERR 设备初始化失败: {exc}", flush=True)
        return 2

    old_cwd = Path.cwd()
    old_argv = sys.argv[:]
    stage = Path(tempfile.mkdtemp(prefix="xb-ddsp-", dir=str(output.parent)))
    try:
        staged_model = stage / model.name
        _link_or_copy(model, staged_model)
        localized_config = _localized_config(config, stage / "config.yaml", repo)
        data_config = localized_config.get("data") or {}
        infer_steps, recommended_steps = _effective_ddsp_infer_steps(
            localized_config,
            args.infer_steps,
        )
        if infer_steps != int(args.infer_steps):
            print(
                f"XB: DDSP-SVC 请求 {int(args.infer_steps)} 步低于模型推荐 "
                f"{recommended_steps} 步，已自动提升到 {infer_steps} 步以保证质量",
                flush=True,
            )
        _patch_torch_load(resolved_device.backend == "cpu")
        sys.path.insert(0, str(repo))
        os.chdir(repo)
        sys.argv = [
            str(upstream),
            "--model_ckpt",
            str(staged_model),
            "--input",
            str(source),
            "--output",
            str(output),
            "--key",
            str(int(args.pitch)),
            "--pitch_extractor",
            f0_method,
            "--f0_min",
            str(float(data_config.get("f0_min", 50))),
            "--f0_max",
            str(float(data_config.get("f0_max", 1100))),
            "--infer_step",
            str(infer_steps),
            "--formant_shift_key",
            str(max(-2.0, min(2.0, float(args.formant_shift)))),
            "--spk_id",
            str(args.speaker or "1"),
        ]
        sys.argv.extend(["--device", str(resolved_device.device)])
        runpy.run_path(str(upstream), run_name="__main__")
        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("上游脚本未生成有效 WAV")
        audio_stats = _finalize_ddsp_output(source, output)
        print(
            "DDSP_AUDIO "
            f"peak={audio_stats['peak']:.6f} rms={audio_stats['rms']:.6f} "
            f"input_rms={audio_stats['reference_rms']:.6f} "
            f"gain={audio_stats['gain']:.3f} finite={audio_stats['finite_ratio']:.2%}",
            flush=True,
        )
        print(f"DDSP_DEVICE {resolved_device.backend} {resolved_device.name}", flush=True)
        print(f"DDSP_OK {output}", flush=True)
        return 0
    except SystemExit as exc:
        code = int(exc.code or 0)
        if code == 0 and output.is_file():
            print(f"DDSP_DEVICE {resolved_device.backend} {resolved_device.name}", flush=True)
            print(f"DDSP_OK {output}", flush=True)
            return 0
        print(f"DDSP_ERR 上游推理提前退出（code={code}）", flush=True)
        return code or 3
    except Exception as exc:  # noqa: BLE001 - worker must return a stable marker
        print(f"DDSP_ERR {exc}", flush=True)
        traceback.print_exc()
        return 3
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
