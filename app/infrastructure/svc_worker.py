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

try:
    from inference_device import (
        patch_directml_checkpoint_load,
        patch_directml_float32,
        patch_directml_sovits_f0_coarse,
        patch_directml_sovits_rmvpe_cpu,
        resolve_torch_device,
    )
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_device import (
        patch_directml_checkpoint_load,
        patch_directml_float32,
        patch_directml_sovits_f0_coarse,
        patch_directml_sovits_rmvpe_cpu,
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
    p.add_argument("--k-step", type=int, default=100, help="浅扩散步数")
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
        import soundfile
        import torch

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

                torchaudio.load = _ta_load  # type: ignore[assignment]
                torchaudio.save = _ta_save  # type: ignore[assignment]
            except Exception as _ta_exc:  # noqa: BLE001
                print(f"SVC_WARN torchaudio->soundfile 垫片未生效: {_ta_exc}")

        import utils as sovits_utils

        if resolved_device.backend == "directml":
            patch_directml_sovits_f0_coarse(sovits_utils)
            patch_directml_sovits_rmvpe_cpu(sovits_utils)
            print(
                "XB: So-VITS-SVC checkpoint/F0 粗化使用 DirectML 安全路径；"
                "RMVPE 使用 CPU 稳定路径，"
                "主模型/扩散/声码器继续使用 AMD DirectML",
                flush=True,
            )

        from inference.infer_tool import Svc
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 依赖导入失败: {exc}")
        traceback.print_exc()
        return 3

    device = resolved_device.device

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
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 模型加载失败: {exc}")
        traceback.print_exc()
        return 4

    # 选择说话人：优先用传入值，否则取配置中的第一个
    spk_ids = list(getattr(svc, "spk2id", {}).keys())
    speaker = args.speaker if args.speaker and args.speaker in spk_ids else (
        spk_ids[0] if spk_ids else args.speaker
    )

    try:
        audio = svc.slice_inference(
            raw_audio_path=args.input,
            spk=speaker,
            tran=args.tran,
            slice_db=args.slice_db,
            cluster_infer_ratio=0,
            auto_predict_f0=False,  # 翻唱歌声必须关闭，否则严重跑调
            noice_scale=0.4,
            pad_seconds=0.5,
            clip_seconds=args.clip,
            lg_num=0,
            lgr_num=0.75,
            f0_predictor=args.f0,
            enhancer_adaptive_key=0,
            cr_threshold=0.05,
            k_step=args.k_step,
            use_spk_mix=False,
            second_encoding=False,
            loudness_envelope_adjustment=1,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"SVC_ERR 推理失败: {exc}")
        traceback.print_exc()
        return 5

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        soundfile.write(out_path, audio, svc.target_sample, format="WAV")
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
