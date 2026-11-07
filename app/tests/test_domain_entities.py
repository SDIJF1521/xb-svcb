"""领域实体与领域规则的单测（domain/entities.py）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config
from domain import (
    FRAMEWORK_DEFAULT,
    ModelInfo,
    PipelineStep,
    StepStatus,
    apply_step_status,
    guess_framework,
    normalize_framework,
)
from application.conversion_service import default_steps, default_steps_ai_enhancement


def test_normalize_framework_prefers_explicit_and_accepts_unknown_bucket() -> None:
    assert normalize_framework("rvc", "So-VITS") == "rvc"
    assert normalize_framework("RVC") == "rvc"
    assert normalize_framework("other") == "other"
    assert normalize_framework("bogus", "SeedVC") == "seed-vc"
    assert normalize_framework(None, "DDSP-SVC") == "ddsp-svc"
    assert normalize_framework("") == FRAMEWORK_DEFAULT


def test_guess_framework_matches_model_type_vocabulary() -> None:
    assert guess_framework("So-VITS") == "so-vits-svc"
    assert guess_framework("SVC") == "so-vits-svc"
    assert guess_framework("rvc") == "rvc"
    assert guess_framework("SeedVC") == "seed-vc"
    assert guess_framework("DDSP-SVC") == "ddsp-svc"
    assert guess_framework(None) == FRAMEWORK_DEFAULT


def test_config_and_domain_share_one_framework_rule() -> None:
    # config 面向 UI 的入口委托给领域规则，避免两套判定漂移。
    for value in ("so-vits-svc", "RVC", "seed-vc", "ddsp-svc", "other", "bogus", ""):
        assert config.modelhub_normalize_framework(value) == normalize_framework(value)
    for model_type in ("So-VITS", "SVC", "rvc", "SeedVC", "DDSP-SVC", None):
        assert config.modelhub_guess_framework(model_type) == guess_framework(model_type)


def test_model_info_engine_paths_flattens_the_aggregate() -> None:
    record = {
        "id": "mdl_1",
        "name": "测试模型",
        "type": "RVC",
        "main_model": {"name": "a.pth", "path": "/m/a.pth"},
        "main_config": {"name": "config.json", "path": "/m/config.json"},
        "index_file": {"name": "a.index", "path": "/m/a.index"},
    }
    paths = ModelInfo.from_dict(record).engine_paths()

    assert paths == {
        "framework": "rvc",
        "main_model_path": "/m/a.pth",
        "main_config_path": "/m/config.json",
        "diffusion_model_path": "",
        "diffusion_config_path": "",
        "index_path": "/m/a.index",
    }


def test_model_info_from_dict_tolerates_partial_records() -> None:
    info = ModelInfo.from_dict({"framework": "seed-vc"})

    assert info.id == ""
    assert info.name == ""
    assert info.main_model.path == ""
    assert info.type == "SVC"
    assert info.engine_paths()["framework"] == "seed-vc"


def test_model_info_engine_paths_infers_framework_from_type() -> None:
    info = ModelInfo.from_dict({"id": "m", "name": "n", "type": "DDSP-SVC"})
    assert info.engine_paths()["framework"] == "ddsp-svc"


def test_pipeline_step_starts_in_wait_state() -> None:
    step = PipelineStep(key="infer", label="模型推理")
    assert step.to_dict() == {"key": "infer", "label": "模型推理", "status": "wait"}


def test_apply_step_status_updates_only_the_matching_step() -> None:
    steps = [PipelineStep("f0", "F0 提取").to_dict(), PipelineStep("mix", "混音合成").to_dict()]

    assert apply_step_status(steps, "mix", StepStatus.DONE) is True
    assert steps[1]["status"] == "done"
    assert steps[0]["status"] == "wait"
    assert apply_step_status(steps, "missing", StepStatus.DONE) is False
    with pytest.raises(ValueError):
        apply_step_status(steps, "mix", "bogus")


def test_default_pipeline_steps_come_from_the_entity() -> None:
    steps = default_steps(enhancement=True, preprocess=True, harmony_removal=True)
    assert [step["key"] for step in steps] == [
        "separate",
        "harmony",
        "repair_input",
        "f0",
        "infer",
        "repair_output",
        "enhance",
        "mix",
    ]
    assert all(step["status"] == StepStatus.WAIT.value for step in steps)
    assert all(isinstance(step["label"], str) and step["label"] for step in steps)

    ai_steps = default_steps_ai_enhancement()
    assert [step["key"] for step in ai_steps] == ["reference", "cover_vocal", "enhance", "mix"]
