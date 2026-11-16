"""任务创建请求规则（domain.work_request）的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from domain.work_request import (
    WorkRequestError,
    check_duplicate_model_ids,
    check_workflow_mode,
    default_title,
    normalize_segments,
    require_multi_selection,
    require_seedvc_reference,
)


def test_default_title_prefers_input_then_file_name_then_placeholder() -> None:
    assert default_title("我的歌", "/music/a.wav") == "我的歌"
    assert default_title("", "/music/song.flac") == "song"
    assert default_title(None, "") == "未命名翻唱"


def test_workflow_mode_rule_only_allows_multi_for_vocal_merge() -> None:
    check_workflow_mode("auto_mix", "single")
    check_workflow_mode("auto_vocal_merge", "multi")
    with pytest.raises(WorkRequestError) as excinfo:
        check_workflow_mode("auto_vocal_merge", "single")
    assert "只支持 multi" in str(excinfo.value)
    assert excinfo.value.not_found is False


def test_multi_selection_requires_models_and_segments() -> None:
    with pytest.raises(WorkRequestError):
        require_multi_selection([], [{"start": 0, "end": 1, "model_id": "a"}])
    with pytest.raises(WorkRequestError):
        require_multi_selection([{"model_id": "a"}], [])
    require_multi_selection([{"model_id": "a"}], [{"start": 0, "end": 1, "model_id": "a"}])


def test_duplicate_model_ids_are_rejected() -> None:
    check_duplicate_model_ids(["a", "b"])
    with pytest.raises(WorkRequestError) as excinfo:
        check_duplicate_model_ids(["a", "a"])
    assert "模型重复" in str(excinfo.value)


def test_segments_are_normalized_and_validated() -> None:
    segments = normalize_segments(
        [
            {"start": 0, "end": 1.5, "model_ids": ["a", "a", "b"]},
            {"start": 2, "end": 4, "model_id": "b"},
        ],
        {"a", "b"},
    )
    assert segments == [
        {"start": 0.0, "end": 1.5, "model_id": "a", "model_ids": ["a", "b"]},
        {"start": 2.0, "end": 4.0, "model_id": "b", "model_ids": ["b"]},
    ]

    with pytest.raises(WorkRequestError) as excinfo:
        normalize_segments([{"start": 3, "end": 3, "model_id": "a"}], {"a"})
    assert "必须大于 start" in str(excinfo.value)

    with pytest.raises(WorkRequestError) as missing:
        normalize_segments([{"start": 0, "end": 1, "model_id": "zzz"}], {"a"})
    assert "必须来自 models" in str(missing.value)


def test_seedvc_reference_requirement() -> None:
    seedvc = {"framework": "seed-vc"}
    require_seedvc_reference(seedvc, {"reference_audio": "/tmp/ref.wav"}, "需要参考音频")
    require_seedvc_reference({"framework": "rvc"}, {}, "需要参考音频")

    with pytest.raises(WorkRequestError) as excinfo:
        require_seedvc_reference(seedvc, {}, "SeedVC 模型 m1 需要 reference_upload_id")
    assert "reference_upload_id" in str(excinfo.value)
