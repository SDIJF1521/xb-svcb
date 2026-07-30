import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.bridge import Api


class ThemeMediaTests(unittest.TestCase):
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
