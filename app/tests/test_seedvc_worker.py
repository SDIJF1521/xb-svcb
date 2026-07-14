import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.seedvc_worker import _apply_local_model_paths, _local_hf_loader


class SeedVcWorkerLocalAssetTests(unittest.TestCase):
    def test_known_remote_model_ids_are_replaced_with_local_directories(self) -> None:
        assets = {
            "whisper": Path("C:/models/whisper-small"),
            "bigvgan": Path("C:/models/bigvgan"),
        }
        config = {
            "model_params": {
                "vocoder": {"name": "nvidia/bigvgan_v2_44khz_128band_512x"},
                "speech_tokenizer": {"name": "openai/whisper-small"},
            }
        }

        self.assertTrue(_apply_local_model_paths(config, assets))
        self.assertEqual(config["model_params"]["vocoder"]["name"], str(assets["bigvgan"]))
        self.assertEqual(config["model_params"]["speech_tokenizer"]["name"], str(assets["whisper"]))

    def test_unknown_model_ids_are_not_replaced(self) -> None:
        config = {
            "model_params": {
                "vocoder": {"name": "custom/vocoder"},
                "speech_tokenizer": {"name": "custom/tokenizer"},
            }
        }
        self.assertFalse(
            _apply_local_model_paths(
                config,
                {"whisper": Path("whisper"), "bigvgan": Path("bigvgan")},
            )
        )

    def test_local_hf_loader_avoids_network_for_bundled_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rmvpe = root / "rmvpe.pt"
            campplus = root / "campplus.bin"
            rmvpe.touch()
            campplus.touch()
            calls: list[tuple] = []

            def original(*args):
                calls.append(args)
                return "remote"

            loader = _local_hf_loader(
                original,
                {"rmvpe": rmvpe, "campplus": campplus},
            )
            self.assertEqual(
                loader("lj1995/VoiceConversionWebUI", "rmvpe.pt"),
                str(rmvpe),
            )
            self.assertEqual(
                loader("funasr/campplus", "campplus_cn_common.bin"),
                str(campplus),
            )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
