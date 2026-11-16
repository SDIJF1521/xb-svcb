"""翻唱任务的请求规则（领域层）。

任务创建有两类入口：桌面桥（前端 JSON）与 FastAPI（Pydantic 请求）。两者都必须遵守
同一套业务规则，因此规则集中在这里，由 ``WorkService.validate_request`` 编排后
供两个入口复用。这里只有纯判断，不读写文件、不认识 HTTP 状态码。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

# 只有多模型模式支持的人声合并工作流。
MULTI_ONLY_WORKFLOWS = frozenset({"auto_vocal_merge", "manual_vocal_merge"})


class WorkRequestError(ValueError):
    """任务创建请求不满足业务规则。

    ``not_found`` 表示请求引用的资源（通常是模型）不存在，调用方通常会把它映射成
    404；其余情况属于参数非法（422）。
    """

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.not_found = not_found


def default_title(raw_title: Any, source_path: Any) -> str:
    """任务标题：优选用户输入，其次源文件名，最后是占位标题。"""
    title = str(raw_title or "").strip()
    if title:
        return title
    path = str(source_path or "").strip()
    if path:
        return Path(path).stem
    return "未命名翻唱"


def check_workflow_mode(workflow: str, mode: str) -> None:
    """人声合并工作流只能在多模型模式下使用。"""
    if str(workflow or "") in MULTI_ONLY_WORKFLOWS and str(mode or "single") != "multi":
        raise WorkRequestError("人声合并工作流只支持 multi 模式")


def require_multi_selection(models: Iterable[Any], segments: Iterable[Any]) -> None:
    """多模型模式必须同时提供模型列表与演唱分句。"""
    if not list(models or []) or not list(segments or []):
        raise WorkRequestError("multi 模式需要 models 和 segments")


def check_duplicate_model_ids(model_ids: Iterable[str]) -> None:
    """同一请求里不能重复选择模型。"""
    seen: set[str] = set()
    for model_id in model_ids:
        key = str(model_id or "")
        if key in seen:
            raise WorkRequestError(f"models 中模型重复：{key}")
        seen.add(key)


def normalize_segments(
    segments: Iterable[dict[str, Any]],
    allowed_model_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """校验并归一化演唱分句：时间有效、模型来自本次选择、保留指派顺序。"""
    allowed = {str(model_id) for model_id in allowed_model_ids}
    normalized: list[dict[str, Any]] = []
    for segment in segments or []:
        try:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
        except (TypeError, ValueError) as exc:
            raise WorkRequestError("segments.start 与 end 必须是数字") from exc
        if end <= start:
            raise WorkRequestError("segments.end 必须大于 start")
        raw_ids = segment.get("model_ids")
        if not raw_ids:
            single = segment.get("model_id")
            raw_ids = [single] if single else []
        model_ids = list(dict.fromkeys(str(model_id) for model_id in raw_ids if model_id))
        if not model_ids or any(model_id not in allowed for model_id in model_ids):
            raise WorkRequestError("segments 中的 model_ids 必须来自 models 且不能为空")
        normalized.append(
            {
                "start": start,
                "end": end,
                "model_id": model_ids[0],
                "model_ids": model_ids,
            }
        )
    return normalized


def require_seedvc_reference(
    model: dict[str, Any] | None,
    params: dict[str, Any] | None,
    message: str,
) -> None:
    """SeedVC 模型必须提供目标音色参考音频。"""
    if str((model or {}).get("framework") or "") != "seed-vc":
        return
    if str((params or {}).get("reference_audio") or "").strip():
        return
    raise WorkRequestError(message)
