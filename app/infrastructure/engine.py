"""推理引擎抽象：按模型框架（so-vits-svc / rvc / …）路由到对应引擎。

共享阶段（人声分离 / 去混响 / 合并 / 混音）与框架无关，只有「推理」按模型的
``framework`` 字段选择不同引擎。新增框架只需实现 ``VoiceConversionEngine`` 协议并
在 ``build_api`` 注册进 ``EngineRegistry`` 即可，无需改动流水线本身。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import config
from domain import InferenceParams


@runtime_checkable
class VoiceConversionEngine(Protocol):
    """歌声转换引擎统一接口。

    ``model`` 为已解析的模型文件角色字典（由 ``WorkService._resolve_model_paths`` 产出），
    至少包含 ``framework`` 与各 ``*_path``（so-vits 的 main/diffusion、RVC 的 main/index）。
    """

    framework: str

    @property
    def available(self) -> bool: ...

    def infer(
        self,
        model: dict[str, Any],
        vocals: Path,
        out_path: Path,
        params: InferenceParams,
        duration: float,
        log_file: Optional[Path] = None,
    ) -> Path: ...


class EngineRegistry:
    """按框架 id 路由引擎；未知框架回退到 so-vits-svc。"""

    def __init__(self, engines: list[Any]) -> None:
        self._by_fw: dict[str, Any] = {}
        for eng in engines:
            fw = getattr(eng, "framework", None)
            if fw:
                self._by_fw[fw] = eng

    def for_framework(self, framework: str | None) -> Any:
        fw = config.modelhub_normalize_framework(framework)
        eng = self._by_fw.get(fw)
        if eng is None:
            eng = self._by_fw.get(config.MODELHUB_DEFAULT_FRAMEWORK)
        if eng is None and self._by_fw:
            eng = next(iter(self._by_fw.values()))
        return eng

    def for_model(self, model: dict[str, Any] | None) -> Any:
        return self.for_framework((model or {}).get("framework"))

    @property
    def sovits(self) -> Any:
        """so-vits 引擎引用（F0 探针等 so-vits 专属能力使用）。"""
        return self._by_fw.get("so-vits-svc")

    def engines(self) -> list[Any]:
        return list(self._by_fw.values())
