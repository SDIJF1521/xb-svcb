"""音频编辑器工程的领域规则（归一化 / 度量 / 查找）。

这些规则原先写在 ``AudioEditorService`` 的私有方法里（``_clean_*``、``_project_duration``
等），属于领域知识而非用例编排：它们只依赖工程结构本身，不读写文件、不认识 ffmpeg。
用例层保留同名薄封装以兼容既有调用点。
"""

from __future__ import annotations

import copy
from typing import Any

from .identity import new_id

# 可用的输出格式与声道标记。
RENDER_FORMATS = ("wav", "mp3", "flac")
CHANNELS = ("stereo", "left", "right")
# 音量包络允许的取值上限（与编辑器 UI 一致的 250%）。
MAX_ENVELOPE_VOLUME = 2.5
# 插件类效果的 type 别名；这些效果来自外部 VST3，不能被当作内置效果处理。
PLUGIN_EFFECT_TYPES = frozenset(
    {"plugin", "vst", "vst3", "external", "external_plugin", "juce", "juce_vst3"}
)
MIN_DURATION = 0.05


def normalize_effect_type(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def clean_effects(raw: Any) -> list[dict[str, Any]]:
    """归一化效果链：类型必需、参数为字典、未知字段原样保留。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        effect_type = normalize_effect_type(item.get("type"))
        if not effect_type:
            continue
        params = item.get("params")
        effect = {
            "id": str(item.get("id") or new_id("fx_")),
            "type": effect_type,
            "name": str(item.get("name") or effect_type),
            "enabled": item.get("enabled", True) is not False,
            "params": dict(params) if isinstance(params, dict) else {},
        }
        for key, value in item.items():
            if key not in effect and key not in {"params"}:
                effect[key] = value
        cleaned.append(effect)
    return cleaned


def is_plugin_effect(effect: dict[str, Any]) -> bool:
    """判断效果是否来自外部插件（VST3）。"""
    return normalize_effect_type(effect.get("type")) in PLUGIN_EFFECT_TYPES


def clean_volume_envelope(raw: Any, duration: float) -> list[dict[str, float]]:
    """归一化音量包络：时间裁剪到片段内、音量裁剪到 0~2.5，按时间去重排序。"""
    if not isinstance(raw, list):
        return []
    points: list[tuple[float, float]] = []
    dur = max(0.01, float(duration or 0.01))
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            time_value = float(item.get("time", item.get("t", 0.0)) or 0.0)
            volume = float(item.get("volume", item.get("value", 1.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        points.append((max(0.0, min(dur, time_value)), max(0.0, min(MAX_ENVELOPE_VOLUME, volume))))
    by_time: dict[float, float] = {}
    for time_value, volume in sorted(points, key=lambda point: point[0]):
        by_time[round(time_value, 3)] = round(volume, 4)
    return [
        {"time": time_value, "volume": by_time[time_value]} for time_value in sorted(by_time)
    ]


def clip_duration(clip: dict[str, Any]) -> float:
    """片段自身时长（不含拉伸），最小 0.01 秒。"""
    try:
        return max(
            0.01,
            float(clip.get("end") or 0.0) - float(clip.get("start") or 0.0),
        )
    except (TypeError, ValueError):
        return 0.01


def clip_stretch(clip: dict[str, Any]) -> float:
    """时间拉伸倍率，限制在 0.25~4.0。"""
    try:
        return max(0.25, min(4.0, float(clip.get("time_stretch", 1.0) or 1.0)))
    except (TypeError, ValueError):
        return 1.0


def normalize_channel(value: Any) -> str:
    channel = str(value or "stereo").strip().lower()
    return channel if channel in CHANNELS else "stereo"


def project_duration(project: dict[str, Any]) -> float:
    """工程总时长 = 所有片段结束时间的最大值，最小 0.05 秒。"""
    duration = 0.0
    for track in project.get("tracks", []) or []:
        for clip in track.get("clips", []) or []:
            try:
                duration = max(duration, float(clip.get("end") or 0.0))
            except (TypeError, ValueError):
                pass
    return max(duration, MIN_DURATION)


def normalize_format(fmt: str | None) -> str:
    """输出格式归一化；不支持时回退 wav。"""
    value = (fmt or "wav").strip().lower().lstrip(".")
    return value if value in RENDER_FORMATS else "wav"


def clean_project(project: dict[str, Any]) -> dict[str, Any]:
    """归一化整个工程：角色 / 轨道 / 片段 / 效果 / 音量包络 / 拉伸 / 声道。

    撤销历史（history / future）在持久化时剔除。
    """
    cleaned = copy.deepcopy(project)
    cleaned.pop("history", None)
    cleaned.pop("future", None)
    cleaned.setdefault("waveform_cache", {})
    cleaned.setdefault("metadata", {})
    roles = cleaned.get("roles")
    if not isinstance(roles, list):
        roles = []
        cleaned["roles"] = roles
    for role in roles:
        if isinstance(role, dict):
            role["effects"] = clean_effects(role.get("effects"))
    for track in cleaned.get("tracks", []) or []:
        track.setdefault("metadata", {})
        track["effects"] = clean_effects(track.get("effects"))
        for clip in track.get("clips", []) or []:
            clip["channel"] = normalize_channel(clip.get("channel"))
            clip["time_stretch"] = clip_stretch(clip)
            clip["effects"] = clean_effects(clip.get("effects"))
            clip["volume_envelope"] = clean_volume_envelope(
                clip.get("volume_envelope"), clip_duration(clip)
            )
    return cleaned


def find_clip(project: dict[str, Any] | None, clip_id: str) -> dict[str, Any] | None:
    """按片段 ID 在工程中查找片段。"""
    if not project:
        return None
    for track in project.get("tracks", []) or []:
        for clip in track.get("clips", []) or []:
            if clip.get("id") == clip_id:
                return clip
    return None


def find_clip_ref(
    project: dict[str, Any], track_id: str, clip_id: str
) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
    """定位片段及其所属轨道与索引，便于原地替换。"""
    for track in project.get("tracks", []) or []:
        if track.get("id") != track_id:
            continue
        for idx, clip in enumerate(track.get("clips", []) or []):
            if clip.get("id") == clip_id:
                return track, idx, clip
    return None, -1, None


def find_track(project: dict[str, Any] | None, track_id: str) -> dict[str, Any] | None:
    """按轨道 ID 查找轨道。"""
    if not project:
        return None
    for track in project.get("tracks", []) or []:
        if track.get("id") == track_id:
            return track
    return None


def find_effect(clip: dict[str, Any], effect_id: str) -> dict[str, Any] | None:
    """在片段的效果链中查找效果。"""
    for effect in clip.get("effects", []) or []:
        if isinstance(effect, dict) and str(effect.get("id") or "") == effect_id:
            return effect
    return None


def should_render_waveform(clip: dict[str, Any]) -> bool:
    """片段是否带有需要重新渲染波形的处理（拉伸/音量/淡化/声道/效果/包络）。"""
    try:
        if abs(clip_stretch(clip) - 1.0) > 0.0001:
            return True
        if float(clip.get("volume", 1.0) or 1.0) != 1.0:
            return True
        if float(clip.get("fade_in", 0.0) or 0.0) > 0.0:
            return True
        if float(clip.get("fade_out", 0.0) or 0.0) > 0.0:
            return True
    except (TypeError, ValueError):
        return True
    if normalize_channel(clip.get("channel")) != "stereo":
        return True
    if clip.get("effects"):
        return True
    if clip.get("volume_envelope"):
        return True
    return False
