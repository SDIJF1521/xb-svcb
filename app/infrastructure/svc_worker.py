"""so-vits-svc 4.1 推理 worker（在用户的 so-vits-svc conda 环境中以子进程方式运行）。

由主程序通过 ``config.SVC_PYTHON`` 启动，工作目录会被切到 so-vits-svc 仓库根，
以便仓库内的相对路径（pretrain/、配置等）正常解析。

调用约定：
    python svc_worker.py --repo <仓库根> --main-model <G_xxx.pth> --main-config <config.json>
        --input <vocals.wav> --output <converted.wav> [--tran 0] [--k-step 100]
        [--speaker NXD] [--f0 rmvpe]
        [--diffusion-model <model.pt> --diffusion-config <diffusion.yaml>]

成功时最后一行输出 ``SVC_OK <output_path>``；失败时以非零码退出并打印 ``SVC_ERR <msg>``。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Optional, Tuple

try:
    from inference_naturalizer import (
        format_naturalizer_stats,
        naturalize_inference_output,
    )
    from inference_device import (
        patch_directml_checkpoint_load,
        patch_directml_float32,
        patch_directml_sovits_diffusion_extract,
        patch_directml_sovits_f0_coarse,
        patch_directml_sovits_rmvpe_cpu,
        patch_directml_sovits_sinegen,
        patch_sovits_fcpe_fallback,
        resolve_torch_device,
    )
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_naturalizer import (
        format_naturalizer_stats,
        naturalize_inference_output,
    )
    from infrastructure.inference_device import (
        patch_directml_checkpoint_load,
        patch_directml_float32,
        patch_directml_sovits_diffusion_extract,
        patch_directml_sovits_f0_coarse,
        patch_directml_sovits_rmvpe_cpu,
        patch_directml_sovits_sinegen,
        patch_sovits_fcpe_fallback,
        resolve_torch_device,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="XB-SVCB so-vits-svc 推理 worker")
    p.add_argument("--repo", required=True, help="so-vits-svc 仓库根目录")
    p.add_argument("--main-model", required=True, help="主模型 G_xxx.pth 路径")
    p.add_argument("--main-config", required=True, help="主模型 config.json 路径")
    p.add_argument("--input", required=True, help="输入人声 wav 路径")
    p.add_argument("--output", required=True, help="输出转换后 wav 路径")
    p.add_argument("--tran", type=int, default=0, help="变调（半音）")
    p.add_argument(
        "--device",
        default="auto",
        help="推理设备：auto / cuda / rocm / directml / cpu",
    )
    p.add_argument("--speaker", default="", help="目标说话人，留空取配置首个")
    p.add_argument("--f0", default="rmvpe", help="F0 预测器")
    p.add_argument("--f0-max", type=float, default=1100.0, help="自适应 F0 上限")
    p.add_argument("--f0-threshold", type=float, default=0.05, help="F0 置信度过滤阈值")
    p.add_argument("--k-step", type=int, default=100, help="浅扩散步数")
    p.add_argument(
        "--diffusion-ratio",
        type=float,
        default=None,
        help="扩散强度 0~1；非零 k_step_max 模型按其训练上限换算步数",
    )
    p.add_argument(
        "--clip",
        type=float,
        default=30.0,
        help="强制切片时长（秒），0 为自动；用于控制显存峰值，长音频建议 20~30",
    )
    p.add_argument("--diffusion-model", default="", help="扩散模型 .pt 路径（可选）")
    p.add_argument("--diffusion-config", default="", help="扩散模型配置 .yaml 路径（可选）")
    p.add_argument("--slice-db", type=int, default=-40, help="切片静音阈值 dB")
    return p


def _configure_rocm_miopen() -> None:
    """Avoid unstable gfx12 MIOpen ASM solvers on Windows ROCm 10.

    RX 9070 (gfx1201) can run the So-VITS graph through PyTorch ROCm, but
    some convolution shapes select an ASM solver that fails with
    ``hipEventCreate ... unspecified launch failure``.  Generic MIOpen
    solvers are stable for SVC and match the workaround used by the UVR
    worker.  ``setdefault`` keeps an explicit user override effective.
    """
    defaults = {
        "MIOPEN_DEBUG_GCN_ASM_KERNELS": "0",
        "MIOPEN_DEBUG_CONV_DIRECT_ASM_3X3U": "0",
        "MIOPEN_DEBUG_CONV_DIRECT_ASM_1X1U": "0",
        "MIOPEN_DEBUG_CONV_IMPLICIT_GEMM_ASM_FWD_V4R1": "0",
        "MIOPEN_DEBUG_CONV_IMPLICIT_GEMM_ASM_FWD_GTC_XDLOPS": "0",
        "MIOPEN_FIND_MODE": "FAST",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)


def _upstream_svc_device(requested: str, resolved_device):  # noqa: ANN001, ANN202
    """Preserve v0.0.21 auto behavior except for explicit DirectML."""
    return (
        resolved_device.device
        if resolved_device.backend == "directml" or requested not in ("", "auto")
        else None
    )


def _diffusion_k_step_limit(svc) -> Optional[int]:  # noqa: ANN001
    """Return the loaded diffusion model's usable shallow-diffusion limit.

    In so-vits-svc 4.1, ``model.k_step_max: 0`` means that all
    ``timesteps`` were trained.  ``Unit2Mel`` normalizes that special value to
    the real limit while it is constructed, so the loaded model is the most
    reliable source.  The configuration fallback also keeps this worker
    compatible with nearby 4.1 forks that do not expose ``k_step_max`` on the
    model object.
    """
    diffusion_model = getattr(svc, "diffusion_model", None)
    limit = getattr(diffusion_model, "k_step_max", None)
    if limit is None:
        limit = getattr(getattr(diffusion_model, "decoder", None), "k_step", None)

    diffusion_args = getattr(svc, "diffusion_args", None)
    model_args = getattr(diffusion_args, "model", None)
    timesteps = getattr(model_args, "timesteps", None)
    configured_limit = getattr(model_args, "k_step_max", None)
    if configured_limit is None:
        configured_limit = getattr(model_args, "k_step", None)

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 0
    try:
        timesteps = int(timesteps)
    except (TypeError, ValueError):
        timesteps = 0
    try:
        configured_limit = int(configured_limit)
    except (TypeError, ValueError):
        configured_limit = 0

    if limit <= 0:
        limit = configured_limit if configured_limit > 0 else timesteps
    if timesteps > 0:
        limit = min(limit, timesteps) if limit > 0 else timesteps
    return limit if limit > 0 else None


def _resolve_diffusion_k_step(
    svc, requested: int, diffusion_ratio: Optional[float] = None  # noqa: ANN001
) -> Tuple[int, Optional[int]]:
    """Resolve ``k_step`` without exceeding the checkpoint's trained range.

    A positive configured ``k_step_max`` identifies a shallow-only checkpoint.
    For those checkpoints the UI ratio is relative to that model-specific
    range, rather than the old hard-coded 200-step range.  Full-step models
    (configured as zero) keep the existing 1..200 mapping for compatibility.
    """
    try:
        effective = max(1, int(requested))
    except (TypeError, ValueError):
        effective = 1
    limit = _diffusion_k_step_limit(svc)

    diffusion_args = getattr(svc, "diffusion_args", None)
    model_args = getattr(diffusion_args, "model", None)
    configured_limit = getattr(model_args, "k_step_max", None)
    if configured_limit is None:
        configured_limit = getattr(model_args, "k_step", None)
    try:
        configured_limit = int(configured_limit)
    except (TypeError, ValueError):
        configured_limit = 0

    if configured_limit > 0 and diffusion_ratio is not None and limit is not None:
        try:
            ratio = max(0.0, min(1.0, float(diffusion_ratio)))
        except (TypeError, ValueError):
            ratio = 0.0
        effective = max(1, round(ratio * limit))
    if limit is not None:
        effective = min(effective, limit)
    return effective, limit


def _disable_missing_volume_embedding(svc, checkpoint_path: str, torch) -> bool:  # noqa: ANN001
    """Disable the optional volume embedding when an old checkpoint omits it.

    Some So-VITS-SVC checkpoints carry ``vol_embedding: true`` in a copied
    config while the actual generator was trained without ``emb_vol``.  The
    upstream loader leaves that layer randomly initialized.  That causes a
    dtype error on CPU and, on ROCm, a large DC output because the random
    layer is fed into the generator.  Treat the checkpoint as authoritative
    and use the model's normal no-volume path when the optional weights are
    absent.
    """
    if not bool(getattr(svc, "vol_embedding", False)):
        return False
    try:
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        state = checkpoint.get("model", checkpoint) if isinstance(checkpoint, dict) else {}
        has_volume_weights = isinstance(state, dict) and any(
            str(key).endswith(("emb_vol.weight", "emb_vol.bias")) for key in state
        )
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_WARN 无法检查音量嵌入参数，保留配置: {exc}", flush=True)
        return False
    if has_volume_weights:
        return False

    svc.vol_embedding = False
    net = getattr(svc, "net_g_ms", None)
    if net is not None:
        net.vol_embedding = False
    print(
        "SVC_WARN checkpoint 缺少 emb_vol.*，已关闭不兼容的随机音量嵌入",
        flush=True,
    )
    return True


def _install_svc_tensor_debug(svc, torch) -> None:  # noqa: ANN001
    """Print finite/value ranges around the generator when explicitly asked."""
    if os.environ.get("SVC_DEBUG_TENSORS", "").strip().lower() not in {"1", "true", "yes"}:
        return
    import functools

    def stats(value) -> str:  # noqa: ANN001
        if not torch.is_tensor(value):
            return type(value).__name__
        value = value.detach()
        finite = bool(torch.isfinite(value).all().item()) if value.numel() else True
        if not value.numel():
            return f"shape={tuple(value.shape)} empty finite={finite}"
        return (
            f"shape={tuple(value.shape)} dtype={value.dtype} device={value.device} "
            f"finite={finite} min={float(torch.nan_to_num(value).min()):.6f} "
            f"max={float(torch.nan_to_num(value).max()):.6f}"
        )

    original_get_unit_f0 = svc.get_unit_f0

    @functools.wraps(original_get_unit_f0)
    def debug_get_unit_f0(*args, **kwargs):  # noqa: ANN001
        result = original_get_unit_f0(*args, **kwargs)
        print(
            "SVC_DEBUG_F0 " + " | ".join(stats(item) for item in result),
            flush=True,
        )
        return result

    svc.get_unit_f0 = debug_get_unit_f0
    original_infer = svc.net_g_ms.infer

    @functools.wraps(original_infer)
    def debug_infer(*args, **kwargs):  # noqa: ANN001
        print(
            "SVC_DEBUG_INPUT " + " | ".join(stats(item) for item in args[:3]),
            flush=True,
        )
        result = original_infer(*args, **kwargs)
        print(
            "SVC_DEBUG_OUTPUT " + " | ".join(stats(item) for item in result),
            flush=True,
        )
        return result

    svc.net_g_ms.infer = debug_infer


def _validate_svc_generator(svc, torch) -> None:  # noqa: ANN001
    """Reject checkpoints whose generator already contains NaN/Inf weights."""
    net = getattr(svc, "net_g_ms", None)
    if net is None:
        return
    invalid: list[str] = []
    for name, value in net.named_parameters():
        if not bool(torch.isfinite(value.detach()).all().item()):
            invalid.append(name)
            if len(invalid) >= 4:
                break
    if len(invalid) < 4:
        for name, value in net.named_buffers():
            if not bool(torch.isfinite(value.detach()).all().item()):
                invalid.append(name)
                if len(invalid) >= 4:
                    break
    if invalid:
        details = ", ".join(invalid)
        raise RuntimeError(
            "SVC checkpoint 包含 NaN/Inf 权重，模型文件已损坏或未完成下载 "
            f"(例如: {details})"
        )


def _validate_svc_audio(audio, input_path: str, np) -> tuple[float, float, float, float]:  # noqa: ANN001
    """Reject non-finite or obvious DC-only output before WAV serialization."""
    values = np.asarray(audio, dtype=np.float32)
    if not bool(np.isfinite(values).all()):
        raise RuntimeError("推理输出包含 NaN/Inf，已阻止写出伪成功音频")
    flat = values.reshape(-1)
    if not len(flat):
        raise RuntimeError("推理输出为空")
    mean = float(np.mean(flat))
    std = float(np.std(flat))
    peak = float(np.max(np.abs(flat)))
    diff_rms = float(np.sqrt(np.mean(np.diff(flat) ** 2))) if len(flat) > 1 else 0.0
    try:
        import soundfile as sf

        source, _ = sf.read(input_path, dtype="float32", always_2d=True)
        source_rms = float(np.sqrt(np.mean(np.asarray(source) ** 2))) if len(source) else 0.0
    except Exception:  # noqa: BLE001
        source_rms = 0.0
    if source_rms > 1e-4:
        if std < 1e-5 and peak > 1e-3:
            raise RuntimeError("推理输出为直流信号，已阻止写出伪成功音频")
        if abs(mean) > max(0.25, 8.0 * std):
            raise RuntimeError("推理输出存在异常直流偏置，已阻止写出伪成功音频")
    return mean, std, peak, diff_rms


def main() -> int:
    args = _build_parser().parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"SVC_ERR 仓库不存在: {repo}")
        return 2

    # 必须在导入仓库模块前切目录并注入 sys.path（仓库内大量使用相对路径加载 pretrain）
    os.chdir(repo)
    if repo not in sys.path:
        sys.path.insert(0, repo)

    use_diffusion = bool(
        args.diffusion_model
        and args.diffusion_config
        and os.path.isfile(args.diffusion_model)
        and os.path.isfile(args.diffusion_config)
    )

    try:
        if str(args.device).strip().lower() == "rocm":
            # Set before importing torch/audio models so the first MIOpen
            # convolution cannot select the gfx12 ASM solver.
            _configure_rocm_miopen()
        import soundfile
        import torch

        # ``auto`` is the normal application route.  ROCm exposes the CUDA
        # compatibility API, so detect it after importing torch and apply the
        # same solver workaround before any model is constructed.
        if getattr(torch.version, "hip", None):
            _configure_rocm_miopen()

        resolved_device = resolve_torch_device(args.device, torch)
        if resolved_device.backend == "directml":
            patch_directml_float32(torch)
            patch_directml_checkpoint_load(torch)

        # PyTorch>=2.6 起 torch.load 默认 weights_only=True，会拒绝反序列化
        # so-vits-svc checkpoint 里的 argparse.Namespace / numpy 标量等非张量对象，
        # 导致"Weights only load failed"。so-vits 仓库本身未适配，这里在导入其模块前
        # 还原旧默认行为（仓库内 .pth/.pt 均为用户本地可信文件）。
        _orig_torch_load = torch.load

        def _torch_load_compat(*a, **kw):  # noqa: ANN001, ANN202
            kw.setdefault("weights_only", False)
            return _orig_torch_load(*a, **kw)

        torch.load = _torch_load_compat  # type: ignore[assignment]

        # 50 系（torch>=2.6/cu128）适配：torchaudio 2.7 的音频 I/O 改走 torchcodec，
        # 缺失/不兼容时 so-vits 里的 torchaudio.load/save 会读到空波形 -> 输出哑音。
        # 这里在导入 so-vits 之前把 torchaudio.load/save 重定向到 soundfile，绕过 torchcodec。
        # 老栈（torch 2.5.1）保持原生 torchaudio 不动。
        try:
            _tv = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2])
        except Exception:  # noqa: BLE001
            _tv = (0, 0)
        if _tv >= (2, 6):
            try:
                import torchaudio

                def _ta_load(filepath, *a, **kw):  # noqa: ANN001, ANN202
                    # so-vits-svc 内部可能传入 io.BytesIO 等文件对象，soundfile 支持直接读取
                    import io

                    if isinstance(filepath, (io.BytesIO, io.RawIOBase, io.BufferedIOBase)):
                        data, sr = soundfile.read(filepath, dtype="float32", always_2d=True)
                    else:
                        data, sr = soundfile.read(str(filepath), dtype="float32", always_2d=True)
                    # soundfile: [frames, channels] -> torchaudio 约定 [channels, frames]
                    return torch.from_numpy(data.T.copy()), sr

                def _ta_save(filepath, src, sample_rate, *a, **kw):  # noqa: ANN001, ANN202
                    arr = src.detach().cpu().float().numpy()
                    if arr.ndim == 1:
                        arr = arr[None, :]
                    # [channels, frames] -> soundfile 约定 [frames, channels]
                    soundfile.write(str(filepath), arr.T, int(sample_rate))

                # TorchAudio 2.11 removed the legacy backend selector. The
                # upstream so-vits-svc loader still calls it before load();
                # our soundfile I/O shim already chooses the backend, so a
                # no-op compatibility entry keeps the loader working.
                if not hasattr(torchaudio, "set_audio_backend"):
                    torchaudio.set_audio_backend = lambda *args, **kw: None  # type: ignore[attr-defined]

                torchaudio.load = _ta_load  # type: ignore[assignment]
                torchaudio.save = _ta_save  # type: ignore[assignment]
            except Exception as _ta_exc:  # noqa: BLE001
                print(f"SVC_WARN torchaudio->soundfile 垫片未生效: {_ta_exc}")

        import utils as sovits_utils
        patch_sovits_fcpe_fallback(sovits_utils, args.f0_max)

        if resolved_device.backend == "directml":
            patch_directml_sovits_f0_coarse(sovits_utils)
            patch_directml_sovits_rmvpe_cpu(sovits_utils)
            print(
                "XB: So-VITS-SVC checkpoint/F0 粗化使用 DirectML 安全路径；"
                "RMVPE/FCPE、声源相位与扩散系数索引使用 CPU 稳定路径，"
                "主模型/扩散网络继续使用 AMD DirectML",
                flush=True,
            )

        from inference.infer_tool import Svc
        if resolved_device.backend == "directml":
            from diffusion import diffusion as diffusion_model
            from vdecoder.hifigan import models as hifigan_models
            from vdecoder.hifiganwithsnake import models as snake_models
            from vdecoder.nsf_hifigan import models as diffusion_vocoder_models

            patch_directml_sovits_diffusion_extract(diffusion_model)
            patch_directml_sovits_sinegen(
                (hifigan_models, snake_models), diffusion_vocoder_models
            )
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 依赖导入失败: {exc}")
        traceback.print_exc()
        return 3

    # Keep v0.0.21's native CUDA/CPU auto-selection exactly unchanged. Only
    # DirectML needs an explicit privateuseone device object; ROCm also follows
    # PyTorch's CUDA-compatible auto path.
    device = _upstream_svc_device(args.device, resolved_device)

    try:
        svc = Svc(
            net_g_path=args.main_model,
            config_path=args.main_config,
            device=device,
            cluster_model_path="",
            nsf_hifigan_enhance=False,
            diffusion_model_path=args.diffusion_model or "logs/44k/diffusion/model_0.pt",
            diffusion_config_path=args.diffusion_config or "configs/diffusion.yaml",
            shallow_diffusion=use_diffusion,
            only_diffusion=False,
            spk_mix_enable=False,
            feature_retrieval=False,
        )
        if resolved_device.backend in {"rocm", "cpu"}:
            # Some so-vits checkpoints contain half-precision parameters while
            # the volume/F0 extractor always produces float32 tensors. Keep
            # the loaded SVC network and its input contract in float32 on
            # ROCm and CPU; this also avoids CPU's mixed-dtype Linear error.
            svc.net_g_ms.float()
            svc.dtype = torch.float32
        _disable_missing_volume_embedding(svc, args.main_model, torch)
        _validate_svc_generator(svc, torch)
        _install_svc_tensor_debug(svc, torch)
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 模型加载失败: {exc}")
        traceback.print_exc()
        return 4

    # 选择说话人：优先用传入值，否则取配置中的第一个
    spk_ids = list(getattr(svc, "spk2id", {}).keys())
    speaker = args.speaker if args.speaker and args.speaker in spk_ids else (
        spk_ids[0] if spk_ids else args.speaker
    )

    effective_k_step = args.k_step
    if use_diffusion:
        effective_k_step, k_step_limit = _resolve_diffusion_k_step(
            svc, args.k_step, args.diffusion_ratio
        )
        if effective_k_step != args.k_step:
            print(
                f"SVC_WARN 浅扩散 k_step 已根据模型训练范围从 "
                f"{args.k_step} 自动调整为 {effective_k_step}",
                flush=True,
            )
        print(
            f"SVC_DIFFUSION k_step={effective_k_step} "
            f"k_step_max={k_step_limit if k_step_limit is not None else 'unknown'}",
            flush=True,
        )

    try:
        audio = svc.slice_inference(
            raw_audio_path=args.input,
            spk=speaker,
            tran=args.tran,
            slice_db=args.slice_db,
            cluster_infer_ratio=0,
            auto_predict_f0=False,  # 翻唱歌声必须关闭，否则严重跑调
            noice_scale=0.25,
            pad_seconds=0.75,
            clip_seconds=args.clip,
            lg_num=0.12 if args.clip > 0 else 0,
            lgr_num=0.75,
            f0_predictor=args.f0,
            enhancer_adaptive_key=0,
            cr_threshold=max(0.0, min(1.0, float(args.f0_threshold))),
            k_step=effective_k_step,
            use_spk_mix=False,
            second_encoding=False,
            loudness_envelope_adjustment=0.65,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 推理失败: {exc}")
        traceback.print_exc()
        return 5

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        # Keep the model output diagnostics before the naturalizer touches the
        # file.  A saturated DC signal can otherwise look successful merely
        # because it is finite and has a non-zero peak.
        import numpy as np

        raw_mean, raw_std, raw_peak, raw_diff = _validate_svc_audio(audio, args.input, np)
        print(
            "SVC_RAW_STATS "
            f"mean={raw_mean:.6f} "
            f"std={raw_std:.6f} "
            f"peak={raw_peak:.6f} "
            f"diff_rms={raw_diff:.6f}",
            flush=True,
        )
        soundfile.write(out_path, audio, svc.target_sample, format="WAV")
        natural_stats = naturalize_inference_output(args.input, out_path, "so-vits-svc")
        print(f"SVC_NATURAL {format_naturalizer_stats(natural_stats)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 写出失败: {exc}")
        traceback.print_exc()
        return 6

    svc.clear_empty()
    print(f"SVC_DEVICE {resolved_device.backend} {resolved_device.name}", flush=True)
    print(f"SVC_OK {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
