"""PyMSS music source separation adapter.

PyMSS is deliberately run in a child process. Its torch/model dependencies are
large and should not be imported into the desktop application's Python process.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from infrastructure.uvr_tool import SeparationResult


class PymssTool:
    _FALLBACK_CATALOG = [
        {
            "name": "bs_roformer_voc_hyperacev2.ckpt",
            "architecture": "bs_roformer",
            "supported": True,
            "category": "vocal/vocal_extraction",
            "purpose": config.PYMSS_PURPOSE_VOCAL,
            "purpose_label": config.PYMSS_PURPOSE_LABELS[config.PYMSS_PURPOSE_VOCAL],
            "target_stem": "vocals",
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
            "size_bytes": 0,
            "downloaded": False,
        },
    ]

    def __init__(self) -> None:
        self._download_lock = threading.RLock()
        self._download_jobs: dict[str, dict[str, Any]] = {}

    @property
    def available(self) -> bool:
        return config.pymss_environment_ready()

    def status(self, model: str = "") -> str:
        return config.pymss_status(model)

    def version(self) -> str | None:
        if not self.available:
            return None
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
            value = (result.stdout or "").strip().splitlines()
            return value[-1] if result.returncode == 0 and value else "PyMSS"
        except (OSError, subprocess.SubprocessError):
            return "PyMSS"

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

    def list_models(self, supported_only: bool = True, purpose: str = "") -> list[dict[str, Any]]:
        """Read the installed PyMSS catalog without importing it in the app."""
        purpose = str(purpose or "").strip().lower()
        if purpose == config.PYMSS_PURPOSE_HARMONY_LEGACY:
            purpose = config.PYMSS_PURPOSE_DEREVERB
        if purpose and purpose not in config.PYMSS_ALLOWED_MODEL_CATEGORIES:
            return []
        if not self.available:
            return self._fallback_models(purpose)
        code = (
            "import json,pymss; "
            f"rows=pymss.list_models(supported={bool(supported_only)!r}); "
            "print(json.dumps([{'name':x.name,'architecture':getattr(x,'architecture',''),"
            "'supported':bool(getattr(x,'supported',True)),'category':getattr(x,'category_path',''),"
            "'primary_category':getattr(x,'primary_category',''),'secondary_category':getattr(x,'secondary_category',''),"
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
                return self._fallback_models(purpose)
            payload = json.loads((result.stdout or "{}"))
            if not isinstance(payload, list):
                return self._fallback_models(purpose)
            filtered: list[dict[str, Any]] = []
            for item in payload:
                item_purpose = self._purpose_for_categories(
                    str(item.get("primary_category") or ""),
                    str(item.get("secondary_category") or ""),
                )
                if not item_purpose or (
                    str(item.get("secondary_category") or "").strip().lower()
                    == "vr_backing_vocal"
                ):
                    continue
                item["purpose"] = item_purpose
                item["purpose_label"] = config.PYMSS_PURPOSE_LABELS[item_purpose]
                item["downloaded"] = bool(config.pymss_model_ready(str(item.get("name") or "")))
                if not purpose or item_purpose == purpose:
                    filtered.append(item)
            return filtered
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return self._fallback_models(purpose)

    def download_model(self, model: str, out_dir: Path | None = None, purpose: str = "") -> dict[str, Any]:
        """Download one catalog model through PyMSS's ModelScope downloader."""
        if not self.available:
            return {"ok": False, "error": "PyMSS 环境未安装"}
        name = str(model or config.PYMSS_DEFAULT_MODEL).strip()
        if not name:
            return {"ok": False, "error": "未指定 PyMSS 模型"}
        if purpose == config.PYMSS_PURPOSE_HARMONY_LEGACY:
            purpose = config.PYMSS_PURPOSE_DEREVERB
        if purpose and purpose not in config.PYMSS_ALLOWED_MODEL_CATEGORIES:
            return {"ok": False, "error": "不支持的 PyMSS 模型用途"}
        catalog = self.list_models(purpose=purpose)
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
        cmd = [
            str(config.PYMSS_PYTHON), str(config.PYMSS_WORKER),
            "--download", "--model", name,
            "--model-dir", str(config.PYMSS_MODEL_DIR),
        ]
        if out_dir:
            cmd.extend(["--out-dir", str(out_dir)])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=7200,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"PyMSS 模型下载启动失败: {exc}"}
        if proc.returncode != 0:
            return {"ok": False, "error": self._error_tail(proc.stdout, proc.stderr)}
        marker_dir = config.PYMSS_MODEL_DIR / ".xb-downloaded"
        try:
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / f"{Path(name).stem.lower()}.json"
            marker.write_text(
                json.dumps({"model": name, "source": "modelscope"}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return {"ok": True, "model": name, "output": (proc.stdout or "").strip()}

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
            try:
                with self._download_lock:
                    self._download_jobs[key]["message"] = "正在从模型站下载…"
                    self._download_jobs[key]["pct"] = 10
                result = self.download_model(name, purpose=purpose)
                with self._download_lock:
                    job = self._download_jobs[key]
                    job.update(
                        status="done" if result.get("ok") else "failed",
                        pct=100 if result.get("ok") else job.get("pct", 10),
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

    def clear_download_job(self, key: str) -> bool:
        """Remove a finished/failed PyMSS download task from the session list."""
        with self._download_lock:
            job = self._download_jobs.get(str(key or ""))
            if not job or job.get("status") == "running":
                return False
            del self._download_jobs[str(key)]
            return True

    def separate(
        self, src: Path, out_dir: Path, model: str = "", device: str = "auto", purpose: str = ""
    ) -> SeparationResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        if not self.available or not src or not Path(src).exists():
            raise RuntimeError("PyMSS 环境未安装或输入音频不存在，请先安装环境并下载模型")
        requested = str(device or "auto").strip().lower()
        aliases = {"gpu": "auto", "dml": "directml", "hip": "rocm"}
        requested = aliases.get(requested, requested)
        if requested not in {"auto", "cuda", "rocm", "directml", "cpu", "mps", "mlx"}:
            raise RuntimeError(f"不支持的 PyMSS 推理设备: {device}")
        model_name = str(model or config.PYMSS_DEFAULT_MODEL).strip()
        model_purpose = str(purpose or config.PYMSS_PURPOSE_VOCAL).strip().lower()
        if model_purpose == config.PYMSS_PURPOSE_HARMONY_LEGACY:
            model_purpose = config.PYMSS_PURPOSE_DEREVERB
        if model_purpose not in config.PYMSS_ALLOWED_MODEL_CATEGORIES:
            raise RuntimeError("不支持的 PyMSS 模型用途")
        known = {
            alias
            for item in self.list_models(purpose=model_purpose)
            for alias in (str(item.get("name") or ""), Path(str(item.get("name") or "")).stem)
            if alias
        }
        if not known or model_name not in known:
            raise RuntimeError("该模型不属于受支持的 PyMSS 人声处理类别")
        cmd = [
            str(config.PYMSS_PYTHON), str(config.PYMSS_WORKER),
            "--model", model_name,
            "--model-dir", str(config.PYMSS_MODEL_DIR),
            "--input", str(src), "--out-dir", str(out_dir),
            "--device", requested,
        ]
        cmd.extend(["--purpose", model_purpose])
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=env, timeout=3600, **config.subprocess_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"PyMSS 分离子进程启动失败: {exc}") from exc
        try:
            with (out_dir / "pymss.log").open("a", encoding="utf-8") as f:
                f.write("$ " + " ".join(cmd) + "\n")
                f.write((proc.stdout or "") + "\n")
                if proc.stderr:
                    f.write("----- stderr -----\n" + proc.stderr + "\n")
        except OSError:
            pass
        result = self._read_result(out_dir)
        if proc.returncode != 0 or not result or not result.vocals.exists():
            raise RuntimeError(f"PyMSS 分离失败: {self._error_tail(proc.stdout, proc.stderr)}")
        return result

    @staticmethod
    def _read_result(out_dir: Path) -> SeparationResult | None:
        path = out_dir / "pymss_result.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        vocals = Path(str(data.get("vocals") or ""))
        instrumental = Path(str(data.get("instrumental") or "")) if data.get("instrumental") else None
        return SeparationResult(vocals, instrumental, simulated=False, device=str(data.get("device") or ""))

    @staticmethod
    def _error_tail(stdout: str | None, stderr: str | None) -> str:
        lines = [line.strip() for line in ((stderr or "") + "\n" + (stdout or "")).splitlines() if line.strip()]
        return " ".join(lines[-4:]) or "未知错误"
