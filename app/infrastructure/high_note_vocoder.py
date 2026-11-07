"""高音声码器补偿适配器。

实现在隔离的美声环境里运行（``VOCAL_ENHANCEMENT_PYTHON`` + 磁盘上的 worker
脚本），主程序只负责调度、解析报告并决定是否采纳结果。这样 Torch / librosa /
声码器权重都不会进入主进程，符合其它 worker 的一致约定。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import config


_WORKER_TIMEOUT_SECONDS = 1800


class HighNoteVocoderProcessor:
    """F0 条件化声码器的超高频带补偿（Snake-HiFiGAN 优先，NSF-HiFiGAN 兜底）。"""

    @property
    def available(self) -> bool:
        return bool(
            config.VOCAL_ENHANCEMENT_PYTHON
            and Path(config.VOCAL_ENHANCEMENT_PYTHON).is_file()
            and Path(config.HIGH_NOTE_VOCODER_WORKER).is_file()
            and config.high_note_vocoder_weight_dir() is not None
        )

    def version(self) -> str | None:
        weights = config.high_note_vocoder_weight_dir()
        return weights.name if weights is not None else None

    def status(self) -> dict[str, Any]:
        weights = config.high_note_vocoder_weight_dir()
        return {
            "available": self.available,
            "python": str(config.VOCAL_ENHANCEMENT_PYTHON or ""),
            "worker": str(config.HIGH_NOTE_VOCODER_WORKER),
            "weights": str(weights or ""),
            "band_hz": config.HIGH_NOTE_VOCODER_BAND_HZ,
            "wet": config.HIGH_NOTE_VOCODER_WET,
        }

    def refine(
        self,
        *,
        rendered: Path,
        dry: Path | None,
        regions: list[tuple[float, float]],
        destination: Path,
        threshold: float = 0.0,
    ) -> dict[str, Any]:
        """只重建 ``regions`` 内的超高频带；未采纳时不写输出文件。"""
        result: dict[str, Any] = {
            "applied": False,
            "output": None,
            "regions": [],
            "architecture": "",
            "reason": "",
            "weights": "",
        }
        if not regions:
            result["reason"] = "没有需要补偿的高音区"
            return result
        if not self.available:
            result["reason"] = "高音声码器不可用（缺少权重或运行环境）"
            return result

        python = Path(str(config.VOCAL_ENHANCEMENT_PYTHON))
        worker = Path(str(config.HIGH_NOTE_VOCODER_WORKER))
        weights = config.high_note_vocoder_weight_dir()
        scope_path = destination.with_suffix(".scope.json")
        report_path = destination.with_suffix(".vocoder.json")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            scope_path.write_text(
                json.dumps(
                    [
                        {"start": float(start), "end": float(end)}
                        for start, end in regions
                        if float(end) > float(start)
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            result["reason"] = f"高音区描述写入失败：{exc}"
            return result

        boundary = max(300.0, float(threshold or 0.0))
        command = [
            str(python),
            str(worker),
            "--input",
            str(rendered),
            "--output",
            str(destination),
            "--regions-json",
            str(scope_path),
            "--report-json",
            str(report_path),
            "--weights-dir",
            str(weights),
            "--band-hz",
            f"{float(config.HIGH_NOTE_VOCODER_BAND_HZ):.1f}",
            "--wet",
            f"{float(config.HIGH_NOTE_VOCODER_WET):.3f}",
            "--min-f0",
            f"{boundary * 0.85:.1f}",
            "--max-f0",
            f"{min(3000.0, boundary * 3.0):.1f}",
            "--device",
            "cpu",
        ]
        if dry is not None and Path(dry).is_file():
            command.extend(["--dry-source", str(dry)])
        for repo in config.high_note_vocoder_repos():
            command.extend(["--repo", str(repo)])

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_WORKER_TIMEOUT_SECONDS,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            result["reason"] = f"高音声码器启动失败：{exc}"
            return result

        report: dict[str, Any] | None = None
        try:
            raw = report_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                report = parsed
        except (OSError, ValueError, json.JSONDecodeError):
            report = None

        if not isinstance(report, dict):
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            result["reason"] = (
                f"高音声码器未返回报告（退出码 {completed.returncode}）"
                + (f"：{detail[-1]}" if detail else "")
            )
            return result

        result["regions"] = report.get("regions") or []
        result["architecture"] = str(report.get("architecture") or "")
        result["weights"] = str(report.get("weights") or "")
        result["reason"] = str(report.get("reason") or "")
        result["applied_seconds"] = float(report.get("applied_seconds") or 0.0)
        if report.get("applied") and destination.is_file():
            result["applied"] = True
            result["output"] = destination
        elif completed.returncode != 0 and not result["reason"]:
            result["reason"] = f"高音声码器退出码 {completed.returncode}"
        return result
