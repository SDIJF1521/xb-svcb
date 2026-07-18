"""SeedVC 推理 worker（运行于 ``.venv-seedvc`` 中，调用官方 Seed-VC inference.py）。

成功时打印 ``SEEDVC_OK <output_path>``；失败时打印 ``SEEDVC_ERR <message>``。
官方脚本输出到目录且自动生成文件名，本 worker 负责把最新生成的 wav 复制到主程序
指定的输出路径，便于复用 XB-SVCB 的统一流水线。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

try:
    from inference_device import patch_directml_no_half, resolve_torch_device
except ImportError:  # package import used by tests/application tooling
    from infrastructure.inference_device import patch_directml_no_half, resolve_torch_device
from typing import Any, Callable


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _latest_wav(folder: Path) -> Path | None:
    wavs = [p for p in folder.glob("*.wav") if p.is_file()]
    if not wavs:
        return None
    return max(wavs, key=lambda p: p.stat().st_mtime)


def _valid_file(path: Path, minimum_size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= minimum_size
    except OSError:
        return False


def _valid_model_dir(path: Path, required: dict[str, int]) -> bool:
    return path.is_dir() and all(
        _valid_file(path / name, minimum_size)
        for name, minimum_size in required.items()
    )


def _installation_root() -> Path:
    worker = Path(__file__).resolve()
    for parent in worker.parents:
        if (parent / "assets" / "models").is_dir():
            return parent
    return worker.parents[2]


def _discover_local_assets(repo: Path, install_root: Path | None = None) -> dict[str, Path]:
    root = install_root or _installation_root()
    bundled = root / "assets" / "models"
    checkpoints = repo / "checkpoints"
    found: dict[str, Path] = {}

    for candidate in (
        bundled / "pretrain" / "rmvpe.pt",
        checkpoints / "rmvpe.pt",
    ):
        if _valid_file(candidate, 300 * 1024 * 1024):
            found["rmvpe"] = candidate.resolve()
            break

    for candidate in (
        bundled / "seedvc" / "campplus_cn_common.bin",
        checkpoints / "campplus_cn_common.bin",
        repo / "campplus_cn_common.bin",
    ):
        if _valid_file(candidate, 20 * 1024 * 1024):
            found["campplus"] = candidate.resolve()
            break

    whisper_required = {
        "config.json": 1024,
        "preprocessor_config.json": 1024,
        "model.safetensors": 900 * 1024 * 1024,
    }
    for candidate in (
        bundled / "seedvc" / "whisper-small",
        checkpoints / "local_whisper_small",
    ):
        if _valid_model_dir(candidate, whisper_required):
            found["whisper"] = candidate.resolve()
            break

    bigvgan_required = {
        "config.json": 1024,
        "bigvgan_generator.pt": 400 * 1024 * 1024,
    }
    for candidate in (
        bundled / "seedvc" / "bigvgan_v2_44khz_128band_512x",
        checkpoints / "local_bigvgan_v2_44khz_128band_512x",
    ):
        if _valid_model_dir(candidate, bigvgan_required):
            found["bigvgan"] = candidate.resolve()
            break

    return found


def _normalized_seedvc_rmvpe(source: Path, repo: Path) -> Path:
    destination = repo / "checkpoints" / "rmvpe.pt"
    marker = destination.with_name(destination.name + ".xb-normalized")
    if _valid_file(destination, 300 * 1024 * 1024) and marker.is_file():
        return destination.resolve()

    import torch

    try:
        obj = torch.load(source, map_location="cpu", weights_only=False)
    except TypeError:
        obj = torch.load(source, map_location="cpu")
    wrapped = False
    state = obj.get("model") if isinstance(obj, dict) else None
    if isinstance(state, dict):
        obj = state
        wrapped = True
    if isinstance(obj, dict):
        cleaned = {key: value for key, value in obj.items() if not key.startswith("unet.tf.")}
        if len(cleaned) != len(obj):
            obj = cleaned
            wrapped = True
    expected = ("unet.encoder.bn.weight", "cnn.weight", "fc.1.bias")
    if not isinstance(obj, dict) or not any(key in obj for key in expected):
        raise RuntimeError(f"自带 RMVPE 格式不兼容: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve() or wrapped:
        temporary = destination.with_name(destination.name + ".xbtmp")
        temporary.unlink(missing_ok=True)
        torch.save(obj, temporary)
        temporary.replace(destination)
    marker.write_text("xb-svcb seedvc rmvpe v1\n", encoding="ascii")
    return destination.resolve()


def _local_hf_loader(
    original: Callable[..., Any],
    assets: dict[str, Path],
) -> Callable[..., Any]:
    local_files = {
        ("lj1995/voiceconversionwebui", "rmvpe.pt"): assets.get("rmvpe"),
        ("funasr/campplus", "campplus_cn_common.bin"): assets.get("campplus"),
    }

    def load(repo_id: str, model_filename: str = "pytorch_model.bin", config_filename: str | None = None):
        key = (str(repo_id).lower(), str(model_filename).replace("\\", "/"))
        local_model = local_files.get(key)
        if config_filename is None and local_model and local_model.exists():
            return str(local_model)
        return original(repo_id, model_filename, config_filename)

    return load


def _apply_local_model_paths(data: dict[str, Any], assets: dict[str, Path]) -> bool:
    model_params = data.get("model_params")
    if not isinstance(model_params, dict):
        return False
    changed = False

    vocoder = model_params.get("vocoder")
    if isinstance(vocoder, dict):
        name = str(vocoder.get("name") or "").strip().lower()
        if name == "nvidia/bigvgan_v2_44khz_128band_512x" and assets.get("bigvgan"):
            vocoder["name"] = str(assets["bigvgan"])
            changed = True

    tokenizer = model_params.get("speech_tokenizer")
    if isinstance(tokenizer, dict):
        name = str(tokenizer.get("name") or "").strip().lower()
        if name == "openai/whisper-small" and assets.get("whisper"):
            tokenizer["name"] = str(assets["whisper"])
            changed = True
    return changed


def _localized_config(config: Path, folder: Path, assets: dict[str, Path]) -> Path:
    if not assets.get("whisper") and not assets.get("bigvgan"):
        return config
    try:
        import yaml

        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not _apply_local_model_paths(data, assets):
            return config
        output = folder / "seedvc_local_config.yml"
        output.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return output
    except Exception as exc:  # noqa: BLE001 - invalid optional local config falls back safely
        print(f"SEEDVC_INFO 本地模型配置生成失败，将使用原配置: {exc}", flush=True)
        return config


def main() -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB SeedVC inference worker")
    parser.add_argument("--repo", required=True, help="Seed-VC 仓库根目录")
    parser.add_argument("--checkpoint", required=True, help="SeedVC checkpoint .pth 路径")
    parser.add_argument("--config", required=True, help="SeedVC config .yml/.yaml 路径")
    parser.add_argument("--reference", required=True, help="目标音色参考音频路径")
    parser.add_argument("--input", required=True, help="待转换人声 wav")
    parser.add_argument("--output", required=True, help="输出 wav 路径")
    parser.add_argument(
        "--device",
        default="auto",
        help="auto / cuda / rocm / directml / cpu",
    )
    parser.add_argument("--pitch", type=int, default=0, help="半音变调")
    parser.add_argument("--diffusion-steps", type=int, default=30)
    parser.add_argument("--length-adjust", type=float, default=1.0)
    parser.add_argument("--cfg-rate", type=float, default=0.7)
    parser.add_argument("--fp16", type=_parse_bool, default=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    checkpoint = Path(args.checkpoint).resolve()
    config = Path(args.config).resolve()
    reference = Path(args.reference).resolve()
    source = Path(args.input).resolve()
    out_path = Path(args.output).resolve()

    for label, path in (
        ("仓库", repo),
        ("模型", checkpoint),
        ("配置", config),
        ("参考音频", reference),
        ("输入音频", source),
    ):
        if not path.exists():
            print(f"SEEDVC_ERR {label}不存在: {path}", flush=True)
            return 2
    if not (repo / "inference.py").exists():
        print(f"SEEDVC_ERR Seed-VC inference.py 不存在: {repo}", flush=True)
        return 2

    if str(args.device or "").lower() == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        fp16 = False
    else:
        fp16 = bool(args.fp16)

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    hf_mirror = (
        os.environ.get("XB_HF_MIRROR")
        or os.environ.get("HF_ENDPOINT")
        or "https://hf-mirror.com"
    ).strip().rstrip("/")
    os.environ.setdefault("XB_HF_MIRROR", hf_mirror)
    os.environ.setdefault("HF_ENDPOINT", hf_mirror)
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", hf_mirror)

    old_cwd = Path.cwd()
    sys.path.insert(0, str(repo))
    try:
        os.chdir(repo)
        try:
            import torch

            resolved_device = resolve_torch_device(args.device, torch)
            if resolved_device.backend == "directml":
                patch_directml_no_half(torch)
                fp16 = False
        except Exception as exc:  # noqa: BLE001
            print(f"SEEDVC_ERR 设备初始化失败: {exc}", flush=True)
            return 3
        local_assets = _discover_local_assets(repo)
        if local_assets.get("rmvpe"):
            try:
                local_assets["rmvpe"] = _normalized_seedvc_rmvpe(
                    local_assets["rmvpe"],
                    repo,
                )
            except Exception as exc:  # noqa: BLE001 - emit a stable worker error
                print(f"SEEDVC_ERR SeedVC RMVPE 底模准备失败: {exc}", flush=True)
                return 3
        try:
            import inference as seedvc_inference  # type: ignore

            seedvc_inference.load_custom_model_from_hf = _local_hf_loader(
                seedvc_inference.load_custom_model_from_hf,
                local_assets,
            )
            seedvc_inference.device = resolved_device.device
            if resolved_device.backend == "directml":
                from transformers import WhisperModel

                original_from_pretrained = WhisperModel.from_pretrained

                def directml_from_pretrained(cls, *model_args, **model_kwargs):  # noqa: ANN001, ANN202
                    model_kwargs["torch_dtype"] = torch.float32
                    return original_from_pretrained(*model_args, **model_kwargs)

                WhisperModel.from_pretrained = classmethod(directml_from_pretrained)
            seedvc_main = seedvc_inference.main
        except Exception as exc:  # noqa: BLE001
            print(f"SEEDVC_ERR SeedVC 依赖导入失败: {exc}", flush=True)
            return 3

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xb_seedvc_") as td:
            out_dir = Path(td)
            inference_config = _localized_config(config, out_dir, local_assets)
            ns = SimpleNamespace(
                source=str(source),
                target=str(reference),
                output=str(out_dir),
                diffusion_steps=max(1, int(args.diffusion_steps)),
                length_adjust=float(args.length_adjust),
                inference_cfg_rate=float(args.cfg_rate),
                f0_condition=True,
                auto_f0_adjust=False,
                semi_tone_shift=int(args.pitch),
                checkpoint=str(checkpoint),
                config=str(inference_config),
                fp16=fp16,
            )
            try:
                seedvc_main(ns)
            except Exception as exc:  # noqa: BLE001
                print(f"SEEDVC_ERR SeedVC 推理失败: {exc}", flush=True)
                return 4
            generated = _latest_wav(out_dir)
            if not generated or not generated.exists():
                print("SEEDVC_ERR SeedVC 未生成 wav 输出", flush=True)
                return 5
            try:
                shutil.copy2(generated, out_path)
            except OSError as exc:
                print(f"SEEDVC_ERR 写出失败: {exc}", flush=True)
                return 6
    finally:
        try:
            os.chdir(old_cwd)
        except OSError:
            pass
    print(f"SEEDVC_DEVICE {resolved_device.backend} {resolved_device.name}", flush=True)
    print(f"SEEDVC_OK {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
