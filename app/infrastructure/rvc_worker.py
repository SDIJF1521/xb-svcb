"""RVC 推理子进程脚本（运行于 ``.venv-rvc`` 中，依赖 rvc-python）。

由 ``RvcEngine`` 以子进程方式调用，与主程序的依赖环境隔离。约定输出：
- 成功：``RVC_OK <output_path>``
- 失败：``RVC_ERR <message>``

rvc-python 首次实例化时会自动下载 hubert / rmvpe 底模（满足「RVC Index 自动识别」
与底模自备需求）。``load_model`` 直接接受 ``.pth`` 路径与可选 ``.index`` 路径。
"""

from __future__ import annotations

import argparse
import sys
import traceback


# RVC 支持的 F0 算法；其余（如 so-vits 的 dio/fcpe）统一回退 rmvpe
_RVC_F0_METHODS = {"harvest", "crepe", "rmvpe", "pm"}


def _resolve_device(requested: str) -> str:
    req = (requested or "auto").strip().lower()
    if req in ("cpu", "cpu:0"):
        return "cpu:0"
    if req.startswith("cuda"):
        return req if ":" in req else "cuda:0"
    # auto：探测 CUDA
    try:
        import torch  # noqa: WPS433

        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:  # noqa: BLE001
        pass
    return "cpu:0"


def main() -> int:
    parser = argparse.ArgumentParser(description="RVC inference worker (rvc-python)")
    parser.add_argument("--model", required=True, help=".pth 主模型路径")
    parser.add_argument("--index", default="", help=".index 检索特征路径（可选）")
    parser.add_argument("--input", required=True, help="输入人声 wav")
    parser.add_argument("--output", required=True, help="输出转换后人声 wav")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--method", default="rmvpe")
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--index-rate", dest="index_rate", type=float, default=0.75)
    parser.add_argument("--rms-mix", dest="rms_mix", type=float, default=0.25)
    parser.add_argument("--protect", type=float, default=0.33)
    parser.add_argument("--filter-radius", dest="filter_radius", type=int, default=3)
    parser.add_argument("--version", default="v2")
    args = parser.parse_args()

    try:
        from rvc_python.infer import RVCInference
    except Exception as exc:  # noqa: BLE001
        print(f"RVC_ERR rvc-python 未安装或导入失败: {exc}", flush=True)
        return 1

    try:
        device = _resolve_device(args.device)
        method = args.method if args.method in _RVC_F0_METHODS else "rmvpe"
        version = args.version if args.version in ("v1", "v2") else "v2"
        index_path = args.index if args.index else ""

        rvc = RVCInference(
            device=device,
            model_path=args.model,
            index_path=index_path,
            version=version,
        )
        rvc.set_params(
            f0up_key=int(args.pitch),
            f0method=method,
            index_rate=float(args.index_rate),
            rms_mix_rate=float(args.rms_mix),
            protect=float(args.protect),
            filter_radius=int(args.filter_radius),
        )
        rvc.infer_file(args.input, args.output)
        print(f"RVC_OK {args.output}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"RVC_ERR {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
