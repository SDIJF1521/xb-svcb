"""PyMSS 模型下载进度：子进程输出解析与后台任务进度。"""

from __future__ import annotations

import subprocess
import sys
import time

from unittest.mock import patch

from infrastructure.pymss_tool import PymssTool
from infrastructure.pymss_worker import _download_progress_emitter


def test_worker_progress_emitter_accumulates_overall_bytes() -> None:
    lines: list[str] = []
    callback = _download_progress_emitter(1000, sink=lines.append)

    callback(400, 500, "Downloading model.ckpt")
    callback(500, 500, "Downloading model.ckpt")
    callback(100, 300, "Downloading model.yaml")
    callback(300, 300, "Downloading model.yaml")

    percent = [int(line.split("\t")[1]) for line in lines]
    assert percent == sorted(percent)
    assert percent[0] == 40
    assert percent[-1] == 80
    assert all(line.startswith("PYMSS_PROGRESS\t") for line in lines)


def test_worker_progress_emitter_falls_back_to_per_file_percent() -> None:
    lines: list[str] = []
    callback = _download_progress_emitter(0, sink=lines.append)

    callback(25, 100, "Downloading tiny.yaml")

    assert lines[-1].split("\t")[1] == "25"


def test_tool_parses_progress_line_and_formats_readable_message() -> None:
    events: list[tuple[int, str]] = []
    lines: list[str] = []

    PymssTool._consume_download_line(
        "PYMSS_PROGRESS\t42\t125000000\t300000000\tDownloading model.ckpt",
        lines,
        lambda percent, message: events.append((percent, message)),
    )
    PymssTool._consume_download_line(
        "plain log line", lines, lambda percent, message: events.append((percent, message))
    )

    assert len(events) == 1
    percent, message = events[0]
    assert percent == 42
    assert "42%" in message
    assert "MB" in message
    assert PymssTool._download_message(-1, 0, 0) == "正在下载"


def test_tool_streams_carriage_return_progress_from_a_live_child() -> None:
    script = (
        "import sys, time\n"
        "sys.stdout.write('PYMSS_PROGRESS\\t10\\t100\\t1000\\tDownloading a.ckpt\\r')\n"
        "sys.stdout.flush()\n"
        "time.sleep(0.05)\n"
        "sys.stdout.write('PYMSS_PROGRESS\\t55\\t550\\t1000\\tDownloading a.ckpt\\r')\n"
        "sys.stdout.flush()\n"
        "print('{\"ok\": true}')\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    progress: list[int] = []
    lines: list[str] = []

    timed_out = PymssTool._pump_download_output(
        proc, lines, lambda percent, _message: progress.append(percent), timeout=30.0
    )
    proc.wait()

    assert timed_out is False
    assert progress == [10, 55]
    assert any(line.strip() == '{"ok": true}' for line in lines)


def test_download_job_surfaces_live_progress() -> None:
    tool = PymssTool()
    observed: list[dict] = []

    def fake_download(model, out_dir=None, purpose="", on_progress=None):  # noqa: ANN001, ARG001
        if on_progress is not None:
            on_progress(50, "正在下载 50%")
        observed.append(tool.download_progress("pymss:demo"))
        return {"ok": True, "model": model}

    with patch.object(type(tool), "available", new=property(lambda self: True)), patch.object(
        tool, "download_model", side_effect=fake_download
    ):
        started = tool.start_download_model("demo.ckpt")
        deadline = time.monotonic() + 2
        job = tool.download_progress(started["key"])
        while job.get("status") == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
            job = tool.download_progress(started["key"])

    assert observed and observed[0]["pct"] == 50
    assert observed[0]["message"] == "正在下载 50%"
    assert job["status"] == "done"
    assert job["pct"] == 100
