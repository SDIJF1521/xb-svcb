"""领域实体。

实体均提供 to_dict / from_dict，便于持久化与跨 pywebview 桥传输（JSON 序列化）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class ModelFile:
    """一个已导入的模型文件（权重或配置）。"""

    name: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ModelFile | None":
        if not data:
            return None
        return cls(name=data.get("name", ""), path=data.get("path", ""))


@dataclass
class ModelInfo:
    """一个已导入的 SVC 模型组：主模型 + 扩散模型，各自含配置文件。

    推理时主模型与扩散模型共同作用，由 ``InferenceParams.diffusion_ratio`` 控制比例。
    """

    id: str
    name: str
    type: str
    sample_rate: str
    size: str
    imported_at: str
    main_model: ModelFile
    main_config: ModelFile
    diffusion_model: Optional[ModelFile] = None
    diffusion_config: Optional[ModelFile] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelInfo":
        return cls(
            id=data["id"],
            name=data["name"],
            type=data.get("type", "SVC"),
            sample_rate=data.get("sample_rate", "44.1kHz"),
            size=data.get("size", "—"),
            imported_at=data.get("imported_at", ""),
            main_model=ModelFile.from_dict(data.get("main_model")) or ModelFile("", ""),
            main_config=ModelFile.from_dict(data.get("main_config")) or ModelFile("", ""),
            diffusion_model=ModelFile.from_dict(data.get("diffusion_model")),
            diffusion_config=ModelFile.from_dict(data.get("diffusion_config")),
        )


@dataclass
class PipelineStep:
    """翻唱流水线中的一个步骤。"""

    key: str
    label: str
    status: str = "wait"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InferenceParams:
    """SVC 推理参数。

    ``diffusion_ratio``: 扩散模型占比 (0~1)，主模型占比为 ``1 - diffusion_ratio``。
    """

    pitch: int = 0
    f0_method: str = "rmvpe"
    index_rate: float = 0.75
    rms_mix: float = 0.25
    uvr_model: str = "MDX-Net"
    diffusion_ratio: float = 0.5
    speaker: str = ""  # 目标说话人，留空则用模型配置中的第一个
    device: str = "auto"  # 推理设备：auto / cuda / cpu

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InferenceParams":
        data = data or {}
        return cls(
            pitch=int(data.get("pitch", 0)),
            f0_method=str(data.get("f0_method", data.get("f0Method", "rmvpe"))),
            index_rate=float(data.get("index_rate", data.get("indexRate", 0.75))),
            rms_mix=float(data.get("rms_mix", data.get("rmsMix", 0.25))),
            uvr_model=str(data.get("uvr_model", data.get("uvrModel", "MDX-Net"))),
            diffusion_ratio=float(data.get("diffusion_ratio", data.get("diffusionRatio", 0.5))),
            speaker=str(data.get("speaker", data.get("spk", ""))),
            device=str(data.get("device", "auto")),
        )


@dataclass
class Work:
    """一次翻唱任务及其产物。"""

    id: str
    title: str
    model: str
    model_id: str
    status: str
    progress: int
    duration: str
    format: str
    size: str
    created_at: str
    source_path: Optional[str] = None
    output_path: Optional[str] = None
    error: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Work":
        return cls(
            id=data["id"],
            title=data["title"],
            model=data.get("model", ""),
            model_id=data.get("model_id", ""),
            status=data.get("status", "queue"),
            progress=int(data.get("progress", 0)),
            duration=data.get("duration", "—"),
            format=data.get("format", "—"),
            size=data.get("size", "—"),
            created_at=data.get("created_at", ""),
            source_path=data.get("source_path"),
            output_path=data.get("output_path"),
            error=data.get("error"),
            params=data.get("params", {}) or {},
            steps=data.get("steps", []) or [],
        )
