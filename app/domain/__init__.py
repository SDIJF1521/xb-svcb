"""领域层：业务实体与枚举，独立于具体实现与框架。"""

from .enums import JobStatus, ModelType, StepStatus
from .entities import (
    FRAMEWORK_DEFAULT,
    FRAMEWORKS,
    InferenceParams,
    ModelFile,
    ModelInfo,
    PipelineStep,
    Work,
    apply_step_status,
    guess_framework,
    normalize_framework,
)
from .audio_editor import EditorClip, EditorProject, EditorTrack

__all__ = [
    "JobStatus",
    "ModelType",
    "StepStatus",
    "ModelInfo",
    "ModelFile",
    "Work",
    "PipelineStep",
    "InferenceParams",
    "EditorClip",
    "EditorProject",
    "EditorTrack",
    "FRAMEWORK_DEFAULT",
    "FRAMEWORKS",
    "apply_step_status",
    "guess_framework",
    "normalize_framework",
]
