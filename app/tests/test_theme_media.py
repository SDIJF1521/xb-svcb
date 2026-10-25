import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.bridge import Api


class ThemeMediaTests(unittest.TestCase):
    def test_pick_theme_image_has_no_file_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            source = root / "large-background.png"
            with source.open("wb") as stream:
                stream.write(b"\x89PNG\r\n\x1a\n")
                stream.seek(50 * 1024 * 1024)
                stream.write(b"image")
            api = object.__new__(Api)

            with (
                patch.object(api, "_open_dialog", return_value=[str(source)]),
                patch("api.bridge.config.THEME_MEDIA_DIR", media_root),
                patch("api.bridge.paths.ensure_dirs"),
                patch("api.bridge.shutil.copy2") as copy_file,
            ):
                result = api.pick_theme_media_file()

            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "image")
            self.assertEqual(result["name"], source.name)
            copy_file.assert_called_once_with(source, media_root / result["path"])

    def test_misnamed_heic_image_is_transcoded_for_browser_display(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            media_root.mkdir(parents=True)
            source = root / "phone-photo.png"
            source.write_bytes(
                b"\x00\x00\x00\x1cftypheic\x00\x00\x00\x00mif1heicmiaf"
            )
            api = object.__new__(Api)

            def convert(_src: Path, dst: Path) -> bool:
                dst.write_bytes(b"\xff\xd8\xffconverted")
                return True

            with (
                patch.object(api, "_open_dialog", return_value=[str(source)]),
                patch.object(api, "_transcode_theme_image", side_effect=convert) as transcode,
                patch("api.bridge.config.THEME_MEDIA_DIR", media_root),
                patch("api.bridge.paths.ensure_dirs"),
            ):
                result = api.pick_theme_media_file()

            self.assertTrue(result["ok"])
            self.assertTrue(result["converted"])
            self.assertEqual(result["mime"], "image/jpeg")
            self.assertTrue(result["path"].endswith(".jpg"))
            transcode.assert_called_once()
            self.assertTrue((media_root / result["path"]).is_file())

    def test_misnamed_jpeg_uses_detected_mime_and_extension(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media_root = root / "theme" / "media"
            media_root.mkdir(parents=True)
            source = root / "photo.png"
            source.write_bytes(b"\xff\xd8\xffjpeg")
            api = object.__new__(Api)

            with (
                patch.object(api, "_open_dialog", return_value=[str(source)]),
                patch("api.bridge.config.THEME_MEDIA_DIR", media_root),
                patch("api.bridge.paths.ensure_dirs"),
            ):
                result = api.pick_theme_media_file()

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
            api = object.__new__(Api)

            with patch("api.bridge.config.THEME_MEDIA_DIR", media_root):
                self.assertFalse(api.delete_theme_media_file(str(outside)))
                self.assertFalse(api.delete_theme_media_file("../outside.png"))
                self.assertFalse(api.delete_theme_media_file("data:image/png;base64,AAAA"))
                self.assertTrue(api.delete_theme_media_file(managed.name))

            self.assertFalse(managed.exists())
            self.assertTrue(outside.exists())

    def test_delete_missing_managed_media_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            media_root = Path(td) / "media"
            media_root.mkdir()
            api = object.__new__(Api)

            with patch("api.bridge.config.THEME_MEDIA_DIR", media_root):
                self.assertTrue(api.delete_theme_media_file("missing.mp4"))


if __name__ == "__main__":
    unittest.main()
