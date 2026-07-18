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
    from inference_device import patch_directml_float32, resolve_torch_device
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_device import patch_directml_float32, resolve_torch_device
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


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _patch_torch_load(force_cpu_map: bool = False) -> None:
    import torch

    original = torch.load

    def compatible_load(*args: Any, **kwargs: Any):
        kwargs.setdefault("weights_only", False)
        if force_cpu_map and str(kwargs.get("map_location", "")).startswith("privateuseone"):
            # DirectML state dictionaries are loaded on CPU first, then the
            # upstream loader moves the initialized module to the GPU.
            kwargs["map_location"] = "cpu"
        try:
            return original(*args, **kwargs)
        except TypeError:
            kwargs.pop("weights_only", None)
            return original(*args, **kwargs)

    torch.load = compatible_load


def _patch_ddsp_directml() -> None:
    """Keep DDSP neural controls on DML and synthesize complex spectra on CPU."""
    import numpy as np
    import torch
    from ddsp.vocoder import CombSubSuperFast

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
    parser.add_argument("--infer-steps", type=int, default=30)
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

        resolved_device = resolve_torch_device(args.device, torch)
        if resolved_device.backend == "directml":
            patch_directml_float32(torch)
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
        _patch_torch_load(resolved_device.backend == "directml")
        sys.path.insert(0, str(repo))
        os.chdir(repo)
        if resolved_device.backend == "directml":
            _patch_ddsp_directml()
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
            str(max(1, int(args.infer_steps))),
            "--formant_shift_key",
            str(max(-2.0, min(2.0, float(args.formant_shift)))),
            "--spk_id",
            str(args.speaker or "1"),
        ]
        sys.argv.extend(["--device", str(resolved_device.device)])
        runpy.run_path(str(upstream), run_name="__main__")
        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("上游脚本未生成有效 WAV")
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
