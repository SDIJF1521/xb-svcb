from __future__ import annotations

import argparse
import configparser
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


STACK_BASE_NAMES = {
    "cpu": "XB-SVCB-Setup-CPU",
    "rocm10": "XB-SVCB-Setup-ROCm10",
    "directml": "XB-SVCB-Setup-DirectML",
    "cu126": "XB-SVCB-Setup-CUDA126",
    "cu128": "XB-SVCB-Setup-CUDA128",
}
MAX_ARTIFACT_BYTES = 2 * 1024**3
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str
    size: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _part_number(path: Path, base_name: str) -> int:
    match = re.fullmatch(re.escape(base_name) + r"-(\d+)\.bin", path.name)
    if not match:
        raise ValueError(f"Unexpected split installer file: {path.name}")
    return int(match.group(1))


def _artifact(path: Path) -> Artifact:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"Installer artifact is empty: {path}")
    if size >= MAX_ARTIFACT_BYTES:
        raise ValueError(f"Installer artifact must stay below 2 GiB: {path}")
    return Artifact(path=path, sha256=_sha256(path), size=size)


def collect_stack(dist: Path, stack: str) -> list[Artifact]:
    base_name = STACK_BASE_NAMES[stack]
    setup = dist / f"{base_name}.exe"
    parts = sorted(
        dist.glob(f"{base_name}-*.bin"),
        key=lambda path: _part_number(path, base_name),
    )
    if not parts:
        raise FileNotFoundError(f"No split payload files found for {stack}: {base_name}-*.bin")
    numbers = [_part_number(path, base_name) for path in parts]
    if numbers != list(range(1, len(parts) + 1)):
        raise ValueError(f"Split payload numbering is not contiguous for {stack}: {numbers}")
    return [_artifact(setup), *(_artifact(path) for path in parts)]


def build_manifest(dist: Path, output: Path, version: str) -> configparser.ConfigParser:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Version must be SemVer-like X.Y.Z, got: {version}")

    manifest = configparser.ConfigParser(interpolation=None)
    manifest.optionxform = str
    manifest["release"] = {
        "version": version,
        "stacks": ",".join(STACK_BASE_NAMES),
    }
    for stack in STACK_BASE_NAMES:
        artifacts = collect_stack(dist, stack)
        section: dict[str, str] = {
            "count": str(len(artifacts)),
            "setup": artifacts[0].path.name,
        }
        for index, artifact in enumerate(artifacts):
            section[f"file{index}"] = artifact.path.name
            section[f"sha256_{index}"] = artifact.sha256
            section[f"size_{index}"] = str(artifact.size)
        manifest[f"stack.{stack}"] = section

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        manifest.write(handle, space_around_delimiters=False)
    return manifest


def validate_existing_manifest(path: Path, version: str) -> configparser.ConfigParser:
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest = configparser.ConfigParser(interpolation=None)
    manifest.optionxform = str
    with path.open("r", encoding="utf-8") as handle:
        manifest.read_file(handle)

    if manifest.get("release", "version", fallback="") != version:
        raise ValueError(f"Manifest version does not match {version}: {path}")
    expected_stacks = list(STACK_BASE_NAMES)
    stacks = [item.strip() for item in manifest.get("release", "stacks", fallback="").split(",") if item.strip()]
    if stacks != expected_stacks:
        raise ValueError(f"Manifest stacks are invalid: {stacks}")

    for stack, base_name in STACK_BASE_NAMES.items():
        section_name = f"stack.{stack}"
        if not manifest.has_section(section_name):
            raise ValueError(f"Manifest section is missing: {section_name}")
        section = manifest[section_name]
        try:
            count = int(section.get("count", "0"))
        except ValueError as exc:
            raise ValueError(f"Invalid artifact count for {stack}") from exc
        if count < 2 or count > 64:
            raise ValueError(f"Invalid artifact count for {stack}: {count}")
        expected_setup = f"{base_name}.exe"
        if section.get("setup") != expected_setup or section.get("file0") != expected_setup:
            raise ValueError(f"Invalid setup artifact for {stack}")

        names: set[str] = set()
        for index in range(count):
            name = section.get(f"file{index}", "")
            digest = section.get(f"sha256_{index}", "")
            try:
                size = int(section.get(f"size_{index}", "0"))
            except ValueError as exc:
                raise ValueError(f"Invalid artifact size for {stack} file {index}") from exc
            if not SAFE_NAME_RE.fullmatch(name) or ".." in name:
                raise ValueError(f"Unsafe artifact name for {stack}: {name}")
            if name.casefold() in names:
                raise ValueError(f"Duplicate artifact name for {stack}: {name}")
            names.add(name.casefold())
            if not SHA256_RE.fullmatch(digest):
                raise ValueError(f"Invalid SHA-256 for {stack}: {name}")
            if size <= 0 or size >= MAX_ARTIFACT_BYTES:
                raise ValueError(f"Invalid artifact size for {stack}: {name} ({size})")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the hash-pinned XB-SVCB online installer manifest.")
    parser.add_argument("--dist", type=Path, help="Directory containing all five offline installers")
    parser.add_argument("--output", type=Path, help="Output INI manifest path")
    parser.add_argument("--validate-existing", type=Path, help="Validate an existing manifest without local artifacts")
    parser.add_argument("--version", required=True, help="XB-SVCB release version")
    args = parser.parse_args()

    if args.validate_existing:
        manifest = validate_existing_manifest(args.validate_existing.resolve(), args.version)
        file_count = sum(int(manifest[f"stack.{stack}"]["count"]) for stack in STACK_BASE_NAMES)
        print(f"ONLINE_MANIFEST_VALID {args.validate_existing.resolve()} stacks={len(STACK_BASE_NAMES)} files={file_count}")
        return 0
    if not args.dist or not args.output:
        parser.error("--dist and --output are required unless --validate-existing is used")

    manifest = build_manifest(args.dist.resolve(), args.output.resolve(), args.version)
    file_count = sum(int(manifest[f"stack.{stack}"]["count"]) for stack in STACK_BASE_NAMES)
    print(f"ONLINE_MANIFEST_OK {args.output.resolve()} stacks={len(STACK_BASE_NAMES)} files={file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
