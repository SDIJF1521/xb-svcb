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
import shutil
import sys
import traceback
import wave


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="XB-SVCB UVR 人声分离 worker")
    p.add_argument("--model-dir", required=True, help="UVR 模型目录")
    p.add_argument("--model", required=True, help="模型文件名（.pth / .onnx）")
    p.add_argument("--input", required=False, help="输入音频路径")
    p.add_argument("--out-dir", required=True, help="输出目录")
    p.add_argument("--server", action="store_true", help="常驻加载模型并逐块处理 JSON 请求")
    p.add_argument(
        "--device",
        default="auto",
        help="分离设备：auto / cuda / rocm / directml / cpu",
    )
    return p


def _classify(paths: list[str]) -> tuple[str, str]:
    """从输出文件列表中识别主轨与副轨。

    返回 (primary, secondary)：
      - 分离模型（如 5_HP-Karaoke）：primary=人声, secondary=伴奏
      - 去混响模型（如 DeEcho-DeReverb）：primary=无混响人声(No Reverb), secondary=混响残留
    """
    primary, secondary = "", ""
    for p in paths:
        name = os.path.basename(os.fspath(p)).lower()
        # 注意：去混响时输入文件名常含 "(Vocals)"，输出会是
        # "..._(Vocals)_(No Reverb)" 与 "..._(Vocals)_(Reverb)"，
        # 因此必须先判混响、最后才判 vocal，避免把带混响的湿声误当成人声。
        if "no reverb" in name or "no_reverb" in name or "noreverb" in name:
            primary = p  # 去混响后的干净人声
        elif "reverb" in name:
            secondary = p  # 混响残留（湿声），丢弃
        elif "instrument" in name or "no_vocal" in name or "accompan" in name:
            secondary = p  # 伴奏轨
        elif "vocal" in name or "voice" in name or "singing" in name:
            primary = p  # 人声轨
    if not primary:
        # Some audio-separator releases omit the stem label from the returned
        # path even though the file itself is valid. Prefer an existing file
        # that is not clearly an instrumental/reverb output.
        candidates = [
            p for p in paths
            if os.path.isfile(p)
            and not any(token in os.path.basename(p).lower() for token in ("instrument", "accompan", "no_vocal", "reverb"))
        ]
        if candidates:
            primary = candidates[-1]
    if not secondary:
        candidates = [
            p for p in paths
            if os.path.isfile(p)
            and any(token in os.path.basename(p).lower() for token in ("instrument", "accompan", "no_vocal"))
        ]
        if candidates:
            secondary = candidates[-1]
    return primary, secondary


def _torch_backend(torch, device: object) -> str:  # noqa: ANN001
    value = str(device or "cpu").lower()
    if value.startswith("privateuseone"):
        return "directml"
    if value.startswith("cuda"):
        return "rocm" if getattr(torch.version, "hip", None) else "cuda"
    return "cpu"


def _patch_directml_vr_lstm() -> None:
    """Run the VR 5.1 recurrent block on CPU while keeping its CNN on DML."""
    from audio_separator.separator.uvr_lib_v5.vr_network import layers_new

    module = layers_new.LSTMModule
    if getattr(module, "_xb_directml_cpu_lstm", False):
        return

    def directml_forward(self, input_tensor):  # noqa: ANN001, ANN202
        n, _, nbins, nframes = input_tensor.size()
        hidden = self.conv(input_tensor)[:, 0].permute(2, 0, 1)
        output_device = hidden.device
        if not getattr(self, "_xb_lstm_on_cpu", False):
            self.lstm.to("cpu")
            self._xb_lstm_on_cpu = True
        hidden, _ = self.lstm(hidden.cpu())
        hidden = hidden.to(output_device)
        hidden = self.dense(hidden.reshape(-1, hidden.size()[-1]))
        return hidden.reshape(nframes, n, 1, nbins).permute(1, 2, 3, 0)

    module.forward = directml_forward
    module._xb_directml_cpu_lstm = True


def _write_residual_vocal(source: str, instrumental: str, output: str) -> bool:
    """Create a vocal residual when a UVR release reports only instrumental."""
    try:
        import numpy as np

        with wave.open(source, "rb") as src_handle:
            src_channels = src_handle.getnchannels()
            src_rate = src_handle.getframerate()
            src = np.frombuffer(src_handle.readframes(src_handle.getnframes()), dtype=np.int16)
        with wave.open(instrumental, "rb") as inst_handle:
            inst_channels = inst_handle.getnchannels()
            inst_rate = inst_handle.getframerate()
            inst = np.frombuffer(inst_handle.readframes(inst_handle.getnframes()), dtype=np.int16)
        if not src_channels or not inst_channels or src_rate != inst_rate:
            return False
        src = src.reshape(-1, src_channels).astype(np.float32)
        inst = inst.reshape(-1, inst_channels).astype(np.float32)
        if inst.shape[1] == 1 and src.shape[1] > 1:
            inst = np.repeat(inst, src.shape[1], axis=1)
        if src.shape[1] == 1 and inst.shape[1] > 1:
            src = np.repeat(src, inst.shape[1], axis=1)
        channels = min(src.shape[1], inst.shape[1])
        length = max(src.shape[0], inst.shape[0])
        src = np.pad(src[:, :channels], ((0, length - src.shape[0]), (0, 0)))
        inst = np.pad(inst[:, :channels], ((0, length - inst.shape[0]), (0, 0)))
        residual = np.clip(src - inst, -32768, 32767).astype(np.int16)
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        with wave.open(output, "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(src_rate)
            handle.writeframes(residual.tobytes())
        return True
    except Exception:  # noqa: BLE001 - fallback must never mask the main error
        return False


def main() -> int:
    args = _build_parser().parse_args()

    inp = os.path.abspath(args.input) if args.input else ""
    out_dir = os.path.abspath(args.out_dir)
    requested_device = str(args.device or "auto").strip().lower()
    os.makedirs(out_dir, exist_ok=True)
    if not args.server and not os.path.isfile(inp):
        print(f"UVR_ERR 输入不存在: {inp}")
        return 2
    if requested_device == "dml":
        requested_device = "directml"
    if requested_device not in {"auto", "cuda", "rocm", "directml", "cpu"}:
        print(f"UVR_ERR 不支持的分离设备: {requested_device}")
        return 2

    # 强制 CPU：在导入 torch / audio_separator 之前隐藏 CUDA，使其自动回退到 CPU。
    if requested_device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    try:
        import torch

        if requested_device in {"cuda", "rocm"} and not torch.cuda.is_available():
            print(
                f"UVR_ERR 已选择 {requested_device.upper()}，但 UVR 环境没有可用的加速设备；"
                "请重新安装 GPU 版 UVR 环境"
            )
            return 6
        if requested_device == "cuda" and getattr(torch.version, "hip", None):
            print("UVR_ERR 已选择 CUDA，但 UVR 环境安装的是 AMD ROCm")
            return 6
        if requested_device == "rocm" and not getattr(torch.version, "hip", None):
            print("UVR_ERR 已选择 ROCm，但 UVR 环境未安装 ROCm Torch")
            return 6

        directml = None
        use_directml = requested_device == "directml"
        if requested_device == "auto" and not torch.cuda.is_available():
            try:
                from inference_device import resolve_torch_device

                directml = resolve_torch_device("directml", torch)
            except (ImportError, RuntimeError):
                directml = None
            else:
                use_directml = True

        if use_directml:
            try:
                import torch_directml
                from inference_device import resolve_torch_device

                directml = directml or resolve_torch_device("directml", torch)
                # audio-separator asks torch-directml for its default adapter.
                # Keep that choice aligned with the app's AMD-first adapter selection.
                torch_directml.default_device = lambda: directml.index
            except (ImportError, RuntimeError) as exc:
                print(f"UVR_ERR 已选择 DirectML，但 UVR 环境不可用: {exc}")
                return 6
        from audio_separator.separator import Separator
        if use_directml:
            _patch_directml_vr_lstm()
    except Exception as exc:  # noqa: BLE001
        print(f"UVR_ERR 依赖导入失败: {exc}")
        traceback.print_exc()
        return 3

    try:
        separator = Separator(
            model_file_dir=args.model_dir,
            output_dir=out_dir,
            output_format="WAV",
            use_directml=use_directml,
        )
        actual_device = str(separator.torch_device or "cpu").lower()
        actual_backend = _torch_backend(torch, separator.torch_device)
        expected_backend = requested_device if requested_device != "auto" else ""
        if expected_backend and actual_backend != expected_backend:
            print(
                f"UVR_ERR 已选择 {expected_backend.upper()}，"
                f"但分离引擎实际设备为 {actual_device}"
            )
            return 6
        if use_directml and args.model.lower().endswith(".onnx"):
            providers = list(separator.onnx_execution_provider or [])
            if "DmlExecutionProvider" not in providers:
                print("UVR_ERR DirectML ONNX Runtime 未启用 DmlExecutionProvider")
                return 6
        print(f"UVR_DEVICE {actual_backend}", flush=True)
        separator.load_model(model_filename=args.model)
    except Exception as exc:  # noqa: BLE001
        print(f"UVR_ERR 分离失败: {exc}")
        traceback.print_exc()
        return 4

    def separate_one(
        source: str,
        requested_output: str = "",
        requested_instrumental: str = "",
    ) -> tuple[str, str]:
        if not os.path.isfile(source):
            raise ValueError(f"输入音频不存在: {source}")
        outputs = separator.separate(source)
        # audio-separator 可能返回基名或绝对路径，统一解析为绝对路径。
        resolved = [
            os.path.abspath(os.fspath(p)) if os.path.isabs(os.fspath(p))
            else os.path.abspath(os.path.join(out_dir, os.fspath(p)))
            for p in (outputs or [])
        ]
        vocals, instrumental = _classify(resolved)
        # audio-separator versions differ in whether they return absolute
        # paths, basenames, or paths with a model suffix. If the returned path
        # is stale, rescan the output directory for this block's generated
        # stems before declaring separation failed.
        discovered: list[str] = []
        if not vocals or not os.path.isfile(vocals):
            stem = os.path.splitext(os.path.basename(source))[0]
            for root, _dirs, names in os.walk(out_dir):
                discovered.extend(
                    os.path.abspath(os.path.join(root, name))
                    for name in names
                    if name.lower().startswith(stem.lower())
                    and name.lower().endswith((".wav", ".flac", ".mp3"))
                )
            if discovered:
                resolved = discovered
                vocals, instrumental = _classify(resolved)
        if (not vocals or not os.path.isfile(vocals)) and instrumental and os.path.isfile(instrumental):
            fallback = os.path.join(
                out_dir,
                f"{os.path.splitext(os.path.basename(source))[0]}_(Vocals)_residual.wav",
            )
            if _write_residual_vocal(source, instrumental, fallback):
                resolved.append(fallback)
                vocals = fallback
        if not vocals or not os.path.isfile(vocals):
            raise RuntimeError(f"未找到人声输出，实际输出: {resolved}")
        if requested_output:
            try:
                os.makedirs(os.path.dirname(requested_output) or out_dir, exist_ok=True)
                shutil.copyfile(vocals, requested_output)
                if requested_instrumental and instrumental and os.path.isfile(instrumental):
                    os.makedirs(os.path.dirname(requested_instrumental) or out_dir, exist_ok=True)
                    shutil.copyfile(instrumental, requested_instrumental)
            finally:
                # Server blocks are transient. Never leave UVR's generated
                # stems accumulating in the session temp directory.
                for generated in resolved:
                    try:
                        os.unlink(generated)
                    except OSError:
                        pass
        return vocals, instrumental

    if args.server:
        print("UVR_SERVER_READY", flush=True)
        for raw in sys.stdin:
            try:
                request = json.loads(raw)
                if request.get("command") == "close":
                    break
                source = str(request.get("input") or "")
                requested_output = str(request.get("output") or "")
                requested_instrumental = str(request.get("instrumental") or "")
                separate_one(source, requested_output, requested_instrumental)
                result = {
                    "ok": True,
                    "output": requested_output,
                    "instrumental": requested_instrumental,
                }
            except Exception as exc:  # noqa: BLE001 - keep serving after one bad block
                result = {"ok": False, "error": str(exc)}
            print("UVR_SERVER_RESULT\t" + json.dumps(result, ensure_ascii=False), flush=True)
        return 0

    if not args.input:
        print("UVR_ERR 非 server 模式必须提供 --input")
        return 2
    try:
        vocals, instrumental = separate_one(inp)
    except Exception as exc:  # noqa: BLE001
        print(f"UVR_ERR {exc}")
        traceback.print_exc()
        return 5

    # 结果以 UTF-8 JSON 写入文件，避免中文路径经子进程 stdout 管道（Windows 默认 GBK）
    # 被父进程按 UTF-8 解码时损坏，从而被误判为"分离失败"。
    try:
        with open(
            os.path.join(out_dir, "uvr_result.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "vocals": vocals,
                    "instrumental": instrumental,
                    "device": actual_backend,
                },
                f,
            )
    except OSError:
        pass

    print(f"UVR_OK\t{vocals}\t{instrumental}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
