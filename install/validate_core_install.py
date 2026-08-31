"""Validate in a disposable environment, never in the live runtime.

Install operations are offline. Optional cache filling fetches only hash-checked
PyPI wheels under explicit size/count budgets; Torch-family downloads are denied.
The caller owns the sandbox and its eventual cleanup. No model inference runs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request


BLOCKED = {"torch", "torchaudio", "torchvision", "triton", "onnxruntime-gpu"}
MAX_WHEEL_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024


def recipe_module(root: Path):
    spec = importlib.util.spec_from_file_location("xb_core_recipe", root / "install/core_recipe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_sandbox(sandbox: Path) -> Path:
    temp_root = Path(os.environ["TEMP"]).resolve()
    if sandbox.parent.resolve() != temp_root or not sandbox.name.startswith("xb-core-install-check-"):
        raise ValueError("Expected a separately created xb-core-install-check-* sandbox under TEMP")
    for path in (sandbox, sandbox / "venv", sandbox / "venv/Scripts"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Sandbox must not redirect to an existing environment")
    python = sandbox / "venv/Scripts/python.exe"
    if not python.is_file() or not python.resolve().is_relative_to(sandbox.resolve()):
        raise ValueError("Missing or redirected sandbox interpreter")
    return python


def metadata_snapshot(sandbox: Path) -> dict:
    return {str(path.relative_to(sandbox)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in (sandbox / "venv/Lib/site-packages").glob("*.dist-info/*") if path.is_file()}


def run(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = result.stdout + result.stderr
    print(output, flush=True)
    return {"command": command, "exit_code": result.returncode, "output": output}


def small_missing_wheel(output: str, folder: Path, spent: int) -> dict:
    match = re.search(r"Failed to download `([^`=]+)==([^`]+)`", output)
    url_match = re.search(r"https://[^\s`]+\.whl", output)
    if not match or not url_match:
        raise ValueError("Failure is not an identifiable missing cached wheel; no download attempted")
    name, version = match.groups()
    name = re.sub(r"[-_.]+", "-", name).lower()
    if name in BLOCKED or name.startswith("nvidia-"):
        raise ValueError(f"Large runtime download reserved for user: {name}=={version}")
    filename = urllib.parse.unquote(urllib.parse.urlparse(url_match[0]).path.rsplit("/", 1)[-1])
    if Path(filename).name != filename or not filename.endswith(".whl"):
        raise ValueError("Invalid wheel filename")
    url = f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)
    candidates = [entry for entry in data["urls"] if entry["filename"] == filename]
    if len(candidates) != 1:
        raise ValueError("Requested wheel not present in official PyPI metadata")
    wheel = candidates[0]
    size = wheel["size"]
    if size > MAX_WHEEL_BYTES or spent + size > MAX_TOTAL_BYTES:
        raise ValueError(f"Download budget exceeded: {filename} ({size} bytes)")
    if urllib.parse.urlparse(wheel["url"]).hostname != "files.pythonhosted.org":
        raise ValueError("Unexpected PyPI download host")
    destination = folder / filename
    if destination.exists():
        raise ValueError("Already downloaded this missing wheel; refusing an unproductive retry")
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    temporary = destination.with_suffix(".incomplete")
    with urllib.request.urlopen(wheel["url"], timeout=30) as response, temporary.open("xb") as stream:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            total += len(chunk)
            if total > size or total > MAX_WHEEL_BYTES:
                raise ValueError("Wheel response exceeds declared size")
            digest.update(chunk)
            stream.write(chunk)
    if total != size or digest.hexdigest() != wheel["digests"]["sha256"]:
        raise ValueError("Downloaded wheel size/SHA-256 mismatch")
    temporary.rename(destination)
    return {"name": name, "version": version, "filename": filename, "bytes": size, "sha256": digest.hexdigest()}


def prepare_install(root: Path, sandbox: Path, uv: str, wheel_dirs: list[Path] | None = None):
    python = validate_sandbox(sandbox)
    recipe = recipe_module(root)
    profile, pins = recipe.load_profile(root / "install/runtime_profiles/core-cu128")
    artifacts = recipe.verify_artifacts(root, profile, {"compat"})
    compat = next(path for path in artifacts if path.name.startswith("descript_audiotools-"))
    # Generate only from hash-checked pins/artifacts, not a stale .tmp resolution.
    lock = sandbox / "requirements.txt"
    lock.write_text("\n".join(f"descript-audiotools @ {compat.as_uri()}" if name == "descript-audiotools"
                              else f"{name}=={version}" for name, version in sorted(pins.items())) + "\n",
                    encoding="utf-8")
    wheels = sandbox / "small-wheels"
    command = [uv, "pip", "install", "--offline", "--no-build", "--link-mode", "hardlink",
               "--python", str(python), "-r", str(lock), "--torch-backend", "cu128",
               "--default-index", "https://mirrors.cloud.tencent.com/pypi/simple",
               "--find-links", str(root / "assets/runtime/core-cu128/compat")]
    wheels.mkdir(exist_ok=True)
    command += ["--find-links", str(wheels)]
    command += ["--find-links", str(root / "assets/runtime/core-cu128/candidate")]
    for directory in wheel_dirs or []:
        command += ["--find-links", str(directory.resolve())]
    recovered = sandbox / "recovered-wheels"
    recovered.mkdir(exist_ok=True)
    command += ["--find-links", str(recovered)]
    return recipe, profile, pins, command


def validate(root: Path, sandbox: Path, uv: str, fill_small_cache: bool,
             recover_cache: Path | None = None, wheel_dirs: list[Path] | None = None) -> dict:
    python = validate_sandbox(sandbox)
    if any((sandbox / "venv/Lib/site-packages").glob("*.dist-info")):
        raise ValueError("Full fresh-install validation requires an empty sandbox environment")
    recipe, profile, pins, command = prepare_install(root, sandbox, uv, wheel_dirs)
    wheels, recovered = sandbox / "small-wheels", sandbox / "recovered-wheels"
    existing_bytes = sum(path.stat().st_size for path in wheels.glob("*.whl"))
    report = {"sandbox": str(sandbox), "live_runtime_modified": False, "downloads": [], "attempts": [],
              "existing_small_wheel_bytes": existing_bytes, "recovered": [],
              "full_model_inference_validated": False}
    for _ in range(len(pins) + 1):
        attempt = run(command)
        report["attempts"].append(attempt)
        if attempt["exit_code"] == 0:
            report["fresh_install_ok"] = True
            before = metadata_snapshot(sandbox)
            report["repeat_install"] = run(command)
            report["repeat_metadata_unchanged"] = before == metadata_snapshot(sandbox)
            report["pip_check"] = run([uv, "pip", "check", "--python", str(python)])
            report["recipe_check"] = recipe.check_environment(python, profile, pins)
            return report
        if recover_cache is not None:
            match = re.search(r"https://[^\s`]+\.whl", attempt["output"])
            if match:
                filename = urllib.parse.unquote(urllib.parse.urlparse(match[0]).path.rsplit("/", 1)[-1])
                spec = importlib.util.spec_from_file_location("xb_recover_cache", root / "install/recover_cached_wheel.py")
                recovery = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recovery)
                try:
                    item = recovery.recover(recover_cache, filename, recovered)
                    report["recovered"].append(item)
                    print(f"Reused verified cache: {filename}", flush=True)
                    continue
                except LookupError:
                    pass  # No matching cache; only then consider a small download.
                except (OSError, ValueError) as exc:
                    report["blocked_reason"] = f"Cache recovery stopped: {exc}"
                    break
        if not fill_small_cache:
            break
        try:
            item = small_missing_wheel(attempt["output"], wheels,
                                      existing_bytes + sum(d["bytes"] for d in report["downloads"]))
            report["downloads"].append(item)
            print(f"Cached small wheel: {item['filename']} ({item['bytes']} bytes)", flush=True)
        except (OSError, ValueError, KeyError) as exc:
            report["blocked_reason"] = str(exc)
            break
    report["fresh_install_ok"] = False
    report.setdefault("blocked_reason", "Offline install failed or retry budget exhausted")
    return report


def validate_repair(root: Path, sandbox: Path, uv: str, wheel_dirs: list[Path] | None = None) -> dict:
    """Inject four-package drift into the disposable full environment, then repair."""
    python = validate_sandbox(sandbox)
    recipe, profile, pins, command = prepare_install(root, sandbox, uv, wheel_dirs)
    before = recipe.check_environment(python, profile, pins)
    if not before["ok"]:
        raise ValueError("Repair test requires a previously verified full sandbox environment")
    artifacts = recipe.verify_artifacts(root, profile)
    rollback = [str(path) for path in artifacts if path.parent.name == "rollback"]
    if len(rollback) != 4:
        raise ValueError("Expected four verified rollback wheels")
    prefixes = ("numpy-", "protobuf-", "tensorboardx-", "descript_audiotools-")

    def unaffected():
        return {key: value for key, value in metadata_snapshot(sandbox).items()
                if not Path(key).parent.name.lower().startswith(prefixes)}

    unchanged_before = unaffected()
    report = {"sandbox": str(sandbox), "live_runtime_modified": False, "before": before,
              "full_model_inference_validated": False, "fault_injection_only": True}
    report["inject_drift"] = run([uv, "pip", "install", "--offline", "--no-index", "--no-deps",
                                  "--python", str(python), *rollback])
    report["drift_check"] = recipe.check_environment(python, profile, pins)
    report["drift_pip_check"] = run([uv, "pip", "check", "--python", str(python)])
    # Always try to restore, even if the deliberate drift operation only partly succeeded.
    report["repair"] = run(command)
    report["after"] = recipe.check_environment(python, profile, pins)
    report["pip_check"] = run([uv, "pip", "check", "--python", str(python)])
    report["other_package_metadata_unchanged"] = unchanged_before == unaffected()
    snapshot = metadata_snapshot(sandbox)
    report["repeat_install"] = run(command)
    report["repeat_metadata_unchanged"] = snapshot == metadata_snapshot(sandbox)
    report["ok"] = (report["inject_drift"]["exit_code"] == 0 and not report["drift_check"]["ok"]
                    and report["drift_pip_check"]["exit_code"] != 0 and report["repair"]["exit_code"] == 0
                    and report["after"]["ok"] and report["pip_check"]["exit_code"] == 0
                    and report["other_package_metadata_unchanged"] and report["repeat_metadata_unchanged"]
                    and report["repeat_install"]["exit_code"] == 0)
    return report


def validate_compat_only(root: Path, sandbox: Path, uv: str) -> dict:
    """Exercise four local wheel replacements, not full dependency correctness."""
    python = validate_sandbox(sandbox)
    recipe = recipe_module(root)
    profile, pins = recipe.load_profile(root / "install/runtime_profiles/core-cu128")
    artifacts = recipe.verify_artifacts(root, profile)
    names = {"numpy", "protobuf", "tensorboardx", "descript-audiotools"}
    candidate = [path for path in artifacts if path.parent.name == "candidate"
                 or path.name.startswith("descript_audiotools-0.7.2+xb1-")]
    rollback = [path for path in artifacts if path.parent.name == "rollback"]
    if len(candidate) != 4 or len(rollback) != 4:
        raise ValueError("Expected exactly four checked candidate and rollback wheels")
    base = [uv, "pip", "install", "--offline", "--no-index", "--no-deps", "--no-build",
            "--link-mode", "hardlink", "--python", str(python)]
    report = {"sandbox": str(sandbox), "scope": "four-package deployment only; --no-deps",
              "live_runtime_modified": False, "full_model_inference_validated": False,
              "full_recipe_install_validated": False, "rollback_is_known_healthy": False}

    def versions():
        result = run([str(python), "-B", "-c",
                      "import importlib.metadata as m,json; print(json.dumps({n:m.version(n) for n in "
                      + repr(sorted(names)) + "}))"])
        if result["exit_code"] != 0:
            raise RuntimeError("Could not inspect sandbox package versions")
        return json.loads(result["output"])

    for stage, paths in (("install", candidate), ("repeat", candidate),
                         ("rollback", rollback), ("restore_recipe", candidate)):
        before = metadata_snapshot(sandbox)
        result = run(base + list(map(str, paths)))
        report[stage] = result
        if result["exit_code"] != 0:
            report["ok"] = False
            return report
        if stage == "repeat":
            report["repeat_metadata_unchanged"] = before == metadata_snapshot(sandbox)
        report[stage + "_versions"] = versions()
    expected = {name: pins[name] for name in names}
    original = {"numpy": "1.26.4", "protobuf": "3.19.6", "tensorboardx": "2.6", "descript-audiotools": "0.7.2"}
    report["ok"] = (report["repeat_metadata_unchanged"] and report["install_versions"] == expected
                    and report["restore_recipe_versions"] == expected and report["rollback_versions"] == original)
    return report


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--fill-small-cache", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--compat-only", action="store_true", help="Only test four local wheels, repeat, rollback and restore; no dependencies")
    mode.add_argument("--repair-check", action="store_true", help="Inject four-package drift in a verified full sandbox and repair offline")
    parser.add_argument("--recover-cache", type=Path, help="Read/verify old cache payloads and export local wheels, never edit cache")
    parser.add_argument("--wheel-dir", type=Path, action="append", default=[], help="Reuse an existing local wheel directory")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.compat_only:
        report = validate_compat_only(args.root.resolve(), args.sandbox.absolute(), args.uv)
    elif args.repair_check:
        report = validate_repair(args.root.resolve(), args.sandbox.absolute(), args.uv, args.wheel_dir)
    else:
        report = validate(args.root.resolve(), args.sandbox.absolute(), args.uv, args.fill_small_cache,
                          args.recover_cache, args.wheel_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.compat_only or args.repair_check:
        return 0 if report["ok"] else 1
    return 0 if (report["fresh_install_ok"] and report["repeat_install"]["exit_code"] == 0
                 and report["repeat_metadata_unchanged"] and report["pip_check"]["exit_code"] == 0
                 and report["recipe_check"]["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
