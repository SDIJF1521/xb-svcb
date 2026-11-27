"""PyMSS music source separation adapter.

PyMSS is deliberately run in a child process. Its torch/model dependencies are
large and should not be imported into the desktop application's Python process.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config
from infrastructure.persistent_worker import PersistentInferenceSession
from infrastructure.pymss_catalog_meta import attach_model_stems, model_stems
from infrastructure.uvr_tool import SeparationResult


class PymssTool:
    # PyMSS keeps a full Torch model in the child process.  Serializing jobs
    # avoids intermittent GPU OOM/context failures when two cover jobs start
    # at the same time (the UI can still queue them normally).
    _separate_lock = threading.RLock()

    _FALLBACK_CATALOG = [
        {
            "name": "bs_roformer_voc_hyperacev2.ckpt",
            "architecture": "bs_roformer",
            "supported": True,
            "category": "vocal/vocal_extraction",
            "purpose": config.PYMSS_PURPOSE_VOCAL,
            "purpose_label": config.PYMSS_PURPOSE_LABELS[config.PYMSS_PURPOSE_VOCAL],
            "target_stem": "vocals",
            "primary_stem": "vocals",
            "stems": ["vocals", "instrumental"],
            "size_bytes": 0,
            "downloaded": False,
        },
        {
            "name": "UVR-DeEcho-DeReverb.pth",
            "architecture": "vr_deecho_dereverb",
            "supported": True,
            "category": "legacy_vr/vr_deecho_dereverb",
            "purpose": config.PYMSS_PURPOSE_DEREVERB,
            "purpose_label": config.PYMSS_PURPOSE_LABELS[config.PYMSS_PURPOSE_DEREVERB],
            "target_stem": "vocals",
            "primary_stem": "No Reverb",
            "stems": ["No Reverb", "Reverb"],
            "size_bytes": 0,
            "downloaded": False,
        },
    ]

    def __init__(self) -> None:
        self._download_lock = threading.RLock()
        self._download_jobs: dict[str, dict[str, Any]] = {}
        # catalog 解析只依赖 PyMSS 安装目录里的 model_catalog.json。缓存解析结果，
        # 避免翻唱页、工作流页、实时页和编辑器反复启动子进程读取同一份目录。
        self._catalog_lock = threading.RLock()
        self._catalog_payloads: dict[bool, list[dict[str, Any]]] = {}
        # PyMSS 版本号需要启动其解释器；系统状态每 30 秒轮询一次，不能每次都重新导入 torch。
        self._version_lock = threading.RLock()
        self._version_cache: str | None = None
        self._version_loaded = False

    @property
    def available(self) -> bool:
        return config.pymss_environment_ready()

    def status(self, model: str = "") -> str:
        return config.pymss_status(model)

    def model_ready(self, model: str = "") -> bool:
        """指定 catalog 模型的权重是否已经下载（端口方法）。"""
        return config.pymss_model_ready(model)

    def downloaded_model_stems(self) -> set[str]:
        """一次扫描目录，返回已下载模型的 stem 集合（端口方法）。"""
        return config.pymss_downloaded_model_stems()

    @staticmethod
    def declared_stems(model: str = "") -> list[str]:
        """模型 yaml 里声明的输出音轨（只读配置，不加载权重）。"""
        return model_stems(model, config.PYMSS_MODEL_DIR)

    def version(self) -> str | None:
        if not self.available:
            return None
        with self._version_lock:
            if self._version_loaded:
                return self._version_cache
        value = self._read_package_version()
        if not value:
            value = "PyMSS"
            try:
                result = subprocess.run(
                    [str(config.PYMSS_PYTHON), "-c", "import pymss; print(getattr(pymss, '__version__', 'pymss'))"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                    **config.subprocess_no_window(),
                )
                lines = (result.stdout or "").strip().splitlines()
                if result.returncode == 0 and lines:
                    value = lines[-1]
            except (OSError, subprocess.SubprocessError):
                value = "PyMSS"
        with self._version_lock:
            self._version_cache = value
            self._version_loaded = True
        return value

    @staticmethod
    def _read_package_version() -> str | None:
        """Read the installed PyMSS version from dist-info without importing torch."""
        python = config.PYMSS_PYTHON
        if not python:
            return None
        root = python.parent.parent
        try:
            candidates = [root / "Lib" / "site-packages"]
            candidates.extend(root.glob("lib/python*/site-packages"))
        except OSError:
            return None
        for site_packages in candidates:
            if not site_packages.is_dir():
                continue
            try:
                metadata_files = sorted(site_packages.glob("pymss-*.dist-info/METADATA"))
            except OSError:
                continue
            for metadata in metadata_files:
                try:
                    for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.lower().startswith("version:"):
                            version = line.split(":", 1)[1].strip()
                            return version or None
                except OSError:
                    continue
        return None

    @staticmethod
    def _purpose_for_categories(primary: str, secondary: str) -> str:
        pair = (str(primary or "").strip().lower(), str(secondary or "").strip().lower())
        for purpose, categories in config.PYMSS_ALLOWED_MODEL_CATEGORIES.items():
            if pair in categories:
                return purpose
        # Catalog revisions have used several names for dereverb models.
        if "dereverb" in pair[1] or "deecho" in pair[1] or "denoise" in pair[1]:
            return config.PYMSS_PURPOSE_DEREVERB
        if pair == ("legacy_vr", "vr_backing_vocal"):
            return config.PYMSS_PURPOSE_HARMONY
        return ""

    @classmethod
    def _fallback_models(cls, purpose: str = "") -> list[dict[str, Any]]:
        return [
            {**item, "downloaded": bool(config.pymss_model_ready(item["name"]))}
            for item in cls._FALLBACK_CATALOG
            if not purpose or item.get("purpose") == purpose
        ]

    def list_models(
        self,
        supported_only: bool = True,
        purpose: str = "",
        include_all: bool = False,
    ) -> list[dict[str, Any]]:
        """读取 PyMSS catalog，并补充模型声明的输出音轨（stems）。"""
        return attach_model_stems(
            self._list_models(
                supported_only=supported_only,
                purpose=purpose,
                include_all=include_all,
            ),
            config.PYMSS_MODEL_DIR,
        )

    def _list_models(
        self,
        supported_only: bool = True,
        purpose: str = "",
        include_all: bool = False,
    ) -> list[dict[str, Any]]:
        """Read the installed PyMSS catalog without importing it in the app."""
        purpose = str(purpose or "").strip().lower()
        if purpose == config.PYMSS_PURPOSE_HARMONY_LEGACY:
            purpose = config.PYMSS_PURPOSE_DEREVERB
        if purpose and purpose not in config.PYMSS_ALLOWED_MODEL_CATEGORIES:
            return []
        if not self.available:
            return self._fallback_models(purpose)
        payload = self._catalog_payload(bool(supported_only))
        if payload is None:
            return self._fallback_models(purpose)
        # 一次扫描模型目录即可判断所有条目的下载状态；逐条调用
        # ``pymss_model_ready`` 会把整个目录重复 rglob 三百多次。
        downloaded_stems = config.pymss_downloaded_model_stems()
        filtered: list[dict[str, Any]] = []
        for item in payload:
            entry = dict(item)
            category = str(entry.get("category") or "").strip()
            primary = str(entry.get("primary_category") or "").strip()
            secondary = str(entry.get("secondary_category") or "").strip()
            if (not primary or not secondary) and "/" in category:
                primary, secondary = (part.strip() for part in category.split("/", 1))
            item_purpose = self._purpose_for_categories(primary, secondary)
            if not include_all and (not item_purpose or secondary.casefold() == "vr_backing_vocal"):
                continue
            entry["purpose"] = item_purpose
            entry["purpose_label"] = config.PYMSS_PURPOSE_LABELS.get(item_purpose, "")
            entry["category_label"] = " / ".join(
                part for part in (
                    str(entry.get("primary_category_label") or "").strip(),
                    str(entry.get("secondary_category_label") or "").strip(),
                ) if part
            ) or category
            name = str(entry.get("name") or "").strip()
            entry["downloaded"] = bool(name) and Path(name).stem.casefold() in downloaded_stems
            if not purpose or item_purpose == purpose:
                filtered.append(entry)
        return filtered

    def _catalog_payload(self, supported_only: bool) -> list[dict[str, Any]] | None:
        """Cached catalog rows; only the static catalog is cached, download state is not."""
        with self._catalog_lock:
            cached = self._catalog_payloads.get(supported_only)
        if cached is not None:
            return cached
        payload = self._read_catalog_json(supported_only)
        if payload is None:
            payload = self._read_catalog_runtime(supported_only)
        if payload is not None:
            with self._catalog_lock:
                self._catalog_payloads[supported_only] = payload
        return payload

    @staticmethod
    def _catalog_python_code() -> str:
        """Lightweight catalog loader: read the JSON shipped with PyMSS directly.

        Importing ``pymss`` pulls in torch, which costs several seconds on every
        catalog or status refresh.  The catalog itself is a plain JSON file, so
        reading it in a short-lived interpreter is enough.
        """
        return (
            "import sysconfig,pathlib; "
            "path=pathlib.Path(sysconfig.get_paths()['purelib'])/'pymss'/'resources'/'model_catalog.json'; "
            "print(path.read_text(encoding='utf-8'))"
        )

    def _read_catalog_json(self, supported_only: bool) -> list[dict[str, Any]] | None:
        try:
            result = subprocess.run(
                [str(config.PYMSS_PYTHON), "-c", self._catalog_python_code()],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        # The JSON file is pretty-printed, so parse the whole payload instead of
        # the last line (warnings, if any, appear before the opening brace).
        text = str(result.stdout or "")
        start = text.find("{")
        if start < 0:
            return None
        try:
            data = json.loads(text[start:])
        except json.JSONDecodeError:
            return None
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return None
        rows: list[dict[str, Any]] = []
        for raw in models:
            if not isinstance(raw, dict):
                continue
            supported = bool(raw.get("supported", True))
            if supported_only and not supported:
                continue
            primary = str(raw.get("primary_category") or "").strip()
            secondary = str(raw.get("secondary_category") or "").strip()
            category = str(raw.get("category_path") or "").strip()
            if not category and primary:
                category = f"{primary}/{secondary}" if secondary else primary
            try:
                size_bytes = int(raw.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size_bytes = 0
            rows.append(
                {
                    "name": str(raw.get("name") or ""),
                    "architecture": str(raw.get("architecture") or ""),
                    "supported": supported,
                    "category": category,
                    "primary_category": primary,
                    "primary_category_label": str(raw.get("primary_category_cn") or ""),
                    "secondary_category": secondary,
                    "secondary_category_label": str(raw.get("secondary_category_cn") or ""),
                    "purpose": secondary,
                    "target_stem": str(raw.get("target_stem") or ""),
                    "size_bytes": size_bytes,
                }
            )
        return rows

    def _read_catalog_runtime(self, supported_only: bool) -> list[dict[str, Any]] | None:
        """Fallback for PyMSS builds without a readable model_catalog.json."""
        code = (
            "import json,pymss; "
            f"rows=pymss.list_models(supported={bool(supported_only)!r}); "
            "print(json.dumps([{'name':x.name,'architecture':getattr(x,'architecture',''),"
            "'supported':bool(getattr(x,'supported',True)),'category':getattr(x,'category_path',''),"
            "'primary_category':getattr(x,'primary_category',''),'primary_category_label':getattr(x,'primary_category_cn',''),"
            "'secondary_category':getattr(x,'secondary_category',''),'secondary_category_label':getattr(x,'secondary_category_cn',''),"
            "'purpose':getattr(x,'secondary_category',''),'target_stem':getattr(x,'target_stem',''),"
            "'size_bytes':int(getattr(x,'size_bytes',0) or 0)} for x in rows], ensure_ascii=False))"
        )
        try:
            result = subprocess.run(
                [str(config.PYMSS_PYTHON), "-c", code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                **config.subprocess_no_window(),
            )
            if result.returncode != 0:
                return None
            # Torch/modelscope may print warnings before the JSON payload.
            payload = self._last_json_payload(result.stdout)
            return payload if isinstance(payload, list) else None
        except (OSError, subprocess.SubprocessError):
            return None

    @staticmethod
    def _last_json_payload(output: str | None) -> Any:
        """Parse the last JSON line emitted by a noisy isolated runtime."""
        lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    def download_model(
        self,
        model: str,
        out_dir: Path | None = None,
        purpose: str = "",
        on_progress: Callable[[int, str], None] | None = None,
    ) -> dict[str, Any]:
        """Download one catalog model through PyMSS's ModelScope downloader.

        ``on_progress(percent, message)`` receives live progress parsed from the
        child process. Without it the downloader is silent, which made the UI
        bar sit at one value for the whole (multi-minute) download and then jump
        to 100%.
        """
        if not self.available:
            return {"ok": False, "error": "PyMSS 环境未安装"}
        model_dir = config.PYMSS_MODEL_DIR
        if model_dir is None:
            return {"ok": False, "error": "PyMSS 模型目录未配置"}
        name = str(model or config.PYMSS_DEFAULT_MODEL).strip()
        if not name:
            return {"ok": False, "error": "未指定 PyMSS 模型"}
        if purpose == config.PYMSS_PURPOSE_HARMONY_LEGACY:
            purpose = config.PYMSS_PURPOSE_DEREVERB
        if purpose and purpose not in config.PYMSS_ALLOWED_MODEL_CATEGORIES:
            return {"ok": False, "error": "不支持的 PyMSS 模型用途"}
        # Downloads are available for every supported PyMSS catalog category.
        # ``purpose`` remains available for legacy callers that want to narrow
        # the lookup, while the model hub can download any listed capability.
        catalog = self.list_models(purpose=purpose, include_all=not bool(purpose))
        requested = name.casefold()
        exact = []
        for item in catalog:
            full = str(item.get("name") or "").strip()
            stem = Path(full).stem
            if requested in {full.casefold(), stem.casefold()}:
                exact.append(full)
        candidates = exact or [
            str(item.get("name") or "").strip()
            for item in catalog
            if str(item.get("name") or "").strip().casefold().startswith(requested)
            or Path(str(item.get("name") or "")).stem.casefold().startswith(requested)
        ]
        candidates = sorted({candidate for candidate in candidates if candidate})
        if len(candidates) == 1:
            name = candidates[0]
        else:
            return {"ok": False, "error": "该模型不属于受支持的 PyMSS 人声处理类别"}
        expected_bytes = 0
        for item in catalog:
            if str(item.get("name") or "") == name:
                try:
                    expected_bytes = max(0, int(item.get("size_bytes") or 0))
                except (TypeError, ValueError):
                    expected_bytes = 0
                break
        cmd = [
            str(config.PYMSS_PYTHON), str(config.PYMSS_WORKER),
            "--download", "--model", name,
            "--model-dir", str(model_dir),
        ]
        if out_dir:
            cmd.extend(["--out-dir", str(out_dir)])
        if expected_bytes > 0:
            cmd.extend(["--expected-bytes", str(expected_bytes)])
        lines: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"PyMSS 模型下载启动失败: {exc}"}
        timed_out = False
        try:
            timed_out = self._pump_download_output(
                proc, lines, on_progress, timeout=7200.0
            )
        finally:
            if proc.poll() is None:
                proc.kill()
        returncode = proc.wait()
        output = "\n".join(lines).strip()
        if timed_out:
            return {"ok": False, "error": "PyMSS 模型下载超时"}
        if returncode != 0:
            return {"ok": False, "error": self._error_tail(output, "")}
        marker_dir = model_dir / ".xb-downloaded"
        try:
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / f"{Path(name).stem.lower()}.json"
            downloaded_files: list[str] = []
            payload: dict[str, Any] = {}
            for line in reversed(lines):
                text = line.strip()
                if not text.startswith("{"):
                    continue
                try:
                    candidate = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    payload = candidate
                    break
            files = payload.get("files") if isinstance(payload, dict) else None
            if isinstance(files, list):
                downloaded_files = [str(entry) for entry in files if str(entry or "").strip()]
            marker_data: dict[str, Any] = {"model": name, "source": "modelscope"}
            if downloaded_files:
                marker_data["files"] = downloaded_files
            marker.write_text(
                json.dumps(marker_data, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return {"ok": True, "model": name, "output": output}

    @staticmethod
    def _pump_download_output(
        proc: subprocess.Popen,
        lines: list[str],
        on_progress: Callable[[int, str], None] | None,
        *,
        timeout: float,
    ) -> bool:
        """Stream the downloader's merged output; return True when it timed out.

        PyMSS/tqdm refresh progress bars with carriage returns and no newline,
        so read raw bytes and split on both ``\\r`` and ``\\n`` instead of using
        text ``readline()`` (which would block until the download ends).
        """
        started = time.monotonic()
        buffer = b""
        stream = proc.stdout
        fd = stream.fileno() if stream is not None else -1
        while True:
            if time.monotonic() - started > timeout:
                return True
            try:
                chunk = os.read(fd, 8192) if fd >= 0 else b""
            except OSError:
                chunk = b""
            if not chunk:
                break
            buffer += chunk
            while True:
                indexes = [index for index in (buffer.find(b"\r"), buffer.find(b"\n")) if index >= 0]
                if not indexes:
                    break
                index = min(indexes)
                raw, buffer = buffer[:index], buffer[index + 1:]
                PymssTool._consume_download_line(
                    raw.decode("utf-8", "replace"), lines, on_progress
                )
        if buffer:
            PymssTool._consume_download_line(
                buffer.decode("utf-8", "replace"), lines, on_progress
            )
        return False

    @staticmethod
    def _consume_download_line(
        raw: str,
        lines: list[str],
        on_progress: Callable[[int, str], None] | None,
    ) -> None:
        line = str(raw or "").strip()
        if not line:
            return
        lines.append(line)
        if len(lines) > 80:
            del lines[:-80]
        if on_progress is None or not line.startswith("PYMSS_PROGRESS\t"):
            return
        PymssTool._report_download_progress(line, on_progress)

    @staticmethod
    def _report_download_progress(
        line: str, on_progress: Callable[[int, str], None]
    ) -> None:
        parts = line.split("\t")
        if len(parts) < 4:
            return
        try:
            pct = int(parts[1])
            done = int(parts[2])
            total = int(parts[3])
        except (TypeError, ValueError):
            return
        detail = parts[4] if len(parts) > 4 else ""
        try:
            on_progress(pct, PymssTool._download_message(pct, done, total, detail))
        except Exception:  # noqa: BLE001 - a UI callback must not fail the download
            pass

    @staticmethod
    def _download_message(pct: int, done: int, total: int, detail: str = "") -> str:
        def human(value: int) -> str:
            size = float(max(0, int(value)))
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024.0 or unit == "GB":
                    return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} GB"

        label = f"正在下载 {pct}%" if pct >= 0 else "正在下载"
        if done > 0 and total > 0:
            label += f"（{human(done)} / {human(total)}）"
        elif done > 0:
            label += f"（{human(done)}）"
        return label

    def start_download_model(self, model: str, purpose: str = "") -> dict[str, Any]:
        """Start a PyMSS model download without blocking the UI bridge."""
        name = str(model or "").strip()
        if not self.available:
            return {"ok": False, "error": "PyMSS 环境未安装"}
        key = f"pymss:{Path(name).stem.lower()}"
        with self._download_lock:
            existing = self._download_jobs.get(key)
            if existing and existing.get("status") == "running":
                return {"ok": True, "key": key, "already": True}
            self._download_jobs[key] = {
                "key": key,
                "model": name,
                "status": "running",
                "pct": 1,
                "message": "已加入后台下载",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "error": None,
            }

        def runner() -> None:
            def on_progress(pct: int, message: str) -> None:
                with self._download_lock:
                    job = self._download_jobs.get(key)
                    if not job or job.get("status") != "running":
                        return
                    if pct >= 0:
                        # Reserve the last 5% for marker/verification work so the
                        # bar reaches 100% only when the model is actually usable.
                        job["pct"] = max(
                            int(job.get("pct") or 0),
                            min(95, 5 + int(round(pct * 0.9))),
                        )
                    if message:
                        job["message"] = message

            try:
                with self._download_lock:
                    self._download_jobs[key]["message"] = "正在准备模型下载…"
                    self._download_jobs[key]["pct"] = 5
                result = self.download_model(name, purpose=purpose, on_progress=on_progress)
                with self._download_lock:
                    job = self._download_jobs[key]
                    job.update(
                        status="done" if result.get("ok") else "failed",
                        pct=100 if result.get("ok") else max(5, int(job.get("pct") or 5)),
                        message="下载完成" if result.get("ok") else "下载失败",
                        result=result,
                        error=result.get("error"),
                    )
            except Exception as exc:  # noqa: BLE001 - background boundary
                with self._download_lock:
                    self._download_jobs[key].update(
                        status="failed", message="下载失败", error=str(exc)
                    )

        threading.Thread(target=runner, daemon=True, name=f"pymss-download-{Path(name).stem}").start()
        return {"ok": True, "key": key}

    def download_progress(self, key: str = "") -> dict[str, Any]:
        with self._download_lock:
            job = self._download_jobs.get(str(key or ""))
            return dict(job) if job else {"key": key, "status": "idle", "pct": 0, "message": ""}

    def download_jobs(self) -> list[dict[str, Any]]:
        with self._download_lock:
            return [dict(job) for job in self._download_jobs.values()]

    @staticmethod
    def _download_marker_path(model_dir: Path, model: str) -> Path:
        stem = Path(str(model or "")).stem.lower()
        return model_dir / ".xb-downloaded" / f"{stem}.json"

    @staticmethod
    def _normalize_cache_path(model_dir: Path, raw: str) -> Path | None:
        text = str(raw or "").strip()
        if not text:
            return None
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = model_dir / path
        try:
            resolved = path.resolve(strict=False)
            root = model_dir.resolve(strict=False)
            if resolved == root or root in resolved.parents:
                return resolved
        except OSError:
            return None
        return None

    @staticmethod
    def _matches_model_artifact(path: Path, stem: str) -> bool:
        if not stem:
            return False
        name = path.name.casefold()
        stem_name = path.stem.casefold()
        if name == f"{stem}.json" and path.parent.name.casefold() == ".xb-downloaded":
            return True
        if name == f"{stem}.pymss_state_dict.pt":
            return True
        if stem_name == stem:
            return True
        if stem_name.startswith(f"{stem}.") or stem_name.startswith(f"{stem}-") or stem_name.startswith(f"{stem}_"):
            return True
        return path.parent.name.casefold() == stem

    def delete_model(self, model: str) -> bool:
        model_name = str(model or "").strip()
        if not model_name:
            return False
        model_dir = config.PYMSS_MODEL_DIR
        if not model_dir or not model_dir.exists():
            return False
        stem = Path(model_name).stem.casefold()
        if not stem:
            return False

        with self._download_lock:
            running = [
                job
                for job in self._download_jobs.values()
                if job.get("status") == "running"
                and Path(str(job.get("model") or "")).stem.casefold() == stem
            ]
        if running:
            return False
        with self._download_lock:
            for key, job in list(self._download_jobs.items()):
                if Path(str(job.get("model") or "")).stem.casefold() == stem and job.get("status") != "running":
                    del self._download_jobs[key]

        marker = self._download_marker_path(model_dir, model_name)
        candidates: list[Path] = []
        if marker.is_file():
            candidates.append(marker)
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                payload = {}
            files = payload.get("files") if isinstance(payload, dict) else None
            if isinstance(files, list):
                for entry in files:
                    resolved = self._normalize_cache_path(model_dir, str(entry))
                    if resolved and resolved not in candidates:
                        candidates.append(resolved)

        try:
            for path in model_dir.rglob("*"):
                if path.is_file() and self._matches_model_artifact(path, stem):
                    if path not in candidates:
                        candidates.append(path)
        except OSError:
            return False

        deleted = False
        for path in sorted({candidate.resolve(strict=False) for candidate in candidates}, key=lambda item: len(item.parts), reverse=True):
            if not path.exists():
                continue
            try:
                path.unlink()
                deleted = True
            except OSError:
                return False

        try:
            for path in sorted(
                (candidate for candidate in model_dir.rglob("*") if candidate.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                if path == model_dir:
                    continue
                try:
                    next(path.iterdir())
                except StopIteration:
                    try:
                        path.rmdir()
                    except OSError:
                        pass
        except OSError:
            pass

        return deleted

    def clear_download_job(self, key: str) -> bool:
        """Remove a finished/failed PyMSS download task from the session list."""
        with self._download_lock:
            job = self._download_jobs.get(str(key or ""))
            if not job or job.get("status") == "running":
                return False
            del self._download_jobs[str(key)]
            return True

    @staticmethod
    def _is_cover_vocal_entry(entry: dict[str, Any]) -> bool:
        """Whether a catalog row can provide vocals for a full-song cover.

        Catalog purpose is not reliable: some useful two-way models
        (``instvox_duality``) and karaoke/backing-vocal models are not in the
        legacy vocal_extraction allow-list. Prefer target stems, while still
        rejecting duet, chorus, speech, multi-stem and pure-instrumental rows.
        """
        purpose = str(entry.get("purpose") or "").strip().lower()
        if purpose in {
            config.PYMSS_PURPOSE_DEREVERB,
            config.PYMSS_PURPOSE_HARMONY_LEGACY,
        }:
            return False
        description = " ".join(
            str(entry.get(key) or "")
            for key in (
                "category_label",
                "primary_category_label",
                "secondary_category_label",
                "purpose_label",
            )
        ).lower()
        if re.search(
            r"双人|二重唱|对唱|合唱|男女声|男声|女声|语音|说话|多轨|单乐器|"
            r"混响|回声|duet|duo|chorus|male.?female|speech|speaker|multi|"
            r"instrument|guitar|bass|drum|piano|reverb|echo|dereverb|deecho|denoise",
            description,
        ):
            return False

        raw_stems = entry.get("target_stems") or entry.get("stems") or []
        if isinstance(raw_stems, str):
            raw_stems = re.split(r"[/,;|]", raw_stems)
        stems = [
            str(stem or "").strip().lower()
            for stem in raw_stems
            if str(stem or "").strip()
        ]
        name = str(entry.get("name") or "").lower()
        unsafe_name = re.search(
            r"(^|[^a-z0-9])(inst|instrumental|multi|speech|speaker|male|female|"
            r"duet|guitar|bass|drum|piano)([^a-z0-9]|$)",
            name,
        )
        instvox = re.search(
            r"instvox|inst_vox|instrumental[_-]?vocal|duality",
            name,
        )
        if unsafe_name and not instvox:
            return False
        if not stems:
            # A few catalog revisions / test doubles expose only a name. If
            # there is no category metadata at all, keep the historical
            # behavior and let the requested vocal purpose through; otherwise
            # require a vocal hint in the description.
            if purpose == config.PYMSS_PURPOSE_VOCAL:
                return True
            if not description.strip():
                return True
            return bool(re.search(r"vocal|voice|人声", description))
        if len(stems) > 2:
            return False
        if not any(re.search(r"vocal|voice|人声", stem) for stem in stems):
            return False
        forbidden = (
            "male", "female", "speech", "speaker", "dialog", "duet",
            "bass", "drum", "guitar", "piano", "other", "multi",
            "男声", "女声", "语音", "说话", "和声", "卡拉", "吉他",
            "贝斯", "鼓", "钢琴", "多轨",
        )
        if any(word in stem for stem in stems for word in forbidden):
            return False
        has_accompaniment = any(
            re.search(r"instrument|accompani|inst$|伴奏", stem) for stem in stems
        )
        return len(stems) == 1 or has_accompaniment

    def _resolve_model(
        self,
        model: str,
        purpose: str,
    ) -> tuple[str, dict[str, Any], str]:
        """Resolve one catalog model and normalize its purpose."""
        model_name = str(model or config.PYMSS_DEFAULT_MODEL).strip()
        model_purpose = str(purpose or config.PYMSS_PURPOSE_VOCAL).strip().lower()
        if model_purpose == config.PYMSS_PURPOSE_HARMONY_LEGACY:
            model_purpose = config.PYMSS_PURPOSE_DEREVERB
        if model_purpose not in {*config.PYMSS_ALLOWED_MODEL_CATEGORIES, "generic"}:
            raise RuntimeError("不支持的 PyMSS 模型用途")
        # Vocal separation needs the complete catalog: useful two-way models
        # may have an empty catalog purpose but valid vocals/instrumental stems.
        include_all = model_purpose in {"generic", config.PYMSS_PURPOSE_VOCAL}
        catalog = self.list_models(
            purpose="" if include_all else model_purpose,
            include_all=include_all,
        )
        model_aliases: dict[str, str] = {}
        catalog_by_name: dict[str, dict[str, Any]] = {}
        for item in catalog:
            full = str(item.get("name") or "").strip()
            if not full:
                continue
            model_aliases[full.casefold()] = full
            model_aliases[Path(full).stem.casefold()] = full
            catalog_by_name[full.casefold()] = item
        requested_model = model_name.casefold()
        resolved = model_aliases.get(requested_model)
        if resolved is None:
            matches = sorted(
                {
                    full
                    for alias, full in model_aliases.items()
                    if alias.startswith(requested_model)
                }
            )
            if len(matches) == 1:
                resolved = matches[0]
        if not resolved:
            raise RuntimeError("该模型不属于受支持的 PyMSS 人声处理类别")
        entry = catalog_by_name.get(resolved.casefold(), {})
        if model_purpose == config.PYMSS_PURPOSE_VOCAL and not self._is_cover_vocal_entry(entry):
            raise RuntimeError("该模型不属于受支持的 PyMSS 人声处理类别")
        return resolved, entry, model_purpose

    def open_realtime_session(
        self,
        model: str = "",
        device: str = "auto",
        out_dir: Path | None = None,
        log_file: Path | None = None,
        *,
        purpose: str = "",
        primary_stem: str = "",
    ) -> PersistentInferenceSession:
        """Keep one PyMSS model loaded for per-block live separation."""
        if not self.available:
            raise RuntimeError("PyMSS 环境未安装，无法启动实时人声分离")
        model_dir = config.PYMSS_MODEL_DIR
        if model_dir is None:
            raise RuntimeError("PyMSS 模型目录未配置")
        model_name, model_entry, model_purpose = self._resolve_model(model, purpose)
        if not config.pymss_model_ready(model_name):
            raise RuntimeError(f"PyMSS 模型未下载: {model_name}")
        requested = str(device or "auto").strip().lower()
        aliases = {"gpu": "auto", "dml": "directml", "hip": "rocm", "amd": "rocm", "rocm10": "rocm"}
        requested = aliases.get(requested, requested)
        if requested == "directml":
            raise RuntimeError("PyMSS 的 AMD 加速需要 ROCm，不支持 DirectML")
        if requested not in {"auto", "cuda", "rocm", "cpu", "mps", "mlx"}:
            raise RuntimeError(f"不支持的 PyMSS 推理设备: {device}")
        directory = Path(out_dir or config.TEMP_DIR / "realtime-pymss")
        directory.mkdir(parents=True, exist_ok=True)
        command = [
            str(config.PYMSS_PYTHON),
            str(config.PYMSS_WORKER),
            "--server",
            "--model", model_name,
            "--model-dir", str(model_dir),
            "--out-dir", str(directory),
            "--device", requested,
            "--purpose", model_purpose,
        ]
        target_stem = str(model_entry.get("target_stem") or "").strip()
        if target_stem:
            command.extend(["--target-stem", target_stem])
        chosen_stem = str(primary_stem or "").strip()
        if chosen_stem:
            command.extend(["--primary-stem", chosen_stem])
        return PersistentInferenceSession(
            command,
            ready_marker="PYMSS_SERVER_READY",
            result_marker="PYMSS_SERVER_RESULT\t",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            log_file=log_file,
            startup_timeout=900.0,
        )

    def separate(
        self,
        src: Path,
        out_dir: Path,
        model: str = "",
        device: str = "auto",
        purpose: str = "",
        primary_stem: str = "",
    ) -> SeparationResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        if not self.available or not src or not Path(src).exists():
            raise RuntimeError("PyMSS 环境未安装或输入音频不存在，请先安装环境并下载模型")
        requested = str(device or "auto").strip().lower()
        aliases = {"gpu": "auto", "dml": "directml", "hip": "rocm", "amd": "rocm", "rocm10": "rocm"}
        requested = aliases.get(requested, requested)
        if requested == "directml":
            raise RuntimeError("PyMSS 的 AMD 加速需要 ROCm，不支持 DirectML")
        if requested not in {"auto", "cuda", "rocm", "directml", "cpu", "mps", "mlx"}:
            raise RuntimeError(f"不支持的 PyMSS 推理设备: {device}")
        model_name, model_entry, model_purpose = self._resolve_model(model, purpose)
        cmd = [
            str(config.PYMSS_PYTHON), str(config.PYMSS_WORKER),
            "--model", model_name,
            "--model-dir", str(config.PYMSS_MODEL_DIR),
            "--input", str(src), "--out-dir", str(out_dir),
            "--device", requested,
        ]
        cmd.extend(["--purpose", model_purpose])
        target_stem = str(model_entry.get("target_stem") or "").strip()
        if target_stem:
            cmd.extend(["--target-stem", target_stem])
        chosen_stem = str(primary_stem or "").strip()
        if chosen_stem:
            # 用户在工作流节点里指定的「主音轨」，优先于 catalog 的默认目标音轨。
            cmd.extend(["--primary-stem", chosen_stem])
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        # ``auto`` is allowed one CPU retry.  This handles transient CUDA/ROCm
        # kernel and VRAM failures without silently changing an explicit device.
        attempts = [requested] if requested != "auto" else ["auto", "cpu"]
        last_stdout = ""
        last_stderr = ""
        with self._separate_lock:
            for attempt_index, attempt_device in enumerate(attempts):
                command = [*cmd]
                command[command.index("--device") + 1] = attempt_device
                try:
                    proc = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=env,
                        timeout=3600,
                        **config.subprocess_no_window(),
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    last_stderr = str(exc)
                    if attempt_index + 1 < len(attempts):
                        continue
                    raise RuntimeError(f"PyMSS 分离子进程启动失败: {exc}") from exc
                last_stdout = proc.stdout or ""
                last_stderr = proc.stderr or ""
                try:
                    with (out_dir / "pymss.log").open("a", encoding="utf-8") as f:
                        f.write("$ " + " ".join(command) + "\n")
                        f.write(last_stdout + "\n")
                        if last_stderr:
                            f.write("----- stderr -----\n" + last_stderr + "\n")
                except OSError:
                    pass
                result = self._read_result(out_dir)
                if proc.returncode == 0 and result and self._result_looks_valid(result):
                    return result
                if attempt_index + 1 < len(attempts):
                    try:
                        (out_dir / "pymss_result.json").unlink(missing_ok=True)
                    except OSError:
                        pass
        raise RuntimeError(f"PyMSS 分离失败: {self._error_tail(last_stdout, last_stderr)}")

    @staticmethod
    def _result_looks_valid(result: SeparationResult) -> bool:
        try:
            path = Path(result.vocals)
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _read_result(out_dir: Path) -> SeparationResult | None:
        path = out_dir / "pymss_result.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        vocals = Path(str(data.get("vocals") or ""))
        instrumental = Path(str(data.get("instrumental") or "")) if data.get("instrumental") else None
        stems = data.get("stems") if isinstance(data.get("stems"), list) else None
        return SeparationResult(
            vocals,
            instrumental,
            simulated=False,
            device=str(data.get("device") or ""),
            stems=stems,
        )

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        lines = [line.strip() for line in ((stderr or "") + "\n" + (stdout or "")).splitlines() if line.strip()]
        return " ".join(lines[-4:]) or "未知错误"
