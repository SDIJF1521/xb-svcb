import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.music_service import MusicService


class MusicServiceApiCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = object.__new__(MusicService)

    async def test_search_does_not_send_removed_result_count_parameter(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "songs": [
                        {
                            "n": 1,
                            "name": "Song",
                            "singer": "Singer",
                            "album": "Album",
                        }
                    ]
                },
            }
        )

        result = await self.service._search("keyword", 3, 15, "wy")

        self.service._request.assert_awaited_once_with({"msg": "keyword"}, "wy")
        self.assertTrue(result["ok"])
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 1)
        self.assertFalse(result["has_more"])

    async def test_song_detail_exposes_vip_audio_url(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "Song",
                    "songname": "Singer",
                    "vipmusicurl": "https://example.test/vip.m4a",
                    "musicurl": "https://example.test/normal.mp3",
                },
            }
        )

        result = await self.service._get_song("keyword", 1, "qq")

        song = result["song"]
        self.assertEqual(song["vipmusicurl"], "https://example.test/vip.m4a")
        self.assertEqual(
            self.service._song_audio_urls(song),
            [
                "https://example.test/vip.m4a",
                "https://example.test/normal.mp3",
            ],
        )

    async def test_lyrics_url_is_resolved_before_parsing(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "Song",
                    "songname": "Singer",
                    "lrc": "https://example.test/song.lrc",
                },
            }
        )
        self.service._fetch_text = AsyncMock(return_value="[00:01.00]First line")

        result = await self.service._get_lyrics("keyword", 1, "wy")

        self.service._fetch_text.assert_awaited_once_with(
            "https://example.test/song.lrc"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines"], [{"time": 1.0, "text": "First line"}])


if __name__ == "__main__":
    unittest.main()
