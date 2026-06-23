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


def _guess_framework(model_type: str | None) -> str:
    """据本地模型 type 推断框架 id（领域层自带，避免依赖 config）。"""
    t = (model_type or "").strip().lower()
    if "rvc" in t:
        return "rvc"
    if "ddsp" in t:
        return "ddsp-svc"
    return "so-vits-svc"


@dataclass
class ModelInfo:
    """一个已导入的声音模型组。

    - so-vits-svc：主模型(``G_*.pth``) + 主配置(``config.json``)，可选浅扩散模型 + 配置。
    - RVC：主模型(``.pth``) + 可选检索 ``index_file``（``.index``），无需主配置。

    ``framework`` 决定推理时使用哪个引擎（so-vits-svc / rvc / …），为后续多框架预留。
    推理时 so-vits 主模型与扩散模型共同作用，由 ``InferenceParams.diffusion_ratio`` 控制比例。
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
    # 模型框架：so-vits-svc / rvc / …（缺省按 type 推断）
    framework: str = "so-vits-svc"
    # RVC 检索特征文件（.index），可选
    index_file: Optional[ModelFile] = None

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
            framework=str(data.get("framework") or _guess_framework(data.get("type"))),
            index_file=ModelFile.from_dict(data.get("index_file")),
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
    """推理参数（so-vits-svc 与 RVC 的超集，各引擎只取自己需要的子集）。

    通用：``pitch``（变调，半音）、``f0_method``（F0 算法）、``device``。
    so-vits-svc：``diffusion_ratio``（扩散占比 0~1）、``speaker``（目标说话人）。
    RVC：``index_rate``（检索特征占比）、``rms_mix``（音量包络混合）、
    ``protect``（清辅音保护）、``filter_radius``（中值滤波半径）、``rvc_version``（v1/v2）。
    """

    pitch: int = 0
    f0_method: str = "rmvpe"
    index_rate: float = 0.75
    rms_mix: float = 0.25
    uvr_model: str = "MDX-Net"
    diffusion_ratio: float = 0.5
    speaker: str = ""  # 目标说话人，留空则用模型配置中的第一个
    device: str = "auto"  # 推理设备：auto / cuda / cpu
    # RVC 专属参数
    protect: float = 0.33  # 清辅音/呼吸保护 (0~0.5)
    filter_radius: int = 3  # F0 中值滤波半径 (0~7)
    rvc_version: str = "v2"  # RVC 模型版本 v1 / v2

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
            protect=float(data.get("protect", 0.33)),
            filter_radius=int(data.get("filter_radius", data.get("filterRadius", 3))),
            rvc_version=str(data.get("rvc_version", data.get("rvcVersion", "v2"))),
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
    # 翻唱模式：single=单模型；multi=多模型混合（按歌词分句指派模型）
    mode: str = "single"
    # 多模型模式下，每个已指派模型的演唱片段：{start, end, model_id}
    segments: list[dict[str, Any]] = field(default_factory=list)

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
            mode=data.get("mode", "single"),
            segments=data.get("segments", []) or [],
        )
