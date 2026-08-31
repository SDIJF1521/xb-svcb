from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.installer
FILENAME = "example-1.0-py3-none-any.whl"
DIST = "example-1.0.dist-info"


def module():
    spec = importlib.util.spec_from_file_location("recover_cache_test", ROOT / "install/recover_cached_wheel.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture(tmp_path):
    cache = tmp_path / "cache"
    archive = cache / "archive-v0/verified-payload"
    content = {"example/__init__.py": b"VALUE = 42\n",
               DIST + "/METADATA": b"Metadata-Version: 2.1\nName: example\nVersion: 1.0\n",
               DIST + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"}
    rows = io.StringIO(newline="")
    writer = csv.writer(rows)
    for name, data in content.items():
        path = archive / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name.replace("/", "\\"), "sha256=" + digest, len(data)))
    writer.writerow((DIST + "\\RECORD", "", ""))
    (archive / DIST / "RECORD").write_text(rows.getvalue(), encoding="utf-8")
    ref = cache / "wheels-v5/index/abc/example/1.0-py3-none-any"
    ref.parent.mkdir(parents=True)
    ref.write_text("archive-v0/verified-payload", encoding="utf-8")
    return cache, archive, content


def test_recovery_preserves_every_functional_byte_and_cache(tmp_path):
    cache, archive, content = fixture(tmp_path)
    source_record = (archive / DIST / "RECORD").read_bytes()
    before = {str(p): p.stat().st_mtime_ns for p in cache.rglob("*") if p.is_file()}
    output = tmp_path / "exports"
    report = module().recover(cache, FILENAME, output)
    assert report["local_repack"] and not report["upstream_wheel_sha256_verified"]
    assert report["payload_files"] == len(content)
    with zipfile.ZipFile(output / FILENAME) as wheel:
        for name, value in content.items():
            assert wheel.read(name) == value
        assert "\\" not in wheel.read(DIST + "/RECORD").decode()
    assert (archive / DIST / "RECORD").read_bytes() == source_record
    assert before == {str(p): p.stat().st_mtime_ns for p in cache.rglob("*") if p.is_file()}
    assert json.loads((output / (FILENAME + ".provenance.json")).read_text())["wheel_sha256"] == report["wheel_sha256"]


@pytest.mark.parametrize("problem", ["tamper", "extra", "missing", "unhashed", "duplicate", "escape", "self_missing"])
def test_recovery_rejects_corrupt_or_modified_payload(tmp_path, problem):
    cache, archive, _ = fixture(tmp_path)
    record = archive / DIST / "RECORD"
    if problem == "tamper":
        (archive / "example/__init__.py").write_bytes(b"VALUE = 43\n")
    elif problem == "extra":
        (archive / DIST / "INSTALLER").write_text("uv")
    elif problem == "missing":
        (archive / "example/__init__.py").unlink()
    else:
        rows = list(csv.reader(io.StringIO(record.read_text())))
        if problem == "unhashed":
            rows[0][1] = ""
        elif problem == "duplicate":
            rows.append(rows[0])
        elif problem == "escape":
            rows[0][0] = "../outside.py"
        else:
            rows.pop()
        stream = io.StringIO(newline="")
        csv.writer(stream).writerows(rows)
        record.write_text(stream.getvalue())
    output = tmp_path / "exports"
    with pytest.raises((ValueError, OSError)):
        module().recover(cache, FILENAME, output)
    assert not (output / FILENAME).exists()


def test_recovery_refuses_output_inside_cache_and_existing_wheel(tmp_path):
    cache, _, _ = fixture(tmp_path)
    recovery = module()
    with pytest.raises(ValueError, match="outside"):
        recovery.recover(cache, FILENAME, cache / "exports")
    output = tmp_path / "exports"
    recovery.recover(cache, FILENAME, output)
    before = (output / FILENAME).read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        recovery.recover(cache, FILENAME, output)
    assert (output / FILENAME).read_bytes() == before


@pytest.mark.parametrize("filename", ["../example.whl", "example-1.0-cp312-cp312-win_amd64.whl", "example-2.0-py3-none-any.whl", "example-1.0-*-none-any.whl"])
def test_recovery_never_substitutes_other_versions_or_platforms(tmp_path, filename):
    cache, _, _ = fixture(tmp_path)
    with pytest.raises((ValueError, LookupError)):
        module().recover(cache, filename, tmp_path / "exports")
