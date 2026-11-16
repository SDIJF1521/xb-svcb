"""MIDI 音高重绘适配器：把编辑器里的 MIDI 音符落到音频上。

重绘本身在隔离的美声环境（Praat/Parselmouth）里以 worker 进程执行，主程序只
负责准备输入、解析报告并决定是否采纳；任何失败都回退到原音频。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import config

_WORKER_TIMEOUT_SECONDS = 900


class MidiPitchProcessor:
    """逐音符移调（保共振峰 PSOLA）。"""

    @property
    def available(self) -> bool:
        return bool(
            config.VOCAL_ENHANCEMENT_PYTHON
            and Path(config.VOCAL_ENHANCEMENT_PYTHON).is_file()
            and Path(config.MIDI_PITCH_WORKER).is_file()
        )

    def version(self) -> str | None:
        return "praat-psola" if self.available else None

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "python": str(config.VOCAL_ENHANCEMENT_PYTHON or ""),
            "worker": str(config.MIDI_PITCH_WORKER),
        }

    def apply(
        self,
        *,
        source: Path,
        notes: list[dict[str, Any]],
        destination: Path,
        f0_curve: Path | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "applied": False,
            "output": None,
            "reason": "",
            "notes": [],
            "skipped": [],
            "applied_notes": 0,
            "applied_seconds": 0.0,
        }
        if not self.available:
            result["reason"] = "MIDI 重绘环境未就绪（缺少 vocal 运行时或 worker）"
            return result
        if not notes:
            result["reason"] = "没有 MIDI 音符"
            return result
        if not Path(source).is_file():
            result["reason"] = "源音频不存在"
            return result

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        notes_path = destination.with_suffix(".notes.json")
        report_path = destination.with_suffix(".report.json")
        try:
            notes_path.write_text(
                json.dumps(
                    [note for note in notes if isinstance(note, dict)],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            result["reason"] = f"MIDI 音符写入失败：{exc}"
            return result

        command = [
            str(config.VOCAL_ENHANCEMENT_PYTHON),
            str(config.MIDI_PITCH_WORKER),
            "--input",
            str(source),
            "--output",
            str(destination),
            "--notes-json",
            str(notes_path),
            "--report-json",
            str(report_path),
        ]
        if f0_curve is not None and Path(f0_curve).is_file():
            command.extend(["--f0-npy", str(f0_curve)])
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
            result["reason"] = f"MIDI 重绘启动失败：{exc}"
            return result

        report: dict[str, Any] | None = None
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                report = parsed
        except (OSError, ValueError, json.JSONDecodeError):
            report = None
        if report is None:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            result["reason"] = (
                f"MIDI 重绘没有返回报告（退出码 {completed.returncode}）"
                + (f"：{detail[-1]}" if detail else "")
            )
            return result

        result.update(
            {
                "reason": str(report.get("reason") or ""),
                "notes": report.get("notes") or [],
                "skipped": report.get("skipped") or [],
                "applied_notes": int(report.get("applied_notes") or 0),
                "applied_seconds": float(report.get("applied_seconds") or 0.0),
            }
        )
        if report.get("applied") and destination.is_file():
            result["applied"] = True
            result["output"] = destination
        elif completed.returncode != 0 and not result["reason"]:
            result["reason"] = f"MIDI 重绘退出码 {completed.returncode}"
        return result
