"""用户扩展插件服务。

插件包是 zip（扩展名可为 .xbplugin），清单中的页面使用受限声明式组件渲染。
前端插件不会执行包内 JavaScript；Python 和混合插件则由独立 Worker 运行可信的
Python 入口，并继承当前用户权限。Worker 只提供崩溃隔离，不是安全沙箱。
"""

from __future__ import annotations

import base64
import copy
import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

import config
from infrastructure.storage import SettingsStore


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_MANIFEST_NAME = "xb-svcb-plugin.json"
_MAX_BUNDLE_BYTES = 20 * 1024 * 1024
_MAX_MANIFEST_BYTES = 512 * 1024
_MAX_UNPACKED_BYTES = 50 * 1024 * 1024
_MAX_FRONTEND_ENTRY_BYTES = 2 * 1024 * 1024
_MAX_FRONTEND_ASSET_BYTES = 10 * 1024 * 1024
_ALLOWED_COMPONENTS = {"text", "number", "select", "switch", "textarea"}
_ALLOWED_ACTIONS = {"message", "create_work", "python"}
_ALLOWED_RUNTIMES = {"frontend", "python", "hybrid"}
_ALLOWED_PERMISSIONS = {
    "python.execute", "filesystem.plugin", "filesystem.data", "network",
    "process", "environment",
}
_ALLOWED_PARAMS = {
    "pitch", "f0_method", "index_rate", "rms_mix", "uvr_model", "diffusion_ratio",
    "device", "protect", "filter_radius", "rvc_version", "ddsp_infer_steps",
    "ddsp_formant_shift", "speaker",
}


class PluginService:
    """安装、配置和执行可审计的声明式插件。"""

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings
        config.PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        config.PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self._settings.get("plugins_enabled", False)),
            "market_url": str(self._settings.get("plugin_market_url", "") or ""),
            "development_dir": str(config.PLUGINS_DIR),
            "security": "前端插件页面在沙箱 iframe 中运行，只能通过宿主通信 API 使用受控能力；Python/混合插件会以当前用户权限执行代码，仅应启用可信来源。",
        }

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "enabled" in payload:
            self._settings.set("plugins_enabled", bool(payload.get("enabled")))
        if "market_url" in payload:
            raw = str(payload.get("market_url") or "").strip()
            if raw and not self._is_github_url(raw):
                return {"ok": False, "error": "插件市场仅支持 GitHub HTTPS raw 或 API 地址。", **self.status()}
            self._settings.set("plugin_market_url", raw)
        return {"ok": True, **self.status()}

    def list(self) -> list[dict[str, Any]]:
        states = self._states()
        result: list[dict[str, Any]] = []
        for folder in sorted(config.PLUGINS_DIR.iterdir(), key=lambda item: item.name):
            if not folder.is_dir():
                continue
            manifest = self._read_manifest(folder / _MANIFEST_NAME)
            if not manifest:
                continue
            plugin_id = manifest["id"]
            state = states.get(plugin_id, {})
            result.append({
                **manifest,
                "installed": True,
                "enabled": bool(state.get("enabled", False)),
                "path": str(folder),
            })
        return result

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        plugin = self._plugin(plugin_id)
        if not plugin:
            return False
        states = self._states()
        was_enabled = bool(states.get(plugin_id, {}).get("enabled", False))
        if (
            enabled
            and not was_enabled
            and plugin.get("runtime") in {"python", "hybrid"}
        ):
            lifecycle = self._run_python(plugin, "lifecycle", "on_enable")
            if not lifecycle.get("ok"):
                return False
        states[plugin_id] = {**states.get(plugin_id, {}), "enabled": enabled}
        self._settings.set("plugin_states", states)
        if (
            not enabled
            and was_enabled
            and plugin.get("runtime") in {"python", "hybrid"}
        ):
            self._run_python(plugin, "lifecycle", "on_disable")
        return True

    def install_bundle(self, path: str) -> dict[str, Any]:
        source = Path(str(path or "")).expanduser()
        if not source.exists() or not source.is_file():
            return {"ok": False, "error": "插件包不存在。"}
        if source.stat().st_size > _MAX_BUNDLE_BYTES:
            return {"ok": False, "error": "插件包超过 20 MB 限制。"}
        try:
            with zipfile.ZipFile(source) as archive:
                if sum(member.file_size for member in archive.infolist()) > _MAX_UNPACKED_BYTES:
                    return {"ok": False, "error": "插件包解压后超过 50 MB 限制。"}
                manifest_member = self._manifest_member(archive)
                if not manifest_member:
                    return {"ok": False, "error": "插件包缺少 xb-svcb-plugin.json。"}
                raw = archive.read(manifest_member)
                manifest = self._parse_manifest(raw)
                if not manifest:
                    return {"ok": False, "error": "插件清单格式无效。"}
                target = config.PLUGINS_DIR / manifest["id"]
                staging = Path(tempfile.mkdtemp(prefix="xb-plugin-", dir=config.PLUGINS_DIR))
                try:
                    # 当前规范只读取清单，仍安全解压文档等资源以保留包的可检查性。
                    for member in archive.infolist():
                        destination = (staging / member.filename).resolve()
                        if staging.resolve() not in destination.parents and destination != staging.resolve():
                            raise ValueError("插件包包含非法路径")
                        if member.is_dir():
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as src, destination.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                    manifest_path = staging / manifest_member
                    if manifest_path.parent != staging:
                        # 支持单一顶级目录，安装时将其内容规范化到插件根目录。
                        normalized = Path(tempfile.mkdtemp(prefix="xb-plugin-", dir=config.PLUGINS_DIR))
                        shutil.copytree(manifest_path.parent, normalized, dirs_exist_ok=True)
                        shutil.rmtree(staging, ignore_errors=True)
                        staging = normalized
                    if target.exists():
                        shutil.rmtree(target)
                    frontend_entry = str(((manifest.get("frontend") or {}).get("entry") or "")).strip()
                    if frontend_entry and not self._safe_plugin_file(staging, frontend_entry, {".html", ".htm"}):
                        raise ValueError("插件前端入口不存在或路径非法")
                    staging.replace(target)
                except Exception:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return {"ok": False, "error": f"无法安装插件：{exc}"}
        states = self._states()
        states[manifest["id"]] = {**states.get(manifest["id"], {}), "enabled": False}
        self._settings.set("plugin_states", states)
        installed = self._plugin(manifest["id"])
        return {
            "ok": True,
            "plugin": installed,
            "message": f"插件已安装到：{installed.get('path') if installed else target}",
        }

    def install_bundle_bytes(self, name: str, data: bytes) -> dict[str, Any]:
        if not data:
            return {"ok": False, "error": "插件包为空。"}
        if len(data) > _MAX_BUNDLE_BYTES:
            return {"ok": False, "error": "插件包超过 20 MB 限制。"}
        suffix = ".zip" if str(name or "").lower().endswith(".zip") else ".xbplugin"
        temporary = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            with temporary:
                temporary.write(data)
            return self.install_bundle(temporary.name)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

    def install_from_market(self, url: str) -> dict[str, Any]:
        raw = str(url or "").strip()
        if not self._is_github_url(raw):
            return {"ok": False, "error": "仅允许从 GitHub HTTPS 地址安装插件。"}
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(raw)
                response.raise_for_status()
                if not self._is_github_url(str(response.url)):
                    return {"ok": False, "error": "GitHub 下载跳转到了不受信任的站点。"}
                if len(response.content) > _MAX_BUNDLE_BYTES:
                    return {"ok": False, "error": "插件包超过 20 MB 限制。"}
                suffix = ".xbplugin"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                    handle.write(response.content)
                    temp_path = handle.name
            try:
                return self.install_bundle(temp_path)
            finally:
                Path(temp_path).unlink(missing_ok=True)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"下载 GitHub 插件失败：{exc}"}

    def uninstall(self, plugin_id: str) -> bool:
        plugin = self._plugin(plugin_id)
        if not plugin:
            return False
        shutil.rmtree(Path(plugin["path"]), ignore_errors=True)
        shutil.rmtree(config.PLUGIN_DATA_DIR / plugin_id, ignore_errors=True)
        states = self._states()
        states.pop(plugin_id, None)
        self._settings.set("plugin_states", states)
        return True

    def fetch_market(self) -> dict[str, Any]:
        url = str(self._settings.get("plugin_market_url", "") or "").strip()
        if not url:
            return {"ok": False, "error": "请先填写插件市场索引地址。", "items": []}
        if not self._is_github_url(url):
            return {"ok": False, "error": "插件市场仅支持 GitHub HTTPS raw 或 API 地址。", "items": []}
        try:
            response = httpx.get(url, timeout=20, follow_redirects=True)
            response.raise_for_status()
            if not self._is_github_url(str(response.url)):
                return {"ok": False, "error": "插件市场跳转到了不受信任的站点。", "items": []}
            payload = self._parse_market_payload(response.text)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"读取插件市场失败：{exc}", "items": []}
        except ValueError as exc:
            return {"ok": False, "error": f"插件市场索引格式无效：{exc}", "items": []}
        items = []
        for item in self._market_records(payload):
            normalized = self._normalise_market_item(item)
            if normalized:
                items.append(normalized)
        return {"ok": True, "items": items}
    def apply_before_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """将已启用插件声明的安全参数补丁合并到翻唱创建请求。"""
        if not self.status()["enabled"]:
            return payload
        result = copy.deepcopy(payload)
        params = result.setdefault("params", {})
        if not isinstance(params, dict):
            params = result["params"] = {}
        for plugin in self.list():
            if not plugin.get("enabled"):
                continue
            patch = ((plugin.get("workflow") or {}).get("before_create") or {}).get("params", {})
            if isinstance(patch, dict):
                for key, value in patch.items():
                    if key in _ALLOWED_PARAMS and key not in params:
                        params[key] = value
            if plugin.get("runtime") in {"python", "hybrid"}:
                response = self._run_python(
                    plugin, "hook", "before_create", payload=result
                )
                candidate = response.get("payload") if response.get("ok") else None
                if isinstance(candidate, dict):
                    result = candidate
        return result

    def run_action(self, plugin_id: str, action_id: str, values: dict[str, Any]) -> dict[str, Any]:
        if not self.status()["enabled"]:
            return {"ok": False, "error": "插件功能当前未开启。"}
        plugin = self._plugin(plugin_id)
        if not plugin or not plugin.get("enabled"):
            return {"ok": False, "error": "插件未安装或未启用。"}
        action = next((item for item in plugin.get("actions", []) if item.get("id") == action_id), None)
        if not action:
            return {"ok": False, "error": "插件动作不存在。"}
        action_type = action.get("type")
        if action_type == "message":
            return {
                "ok": True,
                "type": "message",
                "message": self._interpolate(str(action.get("message") or "操作已完成。"), values),
            }
        if action_type == "create_work":
            template = action.get("payload", {})
            if not isinstance(template, dict):
                return {"ok": False, "error": "插件任务模板无效。"}
            # 可替换字段必须明确写成 {{fieldId}}，不会解释表达式或执行代码。
            payload = self._interpolate(template, values)
            # 页面收到 payload 后会调用正式 create_work；流程钩子统一在那里执行一次。
            return {"ok": True, "type": "create_work", "payload": payload}
        if action_type == "python":
            return self._run_python(
                plugin, "action", str(action.get("handler") or action_id), values=values
            )
        return {"ok": False, "error": "不支持的插件动作。"}

    def frontend_document(self, plugin_id: str) -> dict[str, Any]:
        if not self.status()["enabled"]:
            return {"ok": False, "error": "插件功能当前未开启。"}
        plugin = self._plugin(plugin_id)
        if not plugin or not plugin.get("enabled"):
            return {"ok": False, "error": "插件未安装或未启用。"}
        entry = str(((plugin.get("frontend") or {}).get("entry") or "")).strip()
        if not entry:
            return {"ok": False, "error": "插件未声明 frontend.entry。"}
        path = self._safe_plugin_file(Path(plugin["path"]), entry, {".html", ".htm"})
        if not path:
            return {"ok": False, "error": "插件前端入口不存在或路径非法。"}
        try:
            if path.stat().st_size > _MAX_FRONTEND_ENTRY_BYTES:
                return {"ok": False, "error": "插件前端入口超过 2 MB 限制。"}
            html = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {"ok": False, "error": "无法读取插件前端入口。"}
        return {"ok": True, "entry": entry, "html": html}

    def frontend_asset_data(self, plugin_id: str, asset_path: str) -> dict[str, Any]:
        if not self.status()["enabled"]:
            return {"ok": False, "error": "插件功能当前未开启。"}
        plugin = self._plugin(plugin_id)
        if not plugin or not plugin.get("enabled"):
            return {"ok": False, "error": "插件未安装或未启用。"}
        path = self._safe_plugin_file(Path(plugin["path"]), str(asset_path or ""), None)
        if not path:
            return {"ok": False, "error": "插件资源不存在或路径非法。"}
        try:
            if path.stat().st_size > _MAX_FRONTEND_ASSET_BYTES:
                return {"ok": False, "error": "插件资源超过 10 MB 限制。"}
            data = path.read_bytes()
        except OSError:
            return {"ok": False, "error": "无法读取插件资源。"}
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        return {"ok": True, "name": path.name, "mime": mime, "data": f"data:{mime};base64,{encoded}"}

    def _plugin(self, plugin_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item.get("id") == plugin_id), None)

    def _states(self) -> dict[str, dict[str, Any]]:
        value = self._settings.get("plugin_states", {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _manifest_member(archive: zipfile.ZipFile) -> str | None:
        matches = [item.filename for item in archive.infolist() if item.filename.rstrip("/").endswith(_MANIFEST_NAME)]
        return matches[0] if len(matches) == 1 else None

    def _read_manifest(self, path: Path) -> dict[str, Any] | None:
        try:
            return self._parse_manifest(path.read_bytes())
        except OSError:
            return None

    def _parse_manifest(self, raw: bytes) -> dict[str, Any] | None:
        if len(raw) > _MAX_MANIFEST_BYTES:
            return None
        try:
            item = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(item, dict) or not self._valid_id(str(item.get("id") or "")):
            return None
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in ("name", "version")):
            return None
        pages = item.get("pages", [])
        actions = item.get("actions", [])
        if not isinstance(pages, list) or not isinstance(actions, list):
            return None
        if any(not self._valid_page(page) for page in pages if isinstance(page, dict)) or any(not isinstance(page, dict) for page in pages):
            return None
        if any(not self._valid_action(action) for action in actions if isinstance(action, dict)) or any(not isinstance(action, dict) for action in actions):
            return None
        runtime = str(item.get("runtime") or "frontend")
        python_config = item.get("python") if isinstance(item.get("python"), dict) else {}
        frontend_config = item.get("frontend") if isinstance(item.get("frontend"), dict) else {}
        permissions = item.get("permissions", [])
        if runtime not in _ALLOWED_RUNTIMES:
            return None
        if runtime in {"python", "hybrid"}:
            entry = str(python_config.get("entry") or "").strip()
            if not entry or Path(entry).is_absolute() or ".." in Path(entry).parts or Path(entry).suffix.lower() != ".py":
                return None
        frontend_entry = str(frontend_config.get("entry") or "").strip()
        if frontend_entry:
            frontend_path = Path(frontend_entry)
            if frontend_path.is_absolute() or ".." in frontend_path.parts or frontend_path.suffix.lower() not in {".html", ".htm"}:
                return None
        if not isinstance(permissions, list) or any(value not in _ALLOWED_PERMISSIONS for value in permissions):
            return None
        if runtime in {"python", "hybrid"} and "python.execute" not in permissions:
            return None
        return {
            "id": item["id"], "name": item["name"].strip()[:80], "version": item["version"].strip()[:32],
            "description": str(item.get("description") or "").strip()[:400], "author": str(item.get("author") or "").strip()[:80],
            "runtime": runtime, "python": python_config, "frontend": {"entry": frontend_entry} if frontend_entry else {},
            "permissions": permissions,
            "pages": pages, "actions": actions, "workflow": item.get("workflow") if isinstance(item.get("workflow"), dict) else {},
        }

    def _valid_page(self, page: dict[str, Any]) -> bool:
        if not self._valid_id(str(page.get("id") or "")) or not str(page.get("title") or "").strip():
            return False
        fields = page.get("fields", [])
        return isinstance(fields, list) and all(
            isinstance(field, dict) and self._valid_id(str(field.get("id") or ""))
            and field.get("type") in _ALLOWED_COMPONENTS for field in fields
        )

    def _valid_action(self, action: dict[str, Any]) -> bool:
        if not (
            self._valid_id(str(action.get("id") or ""))
            and action.get("type") in _ALLOWED_ACTIONS
            and bool(str(action.get("label") or "").strip())
        ):
            return False
        return action.get("type") != "python" or bool(
            re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", str(action.get("handler") or ""))
        )

    def _run_python(
        self,
        plugin: dict[str, Any],
        operation: str,
        name: str,
        *,
        values: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not config.PLUGIN_PYTHON or not config.PLUGIN_PYTHON.exists():
            return {"ok": False, "error": "未找到 Python 3.10+ 插件运行环境。"}
        if not config.PLUGIN_WORKER.exists() or not config.PLUGIN_SDK_DIR.exists():
            return {"ok": False, "error": "Python 插件 Worker 或 SDK 缺失。"}
        plugin_dir = Path(plugin["path"]).resolve()
        entry = (plugin_dir / str((plugin.get("python") or {}).get("entry") or "")).resolve()
        if plugin_dir not in entry.parents or not entry.is_file():
            return {"ok": False, "error": "Python 插件入口不存在或路径非法。"}
        request = {
            "sdk_path": str(config.PLUGIN_SDK_DIR),
            "plugin_id": plugin["id"],
            "plugin_dir": str(plugin_dir),
            "data_dir": str(config.PLUGIN_DATA_DIR / plugin["id"]),
            "entry": str(entry),
            "operation": operation,
            "name": name,
            "values": values or {},
            "payload": payload or {},
        }
        try:
            completed = subprocess.run(
                [str(config.PLUGIN_PYTHON), str(config.PLUGIN_WORKER)],
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                cwd=plugin_dir,
                check=False,
                **config.subprocess_no_window(),
            )
            response = json.loads(completed.stdout or "{}")
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Python 插件执行超过 30 秒，已终止。"}
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"Python 插件执行失败：{exc}"}
        if not response.get("ok"):
            detail = str(response.get("traceback") or completed.stderr or "")
            self._write_plugin_error(plugin["id"], detail)
            return {"ok": False, "error": str(response.get("error") or "Python 插件发生错误")}
        result = response.get("result")
        return {"ok": True, **(result if isinstance(result, dict) else {})}

    @staticmethod
    def _safe_plugin_file(root: Path, relative: str, suffixes: set[str] | None) -> Path | None:
        raw = str(relative or "").strip().replace("\\", "/")
        if not raw or raw.startswith("/"):
            return None
        try:
            candidate = (root / raw).resolve()
            plugin_root = root.resolve()
            candidate.relative_to(plugin_root)
        except (OSError, ValueError):
            return None
        if not candidate.is_file():
            return None
        if suffixes is not None and candidate.suffix.lower() not in suffixes:
            return None
        return candidate

    @staticmethod
    def _parse_market_payload(raw: str) -> Any:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            without_blocks = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
            without_line_comments = re.sub(r"(?m)^\s*//.*$", "", without_blocks)
            without_trailing_commas = re.sub(r",(\s*[}\]])", r"\1", without_line_comments)
            try:
                return json.loads(without_trailing_commas)
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc

    @staticmethod
    def _market_records(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            records = payload.get("plugins")
            if isinstance(records, list):
                return records
            records = payload.get("items")
            if isinstance(records, list):
                return records
        return []

    @staticmethod
    def _market_id(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("._-")
        if len(cleaned) < 3:
            cleaned = f"plugin-{cleaned}".strip("-")
        return cleaned[:64]

    def _normalise_market_item(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        module_name = str(item.get("module_name") or item.get("id") or "").strip()
        raw_id = str(item.get("id") or module_name or item.get("project_link") or "").strip()
        plugin_id = self._market_id(raw_id)
        if not plugin_id or not self._valid_id(plugin_id):
            return None
        project_link = str(item.get("project_link") or "").strip()
        homepage = str(
            item.get("homepage")
            or item.get("homepage_url")
            or item.get("repository")
            or item.get("repo")
            or ""
        ).strip()
        if not homepage and project_link:
            homepage = project_link if project_link.startswith("https://") else f"https://pypi.org/project/{project_link}/"
        bundle_url = str(
            item.get("bundle_url")
            or item.get("download_url")
            or item.get("release_url")
            or ""
        ).strip()
        if bundle_url and not self._is_github_url(bundle_url):
            bundle_url = ""
        tags = []
        raw_tags = item.get("tags")
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, dict):
                    label = str(tag.get("label") or tag.get("name") or "").strip()
                    if label:
                        tags.append({"label": label, "color": str(tag.get("color") or "")})
                else:
                    label = str(tag or "").strip()
                    if label:
                        tags.append({"label": label, "color": ""})
        author = str(item.get("author") or item.get("author_name") or item.get("author_id") or "")
        description = str(item.get("description") or item.get("desc") or item.get("summary") or "")
        name = str(item.get("name") or module_name or project_link or plugin_id)
        return {
            "id": plugin_id,
            "module_name": module_name,
            "project_link": project_link,
            "name": name,
            "version": str(item.get("version") or ""),
            "description": description,
            "author": author,
            "bundle_url": bundle_url,
            "homepage": homepage,
            "tags": tags,
            "is_official": bool(item.get("is_official", False)),
        }
    @staticmethod
    def _write_plugin_error(plugin_id: str, detail: str) -> None:
        if not detail.strip():
            return
        try:
            directory = config.PLUGIN_DATA_DIR / plugin_id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "error.log").write_text(detail[-20000:], encoding="utf-8")
        except OSError:
            pass

    def _interpolate(self, value: Any, values: dict[str, Any]) -> Any:
        """递归替换显式字段占位符，保留数值/布尔值，不解析任何表达式。"""
        if isinstance(value, dict):
            return {key: self._interpolate(item, values) for key, item in value.items()}
        if isinstance(value, list):
            return [self._interpolate(item, values) for item in value]
        if not isinstance(value, str):
            return value
        exact = re.fullmatch(r"\{\{([a-zA-Z][a-zA-Z0-9_]{0,40})\}\}", value)
        if exact:
            return values.get(exact.group(1), value)
        result = value
        for key, item in values.items():
            if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,40}", str(key)):
                result = result.replace("{{" + str(key) + "}}", str(item))
        return result

    @staticmethod
    def _valid_id(value: str) -> bool:
        return bool(_ID_RE.fullmatch(value))

    @staticmethod
    def _is_github_url(value: str) -> bool:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (
            host in {"github.com", "api.github.com"}
            or host.endswith(".github.com")
            or host == "githubusercontent.com"
            or host.endswith(".githubusercontent.com")
        )
