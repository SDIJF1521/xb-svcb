"""工作流商城用例：ModelScope 工作流的上传、分页搜索、预览与下载。

职责边界（见 ``docs/ddd-architecture.md``）：

- 本模块只做用例编排：取令牌 → 调网关 / 端口 → 应用领域规则 → 保存 → 返回 DTO；
- 清单格式、节点图收敛、PyMSS 依赖解析等纯规则在 ``domain/workflow_manifest.py``；
- 网络、子进程上传、暂存目录在 ``infrastructure/workflow_hub_client.py``；
- PyMSS 模型安装状态与下载通过 ``PymssGateway`` 端口访问。

下载流程：校验清单 → 写入「已保存工作流」→ 逐个同步缺失的 PyMSS 模型。
整个过程以后台任务暴露进度；未下载前前端只能预览，无法载入工作台。
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
from datetime import datetime
from typing import Any

import config
from domain.workflow_manifest import (
    build_workflow_manifest,
    graph_from_manifest,
    normalize_pymss_requirements,
    parse_workflow_manifest,
    pymss_model_names,
    pymss_model_stem_key,
    pymss_node_default_purpose,
    preview_graph,
    sanitize_graph,
    trim_text,
    workflow_graph_fingerprint,
)
from domain.workflow_graph import validate_graph

from .ports import PymssGateway, SettingsRepository, WorkflowHubGateway
from .work_service import WorkService


class WorkflowHubService:
    """工作流商城：上传 / 搜索 / 预览 / 下载 + PyMSS 依赖同步。"""

    def __init__(
        self,
        settings: SettingsRepository,
        works: WorkService,
        pymss: PymssGateway,
        gateway: WorkflowHubGateway,
    ) -> None:
        self._settings = settings
        self._works = works
        self._pymss = pymss
        self._gateway = gateway
        # 进度：key -> {phase, pct, msg, done, total}；下载 key=wfdl:<repo>，上传 key=wful:<id>
        self._progress: dict[str, dict[str, Any]] = {}
        # 任务：key -> {key, kind, title, status, result, error, created_at}
        self._jobs: dict[str, dict[str, Any]] = {}
        self._progress_lock = threading.Lock()
        # 本地工作流图指纹缓存：id -> (updated_at, sha256)。工作流图很小，
        # 但仍避免每次搜索/翻页重复做规范化与 JSON 序列化。
        self._graph_hash_cache: dict[str, tuple[str, str]] = {}
        self._remote_graph_hash_cache: dict[tuple[str, str], str] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="workflowhub-loop"
        )
        self._thread.start()

    def _run_loop(self) -> None:
        try:
            self._loop.create_task(self._warm_gateway_async())
        except Exception:  # noqa: BLE001 - 预热失败不影响主流程
            pass
        self._loop.run_forever()

    async def _warm_gateway_async(self) -> None:
        self._warm_gateway()

    def _warm_gateway(self) -> None:
        prepare = getattr(self._gateway, "prepare", None)
        if callable(prepare):
            try:
                prepare()
            except Exception:  # noqa: BLE001 - 预热失败不影响按需创建
                pass

    # ---- 进度 / 后台任务 ----
    def _set_progress(
        self, key: str, phase: str, pct: float, msg: str = "", done: int = 0, total: int = 0
    ) -> None:
        with self._progress_lock:
            self._progress[key] = {
                "phase": phase,
                "pct": round(max(0.0, min(100.0, pct)), 1),
                "msg": msg,
                "done": done,
                "total": total,
            }

    def get_progress(self, key: str) -> dict[str, Any]:
        with self._progress_lock:
            current = self._progress.get(key)
            return dict(current) if current else {
                "phase": "", "pct": 0, "msg": "", "done": 0, "total": 0
            }

    def _set_job(self, key: str, **fields: Any) -> None:
        with self._progress_lock:
            job = self._jobs.get(key) or {"key": key}
            job.update(fields)
            self._jobs[key] = job

    def _finish_job(self, key: str, ok: bool, res: Any) -> None:
        error = None
        if not ok:
            error = (res or {}).get("error") if isinstance(res, dict) else "操作失败"
        self._set_job(
            key,
            status="done" if ok else "failed",
            result=res if (ok and isinstance(res, dict)) else None,
            error=error,
        )
        current = self.get_progress(key)
        if ok and current.get("phase") != "done":
            self._set_progress(key, "done", 100, "完成")
        elif not ok and current.get("phase") != "error":
            self._set_progress(key, "error", float(current.get("pct") or 0), error or "操作失败")

    def _spawn(self, key: str, coro: Any) -> None:
        async def _runner() -> None:
            try:
                res = await coro
                ok = bool(res.get("ok")) if isinstance(res, dict) else False
                self._finish_job(key, ok, res if isinstance(res, dict) else {"ok": ok})
            except Exception as exc:  # noqa: BLE001 - 后台任务异常需记录而非崩溃
                self._finish_job(key, False, {"ok": False, "error": str(exc)})

        asyncio.run_coroutine_threadsafe(_runner(), self._loop)

    def start_download(self, repo_id: str) -> dict[str, Any]:
        repo_id = (repo_id or "").strip().strip("/")
        if "/" not in repo_id:
            return {"ok": False, "error": "缺少有效的工作流仓库 ID"}
        key = f"wfdl:{repo_id}"
        with self._progress_lock:
            existing = self._jobs.get(key)
            if existing and existing.get("status") == "running":
                return {"ok": True, "key": key, "already": True}
        self._set_job(
            key,
            kind="download",
            title=f"工作流 · {repo_id}",
            status="running",
            result=None,
            error=None,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._set_progress(key, "start", 0, "排队中…")
        self._spawn(key, self._download(repo_id))
        return {"ok": True, "key": key}

    def start_upload(
        self,
        workflow_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workflow_id = (workflow_id or "").strip()
        if not workflow_id:
            return {"ok": False, "error": "缺少工作流 ID"}
        key = f"wful:{workflow_id}"
        with self._progress_lock:
            existing = self._jobs.get(key)
            if existing and existing.get("status") == "running":
                return {"ok": True, "key": key, "already": True}
        workflow = self._works.get_workflow(workflow_id) or {}
        self._set_job(
            key,
            kind="upload",
            title=f"工作流 · {workflow.get('name') or workflow_id}",
            status="running",
            result=None,
            error=None,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._set_progress(key, "start", 0, "排队中…")
        self._spawn(key, self._upload(workflow_id, metadata or {}))
        return {"ok": True, "key": key}

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._progress_lock:
            jobs = [dict(job) for job in self._jobs.values()]
            progress = {key: dict(value) for key, value in self._progress.items()}
        out: list[dict[str, Any]] = []
        for job in jobs:
            current = progress.get(job["key"], {})
            out.append(
                {
                    **job,
                    "pct": current.get("pct", 0),
                    "msg": current.get("msg", ""),
                    "phase": current.get("phase", ""),
                }
            )
        out.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return out

    def clear_job(self, key: str) -> bool:
        with self._progress_lock:
            self._jobs.pop(str(key or ""), None)
            self._progress.pop(str(key or ""), None)
        return True

    # ---- 令牌（与模型站共用）----
    def get_token(self) -> str:
        return str(self._settings.get(config.MODELSCOPE_TOKEN_SETTING, "") or "")

    def set_token(self, token: str) -> bool:
        self._settings.set(config.MODELSCOPE_TOKEN_SETTING, (token or "").strip())
        try:
            self._gateway.invalidate_cache()
        except Exception:  # noqa: BLE001 - 缓存清理失败不应阻断保存令牌
            pass
        return True

    def upload_ready(self) -> bool:
        return self._gateway.upload_ready()

    # ---- 同步入口（供桥接调用）----
    def _submit(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def search(
        self,
        query: str = "",
        page: int = 1,
        page_size: int = 12,
        mine_only: bool = False,
    ) -> dict[str, Any]:
        return self._submit(
            self._search(query or "", int(page or 1), int(page_size or 12), bool(mine_only))
        )

    def detail(self, repo_id: str) -> dict[str, Any]:
        return self._submit(self._detail(repo_id))

    def download(self, repo_id: str) -> dict[str, Any]:
        return self._submit(self._download(repo_id))

    def upload(self, workflow_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._submit(self._upload(workflow_id, metadata or {}))

    # ---- 本地状态辅助 ----
    def _local_source_map(self) -> dict[str, dict[str, Any]]:
        mapping: dict[str, dict[str, Any]] = {}
        for workflow in self._works.list_workflows():
            source = workflow.get("source")
            if not isinstance(source, dict):
                continue
            repo_id = str(source.get("repo_id") or "").strip().strip("/")
            if repo_id and repo_id not in mapping:
                mapping[repo_id] = workflow
        return mapping

    def _local_graph_map(self) -> dict[str, dict[str, Any]]:
        """本地工作流图指纹 -> 工作流（用于来源元数据缺失时的哈希识别）。"""
        mapping: dict[str, dict[str, Any]] = {}
        cache = getattr(self, "_graph_hash_cache", None)
        if cache is None:
            cache = {}
            self._graph_hash_cache = cache
        for workflow in self._works.list_workflows():
            workflow_id = str(workflow.get("id") or "")
            updated_at = str(workflow.get("updated_at") or "")
            cached = cache.get(workflow_id)
            if cached and cached[0] == updated_at:
                fingerprint = cached[1]
            else:
                fingerprint = workflow_graph_fingerprint(
                    {
                        "nodes": workflow.get("nodes") or [],
                        "edges": workflow.get("edges") or [],
                    }
                ) or ""
                cache[workflow_id] = (updated_at, fingerprint)
                if len(cache) > 256:
                    cache.pop(next(iter(cache)), None)
            if fingerprint and fingerprint not in mapping:
                mapping[fingerprint] = workflow
        return mapping

    def _remote_graph_fingerprint(
        self, repo_id: str, manifest: dict[str, Any], graph: dict[str, Any]
    ) -> str:
        """远端清单图指纹缓存：同一仓库 + 版本只规范化一次。"""
        cache = getattr(self, "_remote_graph_hash_cache", None)
        if cache is None:
            cache = {}
            self._remote_graph_hash_cache = cache
        key = (repo_id, str(manifest.get("version") or ""))
        cached = cache.get(key)
        if cached is not None:
            return cached
        fingerprint = workflow_graph_fingerprint(graph) or ""
        if len(cache) >= 256:
            cache.pop(next(iter(cache)), None)
        cache[key] = fingerprint
        return fingerprint

    def _downloaded_stems(self) -> set[str]:
        try:
            return set(self._pymss.downloaded_model_stems())
        except Exception:  # noqa: BLE001 - 目录不可读时按未安装处理
            return set()

    def _pymss_downloaded(self, name: str, stems: set[str]) -> bool:
        return bool(name) and pymss_model_stem_key(name) in stems

    def _catalog_index(self) -> dict[str, dict[str, Any]]:
        try:
            rows = self._pymss.list_models(include_all=True) or []
        except Exception:  # noqa: BLE001 - 目录不可用不应阻断上传
            return {}
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name:
                index[name] = row
        return index

    def _pymss_requirements_for_manifest(
        self, nodes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """把工作流引用的 PyMSS 模型整理成可跨机器解析的依赖清单。"""
        names = pymss_model_names(nodes)
        if not names:
            return []
        catalog = self._catalog_index()
        default_purposes = pymss_node_default_purpose(nodes)
        requirements: list[dict[str, Any]] = []
        for name in names:
            info = catalog.get(name)
            if not info:
                stem = pymss_model_stem_key(name)
                info = next(
                    (row for key, row in catalog.items() if pymss_model_stem_key(key) == stem),
                    {},
                )
            purpose = str(info.get("purpose") or "").strip()
            if info:
                # 目录里明确给出用途时以目录为准；不在受支持类别内则留空，
                # 让下载器在全量目录里按名称精确匹配，避免错误过滤。
                if purpose not in config.PYMSS_ALLOWED_MODEL_CATEGORIES:
                    purpose = ""
            else:
                purpose = default_purposes.get(name, "")
            requirements.append(
                {
                    "name": name,
                    "purpose": purpose,
                    "purpose_label": trim_text(
                        info.get("purpose_label")
                        or config.PYMSS_PURPOSE_LABELS.get(purpose, ""),
                        40,
                    ),
                    "architecture": trim_text(info.get("architecture"), 60),
                    "category_label": trim_text(
                        info.get("category_label") or info.get("category"), 120
                    ),
                    "target_stem": trim_text(info.get("target_stem"), 60),
                    "size_bytes": max(0, _as_int(info.get("size_bytes"))),
                }
            )
        return normalize_pymss_requirements(requirements)

    def _build_pymss_items(
        self, manifest: dict[str, Any], stems: set[str]
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for requirement in normalize_pymss_requirements(manifest.get("pymss_models")):
            items.append(
                {
                    **requirement,
                    "downloaded": self._pymss_downloaded(requirement["name"], stems),
                }
            )
        return items

    def _build_item(
        self,
        repo_id: str,
        manifest: dict[str, Any],
        *,
        detail: bool,
        source_map: dict[str, dict[str, Any]],
        stems: set[str],
        graph_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        graph = graph_from_manifest(manifest)
        if not graph:
            return None
        source = source_map.get(repo_id)
        download_match = "repo" if source else ""
        if not source and graph_map:
            fingerprint = self._remote_graph_fingerprint(repo_id, manifest, graph)
            if fingerprint:
                source = graph_map.get(fingerprint)
                if source:
                    download_match = "graph_hash"
        item: dict[str, Any] = {
            "repo_id": repo_id,
            "name": manifest["name"],
            "description": manifest.get("description") or "",
            "author": manifest.get("uploaded_by") or "",
            "version": manifest["version"],
            "uploaded_at": manifest.get("uploaded_at") or "",
            "tags": list(manifest.get("tags") or []),
            "url": f"https://www.modelscope.cn/models/{repo_id}",
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "pymss_models": self._build_pymss_items(manifest, stems),
            "downloaded": bool(source),
            "download_match": download_match,
            "local_workflow_id": str((source or {}).get("id") or ""),
            "preview_graph": preview_graph(graph),
        }
        if detail:
            item["graph"] = graph
        return item

    # ---- 搜索 ----
    async def _search(
        self,
        query: str,
        page: int,
        page_size: int,
        mine_only: bool = False,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(48, page_size))
        keyword = (query or "").strip()
        token = self.get_token()

        viewer = ""
        if token:
            verified = await self._gateway.verify_token(token)
            if verified.get("ok") and verified.get("username"):
                viewer = trim_text(verified.get("username"), 40)
        if mine_only and not viewer:
            return {
                "ok": True,
                "items": [],
                "page": page,
                "page_size": page_size,
                "total": 0,
                "has_more": False,
                "viewer": "",
                "mine_only": True,
            }

        result = await self._gateway.search(
            token=token,
            query=keyword,
            page=page,
            page_size=page_size,
            viewer=viewer,
            mine_only=mine_only,
        )
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error") or "搜索工作流失败"}

        tokens = [item for item in keyword.lower().split() if item]
        source_map = self._local_source_map()
        graph_map = self._local_graph_map()
        stems = self._downloaded_stems()
        items: list[dict[str, Any]] = []
        for candidate in result.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            repo_id = str(candidate.get("repo_id") or "").strip().strip("/")
            raw_manifest = candidate.get("manifest")
            if "/" not in repo_id:
                continue
            manifest = parse_workflow_manifest(raw_manifest)
            if not manifest:
                continue
            haystack = (
                f"{manifest['name']} {repo_id} {' '.join(manifest.get('tags') or [])}"
            ).lower()
            if tokens and not all(token in haystack for token in tokens):
                continue
            if mine_only and viewer and manifest.get("uploaded_by") != viewer:
                continue
            item = self._build_item(
                repo_id,
                manifest,
                detail=False,
                source_map=source_map,
                stems=stems,
                graph_map=graph_map,
            )
            if item:
                items.append(item)
        items.sort(key=lambda item: str(item.get("uploaded_at") or ""), reverse=True)

        total_hint = result.get("total")
        page_source_count = int(result.get("page_source_count") or 0)
        has_more = (
            page * page_size < int(total_hint)
            if total_hint is not None
            else page_source_count >= page_size
        )
        if total_hint is not None:
            total = max(int(total_hint), (page - 1) * page_size + len(items))
        else:
            total = (page - 1) * page_size + len(items) + (page_size if has_more else 0)
        return {
            "ok": True,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": bool(has_more),
            "viewer": viewer,
            "mine_only": bool(mine_only),
        }

    async def _detail(self, repo_id: str) -> dict[str, Any]:
        repo_id = (repo_id or "").strip().strip("/")
        if "/" not in repo_id:
            return {"ok": False, "error": "无效的工作流仓库标识"}
        raw = await self._gateway.fetch_manifest(repo_id, self.get_token())
        manifest = parse_workflow_manifest(raw)
        if not manifest:
            return {"ok": False, "error": "该工作流不是本软件上传或清单校验失败"}
        item = self._build_item(
            repo_id,
            manifest,
            detail=True,
            source_map=self._local_source_map(),
            stems=self._downloaded_stems(),
            graph_map=self._local_graph_map(),
        )
        if not item:
            return {"ok": False, "error": "工作流节点图无效，无法预览"}
        return {"ok": True, "item": item}

    # ---- 下载 + PyMSS 同步 ----
    async def _sync_pymss_models(
        self,
        key: str,
        requirements: list[dict[str, Any]],
        stems: set[str],
        start_pct: float,
        end_pct: float,
    ) -> dict[str, Any]:
        """并发安装缺失的 PyMSS 模型，并汇总成功 / 失败。

        一个工作流可能依赖 3~5 个模型，旧实现逐个启动、逐个轮询，网络等待被
        完全串行化。这里用有界并发（默认 3）同时下载，进度按模型大小加权汇总。
        """
        missing = [
            requirement
            for requirement in requirements
            if not self._pymss_downloaded(requirement["name"], stems)
        ]
        if not missing:
            return {"downloaded": [], "failed": []}
        total = len(missing)
        span = max(0.0, end_pct - start_pct)
        weights = [
            max(1, int(requirement.get("size_bytes") or 0)) for requirement in missing
        ]
        total_weight = max(1, sum(weights))
        fractions = [0.0] * total
        running: dict[int, str] = {}
        completed = 0
        concurrency = max(
            1, min(total, int(config.WORKFLOWHUB_PYMSS_DOWNLOAD_CONCURRENCY))
        )

        def report() -> None:
            weighted = sum(
                weights[index] * fractions[index] for index in range(total)
            )
            pct = start_pct + span * (weighted / total_weight)
            names = [running[index] for index in sorted(running)]
            message = f"同步 PyMSS 模型（{completed}/{total}）"
            if names:
                message += "：" + "、".join(names[:2])
            self._set_progress(key, "pymss", pct, message, completed, total)

        semaphore = asyncio.Semaphore(concurrency)

        async def sync_one(
            index: int, requirement: dict[str, Any]
        ) -> tuple[bool, str, str]:
            nonlocal completed
            name = str(requirement["name"])
            async with semaphore:
                running[index] = name
                report()
                if self._pymss_downloaded(name, self._downloaded_stems()):
                    fractions[index] = 1.0
                    completed += 1
                    running.pop(index, None)
                    report()
                    return True, name, ""
                purpose = str(requirement.get("purpose") or "")
                started = self._pymss.start_download_model(name, purpose)
                if not started.get("ok") or not started.get("key"):
                    fractions[index] = 1.0
                    completed += 1
                    running.pop(index, None)
                    report()
                    return (
                        False,
                        name,
                        str(started.get("error") or "无法启动下载"),
                    )
                job_key = str(started.get("key"))
                last_message = ""
                status = "idle"
                while True:
                    job = self._pymss.download_progress(job_key)
                    status = str(job.get("status") or "idle")
                    last_message = str(job.get("message") or last_message)
                    pct = _as_float(job.get("pct"), 0.0)
                    fractions[index] = max(0.0, min(1.0, pct / 100.0))
                    report()
                    if status in ("done", "failed", "idle"):
                        break
                    await asyncio.sleep(float(config.WORKFLOWHUB_PYMSS_POLL_SECONDS))
                fractions[index] = 1.0
                completed += 1
                running.pop(index, None)
                report()
                if status == "done":
                    return True, name, ""
                error = str(
                    self._pymss.download_progress(job_key).get("error")
                    or last_message
                    or "下载失败"
                )
                return False, name, error

        outcomes = await asyncio.gather(
            *(
                sync_one(index, requirement)
                for index, requirement in enumerate(missing)
            )
        )
        downloaded = [name for ok, name, _error in outcomes if ok]
        failed = [
            {"name": name, "error": error}
            for ok, name, error in outcomes
            if not ok
        ]
        return {"downloaded": downloaded, "failed": failed}

    async def _download(self, repo_id: str) -> dict[str, Any]:
        repo_id = (repo_id or "").strip().strip("/")
        key = f"wfdl:{repo_id}"
        if "/" not in repo_id:
            return {"ok": False, "error": "无效的工作流仓库标识"}
        self._set_progress(key, "verify", 2, "校验工作流清单…")
        raw = await self._gateway.fetch_manifest(repo_id, self.get_token())
        manifest = parse_workflow_manifest(raw)
        if not manifest:
            self._set_progress(key, "error", 0, "清单校验失败")
            return {"ok": False, "error": "该工作流不是本软件上传或清单校验失败，已跳过"}
        graph = graph_from_manifest(manifest)
        if not graph:
            self._set_progress(key, "error", 0, "节点图无效")
            return {"ok": False, "error": "工作流节点图无效，无法保存"}

        name = manifest["name"] or "商城工作流"
        source = {
            "origin": "downloaded",
            "repo_id": repo_id,
            "version": manifest["version"],
            "uploaded_at": manifest.get("uploaded_at") or "",
            "author": manifest.get("uploaded_by") or "",
            "lineage_id": manifest.get("lineage_id") or repo_id,
            "remote_name": name,
        }
        self._set_progress(key, "save", 12, "保存到「已保存工作流」…")
        try:
            saved = self._works.save_imported_workflow(name, graph, source)
        except ValueError as exc:
            self._set_progress(key, "error", 0, "工作流校验失败")
            return {"ok": False, "error": str(exc)}
        self._set_job(key, title=f"工作流 · {saved.get('name') or name}")

        requirements = normalize_pymss_requirements(manifest.get("pymss_models"))
        stems = self._downloaded_stems()
        missing = [
            requirement
            for requirement in requirements
            if not self._pymss_downloaded(requirement["name"], stems)
        ]
        self._set_progress(
            key,
            "save",
            20,
            f"已保存工作流「{saved.get('name')}」"
            + (f"，准备同步 {len(missing)} 个 PyMSS 模型" if missing else ""),
        )
        sync = await self._sync_pymss_models(key, requirements, stems, 20.0, 96.0)
        warnings = [
            f"{item['name']}：{item['error']}" for item in sync.get("failed", [])
        ]
        if warnings:
            self._set_progress(
                key,
                "done",
                100,
                f"工作流已保存；{len(warnings)} 个 PyMSS 模型下载失败（可稍后重试）",
            )
        else:
            self._set_progress(key, "done", 100, "工作流已保存，依赖模型已就绪")
        return {
            "ok": True,
            "workflow": saved,
            "repo_id": repo_id,
            "pymss_downloaded": sync.get("downloaded", []),
            "pymss_failed": sync.get("failed", []),
            "warnings": warnings,
        }

    # ---- 上传 ----
    async def _upload(self, workflow_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        key = f"wful:{workflow_id}"
        if not self._gateway.upload_ready():
            return {
                "ok": False,
                "error": "上传组件未安装（.venv-hub）。请在「搭建/修复运行环境」中安装模型上传组件后重试。",
            }
        workflow = self._works.get_workflow(workflow_id)
        if not workflow:
            return {"ok": False, "error": "本地工作流不存在，请先保存工作流"}
        graph = {
            "id": "",
            "name": str(workflow.get("name") or ""),
            "updated_at": "",
            "nodes": workflow.get("nodes") or [],
            "edges": workflow.get("edges") or [],
        }
        problem = validate_graph(graph)
        if problem:
            return {"ok": False, "error": f"工作流无效：{problem}"}
        safe_graph = sanitize_graph(graph)
        if not safe_graph:
            return {"ok": False, "error": "工作流节点图无法序列化，请检查节点参数"}

        self._set_progress(key, "verify", 3, "校验访问令牌…")
        verify = await self._gateway.verify_token(self.get_token())
        if not verify.get("ok"):
            self._set_progress(key, "error", 0, "令牌校验失败")
            return verify
        username = trim_text(verify.get("username"), 40)

        meta = metadata if isinstance(metadata, dict) else {}
        display = trim_text(meta.get("name"), 120) or trim_text(workflow.get("name"), 120) or "工作流"
        version = meta.get("version")
        description = meta.get("description")
        tags = meta.get("tags")
        slug = _slugify(display)
        short = re.sub(r"[^0-9A-Za-z]", "", str(workflow_id).split("_")[-1])[:8] or "x"
        repo_id = f"{username}/{config.WORKFLOWHUB_REPO_PREFIX}-{slug}-{short}"

        self._set_progress(key, "prepare", 8, "整理工作流节点图…")
        requirements = self._pymss_requirements_for_manifest(safe_graph["nodes"])
        uploaded_at = datetime.now().isoformat(timespec="seconds")
        source = workflow.get("source")
        source_meta = source if isinstance(source, dict) else {}
        try:
            manifest = build_workflow_manifest(
                name=display,
                graph=safe_graph,
                version=str(version or ""),
                description=str(description or ""),
                tags=tags,
                pymss_models=requirements,
                uploaded_by=username,
                uploaded_at=uploaded_at,
                lineage_id=trim_text(source_meta.get("lineage_id"), 200)
                or repo_id,
                app_name=config.APP_NAME,
                marker=config.MODELSCOPE_WORKFLOW_MARKER,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        readme = _build_readme(manifest)
        self._set_progress(key, "upload", 10, "上传工作流清单…")

        def on_progress(done: int, total: int, name: str) -> None:
            pct = 10 + (done / total * 89) if total > 0 else 10
            self._set_progress(
                key, "upload", pct, f"上传 {name}（{done}/{total}）", done, total
            )

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._gateway.upload_manifest(
                token=self.get_token(),
                repo_id=repo_id,
                manifest=manifest,
                readme=readme,
                display_name=display,
                on_progress=on_progress,
            ),
        )
        if not result.get("ok"):
            self._set_progress(key, "error", 0, result.get("error", "上传失败"))
            return result
        self._works.mark_workflow_shared(
            workflow_id,
            {
                "origin": "uploaded",
                "repo_id": str(result.get("repo_id") or repo_id),
                "version": manifest["version"],
                "uploaded_at": uploaded_at,
                "author": username,
                "lineage_id": manifest["lineage_id"] or repo_id,
                "remote_name": display,
            },
        )
        try:
            self._gateway.invalidate_cache()
        except Exception:  # noqa: BLE001 - 缓存清理失败不应影响上传结果
            pass
        self._set_progress(key, "done", 100, "完成")
        return result


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return value[:40] or "workflow"


def _build_readme(manifest: dict[str, Any]) -> str:
    tags = "、".join(manifest.get("tags") or [])
    requirements = manifest.get("pymss_models") or []
    lines = [
        f"# {manifest['name']}",
        "",
        f"XB-SVCB AI 翻唱工作流 · v{manifest['version']}",
        "",
    ]
    if manifest.get("description"):
        lines += [manifest["description"], ""]
    if tags:
        lines += [f"标签：{tags}", ""]
    if requirements:
        lines += ["依赖 PyMSS 模型："]
        lines += [f"- {item['name']}" for item in requirements]
        lines += [""]
    lines += [
        f"> 标记: {config.MODELSCOPE_WORKFLOW_MARKER}",
        "",
        "由「XB-SVCB AI 翻唱工具」上传。下载请在软件内「工作流商城」搜索使用。",
        "",
    ]
    return "\n".join(lines)
