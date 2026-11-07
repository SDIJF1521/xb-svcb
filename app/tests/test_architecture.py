"""架构约束测试（可执行的 DDD 分层契约）。

对应文档：``docs/ddd-architecture.md``。

这里用 AST 静态分析 ``app/`` 的 import，把分层规则变成会被 CI 拒绝的红线：

* ``domain`` 只能依赖标准库与自身，不依赖任何框架、配置或外层；
* ``application`` 不得 import ``api`` / ``infrastructure`` / ``composition``；
* ``infrastructure`` 不得 import ``api`` / ``application``；
* ``api`` 不得 import ``infrastructure`` / ``composition``；
* 应用层只有 ``application/adapters.py`` 允许在函数体内延迟 import 基础设施
  （组合根未注入时的默认适配器接缝）。

另外用 ``runtime_checkable`` 协议校验真实适配器是否仍然满足端口契约，
避免端口与实现悄悄漂移。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

LAYERS = ("api", "application", "infrastructure", "domain")
# 允许在模块级 import infrastructure 的门外模块（组合根与入口）。
COMPOSITION_MODULES = {"composition.py", "main.py"}
# 应用层中可以延迟 import 基础设施的唯一接缝。
DEFAULT_ADAPTER_MODULE = APP_DIR / "application" / "adapters.py"

FRAMEWORK_MODULES = {
    "fastapi",
    "starlette",
    "uvicorn",
    "webview",
    "pywebview",
    "httpx",
    "yaml",
    "soundcard",
    "numpy",
    "scipy",
}


def _layer_files(layer: str) -> list[Path]:
    return sorted((APP_DIR / layer).glob("*.py"))


def _module_name(path: Path) -> str:
    return f"{path.parent.name}.{path.stem}"


def _resolve_from(path: Path, node: ast.ImportFrom) -> str | None:
    """把 ``from .x import y`` / ``from pkg import y`` 解析成顶层模块名。"""
    if node.level:
        parts = _module_name(path).split(".")
        base = parts[: -node.level]
        module = ".".join(base + ([node.module] if node.module else []))
        return module
    return node.module


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """返回 (模块级 import 的顶层模块集合, 函数内 import 的顶层模块集合)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_level: set[str] = set()
    deferred: set[str] = set()

    def record(node: ast.AST, bucket: set[str]) -> None:
        if isinstance(node, ast.ImportFrom):
            target = _resolve_from(path, node)
            if target:
                bucket.add(target.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bucket.add(alias.name.split(".")[0])

    for node in tree.body:
        record(node, module_level)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    record(child, deferred)
    return module_level, deferred


def _assert_no_imports(
    paths: list[Path],
    forbidden: set[str],
    reason: str,
    *,
    check_deferred: bool = False,
    deferred_allowlist: set[Path] | None = None,
) -> None:
    allowlist = deferred_allowlist or set()
    violations: list[str] = []
    for path in paths:
        module_level, deferred = _imports(path)
        for name in sorted(module_level & forbidden):
            violations.append(f"{path.relative_to(APP_DIR)} 模块级 import {name}：{reason}")
        if check_deferred and path not in allowlist:
            for name in sorted(deferred & forbidden):
                violations.append(f"{path.relative_to(APP_DIR)} 函数内延迟 import {name}：{reason}")
    assert not violations, "架构约束被破坏：\n" + "\n".join(violations)


def test_domain_is_framework_free() -> None:
    """领域层是内核：只允许标准库与 domain 自身。"""
    _assert_no_imports(
        _layer_files("domain"),
        {"application", "infrastructure", "api", "composition", "config"},
        "领域层不得依赖外层或全局配置",
        check_deferred=True,
    )
    _assert_no_imports(
        _layer_files("domain"),
        FRAMEWORK_MODULES,
        "领域层不得依赖三方框架",
        check_deferred=True,
    )


def test_application_does_not_depend_on_adapters_or_presentation() -> None:
    """用例层只通过端口依赖外部能力，不直接依赖适配器与表现层。"""
    _assert_no_imports(
        _layer_files("application"),
        {"infrastructure", "api", "composition"},
        "用例层不得 import 基础设施、表现层或组合根（应依赖 application.ports）",
        check_deferred=True,
        deferred_allowlist={DEFAULT_ADAPTER_MODULE},
    )


def test_infrastructure_does_not_depend_on_application_or_presentation() -> None:
    """适配层实现端口，不允许反向依赖用例层与表现层。"""
    _assert_no_imports(
        _layer_files("infrastructure"),
        {"application", "api", "composition"},
        "基础设施层不得依赖用例层或表现层",
        check_deferred=True,
    )


def test_presentation_does_not_depend_on_infrastructure() -> None:
    """表现层只调用用例服务，基础设施由组合根注入。"""
    _assert_no_imports(
        _layer_files("api"),
        {"infrastructure", "composition"},
        "表现层不得 import 基础设施或组合根（依赖应由 composition 注入）",
        check_deferred=True,
    )


def test_only_composition_and_entry_touch_infrastructure() -> None:
    """app 根目录下只有组合根与入口可以装配基础设施。"""
    offenders: list[str] = []
    for path in sorted(APP_DIR.glob("*.py")):
        if path.name in COMPOSITION_MODULES:
            continue
        module_level, _ = _imports(path)
        if "infrastructure" in module_level:
            offenders.append(path.name)
    assert not offenders, f"只有组合根可以 import infrastructure，违规模块：{offenders}"


def test_default_adapter_seam_is_documented() -> None:
    """默认适配器接缝必须保持“函数内延迟导入”，不得污染模块级依赖。"""
    assert DEFAULT_ADAPTER_MODULE.is_file(), "缺少 application/adapters.py 接缝"
    module_level, deferred = _imports(DEFAULT_ADAPTER_MODULE)
    assert "infrastructure" not in module_level, (
        "application/adapters.py 不得在模块级 import infrastructure（会导致应用层加载即依赖适配层）"
    )
    assert "infrastructure" in deferred, (
        "application/adapters.py 应通过函数内延迟导入提供默认适配器"
    )


def test_presentation_does_not_reach_into_private_members() -> None:
    """HTTP 层通过公开方法访问桥接门面，不直接读取 facade 的私有成员。"""
    source = (APP_DIR / "api" / "http_server.py").read_text(encoding="utf-8")
    offenders = sorted(
        {
            line.strip()
            for line in source.splitlines()
            if "facade._" in line
        }
    )
    assert not offenders, (
        "HTTP 层不得访问 facade 私有成员，请在 Api 上提供公开方法：\n"
        + "\n".join(offenders)
    )


# ---- 端口与实现的契约 ----

PORT_ADAPTERS = [
    ("infrastructure.ffmpeg_tool", "FfmpegTool", "FfmpegGateway"),
    ("infrastructure.uvr_tool", "UvrTool", "SeparationGateway"),
    ("infrastructure.pymss_tool", "PymssTool", "PymssGateway"),
    ("infrastructure.storage", "ListRepository", "ItemRepository"),
    ("infrastructure.storage", "SettingsStore", "SettingsRepository"),
    ("infrastructure.svc_engine", "SvcEngine", "ToolAdapter"),
    ("infrastructure.vocal_enhancement", "VocalEnhancementProcessor", "VocalEnhancementPort"),
    ("infrastructure.high_note_vocoder", "HighNoteVocoderProcessor", "HighNoteVocoderPort"),
    ("infrastructure.juce_vst3_host", "JuceVst3Host", "PluginHostPort"),
    ("infrastructure.audio_engine", "FFmpegEngine", "AudioEnginePort"),
    ("infrastructure.engine", "EngineRegistry", "EngineRegistryPort"),
    ("infrastructure.theme_media", "ThemeMediaStore", "ThemeMediaStorePort"),
    ("infrastructure.audio_import", "AudioImportStore", "AudioImportStorePort"),
    ("infrastructure.work_files", "WorkFiles", "WorkFilesPort"),
    ("infrastructure.editor_project_store", "EditorProjectStore", "EditorProjectStorePort"),
]


def _protocol_members(protocol: type) -> set[str]:
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    members |= {name for name in dir(protocol) if not name.startswith("_")}
    return members


@pytest.mark.parametrize(("module", "attr", "port"), PORT_ADAPTERS)
def test_adapter_satisfies_port(module: str, attr: str, port: str) -> None:
    """真实适配器必须结构化满足应用层端口协议。

    这里按“类上是否存在协议要求的属性”校验，避免实例化适配器带来环境探测副作用。
    """
    import importlib

    ports = importlib.import_module("application.ports")
    target = getattr(importlib.import_module(module), attr)
    protocol = getattr(ports, port)
    missing = sorted(
        name for name in _protocol_members(protocol) if not hasattr(target, name)
    )
    assert not missing, (
        f"{module}.{attr} 未满足端口 {port}，缺失：{missing}；"
        "请同步更新 application/ports.py 或适配器实现"
    )
