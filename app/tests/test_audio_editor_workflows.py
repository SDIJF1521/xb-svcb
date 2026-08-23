import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.audio_editor_service import AudioEditorService
from domain import EditorProject
from infrastructure.storage import ListRepository


class _FakeFfmpeg:
    available = True

    def __init__(self) -> None:
        self.detect_call = None

    def detect_silences(self, src, **kwargs):
        self.detect_call = (Path(src), kwargs)
        return [
            {"start": 2.8, "end": 3.2, "duration": 0.4},
            {"start": 5.8, "end": 6.2, "duration": 0.4},
        ]


class _FakePluginHost:
    def __init__(self) -> None:
        self.closed = False
        self.transport = None

    def sync_editor(self, _session_id: str, transport=None) -> dict:
        self.transport = transport
        return {
            "ok": True,
            "closed": self.closed,
            "plugin": {
                "name": "Test Plugin",
                "state": "c3RhdGU=",
                "parameter_values": {"mix": 0.75},
            },
        }


class _FakeAudio:
    available = True

    def __init__(self) -> None:
        self.rendered_project = None
        self.monitor_effects = None

    def render_timeline(self, project, dst, _cache_dir, _fmt) -> bool:
        self.rendered_project = project
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"merged")
        return True

    def render_plugin_monitor_input(self, _src, _clip, effects, dst, _cache_dir, _sample_rate) -> bool:
        self.monitor_effects = effects
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"monitor")
        return True

    def trim(self, src, _start, _end, dst, sample_rate=44100):
        del sample_rate
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(Path(src).read_bytes())
        return True


class _FakeEnhancement:
    available = True

    def __init__(self) -> None:
        self.calls = []

    @staticmethod
    def normalize_strength(value, fallback):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return fallback

    def enhance(self, source, output, **kwargs):
        self.calls.append((Path(source), Path(output), kwargs))
        Path(output).write_bytes(Path(source).read_bytes() + b"-enhanced")
        return Path(output)


class AudioEditorWorkflowTests(unittest.TestCase):
    def make_service(self, root: Path) -> tuple[AudioEditorService, ListRepository, _FakeFfmpeg]:
        repo = ListRepository(root / "projects.json")
        ffmpeg = _FakeFfmpeg()
        service = object.__new__(AudioEditorService)
        service._repo = repo
        service._ffmpeg = ffmpeg
        return service, repo, ffmpeg

    @staticmethod
    def project(source: Path) -> dict:
        return {
            "id": "project-1",
            "title": "Workflow test",
            "duration": 14.0,
            "sample_rate": 44100,
            "waveform_cache": {},
            "metadata": {
                "timeline_template_id": "duet",
                "timeline_template_name": "双人对唱",
            },
            "roles": [
                {"id": "role-a", "name": "角色 A", "color": "#4f8cff"},
                {"id": "role-b", "name": "角色 B", "color": "#ff7aa8"},
            ],
            "tracks": [
                {
                    "id": "track-1",
                    "name": "角色 A 轨",
                    "type": "vocal",
                    "locked": False,
                    "mute": False,
                    "volume": 1.0,
                    "metadata": {"template_id": "duet", "role_id": "role-a"},
                    "clips": [
                        {
                            "id": "clip-1",
                            "name": "人声",
                            "start": 5.0,
                            "end": 14.0,
                            "offset": 2.0,
                            "volume": 1.0,
                            "mute": False,
                            "file": str(source),
                            "effects": [],
                            "locked": False,
                            "fade_in": 0.0,
                            "fade_out": 0.0,
                            "metadata": {"role_id": "role-a"},
                        }
                    ],
                }
            ],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "history": [],
            "future": [],
        }

    def test_plain_txt_auto_split_snaps_to_silence_and_preserves_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "voice.wav"
            source.write_bytes(b"audio")
            service, repo, ffmpeg = self.make_service(root)
            repo.add(self.project(source))

            result = service.split_clip_by_lyrics(
                "project-1",
                "track-1",
                "clip-1",
                "第一句\n第二句\n第三句",
                {
                    "padding": 0,
                    "min_clip": 0.2,
                    "auto_silence": True,
                    "threshold_db": -42,
                    "min_silence": 0.3,
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["timing"], "auto")
            self.assertEqual([clip["start"] for clip in result["clips"]], [5.0, 8.0, 11.0])
            self.assertEqual([clip["end"] for clip in result["clips"]], [8.0, 11.0, 14.0])
            self.assertEqual(
                [clip["metadata"]["lyric_text"] for clip in result["clips"]],
                ["第一句", "第二句", "第三句"],
            )
            self.assertTrue(all(clip["metadata"]["lyric_timing"] == "auto" for clip in result["clips"]))
            self.assertEqual(ffmpeg.detect_call[1]["start"], 2.0)
            self.assertEqual(ffmpeg.detect_call[1]["end"], 11.0)

            reopened = service.get("project-1")
            self.assertEqual([role["id"] for role in reopened["roles"]], ["role-a", "role-b"])
            self.assertEqual(reopened["metadata"]["timeline_template_id"], "duet")
            self.assertEqual(reopened["tracks"][0]["metadata"]["role_id"], "role-a")

    def test_remove_project_deletes_project_files_and_owned_cache(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            editor_root = root / "editor"
            cache_root = editor_root / "cache"
            project_dir = editor_root / "project-1"
            nested_file = project_dir / "media" / "voice.wav"
            nested_file.parent.mkdir(parents=True)
            nested_file.write_bytes(b"audio")
            cache_root.mkdir(parents=True)
            owned_cache = cache_root / "project-1_render.wav"
            other_cache = cache_root / "project-10_render.wav"
            owned_cache.write_bytes(b"owned")
            other_cache.write_bytes(b"other")
            outside = root / "original.wav"
            outside.write_bytes(b"original")
            service, repo, _ = self.make_service(root)
            repo.add(self.project(outside))

            with (
                patch("application.audio_editor_service.config.EDITOR_DIR", editor_root),
                patch("application.audio_editor_service.config.EDITOR_CACHE_DIR", cache_root),
            ):
                removed = service.remove("project-1")

            self.assertTrue(removed)
            self.assertIsNone(repo.get("project-1"))
            self.assertFalse(project_dir.exists())
            self.assertFalse(owned_cache.exists())
            self.assertTrue(other_cache.exists())
            self.assertTrue(outside.exists())

    def test_ai_enhance_clip_uses_original_song_reference_and_keeps_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "converted.wav"
            reference = root / "original.wav"
            source.write_bytes(b"converted")
            reference.write_bytes(b"original")
            service, repo, _ = self.make_service(root)
            project = self.project(source)
            project["tracks"][0]["clips"][0]["effects"] = [
                {"id": "gain", "type": "gain", "enabled": True, "params": {"gain_db": 2}}
            ]
            repo.add(project)
            service._audio = _FakeAudio()
            enhancement = _FakeEnhancement()
            service._vocal_enhancement = enhancement

            with patch("application.audio_editor_service.config.EDITOR_DIR", root / "editor"):
                result = service.enhance_clip(
                    "project-1",
                    "track-1",
                    "clip-1",
                    str(reference),
                    {"level": "advanced", "pitch_correction": 0.7},
                )

            self.assertTrue(result["ok"])
            clip = result["clip"]
            self.assertEqual((clip["start"], clip["end"], clip["offset"]), (5.0, 14.0, 0.0))
            self.assertEqual(clip["effects"][0]["id"], "gain")
            self.assertTrue(Path(clip["file"]).is_file())
            self.assertTrue(clip["metadata"]["ai_enhanced"])
            self.assertEqual(clip["metadata"]["ai_enhancement_reference"], str(reference))
            self.assertEqual(enhancement.calls[0][2]["reference"].read_bytes(), b"original")
            self.assertTrue(repo.get("project-1")["history"])

    def test_remove_last_project_clears_shared_editor_cache(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            editor_root = root / "editor"
            cache_root = editor_root / "cache"
            project_dir = editor_root / "project-1"
            project_dir.mkdir(parents=True)
            cache_root.mkdir(parents=True)
            (cache_root / "aud_shared.mp3").write_bytes(b"shared")
            (cache_root / "wf_shared.wav").write_bytes(b"waveform")
            source = root / "source.wav"
            source.write_bytes(b"audio")
            service, repo, _ = self.make_service(root)
            repo.add(self.project(source))

            with (
                patch("application.audio_editor_service.config.EDITOR_DIR", editor_root),
                patch("application.audio_editor_service.config.EDITOR_CACHE_DIR", cache_root),
            ):
                self.assertTrue(service.remove("project-1"))

            self.assertFalse(project_dir.exists())
            self.assertFalse(any(cache_root.iterdir()))

    def test_list_removes_orphan_editor_project_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            editor_root = root / "editor"
            cache_root = editor_root / "cache"
            orphan = editor_root / "edt_orphan"
            orphan.mkdir(parents=True)
            (orphan / "media.wav").write_bytes(b"orphan")
            cache_root.mkdir(parents=True)
            service, _, _ = self.make_service(root)

            with (
                patch("application.audio_editor_service.config.EDITOR_DIR", editor_root),
                patch("application.audio_editor_service.config.EDITOR_CACHE_DIR", cache_root),
            ):
                self.assertEqual(service.list(), [])

            self.assertFalse(orphan.exists())

    def test_remove_project_keeps_record_when_file_cleanup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            editor_root = root / "editor"
            cache_root = editor_root / "cache"
            project_dir = editor_root / "project-1"
            project_dir.mkdir(parents=True)
            source = root / "source.wav"
            source.write_bytes(b"audio")
            service, repo, _ = self.make_service(root)
            repo.add(self.project(source))

            with (
                patch("application.audio_editor_service.config.EDITOR_DIR", editor_root),
                patch("application.audio_editor_service.config.EDITOR_CACHE_DIR", cache_root),
                patch(
                    "application.audio_editor_service.shutil.rmtree",
                    side_effect=PermissionError("in use"),
                ),
            ):
                removed = service.remove("project-1")

            self.assertFalse(removed)
            self.assertIsNotNone(repo.get("project-1"))
            self.assertTrue(project_dir.exists())

    def test_remove_project_rejects_path_traversal_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            editor_root = root / "editor"
            editor_root.mkdir()
            outside = root / "keep.txt"
            outside.write_text("keep", encoding="utf-8")
            service, repo, _ = self.make_service(root)
            project = self.project(outside)
            project["id"] = ".."
            repo.add(project)

            with (
                patch("application.audio_editor_service.config.EDITOR_DIR", editor_root),
                patch(
                    "application.audio_editor_service.config.EDITOR_CACHE_DIR",
                    editor_root / "cache",
                ),
            ):
                removed = service.remove("..")

            self.assertFalse(removed)
            self.assertIsNotNone(repo.get(".."))
            self.assertTrue(outside.exists())

    def test_lrc_parser_remains_timestamp_compatible(self) -> None:
        lines = AudioEditorService._parse_lyric_lines(
            "[00:01.25]第一句\n[00:03.50]第二句"
        )
        self.assertEqual(
            lines,
            [
                {"time": 1.25, "text": "第一句"},
                {"time": 3.5, "text": "第二句"},
            ],
        )

    def test_editor_project_schema_serializes_roles(self) -> None:
        project = EditorProject(
            id="project",
            title="Roles",
            tracks=[],
            duration=1.0,
            roles=[{"id": "lead", "name": "主唱", "color": "#4f8cff"}],
        ).to_dict()
        self.assertEqual(project["roles"][0]["id"], "lead")

    def test_plugin_state_sync_keeps_session_open_and_deduplicates_updates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "voice.wav"
            source.write_bytes(b"audio")
            service, repo, _ = self.make_service(root)
            project = self.project(source)
            project["tracks"][0]["clips"][0]["effects"] = [
                {
                    "id": "effect-1",
                    "type": "plugin",
                    "enabled": True,
                    "params": {"path": "test.vst3"},
                }
            ]
            repo.add(project)
            host = _FakePluginHost()
            service._plugin_host = host
            service._plugin_sessions = {
                "session-1": {
                    "project_id": "project-1",
                    "track_id": "track-1",
                    "clip_id": "clip-1",
                    "effect_id": "effect-1",
                }
            }

            first = service.sync_effect_plugin_editor(
                "session-1",
                {"playing": True, "position_seconds": 6.25},
            )
            self.assertIn("project", first)
            params = first["project"]["tracks"][0]["clips"][0]["effects"][0]["params"]
            self.assertEqual(params["parameters"], {"mix": 0.75})
            self.assertIn("session-1", service._plugin_sessions)
            self.assertEqual(host.transport["timeline_start"], 5.0)
            self.assertEqual(host.transport["timeline_end"], 14.0)
            self.assertTrue(host.transport["audible"])

            second = service.sync_effect_plugin_editor("session-1")
            self.assertNotIn("project", second)

            host.closed = True
            closed = service.sync_effect_plugin_editor("session-1")
            self.assertTrue(closed["closed"])
            self.assertNotIn("session-1", service._plugin_sessions)

    def test_plugin_monitor_renders_only_effects_before_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "voice.wav"
            source.write_bytes(b"audio")
            service, _, _ = self.make_service(root)
            audio = _FakeAudio()
            service._audio = audio
            project = self.project(source)
            track = project["tracks"][0]
            clip = track["clips"][0]
            clip["effects"] = [
                {"id": "gain-1", "type": "gain", "enabled": True, "params": {"gain_db": 2}},
                {"id": "plugin-1", "type": "plugin", "enabled": True, "params": {"path": "test.vst3"}},
                {"id": "limit-1", "type": "limiter", "enabled": True, "params": {}},
            ]

            with patch(
                "application.audio_editor_service.config.EDITOR_CACHE_DIR",
                root / "cache",
            ):
                monitor = service._prepare_plugin_monitor(
                    project,
                    {**track, "id": "stale-track-reference"},
                    clip,
                    "plugin-1",
                )

            self.assertTrue(Path(monitor["input"]).exists())
            self.assertTrue(Path(monitor["bed_input"]).exists())
            self.assertEqual(monitor["timeline_start"], 5.0)
            self.assertEqual(monitor["timeline_end"], 14.0)
            self.assertEqual(monitor["project_duration"], 14.0)
            self.assertEqual(monitor["block_size"], 128)
            self.assertEqual([effect["id"] for effect in audio.monitor_effects], ["gain-1"])
            self.assertEqual(audio.rendered_project["tracks"][0]["clips"], [])

    def test_merge_clips_renders_timeline_and_replaces_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first_source = root / "first.wav"
            second_source = root / "second.wav"
            first_source.write_bytes(b"first")
            second_source.write_bytes(b"second")
            service, repo, _ = self.make_service(root)
            audio = _FakeAudio()
            service._audio = audio
            service._project_dir = lambda _project_id: root / "editor-project"
            project = self.project(first_source)
            first = project["tracks"][0]["clips"][0]
            first["end"] = 8.0
            first["volume"] = 0.7
            first["effects"] = [
                {"id": "gain-1", "type": "gain", "enabled": True, "params": {"gain_db": 2}}
            ]
            second = {
                **first,
                "id": "clip-2",
                "name": "和声",
                "start": 8.25,
                "end": 11.0,
                "offset": 0.5,
                "file": str(second_source),
                "volume": 1.1,
                "effects": [],
                "metadata": {"role_id": "role-b"},
            }
            project["tracks"][0]["clips"].append(second)
            repo.add(project)

            result = service.merge_clips(
                "project-1",
                "track-1",
                ["clip-1", "clip-2"],
            )

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["project"]["tracks"][0]["clips"]), 1)
            merged = result["clip"]
            self.assertEqual((merged["start"], merged["end"], merged["offset"]), (5.0, 11.0, 0.0))
            self.assertEqual(merged["effects"], [])
            self.assertEqual(merged["metadata"]["merged_clip_ids"], ["clip-1", "clip-2"])
            self.assertNotIn("role_id", merged["metadata"])
            self.assertTrue(Path(merged["file"]).exists())
            self.assertEqual(audio.rendered_project["tracks"][0]["volume"], 1.0)
            self.assertEqual(
                [(item["start"], item["end"]) for item in audio.rendered_project["tracks"][0]["clips"]],
                [(0.0, 3.0), (3.25, 6.0)],
            )


if __name__ == "__main__":
    unittest.main()
