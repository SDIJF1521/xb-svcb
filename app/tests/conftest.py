"""Test layers are selectable; unavailable integration inputs are reported explicitly."""
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-model-inference", action="store_true", default=False,
                     help="Explicitly enable tests marked model_inference")
    parser.addoption("--require-packaging-inputs", action="store_true", default=False,
                     help="Fail packaging integration checks instead of skipping missing engine sources")


def pytest_collection_modifyitems(config, items):
    runtime_files = {
        "test_core_compat.py", "test_core_recipe.py", "test_runtime_manifest.py", "test_runtime_audit.py",
        "test_inference_devices.py", "test_inference_naturalizer.py", "test_inference_regressions.py",
        "test_seedvc_worker.py", "test_ddsp_support.py", "test_rvc_directml.py",
        "test_uvr_status.py", "test_persistent_worker.py", "test_vocal_enhancement.py",
    }
    for item in items:
        filename = Path(str(item.path)).name
        if "wheelhouse" in item.name or filename == "test_wheelhouse_plan.py":
            item.add_marker(pytest.mark.packaging)
        elif filename in runtime_files:
            item.add_marker(pytest.mark.runtime)
        elif filename.startswith("test_install") or filename == "test_configure_user_env.py":
            item.add_marker(pytest.mark.installer)
        if item.get_closest_marker("model_inference") and not config.getoption("--run-model-inference"):
            item.add_marker(pytest.mark.skip(reason="Real inference deferred; use --run-model-inference with model/audio fixtures"))
