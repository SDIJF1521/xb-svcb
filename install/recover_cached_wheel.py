"""Export a RECORD-verified uv cache payload as a local wheel, without downloads.

Never edits the cache or an installed environment. The exported ZIP is a local
repack, not a byte-identical upstream wheel. Cached RECORD verifies integrity,
not independent publisher authenticity. Unknown cache layouts fail closed.
"""
from __future__ import annotations

import argparse
import base64
import csv
from email.parser import Parser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def safe_path(root: Path, raw: str) -> tuple[str, Path]:
    normalized = raw.replace("\\", "/")
    name = PurePosixPath(normalized)
    if (not raw or name.is_absolute() or ".." in name.parts or ":" in raw
            or normalized != str(name)):
        raise ValueError(f"Unsafe RECORD path: {raw}")
    path = root
    for part in name.parts:
        path /= part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Redirected cache path: {raw}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Cache path escapes root: {raw}")
    return str(name), path


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def find_archive(cache: Path, filename: str) -> tuple[Path, Path]:
    if Path(filename).name != filename or not filename.endswith(".whl"):
        raise ValueError("Expected a wheel filename")
    fields = filename[:-4].split("-")
    if len(fields) != 5 or not re.fullmatch(r"[A-Za-z0-9_.+!-]+", filename[:-4]):
        raise ValueError("Unsupported wheel filename; cache not modified")
    name, version, py, abi, platform = fields
    key = f"{version}-{py}-{abi}-{platform}"
    for bucket in ("wheels-v6", "wheels-v5"):
        base = cache / bucket
        references = sorted(base.glob(f"index/*/{canonical(name)}/{key}"))
        references += sorted(base.glob(f"pypi/{canonical(name)}/{key}"))
        for reference in references:
            if not reference.is_file() or reference.stat().st_size > 128:
                continue
            _, reference = safe_path(cache, reference.relative_to(cache).as_posix())
            raw = reference.read_text(encoding="utf-8")
            if not re.fullmatch(r"archive-v0/[A-Za-z0-9_-]+", raw):
                continue
            _, archive = safe_path(cache, raw)
            if archive.is_dir():
                return reference, archive
    raise LookupError(f"No supported cached payload for {filename}")


def repack(archive: Path, filename: str, output: Path) -> dict:
    name, version, py, abi, platform = filename[:-4].split("-")
    dist_infos = list(archive.glob("*.dist-info"))
    if len(dist_infos) != 1:
        raise ValueError("Expected exactly one cached distribution")
    dist = dist_infos[0].name
    _, record = safe_path(archive, dist + "/RECORD")
    _, metadata_path = safe_path(archive, dist + "/METADATA")
    _, wheel_path = safe_path(archive, dist + "/WHEEL")
    metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
    tags = Parser().parsestr(wheel_path.read_text(encoding="utf-8")).get_all("Tag", [])
    expected_tags = {f"{p}-{a}-{s}" for p in py.split(".") for a in abi.split(".") for s in platform.split(".")}
    if canonical(metadata["Name"]) != canonical(name) or metadata["Version"] != version or set(tags) != expected_tags:
        raise ValueError("Cached name/version/platform does not match requested wheel")
    payload, seen = [], set()
    original_record = record.read_bytes()
    for row in csv.reader(io.StringIO(original_record.decode("utf-8"))):
        if len(row) != 3:
            raise ValueError("Invalid cached RECORD row")
        raw, checksum, size = row
        path_name, path = safe_path(archive, raw)
        if path_name.casefold() in seen:
            raise ValueError("Duplicate cached RECORD path")
        seen.add(path_name.casefold())
        if path_name == dist + "/RECORD":
            if checksum or size:
                raise ValueError("RECORD self-entry must be unhashed")
            continue
        if not checksum.startswith("sha256=") or not size.isdecimal():
            raise ValueError(f"Unverifiable cache file: {path_name}")
        payload.append((path_name, path, checksum, int(size)))
    expected_files = {entry[0] for entry in payload} | {dist + "/RECORD"}
    if (dist + "/RECORD").casefold() not in seen:
        raise ValueError("Missing RECORD self-entry")
    actual_files = set()
    for path in archive.rglob("*"):
        relative = path.relative_to(archive).as_posix()
        _, path = safe_path(archive, relative)
        if path.is_file():
            actual_files.add(relative)
    if actual_files != expected_files:
        raise ValueError("Unrecorded or missing cache files; refusing an installed/modified payload")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / filename
    temporary = output / (filename + ".incomplete")
    if destination.exists() or temporary.exists():
        raise ValueError("Refusing to overwrite an existing export")
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    # Hash while writing so a concurrent cache modification cannot bypass checks.
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as wheel:
        for path_name, path, checksum, size in sorted(payload):
            digest, total = hashlib.sha256(), 0
            with path.open("rb") as source, wheel.open(path_name, "w", force_zip64=True) as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    total += len(chunk)
                    target.write(chunk)
            actual_hash = "sha256=" + base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode()
            if actual_hash != checksum or total != size:
                raise ValueError(f"Cache RECORD mismatch: {path_name}")
            writer.writerow((path_name, checksum, size))
        writer.writerow((dist + "/RECORD", "", ""))
        wheel.writestr(dist + "/RECORD", rows.getvalue())
    temporary.rename(destination)
    return {"filename": filename, "archive": str(archive), "payload_files": len(payload),
            "cached_record_sha256": hashlib.sha256(original_record).hexdigest(),
            "wheel_sha256": sha256(destination), "bytes": destination.stat().st_size,
            "local_repack": True, "upstream_wheel_sha256_verified": False,
            "changes": "ZIP packaging and RECORD path separators only; functional files/metadata unchanged"}


def recover(cache: Path, filename: str, output: Path) -> dict:
    cache = cache.resolve()
    if output.resolve().is_relative_to(cache):
        raise ValueError("Export output must be outside the uv cache")
    reference, archive = find_archive(cache, filename)
    report = repack(archive, filename, output)
    report["cache_reference"] = str(reference)
    (output / (filename + ".provenance.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.cache, args.filename, args.output), indent=2))


if __name__ == "__main__":
    main()
