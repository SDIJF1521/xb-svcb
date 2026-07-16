from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_installer_module():
    installer_path = Path(__file__).resolve().parents[2] / "install" / "install.py"
    spec = importlib.util.spec_from_file_location("xb_installer", installer_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundled_ddsp_pc_vocoder_is_deployed_without_downloading(tmp_path, monkeypatch):
    installer = _load_installer_module()
    ddsp_dir = tmp_path / "ddsp-svc"
    assets_dir = tmp_path / "assets" / "models"
    contentvec = ddsp_dir / "pretrain" / "contentvec" / "pytorch_model.bin"
    rmvpe = ddsp_dir / "pretrain" / "rmvpe" / "model.pt"
    bundled_rmvpe = assets_dir / "pretrain" / "rmvpe.pt"
    vocoder = ddsp_dir / "pretrain" / "nsf_hifigan"
    bundled_vocoder = assets_dir / "pretrain" / "pc_nsf_hifigan"
    for path in (contentvec, rmvpe, bundled_rmvpe, bundled_vocoder / "model.ckpt"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete-model")
    (bundled_vocoder / "config.json").write_text('{"pc_aug": true}', encoding="utf-8")

    monkeypatch.setattr(installer, "DDSP_DIR", ddsp_dir)
    monkeypatch.setattr(installer, "ASSETS_MODELS_DIR", assets_dir)
    monkeypatch.setattr(installer, "_is_large_model_file", lambda path: path.exists())
    monkeypatch.setattr(
        installer,
        "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected download")),
    )

    installer.seed_ddsp_base_models()

    assert (vocoder / "config.json").is_file()
    assert (vocoder / "model").read_bytes() == b"complete-model"
