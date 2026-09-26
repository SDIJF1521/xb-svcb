"""构建 Python 3.12 RVC 依赖配方，保留上游代码。"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

VERSION = "0.1.5+xb312"
WHEEL_NAME = f"rvc_python-{VERSION}-py3-none-any.whl"
REQUIREMENT = f"rvc-python=={VERSION}"
REPLACEMENTS = {
    "fairseq==0.12.2": "fairseq-fixed==0.12.3.1",
    "faiss-cpu==1.7.3": "faiss-cpu==1.8.0",
    "numpy<=1.23.5": "numpy>=1.26.4,<2",
    "omegaconf==2.0.6": "omegaconf==2.3.0",
}


def digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def build(source: Path, output: Path) -> Path:
    original = "rvc_python-0.1.5.dist-info"
    patched = f"rvc_python-{VERSION}.dist-info"
    with zipfile.ZipFile(source) as wheel:
        payload = {name: wheel.read(name) for name in wheel.namelist() if not name.endswith("/")}
    record = original + "/RECORD"
    for name, checksum, size in csv.reader(io.StringIO(payload[record].decode())):
        if name != record and (checksum != "sha256=" + digest(payload[name]) or size != str(len(payload[name]))):
            raise ValueError(f"RVC source RECORD mismatch: {name}")
    metadata_key = original + "/METADATA"
    metadata = BytesParser(policy=policy.compat32).parsebytes(payload[metadata_key])
    if metadata["Name"] != "rvc-python" or metadata["Version"] != "0.1.5":
        raise ValueError("Expected rvc-python 0.1.5")
    requirements = metadata.get_all("Requires-Dist", [])
    if not set(REPLACEMENTS).issubset(requirements):
        raise ValueError("RVC upstream dependency declarations changed")
    del metadata["Requires-Dist"]
    for req in requirements:
        metadata["Requires-Dist"] = REPLACEMENTS.get(req, req)
    metadata.replace_header("Version", VERSION)
    if metadata["Requires-Python"]:
        metadata.replace_header("Requires-Python", ">=3.12,<3.13")
    else:
        metadata["Requires-Python"] = ">=3.12,<3.13"
    payload[metadata_key] = metadata.as_bytes()
    del payload[record]
    payload = {name.replace(original + "/", patched + "/", 1): data for name, data in payload.items()}
    payload[patched + "/xb_compatibility.json"] = json.dumps({
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "dependencies": REPLACEMENTS, "full_model_inference_validated": False,
    }, sort_keys=True).encode()
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    for name, data in sorted(payload.items()):
        writer.writerow((name, "sha256=" + digest(data), len(data)))
    writer.writerow((patched + "/RECORD", "", ""))
    payload[patched + "/RECORD"] = rows.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / WHEEL_NAME
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as wheel:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            wheel.writestr(info, data)
    return destination


def prepare(output: Path, sources: list[Path], *, offline: bool = False) -> Path:
    for directory in sources:
        ready = directory / WHEEL_NAME
        if ready.is_file():
            return ready
    source_name = "rvc_python-0.1.5-py3-none-any.whl"
    source = next((directory / source_name for directory in sources if (directory / source_name).is_file()), None)
    if source is None:
        if offline:
            raise RuntimeError("Python 3.12 RVC compatibility wheel is missing; rebuild the wheelhouse")
        with urllib.request.urlopen("https://pypi.org/pypi/rvc-python/0.1.5/json", timeout=30) as response:
            metadata = json.load(response)
        artifact = next(item for item in metadata["urls"] if item["filename"] == source_name)
        with urllib.request.urlopen(artifact["url"], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != artifact["digests"]["sha256"]:
            raise ValueError("RVC download checksum mismatch")
        output.mkdir(parents=True, exist_ok=True)
        source = output / source_name
        source.write_bytes(data)
    return build(source, output)
