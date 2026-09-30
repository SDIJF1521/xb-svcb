"""RVC 推理子进程脚本（运行于隔离环境中，依赖 rvc-python）。

由 ``RvcEngine`` 以子进程方式调用，与主程序的依赖环境隔离。约定输出：
- 成功：``RVC_OK <output_path>``
- 失败：``RVC_ERR <message>``

rvc-python 默认会在首次实例化时下载 hubert / rmvpe 底模；本 worker 会先从安装包
自带的 ``assets/models/pretrain`` 预置底模，避免新用户首次 RVC 推理时卡在外网下载。
``load_model`` 直接接受 ``.pth`` 路径与可选 ``.index`` 路径。
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os

# FAISS uses OpenMP around its searches while NumPy/OpenBLAS may create another
# worker pool inside each FAISS worker. On Windows that nested parallelism can
# consume every CPU core for tens of minutes before ROCm receives the next RVC
# segment. These variables must be set before importing NumPy/FAISS (the local
# infrastructure imports below can import NumPy). A dedicated XB setting keeps
# the limit explicit and user-overridable without inheriting a machine-wide
# OPENBLAS_NUM_THREADS value.
if __name__ == "__main__":
    try:
        _rvc_blas_threads = max(
            1, int(os.environ.get("XB_RVC_BLAS_THREADS", "1"))
        )
    except (TypeError, ValueError):
        _rvc_blas_threads = 1
    for _rvc_blas_env in (
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[_rvc_blas_env] = str(_rvc_blas_threads)
    del _rvc_blas_env, _rvc_blas_threads

import shutil
import sys
import tempfile
import time
import traceback
import urllib.request
import wave
from pathlib import Path

try:
    from inference_naturalizer import (
        format_naturalizer_stats,
        naturalize_inference_output,
    )
    from inference_device import (
        ResolvedDevice,
        patch_directml_checkpoint_load,
        patch_directml_float32,
        patch_directml_rmvpe_cpu,
        resolve_torch_device,
    )
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_naturalizer import (
        format_naturalizer_stats,
        naturalize_inference_output,
    )
    from infrastructure.inference_device import (
        ResolvedDevice,
        patch_directml_checkpoint_load,
        patch_directml_float32,
        patch_directml_rmvpe_cpu,
        resolve_torch_device,
    )


# RVC 支持的 F0 算法；其余（如 so-vits 的 dio/fcpe）统一回退 rmvpe
_RVC_F0_METHODS = {"harvest", "crepe", "rmvpe", "pm"}
_MIN_BASE_MODEL_BYTES = 32 * 1024 * 1024
_HF_MIRROR = (
    os.environ.get("XB_HF_MIRROR")
    or os.environ.get("HF_ENDPOINT")
    or "https://hf-mirror.com"
).strip().rstrip("/")
_RVC_BASE_DOWNLOADS = {
    "hubert_base.pt": [
        f"{_HF_MIRROR}/Daswer123/RVC_Base/resolve/main/hubert_base.pt",
        "https://huggingface.co/Daswer123/RVC_Base/resolve/main/hubert_base.pt",
    ],
    "rmvpe.pt": [
        f"{_HF_MIRROR}/Daswer123/RVC_Base/resolve/main/rmvpe.pt",
        "https://huggingface.co/Daswer123/RVC_Base/resolve/main/rmvpe.pt",
    ],
    "rmvpe.onnx": [
        f"{_HF_MIRROR}/Daswer123/RVC_Base/resolve/main/rmvpe.onnx",
        "https://huggingface.co/Daswer123/RVC_Base/resolve/main/rmvpe.onnx",
    ],
}
_RVC_BASE_SOURCES = {
    "hubert_base.pt": (
        "rvc/hubert_base.pt",
        "pretrain/hubert_base.pt",
        "pretrain/checkpoint_best_legacy_500.pt",
        "checkpoint_best_legacy_500.pt",
    ),
    "rmvpe.pt": (
        "rvc/rmvpe.pt",
        "pretrain/rmvpe.pt",
        "rmvpe.pt",
    ),
    "rmvpe.onnx": (
        "rvc/rmvpe.onnx",
        "pretrain/rmvpe.onnx",
        "rmvpe.onnx",
    ),
}
_RVC_DIRECTML_DEFAULT_THREADS = 1
_RVC_DIRECTML_DEFAULT_WINDOWS = {
    "x_pad": 1,
    "x_query": 3,
    "x_center": 12,
    "x_max": 14,
}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(str(os.environ.get(name, default)).strip()))
    except (TypeError, ValueError):
        return default


def _apply_rvc_directml_thread_limits(torch_module=None) -> int:  # noqa: ANN001
    threads = _env_int(
        "XB_RVC_DIRECTML_THREADS",
        _RVC_DIRECTML_DEFAULT_THREADS,
    )
    for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ.setdefault(name, str(threads))
    if torch_module is not None:
        try:
            torch_module.set_num_threads(threads)
        except Exception:  # noqa: BLE001
            pass
        try:
            torch_module.set_num_interop_threads(1)
        except Exception:  # noqa: BLE001
            pass
    return threads


def _apply_rvc_directml_memory_profile(rvc) -> tuple[int, int, int, int]:  # noqa: ANN001
    x_pad = _env_int("XB_RVC_DIRECTML_X_PAD", _RVC_DIRECTML_DEFAULT_WINDOWS["x_pad"])
    x_query = _env_int(
        "XB_RVC_DIRECTML_X_QUERY",
        _RVC_DIRECTML_DEFAULT_WINDOWS["x_query"],
    )
    x_center = _env_int(
        "XB_RVC_DIRECTML_X_CENTER",
        _RVC_DIRECTML_DEFAULT_WINDOWS["x_center"],
    )
    x_max = _env_int("XB_RVC_DIRECTML_X_MAX", _RVC_DIRECTML_DEFAULT_WINDOWS["x_max"])
    x_query = min(x_query, max(1, x_center - 1))
    x_max = max(x_max, x_center + 1)
    rvc.config.x_pad = x_pad
    rvc.config.x_query = x_query
    rvc.config.x_center = x_center
    rvc.config.x_max = x_max
    return x_pad, x_query, x_center, x_max


def _configure_rvc_torch_load(torch_module, *, directml: bool) -> None:  # noqa: ANN001
    """Apply checkpoint compatibility before importing rvc-python/torchcrepe."""
    if directml:
        # torchcrepe passes the privateuseone torch.device to map_location.
        # Deserialize on CPU; torchcrepe moves the initialized model to DML next.
        patch_directml_checkpoint_load(torch_module)

    original_load = torch_module.load

    def load_compat(*args, **kwargs):  # noqa: ANN001, ANN202
        # PyTorch >=2.6 changed the default, while legacy RVC/fairseq checkpoints
        # still require the former behavior. Explicit callers such as torchcrepe
        # retain their requested weights_only value.
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    torch_module.load = load_compat


def _usable_file(path: Path, min_bytes: int = _MIN_BASE_MODEL_BYTES) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def _candidate_model_files(relative_paths: tuple[str, ...]) -> list[Path]:
    bases: list[Path] = []
    for key in ("XB_RVC_BASE_MODEL_DIR", "XB_RVC_PRETRAIN_DIR", "XB_PRETRAIN_DIR"):
        raw = os.environ.get(key)
        if raw:
            bases.append(Path(raw).expanduser())

    here = Path(__file__).resolve()
    for parent in here.parents:
        bases.extend(
            [
                parent / "assets" / "models",
                parent / "engines" / "so-vits-svc",
                parent / "engines" / "so-vits-svc" / "pretrain",
                parent,
            ]
        )

    seen: set[str] = set()
    out: list[Path] = []
    for base in bases:
        for rel in relative_paths:
            rel_path = Path(rel)
            for path in (base / rel_path, base / rel_path.name):
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(path)
    return out


def _link_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".xbtmp")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    tmp.replace(dest)


def _load_torch_checkpoint(path: Path):  # noqa: ANN202
    import torch  # noqa: WPS433

    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _extract_rvc_rmvpe_state(obj):  # noqa: ANN001, ANN202
    state = obj.get("model") if isinstance(obj, dict) else None
    changed = False
    if isinstance(state, dict):
        obj = state
        changed = True
    if not isinstance(obj, dict):
        return None, False
    cleaned = {key: val for key, val in obj.items() if not key.startswith("unet.tf.")}
    if len(cleaned) != len(obj):
        obj = cleaned
        changed = True
    expected = ("unet.encoder.bn.weight", "cnn.weight", "fc.1.bias")
    if any(key in obj for key in expected):
        return obj, changed
    return None, False


def _ensure_rvc_rmvpe_checkpoint(path: Path) -> bool:
    if not _usable_file(path):
        return False
    try:
        obj = _load_torch_checkpoint(path)
        state, changed = _extract_rvc_rmvpe_state(obj)
        if state is None:
            return False
        if not changed:
            return True
        tmp = path.with_name(path.name + ".xbtmp")
        import torch  # noqa: WPS433

        torch.save(state, tmp)
        tmp.replace(path)
        print("XB: normalized RMVPE checkpoint for RVC", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"XB: RMVPE checkpoint validation failed: {exc}", flush=True)
        try:
            path.with_name(path.name + ".xbtmp").unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _write_rvc_rmvpe_checkpoint(src: Path, dest: Path) -> bool:
    try:
        obj = _load_torch_checkpoint(src)
        state, _changed = _extract_rvc_rmvpe_state(obj)
        if state is None:
            print(f"XB: skipped incompatible RMVPE checkpoint: {src}", flush=True)
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".xbtmp")
        import torch  # noqa: WPS433

        torch.save(state, tmp)
        tmp.replace(dest)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"XB: failed to prepare RMVPE checkpoint {src}: {exc}", flush=True)
        try:
            dest.with_name(dest.name + ".xbtmp").unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _copy_bundled_base_model(name: str, dest: Path, *, required: bool) -> bool:
    sources = [src for src in _candidate_model_files(_RVC_BASE_SOURCES[name]) if _usable_file(src)]
    if name == "rmvpe.pt":
        if _ensure_rvc_rmvpe_checkpoint(dest):
            return True
        for src in sources:
            if _write_rvc_rmvpe_checkpoint(src, dest):
                print(f"XB: RVC base model ready locally: {name}", flush=True)
                return True
        return not required

    if _usable_file(dest):
        if not sources:
            return True
        try:
            if any(dest.stat().st_size == src.stat().st_size for src in sources):
                return True
        except OSError:
            pass

    for src in sources:
        _link_or_copy(src, dest)
        print(f"XB: RVC base model ready locally: {name}", flush=True)
        return True

    return not required


def _download_base_model(name: str, dest: Path) -> bool:
    if name == "rmvpe.pt":
        if _ensure_rvc_rmvpe_checkpoint(dest):
            return True
    elif _usable_file(dest):
        return True
    urls = _RVC_BASE_DOWNLOADS.get(name, ())
    tmp = dest.with_name(dest.name + ".download")
    for url in urls:
        try:
            print(f"XB: downloading missing RVC base model {name}: {url}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, tmp.open("wb") as f:
                shutil.copyfileobj(resp, f, length=1024 * 1024)
            if not _usable_file(tmp):
                raise RuntimeError("downloaded file is too small or empty")
            tmp.replace(dest)
            if name == "rmvpe.pt" and not _ensure_rvc_rmvpe_checkpoint(dest):
                raise RuntimeError("downloaded RMVPE checkpoint is incompatible")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"XB: RVC base model source failed: {exc}", flush=True)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return False


def _prepare_rvc_base_models(lib_dir: str) -> None:
    """Pre-seed rvc-python base models from XB bundled assets before it goes online."""
    base_dir = Path(lib_dir) / "base_model"
    base_dir.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for name in ("hubert_base.pt", "rmvpe.pt"):
        dest = base_dir / name
        if _copy_bundled_base_model(name, dest, required=True):
            continue
        if _download_base_model(name, dest):
            continue
        missing.append(name)

    # rvc-python checks for this file in its generic downloader, but XB uses
    # PyTorch RMVPE for CUDA/CPU and the stable CPU RMVPE path for DirectML.
    _copy_bundled_base_model("rmvpe.onnx", base_dir / "rmvpe.onnx", required=False)

    if missing:
        raise RuntimeError(
            "RVC 底模缺失，且本地自带模型/镜像下载都不可用："
            + ", ".join(missing)
            + "。请重新运行“搭建/修复运行环境”，或把这些文件放到 "
            + str(base_dir)
        )


def _resolve_device(requested: str) -> ResolvedDevice:
    import torch  # noqa: WPS433

    return resolve_torch_device(requested, torch)


def _should_force_fp32(
    backend: str,
    torch_version: tuple[int, int],
    *,
    rocm_fp32: bool = False,
) -> bool:
    """Return whether this RVC backend needs the fp32 compatibility path."""
    return (
        backend in {"cpu", "directml"}
        or (backend == "cuda" and torch_version >= (2, 6))
        or (backend == "rocm" and rocm_fp32)
    )


def _module_device(module) -> str:  # noqa: ANN001
    """Return the first parameter device without assuming a model layout."""
    if module is None:
        return "unloaded"
    try:
        parameter = next(module.parameters())
    except (AttributeError, StopIteration, TypeError):
        return "unknown"
    return str(getattr(parameter, "device", "unknown"))


def _rvc_device_report(rvc, resolved: ResolvedDevice, torch_module) -> str:  # noqa: ANN001
    """Describe the devices actually used by RVC's lazily loaded components."""
    vc = getattr(rvc, "vc", None)
    pipeline = getattr(vc, "pipeline", None)
    hubert = getattr(vc, "hubert_model", None)
    rmvpe = getattr(pipeline, "model_rmvpe", None)
    rmvpe_model = getattr(rmvpe, "model", None)
    return (
        "RVC_COMPONENT_DEVICES "
        f"backend={resolved.backend} target={resolved.device} "
        f"config={getattr(getattr(rvc, 'config', None), 'device', 'unknown')} "
        f"is_half={bool(getattr(getattr(rvc, 'config', None), 'is_half', False))} "
        f"net_g={_module_device(getattr(vc, 'net_g', None))} "
        f"hubert={_module_device(hubert)} "
        f"rmvpe={_module_device(rmvpe_model)} "
        f"torch_cuda={bool(getattr(torch_module.cuda, 'is_available', lambda: False)())}"
    )


def _configure_rocm_runtime(torch_module, resolved: ResolvedDevice) -> None:  # noqa: ANN001
    """Avoid an exhaustive MIOpen search on the first ROCm RVC inference.

    RVC creates many different convolution shapes while loading HuBERT, RMVPE
    and the synthesizer.  On a fresh Windows ROCm install, MIOpen's default
    search can benchmark every candidate with large host workspaces before the
    first audio block completes.  CUDA/cuDNN and DirectML do not have this
    startup behavior.  FAST still selects a valid MIOpen solution and keeps
    the setting user-overridable for machines with a warmed MIOpen database.
    """
    if resolved.backend != "rocm":
        return
    os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
    print(
        "XB: ROCm MIOpen 算法搜索模式="
        f"{os.environ.get('MIOPEN_FIND_MODE', 'FAST')}（避免首次推理长时间调优）",
        flush=True,
    )


def _configure_faiss_runtime(faiss_module) -> int:  # noqa: ANN001
    """Keep FAISS parallel while preventing nested BLAS oversubscription."""
    logical_cpus = max(1, int(os.cpu_count() or 1))
    default_threads = max(1, min(8, logical_cpus // 2))
    threads = _env_int("XB_RVC_FAISS_THREADS", default_threads)
    try:
        faiss_module.omp_set_num_threads(threads)
    except (AttributeError, TypeError, ValueError) as exc:
        print(f"XB: FAISS 线程配置失败（继续使用库默认值）: {exc}", flush=True)
        return threads
    print(
        "XB: RVC 索引检索线程 "
        f"FAISS={threads} BLAS={os.environ.get('OPENBLAS_NUM_THREADS', 'default')}",
        flush=True,
    )
    return threads


def _infer_file_checked(rvc, input_path: str, output_path: str) -> str:  # noqa: ANN001
    """Run rvc-python inference and surface vc_single failures before wav writing."""
    if not rvc.current_model:
        raise ValueError("Please load a model first.")

    model_info = rvc.models[rvc.current_model]
    file_index = model_info.get("index", "")
    wav_opt = rvc.vc.vc_single(
        sid=0,
        input_audio_path=input_path,
        f0_up_key=rvc.f0up_key,
        f0_method=rvc.f0method,
        file_index=file_index,
        index_rate=rvc.index_rate,
        filter_radius=rvc.filter_radius,
        resample_sr=rvc.resample_sr,
        rms_mix_rate=rvc.rms_mix_rate,
        protect=rvc.protect,
        f0_file="",
        file_index2="",
    )
    if isinstance(wav_opt, tuple):
        message = wav_opt[0] if wav_opt and isinstance(wav_opt[0], str) else repr(wav_opt)
        raise RuntimeError(message.strip() or "RVC vc_single failed")
    if not hasattr(wav_opt, "dtype"):
        raise RuntimeError(f"RVC returned non-audio output: {type(wav_opt).__name__}")

    from scipy.io import wavfile  # noqa: WPS433

    wavfile.write(output_path, rvc.vc.tgt_sr, wav_opt)
    return output_path


def _warm_up_realtime(rvc) -> None:  # noqa: ANN001
    """Load lazy HuBERT/F0 components before accepting live audio."""
    sample_rate = 16000
    frame_count = sample_rate * 2
    tone = array.array(
        "h",
        (
            int(1200 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
            for index in range(frame_count)
        ),
    )
    with tempfile.TemporaryDirectory(prefix="xb_rvc_warmup_") as temp_dir:
        source = Path(temp_dir) / "warmup.wav"
        output = Path(temp_dir) / "warmup-out.wav"
        with wave.open(str(source), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(tone.tobytes())
        _infer_file_checked(rvc, str(source), str(output))


def main() -> int:
    parser = argparse.ArgumentParser(description="RVC inference worker (rvc-python)")
    parser.add_argument("--model", required=True, help=".pth 主模型路径")
    parser.add_argument("--index", default="", help=".index 检索特征路径（可选）")
    parser.add_argument("--input", default="", help="输入人声 wav")
    parser.add_argument("--output", default="", help="输出转换后人声 wav")
    parser.add_argument("--server", action="store_true", help="常驻进程，逐行接收 JSON 音频块")
    parser.add_argument("--low-latency", action="store_true", help="实时变声模式：跳过逐块自然度后处理")
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
        import torch  # noqa: WPS433
        resolved_device = _resolve_device(args.device)
        print(
            "RVC_RUNTIME "
            f"pid={os.getpid()} exe={sys.executable} "
            f"prefix={sys.prefix} base_prefix={sys.base_prefix} "
            f"torch={getattr(torch, '__file__', '')} "
            f"version={torch.__version__} hip={getattr(torch.version, 'hip', None)}",
            flush=True,
        )
        _configure_rocm_runtime(torch, resolved_device)
        if resolved_device.backend == "directml":
            _apply_rvc_directml_thread_limits(torch)
            patch_directml_float32(torch)
        _configure_rvc_torch_load(
            torch,
            directml=resolved_device.backend == "directml",
        )

        import rvc_python.download_model as rvc_download_model
        import rvc_python.infer as rvc_infer
        import rvc_python.lib.rmvpe as rvc_rmvpe
        import faiss  # noqa: WPS433

        _configure_faiss_runtime(faiss)
        rvc_download_model.download_rvc_models = _prepare_rvc_base_models
        rvc_infer.download_rvc_models = _prepare_rvc_base_models
        if resolved_device.backend == "directml":
            patch_directml_rmvpe_cpu(rvc_rmvpe)
            print("XB: RVC RMVPE 使用 CPU 稳定路径，主模型继续使用 AMD DirectML", flush=True)
            import torch_directml  # type: ignore

            torch_directml.default_device = lambda: resolved_device.index
            original_config = rvc_infer.Config

            def directml_config(lib_dir, _device):  # noqa: ANN001, ANN202
                return original_config(lib_dir, "cpu", is_dml=True)

            rvc_infer.Config = directml_config
        RVCInference = rvc_infer.RVCInference
    except Exception as exc:  # noqa: BLE001
        print(f"RVC_ERR rvc-python 未安装或导入失败: {exc}", flush=True)
        return 1

    try:
        device = str(resolved_device.device)
        method = args.method if args.method in _RVC_F0_METHODS else "rmvpe"
        version = args.version if args.version in ("v1", "v2") else "v2"
        index_path = args.index if args.index else ""

        # 先不传 model_path 构造（避免在构造期就按默认 is_half=True 把模型转半精度），
        # 以便在加载模型前按需切换精度。
        rvc = RVCInference(device=device, version=version)
        if resolved_device.backend in {"cuda", "rocm", "directml"}:
            # rvc-python's Config performs its own hardware detection and can
            # rewrite the device on older AMD/Windows combinations.  The
            # resolver above has already validated the selected backend, so
            # keep every RVC object on that exact device.
            rvc.device = resolved_device.device
            rvc.config.device = resolved_device.device
            rvc.vc.device = resolved_device.device
        if resolved_device.backend == "directml":
            x_pad, x_query, x_center, x_max = _apply_rvc_directml_memory_profile(rvc)
            print(
                "XB: RVC DirectML 低显存切片 "
                f"x_pad={x_pad}, x_query={x_query}, "
                f"x_center={x_center}, x_max={x_max}",
                flush=True,
            )

        # CPU 适配：PyTorch 不支持 CPU half batch_norm，RMVPE 在 is_half=True 时会报
        # "batch_norm not implemented for Half"。CPU 路径必须在加载模型前切 fp32。
        # 50 系（Blackwell, torch>=2.6/cu128）适配：rvc-python 对 5060/5070/5090 默认开
        # fp16（is_half=True），但 fp16 在 Blackwell + 新 torch 上会产生「虚弱/没气/哑音」
        # 的劣化输出。这里在加载模型前强制 fp32，并切到 fp32 对应的切片窗口参数。
        # 老栈（torch 2.1.1 / 40 系及以下）保持默认 fp16（更快且本就正常），不受影响。
        try:
            import torch  # noqa: WPS433

            _tv = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2])
            _cuda_mem_gb = 0.0
            if resolved_device.backend in {"cuda", "rocm"} and torch.cuda.is_available():
                try:
                    _cuda_idx = int(device.split(":", 1)[1]) if ":" in device else 0
                except (TypeError, ValueError):
                    _cuda_idx = 0
                _cuda_mem_gb = torch.cuda.get_device_properties(_cuda_idx).total_memory / (1024**3)
        except Exception:  # noqa: BLE001
            _tv = (0, 0)
            _cuda_mem_gb = 0.0
        # PyTorch 2.6+ needs fp32 for the affected NVIDIA Blackwell CUDA
        # stack, but the same version test must not catch ROCm.  ROCm wheels
        # expose HIP through the CUDA API and rvc-python's default fp16 path
        # is the GPU fast path.  Forcing ROCm 10 (Torch 2.13) to fp32 makes
        # the RVC model look like a CPU workload on supported AMD cards.
        rocm_fp32 = (
            resolved_device.backend == "rocm"
            and os.environ.get("XB_RVC_ROCM_FP32", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        force_fp32 = _should_force_fp32(
            resolved_device.backend,
            _tv,
            rocm_fp32=rocm_fp32,
        )
        if force_fp32:
            try:
                rvc.config.is_half = False
                # fp32 切片窗口（对应 config.device_config 里 is_half=False 分支）
                rvc.config.x_pad = 1
                if resolved_device.backend == "directml":
                    _apply_rvc_directml_memory_profile(rvc)
                else:
                    rvc.config.x_query = 6
                    rvc.config.x_center = 38
                    rvc.config.x_max = 41
                if resolved_device.backend == "directml":
                    reason = "AMD DirectML"
                elif resolved_device.backend == "cpu":
                    reason = "CPU 推理"
                elif resolved_device.backend == "rocm":
                    reason = "ROCm 强制 fp32 配置"
                else:
                    reason = "新 torch"
                print(f"XB: {reason}检测到，RVC 强制 fp32", flush=True)
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

        low_vram_cuda = resolved_device.backend in {"cuda", "rocm"} and 0 < _cuda_mem_gb <= 8.0
        if low_vram_cuda:
            try:
                rvc.config.x_pad = 1
                rvc.config.x_query = 5
                rvc.config.x_center = 30
                rvc.config.x_max = 32
                print(f"XB: CUDA 显存 {_cuda_mem_gb:.1f}GB，RVC 启用低显存切片", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"XB: 设置低显存切片失败（继续用默认切片）: {exc}", flush=True)

        rvc.load_model(args.model, version=version, index_path=index_path)
        print(
            "RVC_DEVICE "
            f"{resolved_device.backend} {resolved_device.name} "
            f"target={resolved_device.device} torch={torch.__version__}",
            flush=True,
        )
        print(_rvc_device_report(rvc, resolved_device, torch), flush=True)
        rvc.set_params(
            f0up_key=int(args.pitch),
            f0method=method,
            index_rate=float(args.index_rate),
            rms_mix_rate=float(args.rms_mix),
            protect=float(args.protect),
            filter_radius=int(args.filter_radius),
        )
        if args.server:
            try:
                _warm_up_realtime(rvc)
                print("XB: RVC 实时组件预热完成", flush=True)
                print(_rvc_device_report(rvc, resolved_device, torch), flush=True)
            except Exception as exc:  # noqa: BLE001 - a real block may still succeed
                print(f"XB: RVC 实时预热失败（继续启动）: {exc}", flush=True)
            print("RVC_SERVER_READY", flush=True)
            for raw in sys.stdin:
                try:
                    request = json.loads(raw)
                    if request.get("command") == "close":
                        break
                    input_path = str(request.get("input") or "")
                    output_path = str(request.get("output") or "")
                    if not input_path or not output_path:
                        raise ValueError("输入或输出路径为空")
                    infer_started = time.perf_counter()
                    _infer_file_checked(rvc, input_path, output_path)
                    if resolved_device.backend in {"cuda", "rocm"}:
                        torch.cuda.synchronize()
                    infer_seconds = time.perf_counter() - infer_started
                    post_started = time.perf_counter()
                    if not args.low_latency:
                        naturalize_inference_output(input_path, output_path, "rvc")
                    post_seconds = time.perf_counter() - post_started
                    print(
                        "RVC_TIMING "
                        f"infer_seconds={infer_seconds:.3f} "
                        f"postprocess_seconds={post_seconds:.3f}",
                        flush=True,
                    )
                    result = {"ok": True, "output": output_path}
                except Exception as exc:  # noqa: BLE001 - per-block errors must not kill the session
                    result = {"ok": False, "error": str(exc)}
                print("RVC_SERVER_RESULT\t" + json.dumps(result, ensure_ascii=False), flush=True)
            return 0
        if not args.input or not args.output:
            raise ValueError("非 server 模式必须提供 --input 和 --output")
        infer_started = time.perf_counter()
        _infer_file_checked(rvc, args.input, args.output)
        if resolved_device.backend in {"cuda", "rocm"}:
            # The HIP queue is asynchronous. Synchronizing here makes the
            # device report describe completed GPU work, not only enqueued work.
            torch.cuda.synchronize()
        infer_seconds = time.perf_counter() - infer_started
        print(_rvc_device_report(rvc, resolved_device, torch), flush=True)
        post_started = time.perf_counter()
        natural_stats = naturalize_inference_output(args.input, args.output, "rvc")
        post_seconds = time.perf_counter() - post_started
        print(
            "RVC_TIMING "
            f"infer_seconds={infer_seconds:.3f} "
            f"postprocess_seconds={post_seconds:.3f}",
            flush=True,
        )
        print(f"RVC_NATURAL {format_naturalizer_stats(natural_stats)}", flush=True)
        print(f"RVC_OK {args.output}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"RVC_ERR {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
