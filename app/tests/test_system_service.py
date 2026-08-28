from unittest.mock import patch

from application.system_service import SystemService


class _Tool:
    def __init__(self, available: bool, status: str = "未安装") -> None:
        self.available = available
        self._status = status

    def status(self) -> str:
        return self._status

    def version(self) -> str | None:
        return "test" if self.available else None


def _capabilities(*, svc_ok: bool) -> dict:
    runtime = {
        "ok": svc_ok,
        "preferred": "cpu",
        "backends": ["cpu"] if svc_ok else [],
        "devices": [],
    }
    return {
        "preferred": "cpu",
        "options": [],
        "frameworks": {
            "uvr": dict(runtime),
            "so-vits-svc": dict(runtime),
            "rvc": dict(runtime),
            "seed-vc": dict(runtime),
            "ddsp-svc": dict(runtime),
        },
    }


def test_optional_components_do_not_make_global_status_degraded() -> None:
    service = SystemService(
        ffmpeg=_Tool(True),
        uvr=_Tool(False, "模型未就绪"),
        svc=_Tool(True),
        pymss=_Tool(False, "未找到 .venv-pymss"),
        vocal_enhancement=_Tool(False),
    )

    with patch(
        "application.system_service.inference_device_capabilities",
        return_value=_capabilities(svc_ok=True),
    ):
        result = service.status()

    assert result["ready"] is True
    assert result["tools"]
    assert all(tool.get("required") is False for tool in result["tools"] if tool["key"] != "ffmpeg")
    assert next(tool for tool in result["tools"] if tool["key"] == "ffmpeg")["required"] is True


def test_runtime_probe_failure_is_not_reported_as_ready() -> None:
    service = SystemService(
        ffmpeg=_Tool(True),
        uvr=_Tool(False),
        svc=_Tool(True),
    )

    with patch(
        "application.system_service.inference_device_capabilities",
        return_value={
            **_capabilities(svc_ok=False),
            "frameworks": {
                **_capabilities(svc_ok=False)["frameworks"],
                "so-vits-svc": {
                    "ok": False,
                    "preferred": "cpu",
                    "backends": ["cpu"],
                    "devices": [],
                    "error": "torch 导入失败",
                },
            },
        },
    ):
        result = service.status()

    assert result["ready"] is False
    svc = next(tool for tool in result["tools"] if tool["key"] == "svc")
    assert svc["ok"] is False
    assert "torch 导入失败" in svc["status"]


def test_pymss_missing_model_explains_that_environment_is_ready() -> None:
    service = SystemService(
        ffmpeg=_Tool(True),
        uvr=_Tool(False),
        svc=_Tool(True),
        pymss=_Tool(True, "模型未下载"),
    )

    with patch(
        "application.system_service.inference_device_capabilities",
        return_value=_capabilities(svc_ok=True),
    ):
        result = service.status()

    pymss = next(tool for tool in result["tools"] if tool["key"] == "pymss")
    assert pymss["ok"] is False
    assert "环境已就绪" in pymss["status"]
    assert "模型管理页" in pymss["status"]
