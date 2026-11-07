"""歌声增强（修音 / 音色美化）的领域规则。

包含增强等级、默认强度、强度归一化，以及从作品记录解析增强设置的规则。
这些规则与具体处理进程无关，因此属于领域层；基础设施层的
``VocalEnhancementProcessor`` 只负责执行。
"""

from __future__ import annotations

from typing import Any, TypedDict

LEVEL_BASIC = "basic"
LEVEL_ADVANCED = "advanced"
LEVELS = frozenset({LEVEL_BASIC, LEVEL_ADVANCED})

# 各维度默认强度（关闭手动调参或字段缺失时使用）。
DEFAULT_CONTROLS: dict[str, float] = {
    "pitch_correction": 0.45,
    "timing_alignment": 0.45,
    "timbre_focus": 0.60,
    "ai_eq": 0.55,
    "ai_compressor": 0.45,
    "ai_exciter": 0.25,
    "stereo_width": 0.30,
    "loudness_envelope": 0.58,
}


class VocalEnhancementControls(TypedDict):
    """歌声增强各维度的强度（0.0 ~ 1.0）。"""

    pitch_correction: float
    timing_alignment: float
    timbre_focus: float
    ai_eq: float
    ai_compressor: float
    ai_exciter: float
    stereo_width: float
    loudness_envelope: float


def normalize_level(value: Any) -> str:
    """把外部传入的增强等级归一化为受支持的等级。"""
    level = str(value or LEVEL_BASIC).strip().lower()
    return level if level in LEVELS else LEVEL_BASIC


def normalize_strength(value: Any, fallback: float) -> float:
    """把强度归一化到 0.0 ~ 1.0；非法值（含 NaN）回落为默认值。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = fallback
    if numeric != numeric:  # NaN
        numeric = fallback
    return max(0.0, min(1.0, numeric))


def controls_from_mapping(raw: dict[str, Any]) -> VocalEnhancementControls:
    """按默认值兜底构造 8 个维度的强度。"""
    return {
        key: normalize_strength(raw.get(key, default), default)  # type: ignore[typeddict-item]
        for key, default in DEFAULT_CONTROLS.items()
    }  # type: ignore[return-value]


def enhancement_settings(
    work: dict[str, Any],
) -> tuple[bool, str, VocalEnhancementControls]:
    """从作品记录解析 (是否启用, 等级, 各维度强度)。"""
    raw = work.get("vocal_enhancement") or {}
    if not isinstance(raw, dict):
        return False, LEVEL_BASIC, controls_from_mapping({})

    level = normalize_level(raw.get("level"))
    controls = controls_from_mapping(raw)
    if work.get("high_pitch_guard_applied"):
        # 防护装置已恢复高谐波。音色塑造控制部分被有意调至更轻，以保持受保护的辅音自然清晰。
        controls["timbre_focus"] *= 0.68
        controls["ai_eq"] *= 0.78
        controls["ai_compressor"] *= 0.82
        controls["ai_exciter"] *= 0.45
    return bool(raw.get("enabled")), level, controls
