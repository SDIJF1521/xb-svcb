from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.conversion_service import ConversionService, default_steps, default_steps_multi
from application.work_service import WorkService


def test_preprocess_normalizes_optional_harmony_settings() -> None:
    result = WorkService._preprocess(
        {
            "preprocess": {
                "enabled": True,
                "engine": "pymss",
                "pymss_model": "voc.ckpt",
                "harmony_removal_enabled": True,
                "harmony_model": "bve.pth",
            }
        }
    )
    assert result == {
        "enabled": True,
        "engine": "pymss",
        "pymss_model": "voc.ckpt",
        "harmony_removal_enabled": True,
        "harmony_model": "bve.pth",
    }


def test_harmony_is_disabled_when_preprocessing_is_disabled() -> None:
    enabled, engine, model, harmony, harmony_model = ConversionService._preprocess_settings(
        {
            "preprocess": {
                "enabled": False,
                "engine": "pymss",
                "harmony_removal_enabled": True,
            }
        }
    )
    assert (enabled, engine, model, harmony) == (
        False,
        "pymss",
        config.PYMSS_DEFAULT_MODEL,
        False,
    )
    assert harmony_model == config.PYMSS_DEFAULT_HARMONY_MODEL


def test_pipeline_steps_include_harmony_only_when_requested() -> None:
    assert [step["key"] for step in default_steps(harmony_removal=True)][:3] == [
        "separate",
        "harmony",
        "repair_input",
    ]
    assert [step["key"] for step in default_steps_multi(harmony_removal=True)][:3] == [
        "separate",
        "harmony",
        "repair_input",
    ]
