"""领域层：业务实体与枚举，独立于具体实现与框架。"""

from .enums import JobStatus, ModelType, StepStatus
from .entities import ModelInfo, ModelFile, Work, PipelineStep, InferenceParams

__all__ = [
    "JobStatus",
    "ModelType",
    "StepStatus",
    "ModelInfo",
    "ModelFile",
    "Work",
    "PipelineStep",
    "InferenceParams",
]
