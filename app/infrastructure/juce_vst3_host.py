"""连接到编辑器插件机架所使用的原生 JUCE VST3 主机。"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import config


class JuceVst3Host:
    """用于 C++ JUCE VST3 主机的轻量级处理桥。

    C++端负责所有VST3/插件UI相关的工作。Python会生成一个JSON请求，
    并通过以下命令之一调用主机：

    - render <request.json>``：将输入的 WAV 文件离线处理为输出的 WAV 文件。
    - show-editor <request.json>：在原生窗口中打开插件编辑器界面。
    - inspect <request.json>：以 JSON 格式输出插件元数据/参数

    请求使用模式 ``xb-svcb.juce-vst3-host.v1`` 和协议版本 1。
    """

    _sessions: dict[str, dict[str, Any]] = {}

    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable or config.JUCE_VST3_HOST_EXE

    def status(self) -> dict[str, Any]:
        path = str(self.executable)
        ready = bool(self.executable and self.executable.exists())
        return {
            "ok": ready,
            "ready": ready,
            "host_path": path,
            "protocol": config.JUCE_VST3_HOST_PROTOCOL,
            "schema": "xb-svcb.juce-vst3-host.v1",
            "message": "JUCE VST3 Host 已就绪" if ready else "未找到 JUCE VST3 Host",
        }

    def render_plugin(
        self,
        src: Path,
        dst: Path,
        effect: dict[str, Any],
        sample_rate: int,
    ) -> bool:
        if not self._ready() or not src.exists():
            return False
        params = self._effect_params(effect)
        plugin_path = self._plugin_path(params)
        if plugin_path is None:
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        request_path = dst.with_suffix(dst.suffix + ".juce-request.json")
        payload = self._base_payload("render", params)
        payload.update(
            {
                "input": str(src),
                "output": str(dst),
                "sample_rate": int(sample_rate or 44100),
                "block_size": int(params.get("block_size") or 512),
            }
        )
        self._write_request(request_path, payload)
        try:
            res = subprocess.run(
                [str(self.executable), "render", str(request_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(120, min(1800, int(self._duration_timeout(src)))),
                **config.subprocess_no_window(),
            )
            return res.returncode == 0 and dst.exists()
        except (OSError, subprocess.SubprocessError):
            return False

    def inspect_plugin(self, plugin_path: str) -> dict[str, Any]:
        if not self._ready():
            return {"ok": False, "error": "JUCE VST3 Host 未就绪", **self.status()}
        path = Path(str(plugin_path or ""))
        if not path.exists():
            return {"ok": False, "error": "插件文件不存在", **self.status()}
        request_path = config.EDITOR_CACHE_DIR / f"juce_inspect_{uuid.uuid4().hex}.json"
        self._write_request(
            request_path,
            {
                "schema": "xb-svcb.juce-vst3-host.v1",
                "protocol": config.JUCE_VST3_HOST_PROTOCOL,
                "command": "inspect",
                "plugin": {"path": str(path)},
            },
        )
        try:
            res = subprocess.run(
                [str(self.executable), "inspect", str(request_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": str(exc), **self.status()}
        if res.returncode != 0:
            error = (res.stderr or "插件检查失败").strip()
            try:
                payload = json.loads(res.stdout or "{}")
                error = str(payload.get("error") or error)
            except (json.JSONDecodeError, AttributeError):
                pass
            return {"ok": False, "error": error, **self.status()}
        try:
            payload = json.loads(res.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload.get("ok") is False:
            return {"ok": False, "error": str(payload.get("error") or "插件检查失败"), **self.status()}
        plugin = payload.get("plugin") if isinstance(payload, dict) else payload
        return {"ok": True, **self.status(), "plugin": plugin if isinstance(plugin, dict) else {}}

    def show_editor(
        self,
        effect: dict[str, Any],
        *,
        project_id: str = "",
        clip_id: str = "",
        effect_id: str = "",
        parent_window: str = "",
    ) -> dict[str, Any]:
        if not self._ready():
            return {"ok": False, "error": "JUCE VST3 Host 未就绪", **self.status()}
        params = self._effect_params(effect)
        plugin_path = self._plugin_path(params)
        if plugin_path is None:
            return {"ok": False, "error": "插件文件不存在", **self.status()}
        session_id = uuid.uuid4().hex
        request_path = config.EDITOR_CACHE_DIR / f"juce_gui_{session_id}.json"
        state_path = config.EDITOR_CACHE_DIR / f"juce_state_{session_id}.json"
        payload = self._base_payload("show-editor", params)
        payload.update(
            {
                "session_id": session_id,
                "project_id": project_id,
                "clip_id": clip_id,
                "effect_id": effect_id,
                "parent_window": parent_window,
                "state_output": str(state_path),
            }
        )
        self._write_request(request_path, payload)
        try:
            proc = subprocess.Popen(
                [str(self.executable), "show-editor", str(request_path)],
                text=True,
                encoding="utf-8",
                errors="replace",
                **config.subprocess_no_window(),
            )
            self._sessions[session_id] = {"proc": proc, "state_path": state_path}
        except OSError as exc:
            return {"ok": False, "error": str(exc), **self.status()}
        return {"ok": True, "session_id": session_id, "state_path": str(state_path), **self.status()}

    def close_editor(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id or "", None)
        if not session:
            return {"ok": False, "closed": False, "error": "插件窗口会话不存在", **self.status()}
        proc = session.get("proc")
        state_path = session.get("state_path")
        try:
            if isinstance(proc, subprocess.Popen) and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except OSError as exc:
            return {"ok": False, "closed": False, "error": str(exc), **self.status()}
        state = self._read_state(Path(state_path)) if state_path else {}
        return {
            "ok": True,
            "closed": True,
            "state_path": str(state_path or ""),
            **self.status(),
            **state,
        }

    def sync_editor(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id or "")
        if not session:
            return {"ok": False, "error": "插件窗口会话不存在", **self.status()}
        state_path = session.get("state_path")
        state = self._read_state(Path(state_path)) if state_path else {}
        return {"ok": True, "state_path": str(state_path or ""), **self.status(), **state}

    @staticmethod
    def _read_state(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        plugin = payload.get("plugin")
        return {"plugin": plugin} if isinstance(plugin, dict) else {}

    def _ready(self) -> bool:
        return bool(self.executable and self.executable.exists())

    def _base_payload(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        plugin_path = self._plugin_path(params)
        plugin_params = params.get("parameters")
        return {
            "schema": "xb-svcb.juce-vst3-host.v1",
            "protocol": config.JUCE_VST3_HOST_PROTOCOL,
            "command": command,
            "plugin": {
                "path": str(plugin_path) if plugin_path else "",
                "name": str(params.get("plugin_name") or ""),
                "state": str(params.get("state") or ""),
                "parameters": plugin_params if isinstance(plugin_params, dict) else {},
            },
        }

    @staticmethod
    def _write_request(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _effect_params(effect: dict[str, Any]) -> dict[str, Any]:
        params = effect.get("params")
        merged = dict(params) if isinstance(params, dict) else {}
        for key, value in effect.items():
            if key not in {"id", "type", "enabled", "params", "name"}:
                merged.setdefault(key, value)
        return merged

    @staticmethod
    def _plugin_path(params: dict[str, Any]) -> Path | None:
        raw = params.get("path") or params.get("plugin_path")
        if not raw:
            return None
        path = Path(str(raw))
        return path if path.exists() else None

    @staticmethod
    def _duration_timeout(src: Path) -> int:
        try:
            size_mb = src.stat().st_size / (1024 * 1024)
        except OSError:
            size_mb = 1
        return int(120 + size_mb * 6)
