"""高音声码器补偿的用例编排（转换流水线与编辑器局部重推理共用）。

高音保护的「降调 → 模型推理 → 升回原调」只解决唱得出来，升回原调后的高音仍然
会因为 PSOLA 和气声失去超高频谐波。这里把「在哪些区间补偿、什么情况下回退」的
策略收敛到一处，具体重建由 :class:`application.ports.HighNoteVocoderPort` 的
适配器完成（隔离环境 + 声码器）。

原则：

* 只处理高音保护报告里记录过的区间，并可按检测器确认的失配核心再收窄；
* 端口不可用、抛异常、或 worker 全部区段都未通过验收时，原样返回升调结果；
* 采纳与否则完全由 worker 的逐区验收决定，用例层不再二次放宽。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .ports import HighNoteVocoderPort

_TimeRegion = tuple[float, float]


def read_guard_regions(report_path: Path | None) -> list[_TimeRegion] | None:
    """读取高音保护报告里实际处理过的区间。"""
    if report_path is None:
        return None
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    regions = report.get("regions") if isinstance(report, dict) else None
    parsed: list[_TimeRegion] = []
    for item in regions if isinstance(regions, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            continue
        if end > start:
            parsed.append((start, end))
    return parsed or None


def refine_high_note_band(
    vocoder: HighNoteVocoderPort | None,
    *,
    restored: Path,
    dry: Path | None,
    report_path: Path | None,
    only_regions: list[_TimeRegion] | None,
    threshold: float,
    log: Callable[[str], None] | None = None,
) -> Path:
    """在已确认的高音区重建超高频带；任何异常都回退到升调结果。"""

    def emit(message: str) -> None:
        if log is not None:
            log(message)

    if vocoder is None or not getattr(vocoder, "available", False):
        return restored
    regions = read_guard_regions(report_path)
    if not regions:
        return restored
    if only_regions:
        regions = [
            region
            for region in regions
            if any(region[1] > start and region[0] < end for start, end in only_regions)
        ]
    if not regions:
        return restored
    destination = restored.with_name(f"{restored.stem}_vocoded.wav")
    try:
        result = vocoder.refine(
            rendered=restored,
            dry=dry,
            regions=regions,
            destination=destination,
            threshold=threshold,
        )
    except Exception as exc:  # noqa: BLE001 - 补偿失败绝不能影响保护结果
        emit(f"  高音声码器补偿异常，保留升调结果：{exc}")
        return restored
    if not isinstance(result, dict):
        return restored
    output = result.get("output")
    if result.get("applied") and output is not None and Path(output).is_file():
        accepted = sum(
            1
            for item in result.get("regions") or []
            if isinstance(item, dict) and item.get("status") == "applied"
        )
        architecture = str(result.get("architecture") or "声码器")
        emit(
            f"  高音声码器补偿完成（{architecture}）：重建 {accepted} 个高音区的超高频带，"
            f"共 {float(result.get('applied_seconds') or 0.0):.2f}s"
        )
        return Path(output)
    emit(
        f"  高音声码器补偿未采纳：{result.get('reason') or '未通过验收'}（保留升调结果）"
    )
    return restored
