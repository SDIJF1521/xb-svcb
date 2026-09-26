"""Stage one hardware-specific wheelhouse for an installer build.

The developer cache may contain wheels for every supported hardware stack.  A
release installer must only carry the stack named on its command line, plus
the stack-neutral bootstrap/common groups.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


STACKS = frozenset({"cpu", "rocm10", "cu126", "cu128"})
REQUIRED_COMPONENT_GROUPS = {
    "cpu": ("svc", "rvc", "pymss", "ddsp-legacy"),
    "rocm10": ("pymss", "ddsp-legacy"),
    "cu126": ("pymss", "ddsp-legacy"),
    "cu128": ("pymss", "ddsp-legacy"),
}


def wheel_belongs_to_stack(relative_path: Path, stack: str) -> bool:
    parts = tuple(part.lower() for part in relative_path.parts[:-1])
    if "bootstrap" in parts or "common" in parts:
        return True
    if any(part.startswith("py") and part[2:].isdigit() and part != "py312" for part in parts):
        return False
    selected = STACKS.intersection(parts)
    return selected == {stack}


def _safe_output(root: Path, output: Path, source: Path) -> Path:
    root = root.resolve()
    output = output.resolve()
    source = source.resolve()
    staging_root = (root / ".tmp").resolve()
    if output == source or source in output.parents:
        raise ValueError(f"staging output must not be inside the source wheelhouse: {output}")
    if output == staging_root or staging_root not in output.parents:
        raise ValueError(f"staging output must be a child of {staging_root}: {output}")
    return output


def validate_rocm_wheels(directory: Path) -> None:
    """Inspect the build marker without importing or executing wheel contents."""
    wheels = list(directory.glob("torch-*.whl"))
    if not wheels:
        raise RuntimeError(f"ROCm 10 Torch wheel missing: {directory}")
    if any(directory.glob("torch_directml-*.whl")):
        raise RuntimeError(f"DirectML wheel in ROCm 10 wheelhouse: {directory}")
    for wheel in wheels:
        try:
            with zipfile.ZipFile(wheel) as archive:
                tree = ast.parse(archive.read("torch/version.py").decode("utf-8"))
            versions = {}
            for node in tree.body:
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if isinstance(node, ast.AnnAssign) else []
                )
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"hip", "rocm"}:
                        versions[target.id] = ast.literal_eval(node.value)
            hip, rocm = versions.get("hip"), versions.get("rocm")
            if not isinstance(hip, str) or not hip or not isinstance(rocm, str) or rocm.split(".")[0] != "10":
                raise ValueError(f"expected ROCm 10 with HIP, got ROCm {rocm!r}, HIP {hip!r}")
        except (KeyError, ValueError, SyntaxError, zipfile.BadZipFile) as exc:
            raise RuntimeError(
                f"Invalid ROCm 10 Torch wheel: {wheel}: {exc}. "
                "Rebuild using XB_TORCH_ROCM_INDEX and matching XB_ROCM_TORCH_VERSION."
            ) from exc


def stage_wheelhouse(root: Path, stack: str, output: Path) -> dict[str, object]:
    if stack not in STACKS:
        raise ValueError(f"unsupported stack: {stack}")

    root = root.resolve()
    source = root / "assets" / "wheels"
    if not (source / "wheelhouse.json").is_file():
        raise FileNotFoundError(f"wheelhouse manifest not found: {source / 'wheelhouse.json'}")
    output = _safe_output(root, output, source)

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    groups: dict[str, int] = defaultdict(int)
    linked = 0
    copied = 0
    for wheel in sorted(source.rglob("*.whl")):
        relative = wheel.relative_to(source)
        if not wheel_belongs_to_stack(relative, stack):
            continue
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(wheel, destination)
            linked += 1
        except OSError:
            shutil.copy2(wheel, destination)
            copied += 1
        groups[relative.parent.as_posix()] += 1

    required = output / "py312" / stack
    if not required.is_dir() or not any(required.glob("*.whl")):
        raise RuntimeError(f"selected wheelhouse group is empty: {required}")
    bootstrap = output / "bootstrap"
    if not bootstrap.is_dir() or not any(bootstrap.glob("*.whl")):
        raise RuntimeError(f"bootstrap wheelhouse group is empty: {bootstrap}")
    for component in REQUIRED_COMPONENT_GROUPS[stack]:
        group = output / component / "py312" / stack
        if not group.is_dir() or not any(group.glob("*.whl")):
            raise RuntimeError(
                f"selected wheelhouse component group is empty: {group}; "
                "rebuild the wheelhouse before packaging"
            )

    if stack == "rocm10":
        for group in groups:
            if "rocm10" in Path(group).parts:
                validate_rocm_wheels(output / group)

    manifest: dict[str, object] = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": "win_amd64",
        "package_stack": stack,
        "source": "filtered from the developer assets/wheels cache",
        "groups": [
            {"path": path, "wheel_count": count}
            for path, count in sorted(groups.items())
        ],
    }
    (output / "wheelhouse.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["hardlinked_wheels"] = linked
    manifest["copied_wheels"] = copied
    manifest["wheel_count"] = linked + copied
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stack", choices=sorted(STACKS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = stage_wheelhouse(args.root, args.stack, args.output)
    print(
        f"Staged {result['wheel_count']} wheels for {args.stack} "
        f"({result['hardlinked_wheels']} hardlinks, {result['copied_wheels']} copies)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
