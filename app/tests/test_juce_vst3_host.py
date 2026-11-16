import json
import tempfile
from pathlib import Path

from infrastructure.juce_vst3_host import JuceVst3Host


def test_instrument_plugin_uses_safe_playback_fallback() -> None:
    reason = JuceVst3Host._realtime_compatibility_reason(
        {"is_instrument": True, "inputs": 0, "outputs": 2}
    )
    assert "乐器" in reason


def test_plugin_without_audio_bus_uses_safe_playback_fallback() -> None:
    reason = JuceVst3Host._realtime_compatibility_reason(
        {"is_instrument": False, "inputs": 0, "outputs": 2}
    )
    assert "输入输出总线" in reason


def test_audio_effect_plugin_can_use_realtime_output() -> None:
    reason = JuceVst3Host._realtime_compatibility_reason(
        {"is_instrument": False, "inputs": 2, "outputs": 2}
    )
    assert reason == ""


def test_only_one_plugin_session_can_keep_native_output_enabled() -> None:
    original = JuceVst3Host._sessions
    with tempfile.TemporaryDirectory() as td:
        control = Path(td) / "other.json"
        JuceVst3Host._sessions = {
            "active": {},
            "other": {
                "control_path": control,
                "control_revision": 4,
                "last_transport": {
                    "playing": True,
                    "audible": True,
                    "output_enabled": True,
                    "position_seconds": 1.25,
                },
            },
        }
        try:
            JuceVst3Host._disable_other_outputs("active")
            payload = json.loads(control.read_text(encoding="utf-8"))
            assert payload["output_enabled"] is False
            assert payload["playing"] is True
            assert payload["revision"] == 5
        finally:
            JuceVst3Host._sessions = original


def test_playback_position_alone_does_not_rewrite_transport_control() -> None:
    previous = {
        "playing": True,
        "audible": True,
        "output_enabled": True,
        "seek_revision": 3,
        "timeline_start": 0.0,
        "timeline_end": 20.0,
        "position_seconds": 4.0,
    }
    current = {**previous, "position_seconds": 4.2}
    assert JuceVst3Host._transport_requires_write(previous, current) is False


def test_seek_or_playback_change_rewrites_transport_control() -> None:
    previous = {"playing": True, "seek_revision": 3}
    assert JuceVst3Host._transport_requires_write(
        previous, {**previous, "seek_revision": 4}
    ) is True
    assert JuceVst3Host._transport_requires_write(
        previous, {**previous, "playing": False}
    ) is True
