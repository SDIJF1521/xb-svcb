from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_helper_module():
    helper_path = (
        Path(__file__).resolve().parents[2] / "install" / "configure_user_env.py"
    )
    spec = importlib.util.spec_from_file_location("xb_configure_user_env", helper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_user_path_preserves_special_values_and_adds_once() -> None:
    helper = _load_helper_module()
    current = (
        r"C:\Tools;%DevEco Studio%;C:\Program Files\Existing;;"
        r"C:\Program Files (x86)\Microsoft Visual Studio\BuildTools"
    )

    merged, added, existing = helper.merge_user_path(
        current,
        [
            "c:\\program files\\existing\\",
            r"C:\Program Files (x86)\New Tool",
        ],
    )

    assert merged.startswith(current)
    assert "%DevEco Studio%" in merged
    assert added == [r"C:\Program Files (x86)\New Tool"]
    assert existing == ["c:\\program files\\existing\\"]
    assert merged.endswith(r"C:\Program Files (x86)\New Tool")
