"""Read-only, no-download dependency/import audit of the executing interpreter.

Run with the MODEL runtime's Python, not the desktop application's Python.
Passing this check is necessary, but is not an audio inference/quality test.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path


def dependency_issues() -> list[str]:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    distributions = list(metadata.distributions())
    versions = {canonicalize_name(dist.metadata["Name"]): dist.version
                for dist in distributions if dist.metadata.get("Name")}
    issues = []
    for dist in distributions:
        for raw in dist.requires or []:
            try:
                requirement = Requirement(raw)
                if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                    continue
                actual = versions.get(canonicalize_name(requirement.name))
                if actual is None or (requirement.specifier and
                                      not requirement.specifier.contains(actual, prereleases=True)):
                    issues.append(f"{dist.metadata['Name']}=={dist.version} requires {requirement}; "
                                  f"installed: {actual or 'MISSING'}")
            except (ValueError, TypeError) as exc:
                issues.append(f"Invalid requirement in {dist.metadata.get('Name')}: {raw}: {exc}")
    return sorted(set(issues))


def probe(name: str, code: str, cwd: Path, timeout: int) -> dict:
    if not cwd.is_dir():
        return {"name": name, "ok": False, "error": f"Missing source directory: {cwd}"}
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8")
    # Imports only; refuse Python socket connections even if a library ignores
    # the HuggingFace offline flags. This is not an OS security sandbox.
    offline = (
        "import sys\n"
        "def deny_network(event, args):\n"
        "    if event in ('socket.connect', 'socket.sendto'):\n"
        "        raise RuntimeError('Network disabled during runtime audit')\n"
        "sys.addaudithook(deny_network)\n"
    )
    try:
        result = subprocess.run([sys.executable, "-B", "-c", offline + code], cwd=cwd,
                                env=env, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"name": name, "ok": result.returncode == 0,
                "exit_code": result.returncode, "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-6000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"name": name, "ok": False, "error": str(exc)}


def audit(root: Path, timeout: int = 45, require_cuda: bool = False) -> dict:
    versions = {}
    for name in ("torch", "torchaudio", "torchvision", "numpy", "protobuf",
                 "audio-separator", "onnx-weekly", "descript-audiotools", "transformers"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    try:
        issues = dependency_issues()
    except ImportError as exc:
        issues = [f"Cannot audit dependency metadata: {exc}"]
    torch_code = (
        "import torch, torchaudio, torchvision\n"
        "print(torch.__version__, torchaudio.__version__, torchvision.__version__)\n"
        "print('CUDA available:', torch.cuda.is_available())\n"
    )
    if require_cuda:
        torch_code += (
            "assert torch.cuda.is_available(), 'Requested CUDA runtime is unavailable'\n"
            "print(torch.cuda.get_device_name(0))\n"
            "print('CUDA computation:', torch.ones(1, device='cuda').sum().item())\n"
        )
    checks = [
        ("torch", torch_code, root),
        ("uvr_mdx", "from audio_separator.separator.architectures.mdx_separator import MDXSeparator", root),
        ("uvr_vr", "from audio_separator.separator.architectures.vr_separator import VRSeparator", root),
        ("seedvc", "import inference; from modules.length_regulator import InterpolateRegulator", root / "engines/seed-vc"),
        ("ddsp", "import ddsp.vocoder; import reflow.vocoder", root / "engines/ddsp-svc"),
    ]
    imports = [probe(name, code, cwd, timeout) for name, code, cwd in checks]
    return {"python": sys.executable, "root": str(root), "versions": versions,
            "dependency_issues": issues, "imports": imports,
            "ok": not issues and all(item["ok"] for item in imports),
            "audio_inference_tested": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="Optional JSON report; no environment changes")
    parser.add_argument("--timeout", type=int, default=45, help="Timeout per import subprocess")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    report = audit(args.root.resolve(), args.timeout, args.require_cuda)
    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
