"""F0 提取 worker（在用户的 so-vits-svc conda 环境中以子进程方式运行）。

复用 so-vits-svc 4.1 仓库内的 F0 预测器（rmvpe / crepe / dio / harvest / pm / fcpe），
在干净人声上真实计算基频曲线，保存为 .npy，并输出统计信息：
  - 浊音帧占比（voiced ratio）：用于判断是否真的检测到人声；
  - 基频中位数（Hz）与对应音名：便于核对音高是否合理。

调用约定：
    python f0_worker.py --repo <仓库根> --config <主模型 config.json>
        --input <vocals.wav> --out-npy <f0.npy> [--f0 rmvpe] [--device auto]

成功时最后一行输出：
    F0_OK\t<voiced_ratio>\t<median_hz>\t<note>\t<npy_path>
失败时打印 ``F0_ERR <msg>`` 并以非零码退出。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _hz_to_note(hz: float) -> str:
    if hz <= 0:
        return "-"
    midi = 69 + 12 * math.log2(hz / 440.0)
    idx = int(round(midi))
    name = _NOTE_NAMES[idx % 12]
    octave = idx // 12 - 1
    return f"{name}{octave}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="XB-SVCB so-vits-svc F0 提取 worker")
    p.add_argument("--repo", required=True, help="so-vits-svc 仓库根目录")
    p.add_argument("--config", required=True, help="主模型 config.json 路径")
    p.add_argument("--input", required=True, help="输入人声 wav 路径")
    p.add_argument("--out-npy", required=True, help="F0 曲线输出 .npy 路径")
    p.add_argument("--f0", default="rmvpe", help="F0 预测器")
    p.add_argument("--device", default="auto", help="设备：auto / cuda / cpu")
    return p


def main() -> int:
    args = _build_parser().parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"F0_ERR 仓库不存在: {repo}")
        return 2
    if not os.path.isfile(args.input):
        print(f"F0_ERR 输入不存在: {args.input}")
        return 2

    os.chdir(repo)
    if repo not in sys.path:
        sys.path.insert(0, repo)

    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    try:
        import librosa
        import numpy as np
        import torch
        import utils
    except Exception as exc:  # noqa: BLE001
        print(f"F0_ERR 依赖导入失败: {exc}")
        traceback.print_exc()
        return 3

    # 从模型配置读取采样率与 hop，保证与推理时一致
    try:
        with open(args.config, "r", encoding="utf-8") as f:
            hps = json.load(f)
        sampling_rate = int(hps["data"]["sampling_rate"])
        hop_length = int(hps["data"]["hop_length"])
    except Exception as exc:  # noqa: BLE001
        print(f"F0_ERR 读取配置失败: {exc}")
        return 4

    if args.device in ("", "auto"):
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device

    try:
        wav, _ = librosa.load(args.input, sr=sampling_rate, mono=True)
    except Exception as exc:  # noqa: BLE001
        print(f"F0_ERR 读取音频失败: {exc}")
        traceback.print_exc()
        return 5

    try:
        predictor = utils.get_f0_predictor(
            args.f0,
            hop_length=hop_length,
            sampling_rate=sampling_rate,
            device=device,
            threshold=0.05,
        )
        f0, uv = predictor.compute_f0_uv(wav)
    except Exception as exc:  # noqa: BLE001
        print(f"F0_ERR F0 计算失败: {exc}")
        traceback.print_exc()
        return 6

    f0 = np.asarray(f0, dtype=np.float32)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_npy)), exist_ok=True)
        np.save(args.out_npy, f0)
    except Exception as exc:  # noqa: BLE001
        print(f"F0_ERR 保存 F0 失败: {exc}")
        return 7

    voiced = f0 > 0
    voiced_ratio = float(voiced.mean()) if f0.size else 0.0
    median_hz = float(np.median(f0[voiced])) if voiced.any() else 0.0
    note = _hz_to_note(median_hz)

    print(f"F0_OK\t{voiced_ratio:.4f}\t{median_hz:.2f}\t{note}\t{os.path.abspath(args.out_npy)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
