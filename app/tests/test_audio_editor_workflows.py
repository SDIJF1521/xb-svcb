import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
