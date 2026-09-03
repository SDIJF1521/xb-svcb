"""Read/verify the experimental core recipe; never install or download packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parent / "runtime_profiles" / "core-cu128"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Recipe path escapes its root: {relative}")
    return path


def read_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z0-9-]+)==([A-Za-z0-9.+!-]+)", line)
        if not match or match[1] in pins:
            raise ValueError(f"Expected a unique exact version pin: {line}")
        pins[match[1]] = match[2]
    if not pins:
        raise ValueError("Empty core recipe")
    return pins


def load_profile(directory: Path = PROFILE_DIR) -> tuple[dict, dict[str, str]]:
    profile = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
    if profile.get("schema") != 1 or profile.get("stack") != "cu128" or not profile.get("experimental"):
        raise ValueError("Unsupported core recipe")
    lock = contained(directory, profile["lock"])
    if sha256(lock) != profile["lock_sha256"]:
        raise ValueError("Core recipe lock hash mismatch; regenerate and review the profile")
    return profile, read_pins(lock)


def verify_artifacts(root: Path, profile: dict, groups: set[str] | None = None) -> list[Path]:
    verified = []
    for artifact in profile["artifacts"]:
        if groups is not None and artifact["group"] not in groups:
            continue
        path = contained(root, artifact["path"])
        if not path.is_file():
            raise ValueError(f"Missing local recipe artifact: {path}; see the profile README")
        if path.stat().st_size != artifact["bytes"] or sha256(path) != artifact["sha256"]:
            raise ValueError(f"Recipe artifact hash/size mismatch: {path}")
        verified.append(path)
    return verified


def verify_resolution(path: Path, pins: dict[str, str]) -> None:
    resolved = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("descript-audiotools @ "):
            resolved["descript-audiotools"] = pins["descript-audiotools"]
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ;]+)", line)
        if not match:
            raise ValueError(f"Unexpected compiled recipe entry: {line}")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        resolved[name] = match[2]
    if resolved != pins:
        changed = sorted(name for name in pins.keys() | resolved.keys()
                         if pins.get(name) != resolved.get(name))
        raise ValueError("Resolved dependencies drifted from core recipe: " + ", ".join(changed))


def check_environment(python: Path, profile: dict, pins: dict[str, str]) -> dict:
    code = (
        "import importlib.metadata as m,json,re,sys,platform; "
        "print(json.dumps({'python':platform.python_version(),'system':sys.platform,"
        "'machine':platform.machine(),'packages':{re.sub(r'[-_.]+','-',d.metadata['Name']).lower():"
        "d.version for d in m.distributions()}}))"
    )
    result = subprocess.run([str(python), "-B", "-c", code], capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=30)
    actual = json.loads(result.stdout)
    packages = actual.pop("packages")
    optional = set(profile.get("optional_packages", []))
    missing = sorted(name for name in pins if name not in packages and name not in optional)
    changed = {name: {"expected": version, "actual": packages[name]}
               for name, version in pins.items() if name in packages and packages[name] != version}
    extra = sorted(packages.keys() - pins.keys())
    platform_ok = (actual["python"].split(".")[:2] == ["3", "10"]
                   and actual["system"] == "win32" and actual["machine"].lower() in {"amd64", "x86_64"})
    return {**actual, "ok": platform_ok and not missing and not changed and not extra,
            "platform_ok": platform_ok, "installed_count": len(packages), "locked_count": len(pins),
            "missing": missing, "changed": changed, "extra": extra,
            "missing_optional": sorted(optional - packages.keys()),
            "full_model_inference_validated": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--profile-dir", type=Path, default=PROFILE_DIR)
    parser.add_argument("--python", type=Path, help="Also compare installed metadata with the exact recipe")
    args = parser.parse_args()
    profile, pins = load_profile(args.profile_dir)
    paths = verify_artifacts(args.root, profile)
    print(f"Verified {len(paths)} local artifacts; {len(pins)} exact version pins (experimental)")
    if args.python:
        report = check_environment(args.python, profile, pins)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
