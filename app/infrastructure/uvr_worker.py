"""人声分离 worker（在独立 venv 中以子进程运行 audio-separator）。

复用本地 Ultimate Vocal Remover 的 MDX 模型权重，把输入音频分离为人声与伴奏两轨。

调用约定：
    python uvr_worker.py --model-dir <UVR/MDX_Net_Models> --model <xxx.onnx>
        --input <song> --out-dir <work_dir>

成功时最后一行输出 ``UVR_OK\t<vocals_path>\t<instrumental_path>``（任一缺失则为空）；
失败时打印 ``UVR_ERR <msg>`` 并以非零码退出。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="XB-SVCB UVR 人声分离 worker")
    p.add_argument("--model-dir", required=True, help="UVR 模型目录")
    p.add_argument("--model", required=True, help="模型文件名（.onnx）")
    p.add_argument("--input", required=True, help="输入音频路径")
    p.add_argument("--out-dir", required=True, help="输出目录")
    p.add_argument("--device", default="auto", help="分离设备：auto / cuda / cpu")
    return p


def _classify(paths: list[str]) -> tuple[str, str]:
    """从输出文件列表中识别主轨与副轨。

    返回 (primary, secondary)：
      - 分离模型（如 5_HP-Karaoke）：primary=人声, secondary=伴奏
      - 去混响模型（如 DeEcho-DeReverb）：primary=无混响人声(No Reverb), secondary=混响残留
    """
    primary, secondary = "", ""
    for p in paths:
        name = os.path.basename(p).lower()
        # 注意：去混响时输入文件名常含 "(Vocals)"，输出会是
        # "..._(Vocals)_(No Reverb)" 与 "..._(Vocals)_(Reverb)"，
        # 因此必须先判混响、最后才判 vocal，避免把带混响的湿声误当成人声。
        if "no reverb" in name or "no_reverb" in name or "noreverb" in name:
            primary = p  # 去混响后的干净人声
        elif "reverb" in name:
            secondary = p  # 混响残留（湿声），丢弃
        elif "instrument" in name or "no_vocal" in name or "accompan" in name:
            secondary = p  # 伴奏轨
        elif "vocal" in name:

            primary = p  # 人声轨
    return primary, secondary


def main() -> int:
    args = _build_parser().parse_args()

    inp = os.path.abspath(args.input)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isfile(inp):
        print(f"UVR_ERR 输入不存在: {inp}")
        return 2

    # 强制 CPU：在导入 torch / audio_separator 之前隐藏 CUDA，使其自动回退到 CPU。
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    try:
        from audio_separator.separator import Separator
    except Exception as exc:  # noqa: BLE001
        print(f"UVR_ERR 依赖导入失败: {exc}")
        traceback.print_exc()
        return 3

    try:
        separator = Separator(
            model_file_dir=args.model_dir,
            output_dir=out_dir,
            output_format="WAV",
        )
        separator.load_model(model_filename=args.model)
        outputs = separator.separate(inp)
    except Exception as exc:  # noqa: BLE001
        print(f"UVR_ERR 分离失败: {exc}")
        traceback.print_exc()
        return 4

    # audio-separator 可能返回基名或绝对路径，统一解析为绝对路径
    resolved = [
        p if os.path.isabs(p) else os.path.join(out_dir, p) for p in (outputs or [])
    ]
    vocals, instrumental = _classify(resolved)

    if not vocals:
        print(f"UVR_ERR 未找到人声输出，实际输出: {resolved}")
        return 5

    # 结果以 UTF-8 JSON 写入文件，避免中文路径经子进程 stdout 管道（Windows 默认 GBK）
    # 被父进程按 UTF-8 解码时损坏，从而被误判为"分离失败"。
    try:
        with open(
            os.path.join(out_dir, "uvr_result.json"), "w", encoding="utf-8"
        ) as f:
            json.dump({"vocals": vocals, "instrumental": instrumental}, f)
    except OSError:
        pass

    print(f"UVR_OK\t{vocals}\t{instrumental}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
