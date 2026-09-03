"""Resolve a runtime for the Inno installer without importing the desktop app."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def resolve_python(root: Path, component: str, legacy: str) -> Path:
    explicit = os.environ.get(f"XB_{component.upper()}_PYTHON")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    try:
        manifest = Path(os.environ.get("XB_RUNTIME_MANIFEST") or root / "runtime.json").expanduser()
        if not manifest.is_absolute():
            manifest = root / manifest
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and payload.get("version") == 1:
            mapping = payload.get("python", {})
            raw = mapping.get(component) if isinstance(mapping, dict) else None
            if isinstance(raw, str) and raw.strip():
                candidate = Path(raw).expanduser()
                if not candidate.is_absolute():
                    candidate = manifest.parent / candidate
                if candidate.is_file():
                    return candidate.resolve()
    except (OSError, ValueError, RuntimeError):
        pass
    return root / legacy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--component",
        required=True,
        choices=("uvr", "seedvc", "ddsp", "svc", "rvc", "vocal", "pymss", "hub", "plugins"),
    )
    parser.add_argument("--legacy", required=True)
    parser.add_argument("--output-file", type=Path)
    args = parser.parse_args()
    resolved = str(resolve_python(args.root.resolve(), args.component, args.legacy))
    if args.output_file:
        args.output_file.write_text(resolved + "\n", encoding="utf-8")
    else:
        print(resolved)


if __name__ == "__main__":
    main()
