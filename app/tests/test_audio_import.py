"""浏览器音频导入用例的测试（落盘实现位于 infrastructure.audio_import）。"""

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.audio_import_service import AudioImportService
from infrastructure.audio_import import AudioImportStore


class AudioImportTests(unittest.TestCase):
    @staticmethod
    def service() -> AudioImportService:
        return AudioImportService(AudioImportStore())

    def test_streamed_audio_import_preserves_chunked_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = (b"RIFF" + bytes(range(256))) * 4096
            service = self.service()
            with patch("infrastructure.audio_import.config.TEMP_DIR", Path(td) / "temp"):
                token = service.start("large-song.wav")
                self.assertIsNotNone(token)
                assert token is not None
                for offset in range(0, len(payload), 777):
                    chunk = payload[offset : offset + 777]
                    encoded = base64.b64encode(chunk).decode("ascii")
                    self.assertTrue(service.append(token, f"data:audio/wav;base64,{encoded}"))

                path = service.finish(token)
                self.assertIsNotNone(path)
                assert path is not None
                self.assertEqual(Path(path).suffix, ".wav")
                self.assertEqual(Path(path).read_bytes(), payload)
                self.assertFalse(Path(f"{path}.part").exists())

    def test_cancelled_audio_import_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = self.service()
            with patch("infrastructure.audio_import.config.TEMP_DIR", Path(td) / "temp"):
                token = service.start("cancelled.mp3")
                self.assertIsNotNone(token)
                assert token is not None
                self.assertTrue(service.append(token, "data:audio/mpeg;base64,QUJD"))
                self.assertTrue(service.cancel(token))
                self.assertIsNone(service.finish(token))
                self.assertEqual(list((Path(td) / "temp" / "dropped-audio").iterdir()), [])

    def test_one_shot_audio_payload_is_written_to_temp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = self.service()
            payload = base64.b64encode(b"RIFF-one-shot").decode("ascii")
            with patch("infrastructure.audio_import.config.TEMP_DIR", Path(td) / "temp"):
                path = service.save_data("song.wav", f"data:audio/wav;base64,{payload}")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(Path(path).read_bytes(), b"RIFF-one-shot")
            self.assertIsNone(service.save_data("song.mid", payload))


if __name__ == "__main__":
    unittest.main()
