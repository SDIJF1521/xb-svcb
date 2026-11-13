import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.audio_engine import FFmpegEngine


class _RecordingEffects:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, list[str], Path]] = []

    def render_file(self, src, effects, dst, _cache_dir, _sample_rate):
        effect_ids = [str(effect.get("id") or "") for effect in effects]
        self.calls.append((Path(src), effect_ids, Path(dst)))
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(Path(src).read_bytes() + b"-fx")
        return Path(dst)


class _RecordingPitchTool:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, int]] = []

    def pitch(self, src, dst, semitones, sample_rate=44100):
        self.calls.append((Path(src), Path(dst), int(semitones)))
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"pitched")
        return True


class _RecordingEngine(FFmpegEngine):
    def __init__(self) -> None:
        self._effects = _RecordingEffects()
        self._tool = _RecordingPitchTool()
        self.flat_projects: list[dict] = []

    def _render_flat_timeline(self, project, dst, _cache_dir, _output_format="wav"):
        self.flat_projects.append(project)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"mix")
        return True


class ScopedAudioEffectsTests(unittest.TestCase):
    @staticmethod
    def _clip(clip_id: str, source: Path, role_id: str = "") -> dict:
        return {
            "id": clip_id,
            "file": str(source),
            "start": 0.0,
            "end": 4.0,
            "offset": 0.0,
            "volume": 1.0,
            "mute": False,
            "effects": [],
            "fade_in": 0.0,
            "fade_out": 0.0,
            "channel": "stereo",
            "metadata": {"role_id": role_id} if role_id else {},
        }

    def test_role_bus_is_processed_before_track_bus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "voice.wav"
            source.write_bytes(b"audio")
            project = {
                "sample_rate": 44100,
                "duration": 4.0,
                "roles": [
                    {
                        "id": "role-a",
                        "name": "角色 A",
                        "effects": [{"id": "role-fx", "type": "reverb", "enabled": True}],
                    },
                    {"id": "role-b", "name": "角色 B", "effects": []},
                ],
                "tracks": [
                    {
                        "id": "track-1",
                        "volume": 1.0,
                        "mute": False,
                        "effects": [{"id": "track-fx", "type": "compressor", "enabled": True}],
                        "metadata": {"role_id": "role-a"},
                        "clips": [
                            self._clip("clip-a", source),
                            self._clip("clip-b", source, "role-b"),
                        ],
                    }
                ],
            }
            engine = _RecordingEngine()

            ok = engine.render_timeline(project, root / "out.wav", root / "cache", "wav")

            self.assertTrue(ok)
            self.assertEqual([call[1] for call in engine._effects.calls], [["role-fx"], ["track-fx"]])
            role_projects = [item for item in engine.flat_projects if item["tracks"][0]["id"] == "track-1"]
            self.assertEqual(
                [[clip["id"] for clip in item["tracks"][0]["clips"]] for item in role_projects],
                [["clip-a"], ["clip-b"]],
            )

    def test_projects_without_bus_effects_keep_single_pass_render(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "voice.wav"
            source.write_bytes(b"audio")
            project = {
                "sample_rate": 44100,
                "duration": 4.0,
                "roles": [{"id": "role-a", "effects": []}],
                "tracks": [
                    {
                        "id": "track-1",
                        "volume": 1.0,
                        "mute": False,
                        "effects": [],
                        "clips": [self._clip("clip-a", source, "role-a")],
                    }
                ],
            }
            engine = _RecordingEngine()

            ok = engine.render_timeline(project, root / "out.wav", root / "cache", "wav")

            self.assertTrue(ok)
            self.assertEqual(engine.flat_projects, [project])
            self.assertEqual(engine._effects.calls, [])
            self.assertEqual(engine._tool.calls, [])

    def test_role_pitch_shifts_role_bus(self) -> None:
        """角色「变调」必须真正落到渲染：整条角色总线按半音数变调。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "voice.wav"
            source.write_bytes(b"audio")
            project = {
                "sample_rate": 44100,
                "duration": 4.0,
                "roles": [{"id": "role-a", "pitch": 2, "effects": []}],
                "tracks": [
                    {
                        "id": "track-1",
                        "volume": 1.0,
                        "mute": False,
                        "effects": [],
                        "clips": [self._clip("clip-a", source, "role-a")],
                    }
                ],
            }
            engine = _RecordingEngine()

            ok = engine.render_timeline(project, root / "out.wav", root / "cache", "wav")

            self.assertTrue(ok)
            self.assertEqual([call[2] for call in engine._tool.calls], [2])
            # 变调后走的是角色总线，不再是单趟直出
            self.assertNotEqual(engine.flat_projects[:1], [project])

    def test_role_pitch_is_clamped_and_ignores_invalid_values(self) -> None:
        self.assertEqual(FFmpegEngine._role_pitch({"pitch": 99}), 24)
        self.assertEqual(FFmpegEngine._role_pitch({"pitch": -99}), -24)
        self.assertEqual(FFmpegEngine._role_pitch({"pitch": "abc"}), 0)
        self.assertEqual(FFmpegEngine._role_pitch(None), 0)


if __name__ == "__main__":
    unittest.main()
