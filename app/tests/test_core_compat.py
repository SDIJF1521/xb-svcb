from __future__ import annotations

import csv
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location("xb_" + name, ROOT / "install" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_distribution(tmp_path):
    builder = load("build_core_compat")
    site = tmp_path / "source"
    files = {
        "audiotools/__init__.py": b'__version__ = "0.7.2"\n',
        builder.ORIGINAL + "/METADATA": (
            b"Metadata-Version: 2.1\nName: descript-audiotools\nVersion: 0.7.2\n"
            b"Requires-Dist: protobuf (<3.20,>=3.9.2)\nRequires-Dist: tensorboard\n"
            b"Requires-Dist: torch\nLicense: MIT\n\nUpstream description\n"
        ),
        builder.ORIGINAL + "/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
    }
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    for relative, data in files.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        writer.writerow((relative, "sha256=" + builder.digest(data), len(data)))
    writer.writerow((builder.ORIGINAL + "/RECORD", "", ""))
    (site / builder.ORIGINAL / "RECORD").write_text(rows.getvalue(), encoding="utf-8")
    return builder, site, files


def test_local_wheel_is_distinct_reproducible_and_preserves_source(tmp_path):
    builder, site, files = source_distribution(tmp_path)
    wheel = builder.build(site, tmp_path / "output")
    original = wheel.read_bytes()
    assert builder.build(site, tmp_path / "output").read_bytes() == original
    for relative, data in files.items():
        assert (site / relative).read_bytes() == data
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(builder.PATCHED + "/METADATA").decode()
        assert "Version: 0.7.2+xb1" in metadata
        assert "Requires-Dist: protobuf ==7.36.0" in metadata
        assert "Requires-Dist: torch" in metadata
        assert "License: MIT" in metadata
        for name, checksum, size in csv.reader(io.StringIO(archive.read(builder.PATCHED + "/RECORD").decode())):
            if checksum:
                data = archive.read(name)
                assert checksum == "sha256=" + builder.digest(data)
                assert size == str(len(data))
        assert json.loads(archive.read(builder.PATCHED + "/xb_compatibility.json"))["experimental"]


def test_builder_rejects_modified_installed_files(tmp_path):
    builder, site, _ = source_distribution(tmp_path)
    (site / "audiotools/__init__.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="RECORD validation failed"):
        builder.build(site, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_wheel_and_installed_record_build_identical_wheels(tmp_path):
    builder, site, _ = source_distribution(tmp_path)
    upstream = tmp_path / "original.whl"
    with zipfile.ZipFile(upstream, "w") as archive:
        for path in site.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(site).as_posix())
    from_wheel = builder.build_from_wheel(upstream, tmp_path / "from-wheel")
    # uv/pip append machine/installer-specific rows; these must not affect provenance.
    record = site / builder.ORIGINAL / "RECORD"
    record.write_text(record.read_text() + builder.ORIGINAL + "/INSTALLER,,\n", encoding="utf-8")
    from_site = builder.build(site, tmp_path / "from-site")
    assert from_wheel.read_bytes() == from_site.read_bytes()


def test_source_wheel_rejects_traversal_before_extraction(tmp_path):
    builder = load("build_core_compat")
    upstream = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(upstream, "w") as archive:
        archive.writestr("../escaped", "invalid")
    with pytest.raises(ValueError, match="Unsafe"):
        builder.build_from_wheel(upstream, tmp_path / "out")
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("path", ["../outside", "C:/outside", "/outside", "other_package/code.py"])
def test_builder_rejects_unexpected_record_paths(tmp_path, path):
    builder, site, _ = source_distribution(tmp_path)
    record = site / builder.ORIGINAL / "RECORD"
    record.write_text(f"{path},sha256=invalid,0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        builder.build(site, tmp_path / "out")


def test_compatibility_recipe_only_changes_explicit_shared_install(tmp_path):
    installer = load("install")
    installer.CORE_COMPAT_WHEEL = tmp_path / "candidate.whl"
    assert installer._core_requirement_overrides("seedvc") == {}
    assert installer._core_requirement_overrides("ddsp") == installer.DDSP_REQ_OVERRIDES
    installer.CONSOLIDATED_RUNTIME = True
    assert installer._core_requirement_overrides("seedvc") == {"numpy": "numpy==2.2.6"}
    assert installer._core_requirement_overrides("ddsp")["transformers"] == "transformers==4.46.3"
    installer.CORE_COMPAT_WHEEL = None
    assert "numpy" not in installer._core_requirement_overrides("ddsp")


def test_compat_preflight_only_includes_new_pins_and_never_installs(tmp_path, monkeypatch):
    builder, site, _ = source_distribution(tmp_path)
    wheel = builder.build(site, tmp_path / "wheels")
    installer = load("install")
    installer._derive_paths(tmp_path)
    for source in (installer.SEEDVC_DIR, installer.DDSP_DIR):
        source.mkdir(parents=True)
        (source / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    monkeypatch.setattr(installer, "ensure_uv", lambda: "uv")
    monkeypatch.setattr(installer, "detect_gpu_stack", lambda: "cu128")
    monkeypatch.setattr(installer, "_wheelhouse_dirs", lambda **kwargs: [])
    monkeypatch.setattr(installer, "STEPS", {name: lambda *args: pytest.fail("unexpected installation")
                                            for name in installer.ORDER})
    monkeypatch.setattr(installer.sys, "argv", ["install.py", "--consolidated", "--cu128", "--only", "uvr", "seedvc", "ddsp",
                                              "--core-compat-wheel", str(wheel), "--preflight-only"])

    def compile_only(command):
        assert command[1:3] == ["pip", "compile"]
        combined = Path(command[3]).read_text(encoding="utf-8")
        assert "numpy==1.26.4" not in combined
        assert "numpy==2.2.6" in combined
        assert "protobuf==7.36.0" in combined
        assert "tensorboardX==2.6.5" in combined
        assert wheel.resolve().as_uri() in combined
        Path(command[command.index("--output-file") + 1]).write_text("# test lock\n")

    monkeypatch.setattr(installer, "run", compile_only)
    assert installer.main() == 0
    assert not installer.CORE_VENV.exists()
    assert not installer.RUNTIME_MANIFEST.exists()
    assert (installer.SEEDVC_DIR / "requirements.txt").read_text() == "numpy==1.26.4\n"


def test_installer_rejects_plain_upstream_wheel(tmp_path):
    builder, site, files = source_distribution(tmp_path)
    wheel = tmp_path / "invalid.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(builder.PATCHED + "/METADATA", files[builder.ORIGINAL + "/METADATA"])
    with pytest.raises(ValueError, match="不匹配"):
        load("install")._validate_core_compat_wheel(wheel)


def test_probe_only_overrides_requested_modules_and_blocks_network():
    probe = load("probe_core_compat")
    header = probe.probe_header({"google.protobuf": "test/google"})
    assert "if fullname in SOURCES" in header
    assert "socket.connect" in header
    assert "sys.path.insert" not in header
    assert set(probe.checks(ROOT)) == {"uvr_onnx", "seedvc", "ddsp", "tensorboard", "tensorboardx"}
