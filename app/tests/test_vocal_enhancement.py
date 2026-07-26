from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.conversion_service import default_steps, default_steps_multi
from application.work_service import WorkService
from infrastructure.vocal_enhancement import VocalEnhancementProcessor
from infrastructure import vocal_enhancement_worker


def test_optional_pipeline_step_is_inserted_before_mix() -> None:
    assert [step["key"] for step in default_steps()] == [
        "separate",
        "f0",
        "infer",
        "mix",
    ]
    assert [step["key"] for step in default_steps(True)] == [
        "separate",
        "f0",
        "infer",
        "enhance",
        "mix",
    ]
    assert [step["key"] for step in default_steps_multi(True)] == [
        "separate",
        "split",
        "infer",
        "merge",
        "enhance",
        "mix",
    ]


def test_work_service_normalizes_levels_and_disables_manual_merge() -> None:
    assert WorkService._vocal_enhancement(
        {"vocal_enhancement": {"enabled": True, "level": "advanced"}},
        "auto_mix",
    ) == {"enabled": True, "level": "advanced"}
    assert WorkService._vocal_enhancement(
        {"vocal_enhancement": {"enabled": True, "level": "unknown"}},
        "auto_mix",
    ) == {"enabled": True, "level": "basic"}
    assert WorkService._vocal_enhancement(
        {"vocal_enhancement": {"enabled": True, "level": "advanced"}},
        "manual_vocal_merge",
    ) == {"enabled": False, "level": "advanced"}


def test_worker_basic_and_advanced_layers_use_expected_order(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF-source")
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-ref")
    calls: list[str] = []

    def fake_silence(_source: Path, output: Path) -> None:
        calls.append("silence")
        output.write_bytes(b"RIFF-silenced")

    def fake_match(_source: Path, _ref: Path, output: Path) -> None:
        calls.append("match")
        output.write_bytes(b"RIFF-matched")

    def fake_deepfilter(_source: Path, output: Path) -> None:
        calls.append("deepfilter")
        output.write_bytes(b"RIFF-filtered")

    def fake_pedalboard_basic(_source: Path, output: Path) -> None:
        calls.append("pedalboard_basic")
        output.write_bytes(b"RIFF-dsp-basic")

    def fake_pedalboard_mastering(_source: Path, output: Path) -> None:
        calls.append("pedalboard_mastering")
        output.write_bytes(b"RIFF-dsp-master")

    with (
        patch.object(
            vocal_enhancement_worker, "_silence_vocalfloor_file", fake_silence
        ),
        patch.object(vocal_enhancement_worker, "_match_reference", fake_match),
        patch.object(vocal_enhancement_worker, "_deepfilter", fake_deepfilter),
        patch.object(
            vocal_enhancement_worker, "_pedalboard_basic", fake_pedalboard_basic
        ),
        patch.object(
            vocal_enhancement_worker,
            "_pedalboard_mastering",
            fake_pedalboard_mastering,
        ),
    ):
        # 无 reference 时跳过匹配
        basic = tmp_path / "basic.wav"
        vocal_enhancement_worker.run(source, basic, "basic", "cpu")
        assert calls == ["silence", "deepfilter", "pedalboard_basic"]
        assert basic.read_bytes() == b"RIFF-dsp-basic"

        calls.clear()
        # 有 reference 时启用匹配
        advanced = tmp_path / "advanced.wav"
        vocal_enhancement_worker.run(source, advanced, "advanced", "auto", reference)
        assert calls == ["silence", "match", "deepfilter", "pedalboard_mastering"]
        assert advanced.read_bytes() == b"RIFF-dsp-master"


def test_processor_invokes_isolated_worker_and_uses_project_cache(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "enhanced.wav"
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    marker = tmp_path / "runtime.ready"
    cache_home = tmp_path / "cache"
    for path in (source, python, worker, marker):
        path.write_bytes(b"ready")

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        output.write_bytes(b"RIFF-enhanced")
        assert cmd[:2] == [str(python), str(worker)]
        assert cmd[cmd.index("--level") + 1] == "advanced"
        assert kwargs["env"]["USERPROFILE"] == str(cache_home)
        return subprocess.CompletedProcess(cmd, 0, "VOCAL_ENHANCE_OK", "")

    with (
        patch.object(config, "VOCAL_ENHANCEMENT_PYTHON", python),
        patch.object(config, "VOCAL_ENHANCEMENT_WORKER", worker),
        patch.object(config, "VOCAL_ENHANCEMENT_MARKER", marker),
        patch.object(config, "VOCAL_ENHANCEMENT_MODEL_DIR", cache_home),
        patch("infrastructure.vocal_enhancement.subprocess.run", side_effect=fake_run),
    ):
        result = VocalEnhancementProcessor().enhance(
            source,
            output,
            level="advanced",
            device="auto",
        )

    assert result == output
    assert output.read_bytes() == b"RIFF-enhanced"
