"""运行日志的多语言输出（写入磁盘的日志本身要可读）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain import log_text


def test_all_rules_compile_for_every_locale() -> None:
    """占位符与捕获组必须一一对应，否则规则会被静默跳过。"""
    assert len(log_text._COMPILED["en-US"]) == len(log_text._EN_RULES)
    assert len(log_text._COMPILED["ja-JP"]) == len(log_text._JA_RULES)


def test_normalize_locale() -> None:
    assert log_text.normalize_locale("en-US") == "en-US"
    assert log_text.normalize_locale("ja-JP") == "ja-JP"
    assert log_text.normalize_locale("fr-FR") == "zh-CN"
    assert log_text.normalize_locale(None) == "zh-CN"


def test_chinese_logs_are_unchanged() -> None:
    line = "  [1/11] 输入音频 开始"
    assert log_text.translate_line(line, "zh-CN") == line
    assert log_text.translate_log_text(line, "zh-CN") == line


def test_static_and_parameterized_lines() -> None:
    assert log_text.translate_line("任务完成 ✅", "en-US") == "Task complete ✅"
    assert (
        log_text.translate_line("  模型推理完成", "en-US") == "  Model inference complete"
    )
    assert (
        log_text.translate_line("源文件: a.wav | 时长: 12.3s | 设备: cuda:0", "en-US")
        == "Source: a.wav | Duration: 12.3s | Device: cuda:0"
    )
    assert (
        log_text.translate_line("  变调 +2 半音", "en-US") == "  Pitch shift +2 semitones"
    )
    assert (
        log_text.translate_line("合唱叠加 2 路转换人声", "ja-JP")
        == "ハモリ重ね：変換済みボーカル 2 系統"
    )


def test_log_header_lines() -> None:
    header = "\n".join(
        [
            "=== My Mix (自定义工作流) ===",
            "开始时间: 2026-11-13T21:33:39",
            "工作流: My Flow",
            "参数: {'pitch': 0}",
        ]
    )
    assert log_text.translate_log_text(header, "en-US").split("\n") == [
        "=== My Mix (custom workflow) ===",
        "Started at: 2026-11-13T21:33:39",
        "Workflow: My Flow",
        "Parameters: {'pitch': 0}",
    ]
    assert log_text.translate_log_text(header, "ja-JP").split("\n") == [
        "=== My Mix（カスタムワークフロー）===",
        "開始時間：2026-11-13T21:33:39",
        "ワークフロー：My Flow",
        "パラメータ：{'pitch': 0}",
    ]


def test_user_data_and_unknown_lines_are_kept() -> None:
    # 作品名 / 路径不能被翻译，否则日志对不上真实文件
    line = r"  源音频: D:\music\海棠花.mp3 → D:\works\wrk_1\source.wav"
    translated = log_text.translate_line(line, "en-US")
    assert translated.endswith(r"D:\works\wrk_1\source.wav")
    assert "海棠花" in translated

    unknown = "  这条日志还没有词条"
    assert log_text.translate_line(unknown, "en-US") == unknown


def test_translation_is_idempotent() -> None:
    translated = log_text.translate_line("[1/11] 输入音频 开始", "en-US")
    assert log_text.translate_line(translated, "en-US") == translated


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("[2/11] 人声分离 开始", "[2/11] Vocal separation started"),
        ("[3/11] 歌声转换 开始", "[3/11] Voice conversion started"),
        ("[11/11] 输出成品 开始", "[11/11] Final output started"),
    ],
)
def test_workflow_node_start_lines(line: str, expected: str) -> None:
    assert log_text.translate_line(line, "en-US") == expected
