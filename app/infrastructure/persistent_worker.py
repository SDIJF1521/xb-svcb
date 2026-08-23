"""Line-oriented persistent inference worker client."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

import config


class PersistentInferenceSession:
    """Keep a model worker alive and exchange one JSON request per audio block."""

    def __init__(
        self,
        command: list[str],
        *,
        ready_marker: str,
        result_marker: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        log_file: Path | None = None,
        startup_timeout: float = 900.0,
    ) -> None:
        self._result_marker = result_marker
        self._log_file = log_file
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._recent_output: deque[str] = deque(maxlen=24)
        self._process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env or os.environ.copy(),
            **config.subprocess_no_window(),
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()
        self._wait_for(ready_marker, timeout=startup_timeout)

    def infer(
        self,
        input_path: Path,
        output_path: Path,
        timeout: float = 3600.0,
        **extra: Any,
    ) -> Path:
        if self._process.poll() is not None or self._process.stdin is None:
            raise RuntimeError("实时推理 worker 已退出")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        payload = {"input": str(input_path), "output": str(output_path), **extra}
        request = json.dumps(payload, ensure_ascii=False)
        try:
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError("无法向实时推理 worker 发送音频块") from exc
        raw = self._wait_for(self._result_marker, timeout=timeout)
        try:
            result = json.loads(raw.split("\t", 1)[1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"实时推理 worker 返回无效结果: {raw}") from exc
        if not result.get("ok") or not output_path.is_file():
            raise RuntimeError(str(result.get("error") or "实时音频块推理失败"))
        return output_path

    def close(self) -> None:
        process = self._process
        if process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.write('{"command":"close"}\n')
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=5)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    def _read_output(self) -> None:
        stdout = self._process.stdout
        if stdout is None:
            self._lines.put(None)
            return
        try:
            for raw in stdout:
                line = raw.rstrip("\r\n")
                self._append_log(line)
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def _wait_for(self, marker: str, timeout: float) -> str:
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty as exc:
                self.close()
                raise RuntimeError(f"实时推理 worker 等待超时: {marker}") from exc
            if line is None:
                code = self._process.poll()
                details = "；".join(item for item in self._recent_output if item)
                suffix = f"；输出：{details[-1200:]}" if details else ""
                raise RuntimeError(f"实时推理 worker 提前退出（{code}）{suffix}")
            if line.startswith(marker):
                return line

    def _append_log(self, line: str) -> None:
        self._recent_output.append(line)
        if not self._log_file:
            return
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with self._log_file.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            pass

    def __enter__(self) -> "PersistentInferenceSession":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
