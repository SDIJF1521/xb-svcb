"""PyMSS 模型元数据：权重解析与多轨模型的伴奏判定。"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import config
from infrastructure import pymss_catalog_meta
from infrastructure.pymss_catalog_meta import _resolve_weight
from infrastructure.pymss_tool import PymssTool
from infrastructure.pymss_worker import (
    normalized_output_label,
    _pick_accompaniment,
)


def _write_silence(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


def test_accompaniment_picker_ignores_extra_stems_of_multi_track_models(
    tmp_path: Path,
) -> None:
    names = ["song_vocals", "song_drums", "song_bass", "song_other", "song_piano", "song_guitar"]
    for name in names:
        _write_silence(tmp_path / f"{name}.wav")
    vocal = tmp_path / "song_vocals.wav"

    # A six-stem model's "other" track is a real stem, not the karaoke bed.
    assert _pick_accompaniment(tmp_path, vocal, "generic", 6) is None


def test_accompaniment_picker_keeps_instrumental_of_three_stem_models(
    tmp_path: Path,
) -> None:
    for name in ("song_male", "song_female", "song_instrumental"):
        _write_silence(tmp_path / f"{name}.wav")

    picked = _pick_accompaniment(
        tmp_path, tmp_path / "song_male.wav", "vocal_separation", 3
    )

    assert picked is not None
    assert picked.name == "song_instrumental.wav"


def test_pymss_model_ready_requires_exact_weight_name(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    weight_dir = tmp_path / "vocal" / "vocal_extraction"
    weight_dir.mkdir(parents=True)
    (weight_dir / "mel_band_roformer_vocals_v2_gabox.ckpt").write_bytes(b"w")
    monkeypatch.setattr(config, "PYMSS_MODEL_DIR", tmp_path)

    assert config.pymss_model_ready("mel_band_roformer_vocals_v2_gabox.ckpt") is True
    assert config.pymss_model_ready("mel_band_roformer_vocals_v2_gabox") is True
    # A shorter catalog name must not be satisfied by a longer model's file.
    assert config.pymss_model_ready("mel_band_roformer_vocals_v2") is False
    assert config.pymss_model_ready("bs_roformer_voc_hyperacev2") is False


def test_weight_resolution_does_not_cross_match_similar_names() -> None:
    index = {"mel_band_roformer_vocals_v2_gabox": Path("a.ckpt")}

    assert _resolve_weight("mel_band_roformer_vocals_v2", index) is None
    assert _resolve_weight("mel_band_roformer_vocals_v2_gabox", index) is not None

def test_parse_training_meta_handles_empty_target_instrument() -> None:
    text = (
        "model:\n"
        "  num_stems: 2\n"
        "training:\n"
        "  instruments:\n"
        "  - vocals\n"
        "  - other\n"
        "  target_instrument:\n"
        "  num_epochs: 1000\n"
    )

    meta = pymss_catalog_meta.parse_training_meta(text)

    assert meta["instruments"] == ["vocals", "other"]
    assert meta["target_instrument"] == ""
    assert meta["num_stems"] == 2


def test_resolve_output_stems_maps_instrument_target_to_instrumental() -> None:
    stems, primary = pymss_catalog_meta.resolve_output_stems(
        ["vocals", "instrument"], "instrument"
    )

    assert stems == ["instrumental", "other"]
    assert primary == "instrumental"
    assert "vocals" not in stems


def test_resolve_output_stems_maps_vocal_target_to_vocals_and_instrumental() -> None:
    stems, primary = pymss_catalog_meta.resolve_output_stems(
        ["Vocals", "Instrumental"], "Vocals"
    )

    assert stems == ["vocals", "instrumental"]
    assert primary == "vocals"


def test_resolve_output_stems_keeps_multi_stem_models() -> None:
    stems, primary = pymss_catalog_meta.resolve_output_stems(
        ["male", "female"], ""
    )

    assert stems == ["male", "female"]
    assert primary == ""


def test_worker_normalizes_target_and_residual_labels() -> None:
    assert (
        normalized_output_label("instrument", "instrument", ["instrumental", "other"])
        == "instrumental"
    )
    assert (
        normalized_output_label("vocals", "instrument", ["instrumental", "other"])
        == "other"
    )
    assert (
        normalized_output_label("Vocals", "Vocals", ["vocals", "instrumental"])
        == "vocals"
    )
    assert (
        normalized_output_label("Instrumental", "Vocals", ["vocals", "instrumental"])
        == "instrumental"
    )

def test_write_result_keeps_file_and_stdout_payload_consistent(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    from infrastructure.pymss_worker import _write_result

    payload = {
        "vocals": str(tmp_path / "pymss_vocals.wav"),
        "instrumental": None,
        "removed_harmony": None,
        "device": "cuda",
        "target_stem": "instrumental",
        "stems": [{"name": "instrumental", "path": str(tmp_path / "pymss_vocals.wav")}],
    }

    _write_result(tmp_path, payload)

    written = json.loads((tmp_path / "pymss_result.json").read_text(encoding="utf-8"))
    assert written == payload
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert printed["ok"] is True
    assert printed["vocals"] == payload["vocals"]
    assert printed["removed_harmony"] is None
    assert printed["stems"] == payload["stems"]

def test_split_target_stems_handles_multi_stem_catalog_values() -> None:
    assert pymss_catalog_meta.split_target_stems("instrumental/vocals") == [
        "instrumental",
        "vocals",
    ]
    assert pymss_catalog_meta.split_target_stems(
        "drums/bass/other/vocals/guitar/piano"
    ) == ["drums", "bass", "other", "vocals", "guitar", "piano"]
    assert pymss_catalog_meta.split_target_stems("speech") == ["speech"]
    assert pymss_catalog_meta.split_target_stems("") == []


def test_attach_model_stems_exposes_target_tokens_for_missing_models(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    monkeypatch.setattr(config, "PYMSS_MODEL_DIR", tmp_path / "empty")

    rows = [{"name": "5_HP-Karaoke-UVR.pth", "target_stem": "instrumental/vocals"}]
    pymss_catalog_meta.attach_model_stems(rows, tmp_path / "empty")

    assert rows[0]["stems"] == []
    assert rows[0]["target_stems"] == ["instrumental", "vocals"]
    assert rows[0]["primary_stem"] == "instrumental"


def test_cover_vocal_entry_accepts_duality_and_karaoke_models() -> None:
    assert PymssTool._is_cover_vocal_entry(
        {
            "name": "melband_roformer_instvox_duality_v2.ckpt",
            "purpose": "",
            "category_label": "人声 / 人声-伴奏双向分离",
            "target_stems": ["vocals", "instrumental"],
        }
    )
    assert PymssTool._is_cover_vocal_entry(
        {
            "name": "mel_band_roformer_karaoke_gabox_v2.ckpt",
            "purpose": "",
            "category_label": "卡拉OK/和声",
            "target_stems": ["backing_vocal"],
        }
    )


def test_cover_vocal_entry_accepts_legacy_catalog_row_without_metadata() -> None:
    assert PymssTool._is_cover_vocal_entry({"name": "model.ckpt"})


def test_cover_vocal_entry_rejects_duet_and_pure_instrumental_models() -> None:
    assert not PymssTool._is_cover_vocal_entry(
        {
            "name": "model_mel_band_roformer_ep_0_sdr_7.9319_fixed.ckpt",
            "purpose": "vocal_separation",
            "category_label": "人声 / 双人/二重唱分离",
            "target_stems": ["vocals"],
        }
    )
    assert not PymssTool._is_cover_vocal_entry(
        {
            "name": "UVR-MDX-NET-Inst_HQ_4",
            "purpose": "vocal_separation",
            "target_stems": ["instrumental"],
        }
    )