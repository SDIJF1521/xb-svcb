"""领域枚举。"""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """翻唱任务状态。"""

    QUEUE = "queue"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class StepStatus(str, Enum):
    """流水线单步状态。"""

    WAIT = "wait"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


class ModelType(str, Enum):
    """SVC 模型类型。"""

    SVC = "SVC"
    SOVITS = "So-VITS"
    RVC = "RVC"
    UNKNOWN = "Unknown"

    @classmethod
    def guess(cls, filename: str) -> "ModelType":
        """根据文件名粗略推断模型类型。"""
        name = filename.lower()
        if "rvc" in name or name.endswith(".onnx"):
            return cls.RVC
        if "sovits" in name or "so-vits" in name or "so_vits" in name:
            return cls.SOVITS
        if name.endswith((".pth", ".pt", ".ckpt")):
            return cls.SVC
        return cls.UNKNOWN
