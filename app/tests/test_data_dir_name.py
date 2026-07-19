from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config


def test_default_data_directory_name_is_xb_svcb() -> None:
    assert config.DATA_DIR_NAME == ".xb_svcb"
    assert config.DATA_MARKER_FILE == ".xb_svcb_data"
    assert config.PREVIOUS_DATA_DIR_NAME == ".sb-svcb"
    assert ".sb-svcb" in config.LEGACY_DATA_DIR_NAMES
    assert ".xb_svcb" not in config.LEGACY_DATA_DIR_NAMES


def test_previous_default_directory_is_renamed_without_copying(tmp_path: Path) -> None:
    source = tmp_path / ".sb-svcb"
    model = source / "models" / "voice.pth"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model-data")
    (source / "models.json").write_text(
        '{"path": "' + str(model).replace("\\", "\\\\") + '"}',
        encoding="utf-8",
    )

    with patch.object(config, "write_data_home", return_value=True) as write_home:
        result = config._upgrade_previous_default_data_dir(source)

    target = tmp_path / ".xb_svcb"
    assert result == target
    assert not source.exists()
    assert (target / "models" / "voice.pth").read_bytes() == b"model-data"
    models_json = json.loads((target / "models.json").read_text(encoding="utf-8"))
    assert models_json["path"] == str(target / "models" / "voice.pth")
    write_home.assert_called_once_with(target)


def test_previous_default_rename_rolls_back_when_pointer_write_fails(tmp_path: Path) -> None:
    source = tmp_path / ".sb-svcb"
    source.mkdir()
    (source / "works.json").write_text("[]", encoding="utf-8")

    with patch.object(config, "write_data_home", side_effect=[False, True]) as write_home:
        result = config._upgrade_previous_default_data_dir(source)

    assert result == source
    assert source.is_dir()
    assert (source / "works.json").is_file()
    assert not (tmp_path / ".xb_svcb").exists()
    assert write_home.call_count == 2


def test_existing_old_and_new_directories_are_never_merged(tmp_path: Path) -> None:
    source = tmp_path / ".sb-svcb"
    target = tmp_path / ".xb_svcb"
    source.mkdir()
    target.mkdir()
    (source / "old.txt").write_text("old", encoding="utf-8")
    (target / "new.txt").write_text("new", encoding="utf-8")

    with patch.object(config, "write_data_home") as write_home:
        result = config._upgrade_previous_default_data_dir(source)

    assert result == source
    assert (source / "old.txt").read_text(encoding="utf-8") == "old"
    assert (target / "new.txt").read_text(encoding="utf-8") == "new"
    write_home.assert_not_called()


def test_existing_xb_svcb_repairs_stale_absolute_json_paths(tmp_path: Path) -> None:
    source = tmp_path / ".sb-svcb"
    target = tmp_path / ".xb_svcb"
    target.mkdir()
    stale = source / "models" / "voice.pth"
    current = target / "models" / "voice.pth"
    current.parent.mkdir()
    current.write_bytes(b"model")
    (target / "models.json").write_text(
        '{"main_model": {"path": "'
        + str(stale).replace("\\", "\\\\")
        + '"}}',
        encoding="utf-8",
    )

    result = config._upgrade_previous_default_data_dir(target)

    assert result == target
    payload = json.loads((target / "models.json").read_text(encoding="utf-8"))
    assert payload["main_model"]["path"] == str(current)


def test_xb_svcb_path_repair_handles_forward_slashes(tmp_path: Path) -> None:
    source = tmp_path / ".sb-svcb"
    target = tmp_path / ".xb_svcb"
    target.mkdir()
    stale = str(source / "models" / "voice.pth").replace("\\", "/")
    current = target / "models" / "voice.pth"
    current.parent.mkdir()
    current.write_bytes(b"model")
    (target / "models.json").write_text(
        json.dumps({"main_model_path": stale}),
        encoding="utf-8",
    )

    result = config._upgrade_previous_default_data_dir(target)

    assert result == target
    payload = json.loads((target / "models.json").read_text(encoding="utf-8"))
    assert payload["main_model_path"] == str(current)
