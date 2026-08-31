"""Read-only storage inventory. Never deletes, moves, or deduplicates files.

Sizes are logical bytes, not allocated disk clusters. Hard links are counted by
file identity; exclusive bytes are an upper bound for removing a whole group.
Reparse points/symlinks are not followed. Shared external caches are never safe
to delete merely because this project has no reference to them.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat


GROUPS = (
    ".venv-uvr", ".venv-uvr-demo", "runtimes/core-cu126", "runtimes/core-cu128",
    "runtimes/core-cu128-candidate-old", "app/.venv",
    ".tmp", ".pytest_cache", "assets/runtime/core-cu128", "assets/models",
    "engines", "models", ".git/lfs/objects",
)
MODEL_GROUPS = {"assets/models", "engines", "models"}


def file_identity(path: Path, info) -> tuple:
    if info.st_ino:
        return (info.st_dev, info.st_ino)
    return (str(path.resolve()),)


def files_under(folder: Path, skipped: list, errors: list):
    pending = [folder]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                            skipped.append(str(path))
                        elif stat.S_ISDIR(info.st_mode):
                            pending.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            # DirEntry.stat on Windows may report st_ino/st_nlink=0.
                            # A real stat is needed before claiming hard-link savings.
                            info = path.stat(follow_symlinks=False)
                            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                                skipped.append(str(path))
                                continue
                            yield path, info
                    except OSError as exc:
                        errors.append({"path": str(path), "error": str(exc)})
        except OSError as exc:
            errors.append({"path": str(directory), "error": str(exc)})


def summarize(records: list[dict]) -> dict:
    identities = defaultdict(list)
    children = defaultdict(int)
    for record in records:
        identities[record["identity"]].append(record)
        children[record["child"]] += record["bytes"]
    return {
        "files": len(records), "logical_bytes": sum(r["bytes"] for r in records),
        "unique_file_bytes": sum(rows[0]["bytes"] for rows in identities.values()),
        "exclusive_file_bytes_upper_bound": sum(rows[0]["bytes"] for rows in identities.values()
                                                 if len(rows) == rows[0]["links"]),
        "hardlinked_file_bytes": sum(rows[0]["bytes"] for rows in identities.values() if rows[0]["links"] > 1),
        "children_logical_bytes": dict(sorted(children.items(), key=lambda pair: -pair[1])),
    }


def digest(path: str) -> str:
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def duplicate_models(records: list[dict]) -> list[dict]:
    by_size = defaultdict(list)
    for record in records:
        if record["group"] in MODEL_GROUPS and record["bytes"] >= 32 * 1024 * 1024:
            by_size[record["bytes"]].append(record)
    duplicates = []
    for size, rows in by_size.items():
        if len(rows) < 2:
            continue
        hashes, by_hash = {}, defaultdict(list)
        for row in rows:
            key = row["identity"]
            if key not in hashes:
                hashes[key] = digest(row["path"])
            by_hash[hashes[key]].append(row)
        for sha, matches in by_hash.items():
            if len(matches) > 1:
                distinct = len({r["identity"] for r in matches})
                duplicates.append({"sha256": sha, "bytes_each": size, "paths": [r["path"] for r in matches],
                                   "distinct_files": distinct,
                                   "duplicate_logical_bytes": size * (distinct - 1)})
    return sorted(duplicates, key=lambda row: -row["duplicate_logical_bytes"])


def inventory(root: Path, uv_cache: Path | None = None) -> dict:
    targets = [(name, root / name) for name in GROUPS]
    if uv_cache is not None:
        targets.append(("external_uv_cache", uv_cache))
    groups, all_records, skipped, errors = [], [], [], []
    for name, folder in targets:
        if not folder.is_dir():
            groups.append({"group": name, "path": str(folder), "missing": True})
            continue
        if folder.is_symlink() or getattr(folder.lstat(), "st_file_attributes", 0) & 0x400:
            skipped.append(str(folder))
            continue
        print(f"Scanning {name}", flush=True)
        records = []
        for path, info in files_under(folder, skipped, errors):
            relative = path.relative_to(folder)
            records.append({"group": name, "path": str(path), "identity": file_identity(path, info),
                            "bytes": info.st_size, "links": info.st_nlink,
                            "child": relative.parts[0] if len(relative.parts) > 1 else "(files)"})
        groups.append({"group": name, "path": str(folder), **summarize(records)})
        all_records.extend(records)
    print("Checking same-size model hashes", flush=True)
    return {"root": str(root), "completed_at": datetime.now(timezone.utc).isoformat(),
            "measurement": "logical bytes; not allocated size or a deletion authorization",
            "groups": groups, "duplicate_models": duplicate_models(all_records),
            "skipped_reparse_points": skipped, "errors": errors,
            "note": "Hard-link accounting applies per group. Recheck references/open handles before any future cleanup."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--uv-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.root.resolve(), args.uv_cache.resolve() if args.uv_cache else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {args.output}", flush=True)


if __name__ == "__main__":
    main()
