from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.model_service import ModelService
from infrastructure.ddsp_worker import _localized_config as ddsp_config
from infrastructure.ddsp_worker import _select_entrypoint
from infrastructure.seedvc_worker import (
    _load_v2_models,
    _localized_config,
    _model_family,
    _patch_seedvc_runtime,
    _patch_v1_audio_geometry,
)
from infrastructure.storage import ListRepository, SettingsStore


@pytest.mark.parametrize("kind,script,flag", [
    ("Sins", "main.py", "--model_path"),
    ("CombSub", "main.py", "--model_path"),
    ("CombSubFast", "main.py", "--model_path"),
    ("CombSubSuperFast", "main.py", "--model_path"),
    ("Diffusion", "main_diff.py", "--diff_ckpt"),
    ("DiffusionNew", "main_diff.py", "--diff_ckpt"),
    ("DiffusionFast", "main_diff.py", "--diff_ckpt"),
])
def test_ddsp_classic_and_diffusion_dispatch(tmp_path, kind, script, flag):
    assert _select_entrypoint({"model": {"type": kind}}, tmp_path) == (tmp_path / "legacy", script, flag)


@pytest.mark.parametrize("model,encoder,override,folder", [
    ({}, "contentvec.pt", None, "legacy"),
    ({"n_aux_layers": 6}, "contentvec.pt", None, "6.2"),
    ({"n_aux_layers": 6}, "pytorch_model.bin", None, ""),
    ({"n_aux_layers": 6}, "renamed.bin", "6.2", "6.2"),
])
def test_ddsp_reflow_generation(tmp_path, model, encoder, override, folder):
    data = {"model": {"type": "RectifiedFlow", **model}, "data": {"encoder_ckpt": encoder}, "xb_ddsp_version": override}
    assert _select_entrypoint(data, tmp_path)[0] == tmp_path / folder


def test_ddsp_reflow_uses_checkpoint_layout_when_version_is_missing(tmp_path, monkeypatch):
    import infrastructure.ddsp_worker as worker

    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setattr(worker, "_checkpoint_reflow_version", lambda _path: "6.3")

    data = {
        "model": {"type": "RectifiedFlow", "n_aux_layers": 6},
        "data": {"encoder_ckpt": "pretrain/contentvec/checkpoint_best_legacy_500.pt"},
    }
    selected, script, flag = _select_entrypoint(data, tmp_path, checkpoint)

    assert selected == tmp_path
    assert script == "main_reflow.py"
    assert flag == "--model_ckpt"


def test_missing_custom_encoder_is_never_replaced_with_contentvec(tmp_path):
    config = tmp_path / "custom.yaml"
    config.write_text(yaml.safe_dump({"model": {"type": "Sins"}, "data": {"encoder": "hubertsoft", "encoder_ckpt": "missing/hubert.pt"}}))
    with pytest.raises(FileNotFoundError, match="missing/hubert.pt"):
        ddsp_config(config, tmp_path / "localized.yaml", tmp_path / "engines/ddsp-svc")


def test_ddsp_reflow_migrates_old_pc_nsf_vocoder_path(tmp_path):
    repo = tmp_path / "engines" / "ddsp-svc"
    encoder = repo / "pretrain" / "contentvec" / "pytorch_model.bin"
    vocoder = repo / "pretrain" / "nsf_hifigan" / "model"
    encoder.parent.mkdir(parents=True)
    vocoder.parent.mkdir(parents=True)
    encoder.write_bytes(b"contentvec")
    vocoder.write_bytes(b"vocoder")
    (repo / "main_reflow.py").write_text("# entrypoint", encoding="utf-8")
    config = tmp_path / "model" / "config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump({
        "model": {"type": "RectifiedFlow", "n_aux_layers": 6},
        "data": {
            "encoder": "contentvec768l12tta2x",
            "encoder_ckpt": "pretrain/contentvec/checkpoint_best_legacy_500.pt",
        },
        "vocoder": {
            "type": "nsf-hifigan",
            "ckpt": "pretrain/Vocoder/pc_nsf_hifigan_testing/model",
        },
    }), encoding="utf-8")

    result = ddsp_config(config, tmp_path / "localized.yaml", repo)

    assert Path(result["data"]["encoder_ckpt"]) == encoder
    assert Path(result["vocoder"]["ckpt"]) == vocoder


def test_import_preserves_assets_after_original_directory_is_removed(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    encoder = source / "encoder.pt"
    encoder.write_bytes(b"custom encoder")
    vocoder = source / "vocoder"
    vocoder.mkdir()
    (vocoder / "model").write_bytes(b"custom vocoder")
    (vocoder / "config.json").write_text('{"sampling_rate": 44100}')
    src_config = source / "model.yaml"
    src_config.write_text(yaml.safe_dump({
        "model": {"type": "Sins"},
        "data": {"encoder": "hubertsoft", "encoder_ckpt": "encoder.pt"},
        "enhancer": {"type": "nsf-hifigan", "ckpt": "vocoder/model"},
    }))
    imported = tmp_path / "imported"
    imported.mkdir()
    destination = imported / "config.yaml"
    ModelService._preserve_model_assets(src_config, destination)
    import shutil

    shutil.rmtree(source)
    result = ddsp_config(destination, tmp_path / "localized.yaml", tmp_path / "engines/ddsp-svc")
    assert Path(result["data"]["encoder_ckpt"]).read_bytes() == b"custom encoder"
    vocoder_model = Path(result["enhancer"]["ckpt"])
    assert vocoder_model.read_bytes() == b"custom vocoder"
    assert (vocoder_model.parent / "config.json").is_file()


@pytest.mark.parametrize("framework", ["ddsp-svc", "seed-vc"])
def test_import_keeps_companion_without_overwriting_main_model(tmp_path, framework):
    import config

    main = tmp_path / "main"
    companion = tmp_path / "companion"
    main.mkdir()
    companion.mkdir()
    for folder, content in ((main, b"main"), (companion, b"companion")):
        (folder / "model.pth").write_bytes(content)
        (folder / "config.yaml").write_text("data: {}\n")
    service = ModelService(ListRepository(tmp_path / "models.json"), SettingsStore(tmp_path / "settings.json"))
    with patch.object(config, "MODELS_DIR", tmp_path / "models"):
        model = service.import_model({
            "framework": framework, "main_model": str(main / "model.pth"),
            "main_config": str(main / "config.yaml"),
            "diffusion_model": str(companion / "model.pth"),
            "diffusion_config": str(companion / "config.yaml"),
        })
    assert model is not None
    assert Path(model["main_model"]["path"]).read_bytes() == b"main"
    assert Path(model["diffusion_model"]["path"]).read_bytes() == b"companion"
    if framework == "ddsp-svc":
        assert model["main_config"]["path"] != model["diffusion_config"]["path"]


@pytest.mark.parametrize("tokenizer,f0", [("whisper", True), ("whisper", False), ("xlsr", False), ("cnhubert", False)])
def test_seedvc_f0_follows_model_configuration(tokenizer, f0):
    data = {"model_params": {"speech_tokenizer": {"type": tokenizer}, "DiT": {"f0_condition": f0}, "length_regulator": {"f0_condition": f0}}}
    assert _model_family(data) == ("v1", f0)


def test_seedvc_rejects_conflicting_f0_configuration():
    with pytest.raises(ValueError, match="f0_condition"):
        _model_family({"model_params": {"DiT": {"f0_condition": True}, "length_regulator": {"f0_condition": False}}})


def test_seedvc_v2_selects_wrapper_without_rmvpe():
    assert _model_family({"_target_": "modules.v2.vc_wrapper.VoiceConversionWrapper"}) == ("v2", False)


def test_seedvc_v1_uses_actual_custom_sample_rate_and_hop(tmp_path):
    source = tmp_path / "fake_seedvc.py"
    source.write_text("def main(args):\n    mel_fn_args = args\n    f0_condition = False\n    sr = 22050 if not f0_condition else 44100\n    hop_length = 256 if not f0_condition else 512\n    return sr, hop_length\n")
    spec = importlib.util.spec_from_file_location("fake_seedvc", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _patch_v1_audio_geometry(module)
    assert module.main({"sampling_rate": 48000, "hop_size": 480}) == (48000, 480)


def test_v2_uses_imported_config_and_both_checkpoints(tmp_path, monkeypatch):
    path = tmp_path / "vc_wrapper.yaml"
    path.write_text(yaml.safe_dump({"_target_": "modules.v2.vc_wrapper.VoiceConversionWrapper", "sr": 24000, "ar_checkpoint_path": "configured-ar.pth"}))
    calls = []
    class Wrapper:
        def load_checkpoints(self, **kwargs): calls.append(("checkpoints", kwargs))
        def to(self, device): calls.append(("device", device))
        def eval(self): pass
        def setup_ar_caches(self, **kwargs): calls.append(("cache", kwargs))
    wrapper = Wrapper()
    def instantiate(data):
        assert data["sr"] == 24000
        assert "ar_checkpoint_path" not in data
        return wrapper
    monkeypatch.setitem(sys.modules, "hydra.utils", types.SimpleNamespace(instantiate=instantiate))
    monkeypatch.setitem(sys.modules, "omegaconf", types.SimpleNamespace(DictConfig=dict))
    args = types.SimpleNamespace(config=str(path), ar_checkpoint_path="imported-ar.pth", cfm_checkpoint_path="cfm.pth")
    module = types.SimpleNamespace(device="cuda:0", dtype="float16")
    assert _load_v2_models(args, module) is wrapper
    assert ("checkpoints", {"ar_checkpoint_path": "imported-ar.pth", "cfm_checkpoint_path": "cfm.pth"}) in calls
    assert ("device", "cuda:0") in calls


def test_v2_localization_preserves_vocoder_architecture(tmp_path):
    cfg = tmp_path / "wrapper.yaml"
    cfg.write_text(yaml.safe_dump({"_target_": "modules.v2.vc_wrapper.VoiceConversionWrapper", "vocoder": {"pretrained_model_name_or_path": "nvidia/bigvgan_v2_22khz_80band_256x"}, "content_extractor_narrow": {"tokenizer_name": "openai/whisper-small"}}))
    localized = _localized_config(cfg, tmp_path, {"whisper": tmp_path / "whisper", "bigvgan": tmp_path / "44k-vocoder"})
    data = yaml.safe_load(localized.read_text())
    assert data["vocoder"]["pretrained_model_name_or_path"] == "nvidia/bigvgan_v2_22khz_80band_256x"
    assert data["content_extractor_narrow"]["tokenizer_name"] == str(tmp_path / "whisper")


def test_seedvc_modern_torchaudio_saves_stereo_without_torchcodec(tmp_path):
    import numpy as np
    import soundfile
    import torch

    audio = types.SimpleNamespace()
    proxy = types.SimpleNamespace(load=torch.load)
    _patch_seedvc_runtime(proxy, audio, soundfile, fp16=True)
    samples = torch.stack([torch.full((100,), 0.2), torch.full((100,), -0.4)])
    destination = tmp_path / "stereo.wav"
    audio.save(str(destination), samples, 24000)
    result, sr = soundfile.read(destination)
    assert sr == 24000
    np.testing.assert_allclose(result, samples.numpy().T)
    checkpoint = tmp_path / "checkpoint.pt"
    torch.save({"model": {"weight": torch.ones(2)}}, checkpoint)
    assert torch.equal(proxy.load(checkpoint, "cpu")["model"]["weight"], torch.ones(2))
