"""统一管理随项目分发的模型资产清单。

清单描述两件事：源码/安装包中的自带资产，以及安装后各引擎期望看到的
运行位置。这里默认只检查文件存在性和最小体积；SHA-256 仅在清单已有
摘要，或命令行显式要求时计算，避免应用启动时重新扫描数 GB 的模型。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "xb-svcb.models.v1"
MANIFEST_RELATIVE = Path("assets/models/model-manifest.json")
_CHUNK_SIZE = 1024 * 1024


def manifest_path(root: Path) -> Path:
    return root.resolve() / MANIFEST_RELATIVE


def load_manifest(root: Path) -> dict[str, Any]:
    path = manifest_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return {}
    assets = data.get("assets")
    if not isinstance(assets, list):
        return {}
    return data


def _safe_path(root: Path, raw: str) -> Path | None:
    """Resolve a manifest path and reject paths outside the checkout."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        return None
    base = root.resolve()
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_paths(root: Path, raw: Any) -> list[Path]:
    values: Iterable[Any]
    if isinstance(raw, str):
        values = (raw,)
    elif isinstance(raw, list):
        values = raw
    else:
        values = ()
    return [path for value in values if (path := _safe_path(root, value)) is not None]


def _check_location(
    root: Path,
    asset: dict[str, Any],
    location: str,
    verify_hash: bool,
) -> dict[str, Any]:
    raw_paths = asset.get(location)
    paths = _as_paths(root, raw_paths)
    mode = str(asset.get(f"{location}_mode") or "all").lower()
    required = bool(asset.get("required", True))
    minimum = max(0, int(asset.get("min_bytes") or 0))
    # runtime 位置可能是安装器转换/重命名后的产物（例如 SeedVC RMVPE），
    # 不能默认拿 source 摘要硬比；只有清单显式提供 runtime_sha256 才校验它。
    hash_key = "sha256" if location == "source" else "runtime_sha256"
    expected_hash = str(asset.get(hash_key) or "").strip().lower()
    checks: list[dict[str, Any]] = []

    for path in paths:
        row: dict[str, Any] = {"path": str(path), "relative": str(path.relative_to(root.resolve()))}
        try:
            if not path.is_file():
                row["status"] = "missing"
            else:
                row["bytes"] = path.stat().st_size
                if row["bytes"] < minimum:
                    row["status"] = "too_small"
                elif verify_hash and expected_hash:
                    actual = _sha256(path)
                    row["sha256"] = actual
                    row["status"] = "ok" if actual == expected_hash else "hash_mismatch"
                else:
                    row["status"] = "ok" if expected_hash else "unverified"
        except OSError as exc:
            row["status"] = "error"
            row["error"] = str(exc)
        checks.append(row)

    if not checks:
        status = "invalid_path"
    elif mode == "any":
        status = "ok" if any(item["status"] in {"ok", "unverified"} for item in checks) else checks[0]["status"]
    else:
        status = "ok" if all(item["status"] == "ok" for item in checks) else next(
            item["status"] for item in checks if item["status"] != "ok"
        )
    if status == "missing" and not required:
        status = "optional_missing"
    return {
        "status": status,
        "required": required,
        "mode": mode,
        "minimum_bytes": minimum,
        "expected_sha256": expected_hash or None,
        "files": checks,
    }


def inspect_manifest(
    root: Path,
    location: str = "source",
    verify_hash: bool = False,
) -> dict[str, Any]:
    """检查模型清单，返回稳定的 JSON-friendly 结果。"""
    root = root.resolve()
    manifest = load_manifest(root)
    if not manifest:
        return {
            "ok": False,
            "schema": SCHEMA,
            "location": location,
            "error": f"模型清单不存在或 schema 不匹配: {manifest_path(root)}",
            "assets": [],
            "summary": {"total": 0, "ok": 0, "missing": 0, "unverified": 0},
        }
    if location not in {"source", "runtime", "both"}:
        raise ValueError("location 必须是 source、runtime 或 both")

    rows: list[dict[str, Any]] = []
    locations = ("source", "runtime") if location == "both" else (location,)
    for raw_asset in manifest.get("assets", []):
        if not isinstance(raw_asset, dict):
            continue
        base = {
            "id": str(raw_asset.get("id") or ""),
            "engine": str(raw_asset.get("engine") or ""),
            "description": str(raw_asset.get("description") or ""),
        }
        for selected in locations:
            result = {**base, "location": selected}
            result.update(_check_location(root, raw_asset, selected, verify_hash))
            rows.append(result)

    bad = {"missing", "too_small", "hash_mismatch", "invalid_path", "error"}
    required_rows = [row for row in rows if row["required"]]
    summary = {
        "total": len(rows),
        "ok": sum(row["status"] == "ok" for row in rows),
        "missing": sum(row["status"] in bad for row in rows),
        "unverified": sum(row["status"] == "unverified" for row in rows),
        "optional_missing": sum(row["status"] == "optional_missing" for row in rows),
    }
    return {
        "ok": bool(required_rows) and not any(row["status"] in bad for row in required_rows),
        "schema": manifest.get("schema"),
        "manifest": str(manifest_path(root)),
        "location": location,
        "hashes_checked": verify_hash,
        "assets": rows,
        "external_requirements": manifest.get("external_requirements", []),
        "summary": summary,
    }


def engine_asset_status(root: Path, engine: str, location: str = "runtime") -> dict[str, Any]:
    """返回某个引擎的轻量状态，供系统状态 API 使用。"""
    result = inspect_manifest(root, location=location, verify_hash=False)
    rows = [row for row in result.get("assets", []) if row.get("engine") == engine]
    required = [row for row in rows if row.get("required")]
    blocking = {"missing", "too_small", "hash_mismatch", "invalid_path", "error"}
    return {
        "ok": bool(required) and not any(row.get("status") in blocking for row in required),
        "engine": engine,
        "location": location,
        "assets": rows,
        "required": len(required),
        # 未配置摘要时仍可确认文件存在；ready 表示可用性，不表示已做哈希校验。
        "ready": sum(row.get("status") in {"ok", "unverified"} for row in required),
    }


def _write_hashes(root: Path) -> int:
    path = manifest_path(root)
    manifest = load_manifest(root)
    if not manifest:
        raise RuntimeError(f"模型清单不存在或 schema 不匹配: {path}")
    changed = 0
    for asset in manifest["assets"]:
        if not isinstance(asset, dict):
            continue
        source_paths = _as_paths(root, asset.get("source"))
        if len(source_paths) != 1 or not source_paths[0].is_file():
            continue
        asset["sha256"] = _sha256(source_paths[0])
        changed += 1
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="检查 XB-SVCB 模型资产清单")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--location", choices=("source", "runtime", "both"), default="source")
    parser.add_argument("--verify-hash", action="store_true", help="校验清单中已有的 SHA-256")
    parser.add_argument("--write-hashes", action="store_true", help="为现有自带文件计算并写入 SHA-256")
    parser.add_argument("--strict", action="store_true", help="发现必需资产缺失/损坏时返回非零")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    if args.write_hashes:
        count = _write_hashes(args.root.resolve())
        if not args.json:
            print(f"已写入 {count} 个模型文件的 SHA-256")
    result = inspect_manifest(args.root.resolve(), args.location, args.verify_hash)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            f"模型资产检查 [{args.location}]："
            f"{summary.get('ok', 0)} ok，{summary.get('missing', 0)} 个必需项异常，"
            f"{summary.get('unverified', 0)} 个未做哈希校验"
        )
        for row in result.get("assets", []):
            print(f"[{row.get('status')}] {row.get('engine')}: {row.get('id')}")
    return 0 if not args.strict or result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
