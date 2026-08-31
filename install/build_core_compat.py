"""Build a LOCAL experimental AudioTools wheel without changing site-packages.

The original 0.7.2 package has a protobuf<3.20 pin inherited from older
TensorBoard. Our inference probes use protobuf 7.36.0 and TensorBoard 2.20.0.
This build changes those declared dependencies and its local version only;
it does not claim upstream support. Read/verify every source RECORD hash.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


ORIGINAL = "descript_audiotools-0.7.2.dist-info"
PATCHED_VERSION = "0.7.2+xb1"
PATCHED = f"descript_audiotools-{PATCHED_VERSION}.dist-info"
WHEEL_NAME = f"descript_audiotools-{PATCHED_VERSION}-py3-none-any.whl"


def digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def _source_payload(site: Path) -> tuple[dict[str, bytes], bytes]:
    site = site.resolve()
    record = (site / ORIGINAL / "RECORD").read_bytes()
    payload = {}
    for raw, checksum, size in csv.reader(io.StringIO(record.decode("utf-8"))):
        name = PurePosixPath(raw)
        if name.is_absolute() or ".." in name.parts or "\\" in raw or ":" in raw:
            raise ValueError(f"Unsafe RECORD path: {raw}")
        if not name.parts or name.parts[0] not in {"audiotools", ORIGINAL}:
            raise ValueError(f"Unexpected package payload: {raw}")
        if "__pycache__" in name.parts or name.suffix == ".pyc":
            continue
        if name.parts[0] == ORIGINAL and name.name in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}:
            continue
        path = (site / Path(*name.parts)).resolve()
        if not path.is_relative_to(site):
            raise ValueError(f"RECORD symlink escapes source: {raw}")
        data = path.read_bytes()
        if checksum != "sha256=" + digest(data) or size != str(len(data)):
            raise ValueError(f"Source RECORD validation failed: {raw}")
        if raw in payload:
            raise ValueError(f"Duplicate RECORD path: {raw}")
        payload[raw] = data
    return payload, record


def build(site: Path, output: Path) -> Path:
    payload, _ = _source_payload(site)
    source_hashes = {name: hashlib.sha256(data).hexdigest()
                     for name, data in sorted(payload.items())}
    metadata_key = ORIGINAL + "/METADATA"
    metadata = payload[metadata_key].decode("utf-8")
    replacements = {
        "Version: 0.7.2": f"Version: {PATCHED_VERSION}",
        "Requires-Dist: protobuf (<3.20,>=3.9.2)": "Requires-Dist: protobuf ==7.36.0",
        "Requires-Dist: tensorboard": "Requires-Dist: tensorboard ==2.20.0",
    }
    header, separator, body = metadata.replace("\r\n", "\n").partition("\n\n")
    lines = header.splitlines()
    for original, replacement in replacements.items():
        if lines.count(original) != 1:
            raise ValueError(f"Unexpected upstream metadata: {original}")
        lines[lines.index(original)] = replacement
    payload[metadata_key] = ("\n".join(lines) + separator + body).encode("utf-8")
    version_line = b'__version__ = "0.7.2"'
    if payload["audiotools/__init__.py"].count(version_line) != 1:
        raise ValueError("Unexpected AudioTools version declaration")
    payload["audiotools/__init__.py"] = payload["audiotools/__init__.py"].replace(
        version_line, f'__version__ = "{PATCHED_VERSION}"'.encode())
    payload[ORIGINAL + "/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: xb-core-compat-1\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    ).encode()
    payload = {name.replace(ORIGINAL + "/", PATCHED + "/", 1): data for name, data in payload.items()}
    # RECORD gains installer-specific rows when a wheel is installed. Hash the
    # validated original payload instead, so wheel and site-packages inputs
    # produce identical output. Never include machine-specific paths.
    provenance = {"experimental": True, "upstream_version": "0.7.2", "local_version": PATCHED_VERSION,
                  "source_payload_sha256": hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest(),
                  "metadata_changes": replacements, "full_model_inference_validated": False}
    payload[PATCHED + "/xb_compatibility.json"] = json.dumps(provenance, sort_keys=True, indent=2).encode()
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    for name, data in sorted(payload.items()):
        writer.writerow((name, "sha256=" + digest(data), len(data)))
    writer.writerow((PATCHED + "/RECORD", "", ""))
    payload[PATCHED + "/RECORD"] = rows.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / WHEEL_NAME
    with tempfile.TemporaryDirectory(prefix="xb-wheel-", dir=output) as work:
        temporary = Path(work) / WHEEL_NAME
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 8, 29, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                wheel.writestr(info, data)
        if destination.exists() and destination.read_bytes() != temporary.read_bytes():
            raise ValueError("Refusing to overwrite a different compatibility wheel; choose a fresh output directory")
        if not destination.exists():
            temporary.replace(destination)
    return destination


def build_from_wheel(source: Path, output: Path) -> Path:
    """Rebuild offline from an original wheel, without installing its dependencies."""
    with tempfile.TemporaryDirectory(prefix="xb-audiotools-source-") as work:
        site = Path(work)
        with zipfile.ZipFile(source) as archive:
            seen = set()
            for info in archive.infolist():
                name = PurePosixPath(info.filename)
                if (name.is_absolute() or ".." in name.parts or "\\" in info.filename
                        or ":" in info.filename or not name.parts
                        or name.parts[0] not in {"audiotools", ORIGINAL}
                        or info.filename in seen):
                    raise ValueError(f"Unsafe or duplicate wheel path: {info.filename}")
                seen.add(info.filename)
                if info.is_dir():
                    continue
                target = site / Path(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        return build(site, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-site-packages", type=Path)
    source.add_argument("--source-wheel", type=Path, help="Original 0.7.2 wheel; verified against its RECORD, never installed")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--support-wheel", type=Path, action="append", default=[],
                        help="Stage an already-built small source dependency wheel from the local cache")
    args = parser.parse_args()
    path = (build_from_wheel(args.source_wheel, args.output_dir) if args.source_wheel
            else build(args.source_site_packages, args.output_dir))
    print(path)
    print("SHA256:", hashlib.sha256(path.read_bytes()).hexdigest())
    for support in args.support_wheel:
        if support.suffix != ".whl" or not zipfile.is_zipfile(support):
            parser.error(f"Not a wheel: {support}")
        destination = args.output_dir / support.name
        data = support.read_bytes()
        if destination.exists() and destination.read_bytes() != data:
            parser.error(f"Refusing to replace a different support wheel: {destination}")
        if not destination.exists():
            destination.write_bytes(data)
        print("Support wheel:", destination)


if __name__ == "__main__":
    main()
