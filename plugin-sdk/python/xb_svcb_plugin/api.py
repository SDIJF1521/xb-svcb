"""Small, dependency-free API used by Python and hybrid plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


Handler = Callable[..., Any]
_active_plugin: "Plugin | None" = None


@dataclass(slots=True)
class ActionResult:
    """A result understood by the XB-SVCB plugin page."""

    type: str = "message"
    message: str = ""
    payload: dict[str, Any] | None = None

    @classmethod
    def message_result(cls, message: str) -> "ActionResult":
        return cls(type="message", message=message)

    @classmethod
    def create_work(cls, payload: dict[str, Any]) -> "ActionResult":
        return cls(type="create_work", payload=payload)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"type": self.type}
        if self.message:
            value["message"] = self.message
        if self.payload is not None:
            value["payload"] = self.payload
        return value


@dataclass(slots=True)
class PluginContext:
    """Runtime information and persistent JSON configuration for one plugin."""

    plugin_id: str
    plugin_dir: Path
    data_dir: Path
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, plugin_id: str, plugin_dir: str, data_dir: str) -> "PluginContext":
        storage = Path(data_dir).resolve()
        storage.mkdir(parents=True, exist_ok=True)
        config_path = storage / "config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
        return cls(
            plugin_id=plugin_id,
            plugin_dir=Path(plugin_dir).resolve(),
            data_dir=storage,
            config=config if isinstance(config, dict) else {},
        )

    def save_config(self) -> None:
        target = self.data_dir / "config.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)


class Plugin:
    """Registry for a Python plugin's actions and lifecycle hooks."""

    def __init__(self, plugin_id: str) -> None:
        global _active_plugin
        self.id = plugin_id
        self.actions: dict[str, Handler] = {}
        self.hooks: dict[str, list[Handler]] = {}
        _active_plugin = self

    def action(self, name: str | None = None) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.actions[name or func.__name__] = func
            return func

        return decorator

    def hook(self, name: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.hooks.setdefault(name, []).append(func)
            return func

        return decorator

    def before_create(self, func: Handler) -> Handler:
        return self.hook("before_create")(func)

    def on_enable(self, func: Handler) -> Handler:
        return self.hook("on_enable")(func)

    def on_disable(self, func: Handler) -> Handler:
        return self.hook("on_disable")(func)


def get_plugin() -> Plugin:
    if _active_plugin is None:
        raise RuntimeError("插件入口必须先创建 Plugin(plugin_id)")
    return _active_plugin


def action(name: str | None = None) -> Callable[[Handler], Handler]:
    return get_plugin().action(name)


def before_create(func: Handler) -> Handler:
    return get_plugin().before_create(func)
