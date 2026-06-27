"""轻量音频编辑器领域实体。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EditorClip:
    """时间轴中的一个音频片段。"""

    id: str
    start: float
    end: float
    offset: float
    volume: float
    mute: bool
    file: str
    effects: list[dict[str, Any]] = field(default_factory=list)
    name: str = ""
    locked: bool = False
    fade_in: float = 0.0
    fade_out: float = 0.0
    channel: str = "stereo"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EditorTrack:
    """音频编辑器轨道。"""

    id: str
    name: str
    type: str
    clips: list[dict[str, Any]] = field(default_factory=list)
    locked: bool = False
    mute: bool = False
    volume: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EditorProject:
    """可序列化的轻量时间轴工程。"""

    id: str
    title: str
    tracks: list[dict[str, Any]]
    duration: float
    sample_rate: int = 44100
    waveform_cache: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
