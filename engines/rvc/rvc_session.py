"""Official RVC inference session.

The application used to drive RVC through the third-party ``rvc-python`` package.
This module replaces that dependency with the official RVC inference stack that
is vendored under ``engines/rvc/infer`` (RVC-Project / Retrieval-based-Voice-
Conversion-WebUI, tag 2.2.231006, MIT).  The public surface intentionally keeps
the small shape the worker already relied on:

    session = RvcSession(device="cuda:0", hubert_path=..., rmvpe_path=...)
    session.load_model(model_path, version="v2", index_path="...")
    session.set_params(f0up_key=0, f0_method="rmvpe", ...)
    audio = session.vc.vc_single(...)          # int16 numpy array
    write(output, session.vc.tgt_sr, audio)

Only the wiring lives here; model definitions, the synthesis pipeline and the
F0 extractors are the official files, unmodified except for the small runtime
hooks documented in ``NOTICE.md``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import torch

ENGINE_ROOT = Path(__file__).resolve().parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from infer.lib.audio import load_audio  # noqa: E402
from infer.lib.infer_pack.models import (  # noqa: E402
    SynthesizerTrnMs256NSFsid,
    SynthesizerTrnMs256NSFsid_nono,
    SynthesizerTrnMs768NSFsid,
    SynthesizerTrnMs768NSFsid_nono,
)
from infer.modules.vc.pipeline import Pipeline  # noqa: E402

logger = logging.getLogger(__name__)

_CONFIG_FILES = ("v1/32k.json", "v1/40k.json", "v1/48k.json", "v2/48k.json", "v2/32k.json")
_SYNTHESIZERS = {
    ("v1", 1): SynthesizerTrnMs256NSFsid,
    ("v1", 0): SynthesizerTrnMs256NSFsid_nono,
    ("v2", 1): SynthesizerTrnMs768NSFsid,
    ("v2", 0): SynthesizerTrnMs768NSFsid_nono,
}
_SUPPORTED_VERSIONS = {"v1", "v2"}


class RvcConfig:
    """Minimal stand-in for the official WebUI ``Config`` object.

    The official pipeline only reads the device, precision and slicing window
    fields, so the application keeps ownership of device selection and of the
    fp16/fp32 decision instead of letting ``configs/config.py`` probe hardware
    and rewrite the runtime.
    """

    def __init__(
        self,
        device: str | torch.device,
        is_half: bool,
        *,
        hubert_path: Path,
        rmvpe_path: Path,
        config_dir: Path | None = None,
    ) -> None:
        self.device = device
        self.is_half = bool(is_half)
        self.dtype = torch.float16 if self.is_half else torch.float32
        self.use_jit = False
        self.n_cpu = 0
        self.gpu_name = None
        self.gpu_mem = None
        self.hubert_path = Path(hubert_path)
        self.rmvpe_path = Path(rmvpe_path)
        self.config_dir = Path(config_dir or ENGINE_ROOT / "configs")
        self.json_config = self._load_config_json()
        if self.is_half:
            self.x_pad, self.x_query, self.x_center, self.x_max = 3, 10, 60, 65
        else:
            self.x_pad, self.x_query, self.x_center, self.x_max = 1, 6, 38, 41

    def _load_config_json(self) -> dict[str, Any]:
        configs: dict[str, Any] = {}
        for name in _CONFIG_FILES:
            path = self.config_dir / name
            try:
                configs[name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("RVC config %s is missing or invalid", path)
        return configs


class _VcFacade:
    """Mirror of the ``rvc_python`` VC object used by the worker."""

    def __init__(self, session: "RvcSession") -> None:
        self._session = session

    @property
    def tgt_sr(self) -> int | None:
        return self._session.tgt_sr

    @property
    def net_g(self):  # noqa: ANN201
        return self._session.net_g

    @property
    def hubert_model(self):  # noqa: ANN201
        return self._session.hubert_model

    @property
    def pipeline(self):  # noqa: ANN201
        return self._session.pipeline

    @property
    def device(self):  # noqa: ANN201
        return self._session.config.device

    @device.setter
    def device(self, value: Any) -> None:
        self._session.config.device = value

    def vc_single(
        self,
        sid: int = 0,
        input_audio_path: str = "",
        f0_up_key: int = 0,
        f0_method: str = "rmvpe",
        file_index: str = "",
        index_rate: float = 0.75,
        filter_radius: int = 3,
        resample_sr: int = 0,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
        f0_file: str = "",
        file_index2: str = "",
        **_kwargs: Any,
    ) -> Any:
        # The worker treats a tuple as an error and a numpy array as audio.
        try:
            return self._session.infer(
                sid=sid,
                input_audio_path=input_audio_path,
                f0_up_key=f0_up_key,
                f0_method=f0_method,
                file_index=file_index,
                index_rate=index_rate,
                filter_radius=filter_radius,
                resample_sr=resample_sr,
                rms_mix_rate=rms_mix_rate,
                protect=protect,
                f0_file=f0_file,
                file_index2=file_index2,
            )
        except Exception:  # noqa: BLE001 - worker surfaces the message tail
            info = traceback.format_exc()
            logger.warning(info)
            return info, (None, None)


class RvcSession:
    """One loaded RVC model plus the official synthesis pipeline."""

    def __init__(
        self,
        device: str | torch.device = "cpu",
        version: str = "v2",
        *,
        hubert_path: Path,
        rmvpe_path: Path,
        is_half: bool | None = None,
        config_dir: Path | None = None,
    ) -> None:
        if is_half is None:
            is_half = str(device).startswith(("cuda", "rocm"))
        self.config = RvcConfig(
            device,
            is_half,
            hubert_path=hubert_path,
            rmvpe_path=rmvpe_path,
            config_dir=config_dir,
        )
        self.version = version if version in _SUPPORTED_VERSIONS else "v2"
        self.device = device
        self.vc = _VcFacade(self)
        self.current_model: str | None = None
        self.models: dict[str, dict[str, str]] = {}
        self.tgt_sr: int | None = None
        self.net_g = None
        self.hubert_model = None
        self.pipeline: Pipeline | None = None
        self.if_f0: int | None = None
        self.last_times: list[float] = [0.0, 0.0, 0.0]
        self.low_latency = False
        # Parameter defaults mirror the previous adapter so callers that skip
        # set_params still get the same numbers.
        self.f0method = "harvest"
        self.f0up_key = 0
        self.index_rate = 0.5
        self.filter_radius = 3
        self.resample_sr = 0
        self.rms_mix_rate = 1.0
        self.protect = 0.33
        self._configure_rmvpe_root()

    # ---- official pipeline hooks -------------------------------------
    def _configure_rmvpe_root(self) -> None:
        # The official pipeline resolves ``<rmvpe_root>/rmvpe.pt``; point it at
        # the application's model directory instead of the WebUI assets tree.
        os.environ["rmvpe_root"] = str(Path(self.config.rmvpe_path).parent)

    def configure_low_latency(
        self,
        *,
        pad_seconds: float = 0.1,
        query_seconds: float = 0.04,
        center_seconds: float = 0.5,
        max_seconds: float = 30.0,
    ) -> None:
        """Use a short slicing window for per-block live inference.

        The official defaults keep 3 s of context on each side of the block
        and split anything longer than 65 s. For a 0.5 s live block that means
        the synthesizer encodes 6.5 s of audio for every 0.5 s produced. Short
        but non-zero context keeps RVC stable while staying inside the
        realtime budget.
        """
        self.low_latency = True
        self.config.x_pad = max(0.01, float(pad_seconds))
        self.config.x_query = max(0.01, float(query_seconds))
        self.config.x_center = max(0.05, float(center_seconds))
        # Keep short live blocks in a single pass (no query-point splitting).
        self.config.x_max = max(1.0, float(max_seconds))

    def _load_hubert(self):  # noqa: ANN202
        from fairseq import checkpoint_utils

        hubert_path = Path(self.config.hubert_path)
        if not hubert_path.is_file():
            raise FileNotFoundError(f"RVC HuBERT 底模不存在: {hubert_path}")
        models, _cfg, _task = checkpoint_utils.load_model_ensemble_and_task(
            [str(hubert_path)],
            suffix="",
        )
        model = models[0]
        model = model.half() if self.config.is_half else model.float()
        return model.to(self.config.device).eval()

    # ---- rvc-python compatible surface --------------------------------
    def load_model(
        self,
        model_path_or_name: str,
        version: str = "v2",
        index_path: str = "",
    ) -> None:
        model_path = Path(str(model_path_or_name))
        if not model_path.is_file():
            raise FileNotFoundError(f"RVC 模型不存在: {model_path}")
        if index_path and not Path(index_path).is_file():
            raise ValueError(f"RVC 索引不存在: {index_path}")

        checkpoint = torch.load(str(model_path), map_location="cpu")
        if not isinstance(checkpoint, dict) or "weight" not in checkpoint:
            raise ValueError("不是可识别的 RVC 权重文件")

        config = checkpoint.get("config")
        if not isinstance(config, list) or len(config) < 4:
            raise ValueError("RVC 权重缺少 config 字段")
        self.tgt_sr = int(config[-1])
        config[-3] = int(checkpoint["weight"]["emb_g.weight"].shape[0])
        self.if_f0 = int(checkpoint.get("f0", 1))

        declared = str(checkpoint.get("version") or version or "v2").strip().lower()
        self.version = declared if declared in _SUPPORTED_VERSIONS else "v2"
        synthesizer = _SYNTHESIZERS.get((self.version, self.if_f0))
        if synthesizer is None:
            raise ValueError(
                f"不支持的 RVC 组合: version={self.version!r} f0={self.if_f0!r}"
            )

        kwargs = {"is_half": self.config.is_half} if self.if_f0 == 1 else {}
        self.net_g = synthesizer(*config, **kwargs)
        if hasattr(self.net_g, "enc_q"):
            del self.net_g.enc_q
        missing, unexpected = self.net_g.load_state_dict(checkpoint["weight"], strict=False)
        if missing:
            logger.info("RVC checkpoint missing keys: %s", missing[:5])
        if unexpected:
            logger.info("RVC checkpoint unexpected keys: %s", unexpected[:5])
        self.net_g.eval().to(self.config.device)
        self.net_g = self.net_g.half() if self.config.is_half else self.net_g.float()

        self.pipeline = Pipeline(self.tgt_sr, self.config)
        if self.low_latency:
            # Per-call ``empty_cache`` synchronizes the device and is a large
            # fixed cost for 0.25-0.5 s blocks; the resident worker already
            # bounds memory use.
            self.pipeline.empty_cache = False
        self.current_model = model_path.name
        self.models[self.current_model] = {"pth": str(model_path), "index": index_path}
        declared_note = (
            f" declared={declared}"
            if declared and declared != self.version
            else ""
        )
        print(
            "XB: 官方 RVC 推理栈已加载模型 "
            f"{model_path.name} version={self.version}{declared_note} f0={self.if_f0} "
            f"sr={self.tgt_sr}",
            flush=True,
        )

    def set_params(self, **kwargs: Any) -> None:
        valid = {
            "index_rate",
            "filter_radius",
            "resample_sr",
            "rms_mix_rate",
            "protect",
            "f0up_key",
            "f0method",
        }
        for key, value in kwargs.items():
            if key in valid:
                setattr(self, key, value)
            else:
                print(f"Warning: parameter {key} not recognized and will be ignored.")

    def set_device(self, device: str | torch.device) -> None:
        self.device = device
        self.config.device = device

    # ---- inference ----------------------------------------------------
    def infer(
        self,
        *,
        sid: int,
        input_audio_path: str,
        f0_up_key: int,
        f0_method: str,
        file_index: str,
        index_rate: float,
        filter_radius: int,
        resample_sr: int,
        rms_mix_rate: float,
        protect: float,
        f0_file: str = "",
        file_index2: str = "",
    ) -> np.ndarray:
        if self.net_g is None or self.pipeline is None:
            raise ValueError("Please load a model first.")
        if not input_audio_path:
            raise ValueError("input_audio_path is required")
        if self.hubert_model is None:
            self.hubert_model = self._load_hubert()

        audio = load_audio(input_audio_path, 16000)
        audio_max = float(np.abs(audio).max()) / 0.95
        if audio_max > 1:
            audio = audio / audio_max
        times = [0.0, 0.0, 0.0]

        index = str(file_index or "")
        if index:
            index = (
                index.strip(" ")
                .strip('"')
                .strip("\n")
                .strip('"')
                .strip(" ")
                .replace("trained", "added")
            )
        else:
            index = str(file_index2 or "")
        audio_opt = self.pipeline.pipeline(
            self.hubert_model,
            self.net_g,
            int(sid),
            audio,
            input_audio_path,
            times,
            int(f0_up_key),
            str(f0_method),
            index,
            float(index_rate),
            int(self.if_f0 or 1),
            int(filter_radius),
            int(self.tgt_sr or 0),
            int(resample_sr),
            float(rms_mix_rate),
            self.version,
            float(protect),
            f0_file,
        )
        self.last_times = [float(t) for t in times]
        return audio_opt


def engine_version() -> str:
    """Short provenance string printed in worker logs."""
    return "RVC-Project/Retrieval-based-Voice-Conversion-WebUI@2.2.231006"
