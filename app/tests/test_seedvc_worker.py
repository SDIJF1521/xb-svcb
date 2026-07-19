import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.seedvc_worker import (
    _apply_local_model_paths,
    _local_hf_loader,
    _patch_seedvc_directml_audio_preprocessing,
    _patch_seedvc_directml_f0_postprocessing,
    _patch_whisper_sampling_rate,
    _run_seedvc_with_cpu_fallback,
)


class SeedVcWorkerLocalAssetTests(unittest.TestCase):
    def test_directml_failure_retries_seedvc_once_on_cpu(self) -> None:
        calls: list[tuple] = []
        namespace = SimpleNamespace(fp16=True)
        inference = SimpleNamespace(device="privateuseone:0")
        directml = SimpleNamespace(
            backend="directml",
            device="privateuseone:0",
            name="AMD Radeon",
        )
        cpu = SimpleNamespace(backend="cpu", device="cpu", name="CPU")

        def seedvc_main(args):
            calls.append((inference.device, args.fp16))
            if len(calls) == 1:
                raise RuntimeError("unsupported DirectML operator")

        with patch(
            "infrastructure.seedvc_worker.resolve_torch_device",
            return_value=cpu,
        ) as resolve:
            result = _run_seedvc_with_cpu_fallback(
                seedvc_main, namespace, directml, inference, SimpleNamespace()
            )

        self.assertIs(result, cpu)
        self.assertEqual(calls, [("privateuseone:0", True), ("cpu", False)])
        resolve.assert_called_once_with("cpu", unittest.mock.ANY)

    def test_non_directml_failure_is_not_retried(self) -> None:
        calls: list[str] = []

        def seedvc_main(_args):
            calls.append("run")
            raise RuntimeError("cpu failed")

        cpu = SimpleNamespace(backend="cpu", device="cpu", name="CPU")
        with self.assertRaisesRegex(RuntimeError, "cpu failed"):
            _run_seedvc_with_cpu_fallback(
                seedvc_main,
                SimpleNamespace(fp16=False),
                cpu,
                SimpleNamespace(device="cpu"),
                SimpleNamespace(),
            )
        self.assertEqual(calls, ["run"])

    def test_directml_rmvpe_f0_transfer_is_deferred_for_cpu_statistics(self) -> None:
        calls: list[tuple] = []

        class Tensor:
            def cpu(self):
                calls.append(("cpu",))
                return "cpu-f0"

            def to(self, device, *args, **kwargs):
                calls.append(("to", device, args, kwargs))
                return f"f0-on-{device}"

        class Rmvpe:
            def infer_from_audio(self, *_args, **_kwargs):
                return np.array([0.0, 220.0, 440.0], dtype=np.float32)

        torch_module = type(
            "Torch",
            (),
            {"from_numpy": staticmethod(lambda _array: Tensor())},
        )
        rmvpe_module = type("RmvpeModule", (), {"RMVPE": staticmethod(Rmvpe)})

        _patch_seedvc_directml_f0_postprocessing(torch_module, rmvpe_module)
        model = rmvpe_module.RMVPE()
        marked_f0 = model.infer_from_audio("audio")
        deferred = torch_module.from_numpy(marked_f0)

        self.assertEqual(deferred.to("privateuseone:0"), "cpu-f0")
        self.assertEqual(deferred.to("cuda:0"), "f0-on-cuda:0")
        self.assertEqual(calls, [("cpu",), ("to", "cuda:0", (), {})])

        patched_rmvpe = rmvpe_module.RMVPE
        patched_from_numpy = torch_module.from_numpy
        _patch_seedvc_directml_f0_postprocessing(torch_module, rmvpe_module)
        self.assertIs(rmvpe_module.RMVPE, patched_rmvpe)
        self.assertIs(torch_module.from_numpy, patched_from_numpy)

    def test_directml_audio_features_run_fully_on_cpu_then_return_to_gpu(self) -> None:
        calls: list[tuple] = []

        class Tensor:
            def __init__(self, device: str, label: str) -> None:
                self.device = device
                self.label = label

            def cpu(self):
                calls.append(("cpu", self.label))
                return Tensor("cpu", self.label + "-cpu")

            def to(self, device):
                calls.append(("to", self.label, device))
                return Tensor(str(device), self.label + "-result")

        def mel_spectrogram(waveform, *args, **kwargs):
            calls.append(("mel", waveform.device, args, kwargs))
            return Tensor("cpu", "mel")

        def fbank(waveform, *args, **kwargs):
            calls.append(("fbank", waveform.device, args, kwargs))
            return Tensor("cpu", "fbank")

        audio = type("Audio", (), {"mel_spectrogram": staticmethod(mel_spectrogram)})
        kaldi = type("Kaldi", (), {"fbank": staticmethod(fbank)})
        _patch_seedvc_directml_audio_preprocessing(audio, kaldi)
        directml_wave = Tensor("privateuseone:0", "wave")

        mel = audio.mel_spectrogram(directml_wave, 1024, center=False)
        feature = kaldi.fbank(directml_wave, num_mel_bins=80)

        self.assertEqual(mel.device, "privateuseone:0")
        self.assertEqual(feature.device, "privateuseone:0")
        self.assertIn(("mel", "cpu", (1024,), {"center": False}), calls)
        self.assertIn(("fbank", "cpu", (), {"num_mel_bins": 80}), calls)

    def test_seedvc_audio_preprocessing_keeps_cpu_and_cuda_paths_unchanged(self) -> None:
        calls: list[tuple[str, str]] = []

        class Tensor:
            def __init__(self, device: str) -> None:
                self.device = device

        def mel_spectrogram(waveform):
            calls.append(("mel", waveform.device))
            return waveform

        def fbank(waveform):
            calls.append(("fbank", waveform.device))
            return waveform

        audio = type("Audio", (), {"mel_spectrogram": staticmethod(mel_spectrogram)})
        kaldi = type("Kaldi", (), {"fbank": staticmethod(fbank)})
        _patch_seedvc_directml_audio_preprocessing(audio, kaldi)
        patched_mel = audio.mel_spectrogram
        patched_fbank = kaldi.fbank

        cpu = Tensor("cpu")
        cuda = Tensor("cuda:0")
        self.assertIs(audio.mel_spectrogram(cpu), cpu)
        self.assertIs(kaldi.fbank(cuda), cuda)
        _patch_seedvc_directml_audio_preprocessing(audio, kaldi)

        self.assertIs(audio.mel_spectrogram, patched_mel)
        self.assertIs(kaldi.fbank, patched_fbank)
        self.assertEqual(calls, [("mel", "cpu"), ("fbank", "cuda:0")])

    def test_whisper_feature_extractor_receives_explicit_16khz_rate(self) -> None:
        calls: list[dict] = []

        class FeatureExtractor:
            def __call__(self, *args, **kwargs):
                calls.append(kwargs)
                return "features"

        _patch_whisper_sampling_rate(FeatureExtractor)
        patched = FeatureExtractor.__call__
        self.assertEqual(FeatureExtractor()("audio"), "features")
        self.assertEqual(calls[-1]["sampling_rate"], 16000)

        self.assertEqual(FeatureExtractor()("audio", sampling_rate=8000), "features")
        self.assertEqual(calls[-1]["sampling_rate"], 8000)

        _patch_whisper_sampling_rate(FeatureExtractor)
        self.assertIs(FeatureExtractor.__call__, patched)

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
