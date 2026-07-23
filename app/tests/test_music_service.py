import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.music_service import MusicService, _content_range_total


class MusicServiceApiCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = object.__new__(MusicService)

    def test_content_range_total_is_parsed_for_kuwo_range_download(self) -> None:
        self.assertEqual(_content_range_total("bytes 0-4095/33618441"), 33618441)
        self.assertEqual(_content_range_total("bytes */33618441"), 33618441)
        self.assertEqual(_content_range_total(""), 0)

    def test_kuwo_download_headers_mimic_browser_audio_request(self) -> None:
        headers = MusicService._download_headers(
            "http://car-er.kuwo.cn/resource/song.flac", "kuwo"
        )

        self.assertEqual(headers["Referer"], "https://www.kuwo.cn/")
        self.assertEqual(headers["Sec-Fetch-Dest"], "audio")
        self.assertNotIn("Origin", headers)
        self.assertTrue(MusicService._use_range_download("http://car-er.kuwo.cn/a", "kuwo"))

    async def test_wy_search_uses_supported_result_count_parameter(self) -> None:
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

        self.service._request.assert_awaited_once_with(
            {"msg": "keyword", "g": 15}, "wy"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 1)
        self.assertFalse(result["has_more"])

    async def test_qq_search_does_not_send_result_count_parameter(self) -> None:
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

        result = await self.service._search("keyword", 3, 15, "qq")

        self.service._request.assert_awaited_once_with({"msg": "keyword"}, "qq")
        self.assertTrue(result["ok"])
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 1)
        self.assertFalse(result["has_more"])

    async def test_kuwo_search_uses_supported_result_count_parameter(self) -> None:
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
                            "rid": "123456",
                            "subtitle": "Live",
                        }
                    ]
                },
            }
        )

        result = await self.service._search("keyword", 1, 15, "kuwo")

        self.service._request.assert_awaited_once_with(
            {"msg": "keyword", "g": 15}, "kuwo"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["songs"][0]["rid"], "123456")
        self.assertEqual(result["songs"][0]["subtitle"], "Live")

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

    async def test_kuwo_song_detail_reads_vipmusic_url(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "Song",
                    "songname": "Singer",
                    "album": "Album",
                    "picture": "https://img.example.test/pic.web?rid=123456",
                    "vipmusic": {
                        "level": "lossless",
                        "leveltext": "无损音质",
                        "format": "flac",
                        "url": "https://example.test/song.flac",
                    },
                },
            }
        )

        result = await self.service._get_song("keyword", 1, "kuwo")

        self.service._request.assert_awaited_once_with(
            {"msg": "keyword", "n": 1, "size": "lossless"}, "kuwo"
        )
        song = result["song"]
        self.assertEqual(song["vipmusicurl"], "https://example.test/song.flac")
        self.assertEqual(song["format"], "flac")
        self.assertEqual(song["quality"], "无损音质")
        self.assertEqual(song["rid"], "123456")

    async def test_kuwo_song_detail_prefers_msg_n_even_with_search_rid(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "Song",
                    "songname": "Singer",
                    "vipmusic": {"url": "https://example.test/song.flac"},
                },
            }
        )

        result = await self.service._get_song(
            "keyword", 1, "kuwo", song_id="123456"
        )

        self.service._request.assert_awaited_once_with(
            {"msg": "keyword", "n": 1, "size": "lossless"}, "kuwo"
        )
        self.assertEqual(result["song"]["rid"], "123456")
        self.assertEqual(result["song"]["vipmusicurl"], "https://example.test/song.flac")

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

    async def test_lyrics_prefers_official_inline_lrctxt(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "lrc": "plain lyrics without timestamps",
                    "lrctxt": "[00:02.00]Timed line",
                    "lrcurl": "https://example.test/unused.lrc",
                },
            }
        )
        self.service._fetch_text = AsyncMock(return_value="[00:03.00]Unused")

        result = await self.service._get_lyrics("keyword", 1, "wy")

        self.service._fetch_text.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines"], [{"time": 2.0, "text": "Timed line"}])

    async def test_lyrics_reads_official_nested_music_lrcurl(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "Song",
                    "songname": "Singer",
                    "music": {
                        "lrc": "内置cookie解析歌词",
                        "lrcurl": "https://example.test/nested.lrc",
                    },
                },
            }
        )
        self.service._fetch_text = AsyncMock(return_value="[00:03.25]Nested line")

        result = await self.service._get_lyrics("keyword", 1, "wy")

        self.service._fetch_text.assert_awaited_once_with(
            "https://example.test/nested.lrc"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["lines"], [{"time": 3.25, "text": "Nested line"}]
        )

    async def test_lyrics_tries_lrcurl_when_other_fields_fail(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "lrc": "https://example.test/missing.lrc",
                    "lrctxt": "plain lyrics without timestamps",
                    "lrcurl": "https://example.test/available.lrc",
                },
            }
        )
        self.service._fetch_text = AsyncMock(
            side_effect=["", "[00:04.50]Available line"]
        )

        result = await self.service._get_lyrics("keyword", 1, "qq")

        self.assertEqual(
            self.service._fetch_text.await_args_list,
            [
                unittest.mock.call("https://example.test/missing.lrc"),
                unittest.mock.call("https://example.test/available.lrc"),
            ],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["lines"], [{"time": 4.5, "text": "Available line"}]
        )

    async def test_kuwo_lyrics_reads_nested_lyric_lrc(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "雨爱",
                    "songname": "杨丞琳",
                    "lyric": {
                        "lrc": "[00:00.00]雨爱 - 杨丞琳\n[00:16.64]窗外的天气",
                    },
                },
            }
        )
        self.service._fetch_aggregate_lyrics = AsyncMock(return_value="")

        result = await self.service._get_lyrics(
            "雨爱", 1, "kuwo", song_id="123456"
        )

        self.service._request.assert_awaited_once_with(
            {"action": "song", "id": "123456", "size": "lossless"}, "kuwo"
        )
        self.service._fetch_aggregate_lyrics.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["lines"],
            [
                {"time": 0.0, "text": "雨爱 - 杨丞琳"},
                {"time": 16.64, "text": "窗外的天气"},
            ],
        )

    async def test_kuwo_lyrics_can_use_nested_lrclist_when_lrc_missing(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "雨爱",
                    "songname": "杨丞琳",
                    "lyric": {
                        "lrclist": [
                            {"lineLyric": "雨爱 - 杨丞琳", "time": "0.0"},
                            {"lineLyric": "窗外的天气", "time": "16.64"},
                        ],
                    },
                },
            }
        )
        self.service._fetch_aggregate_lyrics = AsyncMock(return_value="")

        result = await self.service._get_lyrics(
            "雨爱", 1, "kuwo", song_id="123456"
        )

        self.service._fetch_aggregate_lyrics.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["lines"],
            [
                {"time": 0.0, "text": "雨爱 - 杨丞琳"},
                {"time": 16.64, "text": "窗外的天气"},
            ],
        )

    async def test_qq_free_detail_uses_official_aggregate_lyrics_api(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "Song",
                    "songname": "Singer",
                    "html": "https://y.qq.com/n/ryqq/songDetail/003kfFex37Ld2s",
                },
            }
        )
        self.service._fetch_aggregate_lyrics = AsyncMock(
            return_value="[00:05.00]QQ line"
        )
        self.service._fetch_text = AsyncMock(return_value="")

        result = await self.service._get_lyrics("keyword", 1, "qq")

        self.service._fetch_aggregate_lyrics.assert_awaited_once_with(
            "003kfFex37Ld2s", "qq"
        )
        self.service._fetch_text.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines"], [{"time": 5.0, "text": "QQ line"}])

    async def test_kuwo_lyrics_reads_direct_n_response_without_aggregate(self) -> None:
        self.service._request = AsyncMock(
            return_value={
                "ok": True,
                "data": {
                    "name": "雨爱",
                    "songname": "杨丞琳",
                    "lyric": {"lrc": "[00:05.00]酷我单曲响应里的歌词"},
                },
            }
        )
        self.service._fetch_aggregate_lyrics = AsyncMock(return_value="")
        self.service._fetch_text = AsyncMock(return_value="")

        result = await self.service._get_lyrics("雨爱", 1, "kuwo")

        self.service._request.assert_awaited_once_with(
            {"msg": "雨爱", "n": 1, "size": "lossless"}, "kuwo"
        )
        self.service._fetch_aggregate_lyrics.assert_not_awaited()
        self.service._fetch_text.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines"], [{"time": 5.0, "text": "酷我单曲响应里的歌词"}])

    async def test_kuwo_lyrics_can_lookup_rid_then_read_inline_lyric(self) -> None:
        self.service._request = AsyncMock(
            side_effect=[
                {
                    "ok": True,
                    "data": {
                        "name": "Song",
                        "songname": "Singer",
                    },
                },
                {
                    "ok": True,
                    "data": {
                        "songs": [
                            {"n": 1, "name": "Song", "rid": "123456"},
                        ]
                    },
                },
                {
                    "ok": True,
                    "data": {
                        "name": "Song",
                        "songname": "Singer",
                        "lyric": {"lrc": "[00:05.00]Kuwo inline line"},
                    },
                },
            ]
        )
        self.service._fetch_aggregate_lyrics = AsyncMock(return_value="")
        self.service._fetch_text = AsyncMock(return_value="")

        result = await self.service._get_lyrics("keyword", 1, "kuwo")

        self.assertEqual(
            self.service._request.await_args_list,
            [
                unittest.mock.call(
                    {"msg": "keyword", "n": 1, "size": "lossless"}, "kuwo"
                ),
                unittest.mock.call({"msg": "keyword", "g": 13}, "kuwo"),
                unittest.mock.call(
                    {"action": "song", "id": "123456", "size": "lossless"}, "kuwo"
                ),
            ],
        )
        self.service._fetch_aggregate_lyrics.assert_not_awaited()
        self.service._fetch_text.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines"], [{"time": 5.0, "text": "Kuwo inline line"}])

    async def test_aggregate_lyrics_uses_official_endpoint_and_parameters(self) -> None:
        self.service._limiter = MagicMock()
        self.service._limiter.wait = AsyncMock()
        self.service.get_api_key = MagicMock(return_value="api-key")
        response = MagicMock()
        response.json.return_value = {
            "code": 200,
            "msg": "请求成功",
            "data": {"lrc": "[00:06.00]Aggregate line"},
        }

        with patch("httpx.AsyncClient") as client_factory:
            client = client_factory.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=response)

            result = await self.service._fetch_aggregate_lyrics(
                "003kfFex37Ld2s", "qq"
            )

        self.service._limiter.wait.assert_awaited_once_with()
        client.get.assert_awaited_once_with(
            f"{config.MUSIC_API_BASE}/lrc",
            params={
                "key": "api-key",
                "mid": "003kfFex37Ld2s",
                "type": "qq",
            },
        )
        self.assertEqual(result, "[00:06.00]Aggregate line")

    async def test_aggregate_lyrics_ignores_kuwo_inline_lyrics_source(self) -> None:
        self.service._limiter = MagicMock()
        self.service._limiter.wait = AsyncMock()

        result = await self.service._fetch_aggregate_lyrics("123456", "kuwo")

        self.service._limiter.wait.assert_not_awaited()
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
