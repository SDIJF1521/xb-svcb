"""模型服务：导入 / 列出 / 删除 SVC 模型，管理默认模型。"""

from __future__ import annotations

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
        return self._repo.all()

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
            framework: so-vits-svc / rvc / …（缺省 so-vits-svc）
            name(可选), sample_rate(可选)
            - so-vits-svc：main_model + main_config 必填，diffusion_model / diffusion_config 可选。
            - rvc：main_model(.pth) 必填，index_file(.index) 可选，无需 main_config。
        必填文件缺失则返回 None。
        """
        paths.ensure_dirs()
        framework = config.modelhub_normalize_framework(payload.get("framework"))
        is_rvc = framework == "rvc"

        main_model_src = payload.get("main_model")
        main_config_src = payload.get("main_config")
        if not main_model_src:
            return None
        # so-vits 需要主配置；RVC 不需要
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
            diffusion_model = copy(payload.get("diffusion_model"))
            diffusion_config = copy(payload.get("diffusion_config"))

        total = 0
        for mf in (main_model, main_config, diffusion_model, diffusion_config, index_file):
            if mf:
                try:
                    total += Path(mf.path).stat().st_size
                except OSError:
                    pass

        name = payload.get("name") or Path(main_model_src).stem
        model_type = ModelType.RVC.value if is_rvc else ModelType.guess(main_model.name).value
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
        self._repo.add(info.to_dict())
        if not self._settings.get("default_model_id"):
            self._settings.set("default_model_id", model_id)
        return info.to_dict()

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
