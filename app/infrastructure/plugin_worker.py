"""Load one trusted Python plugin and execute a requested action or hook.

The worker receives one JSON request on stdin and emits one JSON response on stdout.
It runs outside the desktop process for crash isolation, but it is not a security sandbox.
"""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
import sys
import traceback
from pathlib import Path
from typing import Any


def _load_sdk(sdk_path: str) -> Path:
    path = Path(sdk_path).resolve()
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path


def _load_module(
    entry: Path,
    plugin_root: Path,
    sdk_path: Path,
    vendor_path: Path | None = None,
):
    module_dir = entry.parent
    vendor = vendor_path or (plugin_root / "vendor")
    # Keep the host SDK first even when a plugin accidentally ships an older
    # xb_svcb_plugin in vendor/. Then expose both package and legacy sibling
    # imports without relying on the process working directory.
    ordered = [sdk_path, module_dir, plugin_root]
    if vendor.is_dir():
        ordered.append(vendor)
    wanted = [str(path) for path in ordered]
    sys.path[:] = wanted + [path for path in sys.path if path not in wanted]
    package_paths = [str(entry.parent)] if entry.name == "__init__.py" else None
    spec = importlib.util.spec_from_file_location(
        "xb_user_plugin", entry, submodule_search_locations=package_paths
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载插件入口：{entry}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # 插件中的 print 进入 stderr，避免污染 stdout 上的 JSON 协议。
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
    return module


async def _call(handler, *args):  # noqa: ANN001
    with redirect_stdout(sys.stderr):
        value = handler(*args)
        if inspect.isawaitable(value):
            value = await value
    return value


def _normalise_result(value: Any) -> dict[str, Any]:
    from xb_svcb_plugin import ActionResult

    if isinstance(value, ActionResult):
        return value.to_dict()
    if value is None:
        return {}
    if isinstance(value, str):
        return {"type": "message", "message": value}
    if isinstance(value, dict):
        return value
    raise TypeError("插件返回值必须是 dict、str、ActionResult 或 None")


async def _run(request: dict[str, Any]) -> dict[str, Any]:
    sdk_path = _load_sdk(str(request["sdk_path"]))
    from xb_svcb_plugin import PluginContext, get_plugin

    entry = Path(str(request["entry"])).resolve()
    plugin_dir = Path(str(request["plugin_dir"])).resolve()
    if plugin_dir not in entry.parents or not entry.is_file():
        raise RuntimeError("Python 入口不在插件目录内或不存在")
    vendor_raw = str(request.get("vendor_path") or "").strip()
    vendor = Path(vendor_raw).resolve() if vendor_raw else plugin_dir / "vendor"
    if plugin_dir not in vendor.parents and vendor != plugin_dir:
        raise RuntimeError("Python vendor 路径不在插件目录内")
    _load_module(entry, plugin_dir, sdk_path, vendor)
    plugin = get_plugin()
    expected_id = str(request["plugin_id"])
    if plugin.id != expected_id:
        raise RuntimeError(f"Python Plugin ID 不匹配：期望 {expected_id}，实际 {plugin.id}")
    context = PluginContext.create(
        expected_id, str(plugin_dir), str(request["data_dir"])
    )
    operation = str(request.get("operation") or "")
    if operation == "action":
        name = str(request.get("name") or "")
        handler = plugin.actions.get(name)
        if handler is None:
            raise RuntimeError(f"未注册 Python 动作：{name}")
        result = await _call(handler, context, request.get("values") or {})
        return _normalise_result(result)
    if operation == "hook":
        name = str(request.get("name") or "")
        payload = request.get("payload") or {}
        for handler in plugin.hooks.get(name, []):
            next_value = await _call(handler, context, payload)
            if next_value is not None:
                if not isinstance(next_value, dict):
                    raise TypeError(f"钩子 {name} 必须返回 dict 或 None")
                payload = next_value
        return {"payload": payload}
    if operation == "lifecycle":
        name = str(request.get("name") or "")
        for handler in plugin.hooks.get(name, []):
            await _call(handler, context)
        return {}
    if operation == "inspect":
        return {
            "actions": sorted(plugin.actions),
            "hooks": sorted(plugin.hooks),
        }
    raise RuntimeError(f"未知 Worker 操作：{operation}")


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        result = asyncio.run(_run(request))
        response = {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - boundary must serialize plugin errors
        response = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=12),
        }
    try:
        encoded = json.dumps(response, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        encoded = json.dumps({
            "ok": False,
            "error": f"Python 插件返回值无法序列化：{exc}",
        }, ensure_ascii=False)
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
