"""模型服务：导入 / 列出 / 删除 SVC 模型，管理默认模型。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from domain import ModelFile, ModelInfo, ModelType
from infrastructure import paths
from infrastructure.storage import ListRepository, SettingsStore


class ModelService:
    def __init__(self, repo: ListRepository, settings: SettingsStore) -> None:
        self._repo = repo
        self._settings = settings

    # ---- 查询 ----
    def list(self) -> list[dict[str, Any]]:
        return [self._normalize_item(item, refresh_size=False) for item in self._repo.all()]

    def overview(self) -> dict[str, Any]:
        """返回本地模型库的多框架统一概览。"""
        default_id = self.default_id()
        summaries: dict[str, dict[str, Any]] = {}
        total_size = 0
        supported = {"so-vits-svc", "rvc", "seed-vc"}

        for fw, name in config.MODELHUB_FRAMEWORKS.items():
            summaries[fw] = {
                "id": fw,
                "name": name,
                "count": 0,
                "size_bytes": 0,
                "size": "0 B",
                "default_model_id": None,
                "default_model_name": "",
                "supported": fw in supported,
            }

        for item in self._repo.all():
            framework = config.modelhub_normalize_framework(
                item.get("framework") or config.modelhub_guess_framework(item.get("type"))
            )
            if framework not in summaries:
                summaries[framework] = {
                    "id": framework,
                    "name": config.MODELHUB_FRAMEWORKS.get(framework, framework),
                    "count": 0,
                    "size_bytes": 0,
                    "size": "0 B",
                    "default_model_id": None,
                    "default_model_name": "",
                    "supported": framework in supported,
                }
            size = self._model_size_bytes(item)
            total_size += size
            entry = summaries[framework]
            entry["count"] += 1
            entry["size_bytes"] += size
            if item.get("id") == default_id:
                entry["default_model_id"] = item.get("id")
                entry["default_model_name"] = item.get("name", "")

        rows = []
        for entry in summaries.values():
            entry["size"] = paths.human_size(int(entry.get("size_bytes") or 0))
            rows.append(entry)
        rows.sort(key=lambda x: (0 if x.get("count") else 1, str(x.get("name") or "")))
        return {
            "total": sum(int(x.get("count") or 0) for x in rows),
            "total_size_bytes": total_size,
            "total_size": paths.human_size(total_size),
            "default_model_id": default_id,
            "frameworks": rows,
        }

    def default_id(self) -> str | None:
        default = self._settings.get("default_model_id")
        if default and self._repo.get(default):
            return default
        items = self._repo.all()
        return items[0]["id"] if items else None

    def get(self, model_id: str) -> dict[str, Any] | None:
        return self._repo.get(model_id)

    # ---- 命令 ----
    def import_model(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """导入一组模型，按 ``framework`` 分支处理所需文件。

        payload 字段（文件均为本地绝对路径）：
            framework: so-vits-svc / rvc / seed-vc / …（缺省 so-vits-svc）
            name(可选), sample_rate(可选)
            - so-vits-svc：main_model + main_config 必填，diffusion_model / diffusion_config 可选。
            - rvc：main_model(.pth) 必填，index_file(.index) 可选，无需 main_config。
            - seed-vc：main_model(.pth) + main_config(.yml/.yaml) 必填；参考音频在推理时选择。
        必填文件缺失则返回 None。
        """
        paths.ensure_dirs()
        framework = config.modelhub_normalize_framework(payload.get("framework"))
        is_rvc = framework == "rvc"
        is_seedvc = framework == "seed-vc"

        main_model_src = payload.get("main_model")
        main_config_src = payload.get("main_config")
        if not main_model_src:
            return None
        # so-vits / SeedVC 需要主配置；RVC 不需要
        if not is_rvc and not main_config_src:
            return None

        model_id = paths.new_id("mdl_")
        dst_dir = config.MODELS_DIR / model_id
        dst_dir.mkdir(parents=True, exist_ok=True)

        def copy(raw: str | None) -> ModelFile | None:
            if not raw:
                return None
            src = Path(raw)
            if not src.exists():
                return None
            dst = dst_dir / src.name
            try:
                shutil.copy2(src, dst)
            except OSError:
                return None
            return ModelFile(name=src.name, path=str(dst))

        main_model = copy(main_model_src)
        if main_model is None:
            shutil.rmtree(dst_dir, ignore_errors=True)
            return None

        main_config = None
        diffusion_model = None
        diffusion_config = None
        index_file = None
        if is_rvc:
            index_file = copy(payload.get("index_file"))
        else:
            main_config = copy(main_config_src)
            if main_config is None:
                shutil.rmtree(dst_dir, ignore_errors=True)
                return None
            if is_seedvc:
                diffusion_model = None
                diffusion_config = None
            else:
                diffusion_model = copy(payload.get("diffusion_model"))
                diffusion_config = copy(payload.get("diffusion_config"))

        total = 0
        for mf in (
            main_model,
            main_config,
            diffusion_model,
            diffusion_config,
            index_file,
        ):
            if mf:
                try:
                    total += Path(mf.path).stat().st_size
                except OSError:
                    pass

        name = payload.get("name") or Path(main_model_src).stem
        if is_rvc:
            model_type = ModelType.RVC.value
        elif is_seedvc:
            model_type = ModelType.SEEDVC.value
        else:
            model_type = ModelType.guess(main_model.name).value
        info = ModelInfo(
            id=model_id,
            name=name,
            type=model_type,
            sample_rate=str(payload.get("sample_rate", "44.1kHz")),
            size=paths.human_size(total),
            imported_at=datetime.now().strftime("%Y-%m-%d"),
            main_model=main_model,
            main_config=main_config or ModelFile("", ""),
            diffusion_model=diffusion_model,
            diffusion_config=diffusion_config,
            framework=framework,
            index_file=index_file,
        )
        record = self._normalize_item(info.to_dict(), refresh_size=True)
        source_repo_id = str(payload.get("source_repo_id") or "").strip().strip("/")
        if source_repo_id:
            record["metadata"] = {
                **(record.get("metadata") or {}),
                "source_repo_id": source_repo_id,
            }
        self._repo.add(record)
        if not self._settings.get("default_model_id"):
            self._settings.set("default_model_id", model_id)
        return record

    def toggle_favorite(self, model_id: str) -> dict[str, Any] | None:
        item = self._repo.get(model_id)
        if not item:
            return None
        item = self._normalize_item(item, refresh_size=False)
        item["favorite"] = not bool(item.get("favorite"))
        self._repo.update(model_id, item)
        return item

    def inspect(self, model_id: str, repair: bool = False) -> dict[str, Any]:
        item = self._repo.get(model_id)
        if not item:
            return {"ok": False, "error": "模型不存在", "issues": []}
        normalized = self._normalize_item(item, refresh_size=True)
        issues: list[dict[str, Any]] = []
        fixed: list[str] = []
        framework = config.modelhub_normalize_framework(
            normalized.get("framework") or config.modelhub_guess_framework(normalized.get("type"))
        )
        normalized["framework"] = framework

        checks = [("main_model", "主模型")]
        if framework != "rvc":
            checks.append(("main_config", "主配置"))
        for key, label in checks:
            raw = normalized.get(key) or {}
            path = Path(str(raw.get("path") or ""))
            if not path.exists():
                issues.append({"key": key, "level": "error", "message": f"{label}文件缺失"})

        if framework == "rvc":
            idx = normalized.get("index_file") or {}
            idx_path = Path(str(idx.get("path") or ""))
            if not idx_path.exists():
                main = Path(str((normalized.get("main_model") or {}).get("path") or ""))
                candidates = sorted(main.parent.glob("*.index")) if main.parent.exists() else []
                if candidates:
                    issues.append({"key": "index_file", "level": "warn", "message": "未绑定 index，发现可修复候选"})
                    if repair:
                        normalized["index_file"] = {
                            "name": candidates[0].name,
                            "path": str(candidates[0]),
                        }
                        fixed.append("index_file")

        if framework == "so-vits-svc":
            cfg = Path(str((normalized.get("main_config") or {}).get("path") or ""))
            if cfg.exists():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                    sr = data.get("sampling_rate") or data.get("sample_rate")
                    if sr:
                        normalized["sample_rate"] = f"{int(sr) / 1000:g}kHz"
                        if repair:
                            fixed.append("sample_rate")
                except (OSError, ValueError, TypeError):
                    issues.append({"key": "main_config", "level": "warn", "message": "配置文件无法解析"})

        size = self._model_size_bytes(normalized)
        normalized["size"] = paths.human_size(size)
        metadata = dict(normalized.get("metadata") or {})
        metadata.update(
            {
                "schema": "xb-svcb.model.v1",
                "framework": framework,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "valid": not any(i.get("level") == "error" for i in issues),
                "issues": issues,
            }
        )
        normalized["metadata"] = metadata
        if repair:
            self._repo.update(model_id, normalized)
        return {
            "ok": metadata["valid"],
            "model": normalized,
            "issues": issues,
            "fixed": fixed,
        }

    def set_default(self, model_id: str) -> bool:
        if not self._repo.get(model_id):
            return False
        self._settings.set("default_model_id", model_id)
        return True

    def remove(self, model_id: str) -> bool:
        item = self._repo.get(model_id)
        if not item:
            return False
        # 删除本地文件夹
        model_dir = config.MODELS_DIR / model_id
        if model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        self._repo.remove(model_id)
        if self._settings.get("default_model_id") == model_id:
            remaining = self._repo.all()
            self._settings.set(
                "default_model_id", remaining[0]["id"] if remaining else None
            )
        return True

    def _normalize_item(self, item: dict[str, Any], refresh_size: bool = False) -> dict[str, Any]:
        normalized = dict(item)
        framework = config.modelhub_normalize_framework(
            normalized.get("framework") or config.modelhub_guess_framework(normalized.get("type"))
        )
        normalized["framework"] = framework
        normalized.setdefault("favorite", False)
        normalized.setdefault("tags", [])
        normalized.setdefault("metadata", {})
        normalized["metadata"] = {
            "schema": "xb-svcb.model.v1",
            "framework": framework,
            **(normalized.get("metadata") or {}),
        }
        if not normalized.get("type"):
            if framework == "rvc":
                normalized["type"] = ModelType.RVC.value
            elif framework == "seed-vc":
                normalized["type"] = ModelType.SEEDVC.value
            else:
                normalized["type"] = "So-VITS"
        if not normalized.get("sample_rate"):
            normalized["sample_rate"] = "44.1kHz"
        if refresh_size or not normalized.get("size"):
            normalized["size"] = paths.human_size(self._model_size_bytes(normalized))
        for key in ("main_model", "main_config"):
            normalized.setdefault(key, {"name": "", "path": ""})
        return normalized

    @staticmethod
    def _model_size_bytes(item: dict[str, Any]) -> int:
        total = 0
        for key in (
            "main_model",
            "main_config",
            "diffusion_model",
            "diffusion_config",
            "index_file",
        ):
            raw = item.get(key)
            if not isinstance(raw, dict):
                continue
            path = raw.get("path")
            if not path:
                continue
            try:
                total += Path(str(path)).stat().st_size
            except OSError:
                pass
        return total
