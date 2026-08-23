from __future__ import annotations

import sys
from pathlib import Path

from infrastructure.persistent_worker import PersistentInferenceSession


def test_persistent_worker_handles_multiple_audio_requests(tmp_path: Path) -> None:
    code = (
        "import json,sys,pathlib;print('READY',flush=True);"
        "\nfor line in sys.stdin:"
        "\n r=json.loads(line);"
        "\n if r.get('command')=='close': break;"
        "\n pathlib.Path(r['output']).write_bytes(pathlib.Path(r['input']).read_bytes());"
        "\n print('RESULT\\t'+json.dumps({'ok':True}),flush=True)"
    )
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with PersistentInferenceSession(
        [sys.executable, "-u", "-c", code],
        ready_marker="READY",
        result_marker="RESULT\t",
        startup_timeout=10,
    ) as session:
        first_out = session.infer(first, tmp_path / "first-out.wav", timeout=10)
        second_out = session.infer(second, tmp_path / "second-out.wav", timeout=10)

    assert first_out.read_bytes() == b"first"
    assert second_out.read_bytes() == b"second"
