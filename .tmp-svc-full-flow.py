from __future__ import annotations

import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "app"))

from api.bridge import build_api  # noqa: E402


def main() -> int:
    api = build_api()
    payload = {
        "title": "游京-SVC-ROCm10-全流程验收",
        "source_path": str(ROOT / ".tmp-svc-full-flow" / "游京_重组测试源.wav"),
        "model_id": "mdl_7f6dbe0803f0",
        "workflow": "auto_mix",
        "params": {
            "device": "rocm",
            "pitch": 0,
            "f0_method": "rmvpe",
            "diffusion_ratio": 0.5,
            "uvr_model": "5_HP-Karaoke-UVR.pth",
            "auto_high_pitch_guard": True,
        },
        "preprocess": {
            "enabled": True,
            "engine": "uvr",
            "harmony_removal_enabled": False,
        },
        "vocal_enhancement": {"enabled": False, "level": "basic"},
    }
    work = api.create_work(payload)
    work_id = str(work["id"])
    print(f"FLOW_WORK_ID {work_id}", flush=True)
    previous = None
    started = time.monotonic()
    while True:
        current = api.get_work(work_id) or {}
        snapshot = (
            current.get("status"),
            current.get("progress"),
            tuple((step.get("key"), step.get("status")) for step in current.get("steps") or []),
            current.get("error"),
        )
        if snapshot != previous:
            print("FLOW_STATUS " + json.dumps({
                "id": work_id,
                "status": current.get("status"),
                "progress": current.get("progress"),
                "steps": current.get("steps"),
                "error": current.get("error"),
                "log_path": current.get("log_path"),
            }, ensure_ascii=False), flush=True)
            previous = snapshot
        if current.get("status") in {"done", "failed"}:
            print("FLOW_RESULT " + json.dumps(current, ensure_ascii=False), flush=True)
            return 0 if current.get("status") == "done" else 1
        if time.monotonic() - started > 7200:
            print("FLOW_TIMEOUT", flush=True)
            return 2
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
