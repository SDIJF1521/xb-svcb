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
        # 50 系（torch>=2.6/cu128）适配：torch>=2.6 起 torch.load 默认 weights_only=True，
        # rvc-python / fairseq 加载 hubert、字典、.pth 主模型时会报 "Weights only load failed"。
        # 导入 rvc-python 之前还原旧默认（RVC 的 .pth/.index/底模均为本地可信文件）。
        # 老栈（torch 2.1.1，默认即 False）加这层无副作用。
        try:
            import torch  # noqa: WPS433

            _orig_torch_load = torch.load

            def _torch_load_compat(*a, **kw):  # noqa: ANN001, ANN202
                kw.setdefault("weights_only", False)
                return _orig_torch_load(*a, **kw)

            torch.load = _torch_load_compat  # type: ignore[assignment]
        except Exception:  # noqa: BLE001
            pass

        from rvc_python.infer import RVCInference
    except Exception as exc:  # noqa: BLE001
        print(f"RVC_ERR rvc-python 未安装或导入失败: {exc}", flush=True)
        return 1

    try:
        device = _resolve_device(args.device)
        method = args.method if args.method in _RVC_F0_METHODS else "rmvpe"
        version = args.version if args.version in ("v1", "v2") else "v2"
        index_path = args.index if args.index else ""

        # 先不传 model_path 构造（避免在构造期就按默认 is_half=True 把模型转半精度），
        # 以便在加载模型前按需切换精度。
        rvc = RVCInference(device=device, version=version)

        # 50 系（Blackwell, torch>=2.6/cu128）适配：rvc-python 对 5060/5070/5090 默认开
        # fp16（is_half=True），但 fp16 在 Blackwell + 新 torch 上会产生「虚弱/没气/哑音」
        # 的劣化输出。这里在加载模型前强制 fp32，并切到 fp32 对应的切片窗口参数。
        # 老栈（torch 2.1.1 / 40 系及以下）保持默认 fp16（更快且本就正常），不受影响。
        try:
            import torch  # noqa: WPS433

            _tv = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2])
        except Exception:  # noqa: BLE001
            _tv = (0, 0)
        if _tv >= (2, 6):
            try:
                rvc.config.is_half = False
                # fp32 切片窗口（对应 config.device_config 里 is_half=False 分支）
                rvc.config.x_pad = 1
                rvc.config.x_query = 6
                rvc.config.x_center = 38
                rvc.config.x_max = 41
                print("XB: 新 torch 检测到，RVC 强制 fp32（规避 50 系 fp16 音质劣化）", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"XB: 设置 fp32 失败（继续用默认精度）: {exc}", flush=True)
            # Blackwell + torch2.7：cuDNN 卷积默认允许 TF32（19 位尾数），HiFiGAN/NSF 声码器
            # 大量卷积在 50 系上因此降精度，听感为「虚弱/没气」。关闭 TF32 强制 fp32 精度
            # （仍走 cuDNN，速度影响很小）；同时关 matmul 的 TF32 兜底。
            try:
                torch.backends.cudnn.allow_tf32 = False
                torch.backends.cuda.matmul.allow_tf32 = False
                # float32 矩阵乘法精度设为最高（torch>=2.0 的统一开关）
                try:
                    torch.set_float32_matmul_precision("highest")
                except Exception:  # noqa: BLE001
                    pass
                print("XB: 已关闭 TF32（cuDNN/matmul），保证 50 系卷积精度", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"XB: 关闭 TF32 失败（继续）: {exc}", flush=True)

        rvc.load_model(args.model, version=version, index_path=index_path)
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
