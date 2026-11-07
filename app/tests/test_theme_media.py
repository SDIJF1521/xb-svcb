"""主题背景媒体用例的测试（存储实现位于 infrastructure.theme_media）。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.theme_media_service import ThemeMediaService
from infrastructure.theme_media import ThemeMediaStore


class ThemeMediaTests(unittest.TestCase):
    @staticmethod
    def service() -> ThemeMediaService:
        return ThemeMediaService(ThemeMediaStore())

    def test_pick_theme_image_has_no_file_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            media_root.mkdir(parents=True)
            source = root / "large-background.png"
            with source.open("wb") as stream:
                stream.write(b"\x89PNG\r\n\x1a\n")
                stream.seek(50 * 1024 * 1024)
                stream.write(b"image")

            def optimize(_src: Path, dst: Path) -> bool:
                dst.write_bytes(b"optimized")
                return True

            with (
                patch("infrastructure.theme_media._transcode_image", side_effect=optimize) as transcode,
                patch("infrastructure.theme_media.config.THEME_MEDIA_DIR", media_root),
                patch("infrastructure.theme_media.paths.ensure_dirs"),
            ):
                result = self.service().save(str(source))

            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "image")
            self.assertEqual(result["name"], source.name)
            self.assertTrue(result["converted"])
            self.assertEqual(result["mime"], "image/webp")
            self.assertTrue(result["path"].endswith(".webp"))
            transcode.assert_called_once_with(source, media_root / result["path"])

    def test_misnamed_heic_image_is_transcoded_for_browser_display(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            media_root.mkdir(parents=True)
            source = root / "phone-photo.png"
            source.write_bytes(
                b"\x00\x00\x00\x1cftypheic\x00\x00\x00\x00mif1heicmiaf"
            )

            def convert(_src: Path, dst: Path) -> bool:
                dst.write_bytes(b"\xff\xd8\xffconverted")
                return True

            with (
                patch("infrastructure.theme_media._transcode_image", side_effect=convert) as transcode,
                patch("infrastructure.theme_media.config.THEME_MEDIA_DIR", media_root),
                patch("infrastructure.theme_media.paths.ensure_dirs"),
            ):
                result = self.service().save(str(source))

            self.assertTrue(result["ok"])
            self.assertTrue(result["converted"])
            self.assertEqual(result["mime"], "image/webp")
            self.assertTrue(result["path"].endswith(".webp"))
            transcode.assert_called_once()
            self.assertTrue((media_root / result["path"]).is_file())

    def test_misnamed_jpeg_uses_detected_mime_and_extension(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            media_root.mkdir(parents=True)
            source = root / "photo.png"
            source.write_bytes(b"\xff\xd8\xffjpeg")

            with (
                patch("infrastructure.theme_media.config.THEME_MEDIA_DIR", media_root),
                patch("infrastructure.theme_media.paths.ensure_dirs"),
            ):
                result = self.service().save(str(source))

            self.assertTrue(result["ok"])
            self.assertFalse(result["converted"])
            self.assertEqual(result["mime"], "image/jpeg")
            self.assertTrue(result["path"].endswith(".jpg"))

    def test_delete_theme_media_only_deletes_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            media_root.mkdir(parents=True)
            managed = media_root / "wallpaper.png"
            outside = root / "outside.png"
            managed.write_bytes(b"managed")
            outside.write_bytes(b"outside")
            service = self.service()

            with patch("infrastructure.theme_media.config.THEME_MEDIA_DIR", media_root):
                self.assertFalse(service.delete(str(outside)))
                self.assertFalse(service.delete("../outside.png"))
                self.assertFalse(service.delete("data:image/png;base64,AAAA"))
                self.assertTrue(service.delete(managed.name))

            self.assertFalse(managed.exists())
            self.assertTrue(outside.exists())

    def test_delete_missing_managed_media_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            media_root = Path(td) / "media"
            media_root.mkdir()

            with patch("infrastructure.theme_media.config.THEME_MEDIA_DIR", media_root):
                self.assertTrue(self.service().delete("missing.mp4"))


if __name__ == "__main__":
    unittest.main()
