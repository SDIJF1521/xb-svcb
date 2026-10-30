from __future__ import annotations

import configparser
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_BUILDER = ROOT / "installer" / "build_online_manifest.py"
ONLINE_SCRIPT = ROOT / "installer" / "xb-svcb-online.iss"
ONLINE_BUILD = ROOT / "installer" / "build-online.ps1"


def _load_manifest_builder():
    spec = importlib.util.spec_from_file_location(
        "xb_build_online_manifest", MANIFEST_BUILDER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_release_files(dist: Path, builder) -> None:
    dist.mkdir(parents=True, exist_ok=True)
    for stack, base_name in builder.STACK_BASE_NAMES.items():
        (dist / f"{base_name}.exe").write_bytes(f"setup:{stack}".encode())
        # Create out of order to prove manifest ordering is numeric, not lexical.
        (dist / f"{base_name}-2.bin").write_bytes(f"part2:{stack}".encode())
        (dist / f"{base_name}-1.bin").write_bytes(f"part1:{stack}".encode())


def test_online_manifest_pins_every_release_artifact(tmp_path: Path) -> None:
    builder = _load_manifest_builder()
    dist = tmp_path / "dist"
    output = dist / "online-manifest.ini"
    _write_release_files(dist, builder)

    manifest = builder.build_manifest(dist, output, "0.1.0")

    assert manifest["release"]["version"] == "0.1.0"
    assert manifest["release"]["stacks"].split(",") == list(
        builder.STACK_BASE_NAMES
    )
    for stack, base_name in builder.STACK_BASE_NAMES.items():
        section = manifest[f"stack.{stack}"]
        expected_names = [
            f"{base_name}.exe",
            f"{base_name}-1.bin",
            f"{base_name}-2.bin",
        ]
        assert section["count"] == "3"
        assert section["setup"] == expected_names[0]
        assert [section[f"file{i}"] for i in range(3)] == expected_names
        for index, name in enumerate(expected_names):
            content = (dist / name).read_bytes()
            assert section[f"sha256_{index}"] == hashlib.sha256(content).hexdigest()
            assert section[f"size_{index}"] == str(len(content))

    parsed = configparser.ConfigParser(interpolation=None)
    parsed.read(output, encoding="utf-8")
    assert parsed["stack.cu128"]["file1"] == "XB-SVCB-Setup-CUDA128-1.bin"


def test_online_manifest_requires_all_five_packages(tmp_path: Path) -> None:
    builder = _load_manifest_builder()
    dist = tmp_path / "dist"
    _write_release_files(dist, builder)
    missing_base = builder.STACK_BASE_NAMES["directml"]
    (dist / f"{missing_base}.exe").unlink()

    with pytest.raises(FileNotFoundError):
        builder.build_manifest(dist, dist / "online-manifest.ini", "0.1.0")


def test_online_manifest_rejects_noncontiguous_split_volumes(tmp_path: Path) -> None:
    builder = _load_manifest_builder()
    dist = tmp_path / "dist"
    base_name = builder.STACK_BASE_NAMES["cpu"]
    dist.mkdir()
    (dist / f"{base_name}.exe").write_bytes(b"setup")
    (dist / f"{base_name}-1.bin").write_bytes(b"one")
    (dist / f"{base_name}-3.bin").write_bytes(b"three")

    with pytest.raises(ValueError, match="not contiguous"):
        builder.collect_stack(dist, "cpu")


def test_online_inno_script_localizes_and_verifies_downloads() -> None:
    script = ONLINE_SCRIPT.read_text(encoding="utf-8")

    assert '#define MyAppVersion "0.1.0"' in script
    assert 'Name: "zhcn"; MessagesFile: "languages\\ChineseSimplified.isl"' in script
    assert 'Name: "en"; MessagesFile: "compiler:Default.isl"' in script
    assert 'Name: "ja"; MessagesFile: "languages\\Japanese.isl"' in script
    assert "DownloadPage.Add(ArtifactUrl(ManifestName), ManifestName," in script
    assert "'{#XB_ONLINE_MANIFEST_SHA256}'" in script
    assert "DownloadPage.Add(ArtifactUrl(FileName), FileName, HashValue)" in script
    assert "function IsSafeBaseName" in script
    assert "function IsHexHash" in script
    assert "GetIniString(SectionName, 'file0'" in script
    assert "ActiveLanguage()" in script
    assert "ewWaitUntilTerminated" in script
    assert "Get-CimInstance Win32_VideoController" in script
    assert "--query-gpu=compute_cap" in script
    assert "ExpandConstant('{src}')" in script
    assert "XB-SVCB-Downloads\\{#MyAppVersion}\\" in script
    assert "ForceDirectories(DownloadDirectory)" in script
    assert "CopyFile(TempPath, DestinationPath, False)" in script
    assert "DownloadedSetup := AddBackslash(DownloadDirectory) + SetupName" in script

    custom = script.split("[CustomMessages]", 1)[1].split("[Code]", 1)[0]
    catalogs: dict[str, set[str]] = {
        language: set() for language in ("zhcn", "en", "ja")
    }
    for language, key in re.findall(
        r"^(zhcn|en|ja)\.([A-Za-z0-9]+)=", custom, re.MULTILINE
    ):
        catalogs[language].add(key)
    assert catalogs["zhcn"]
    assert catalogs["zhcn"] == catalogs["en"] == catalogs["ja"]

    code = script.split("[Code]", 1)[1]
    referenced = set(re.findall(r"\bM(?:[12])?\('([A-Za-z0-9]+)'", code))
    assert referenced <= catalogs["en"]
    assert re.findall(r"'[^'\r\n]*[\u4e00-\u9fff][^'\r\n]*'", code) == []


def test_online_build_uses_public_url_without_oss_credentials() -> None:
    build = ONLINE_BUILD.read_text(encoding="utf-8")

    assert "$env:XB_OSS_BASE_URL" in build
    assert "must use HTTPS" in build
    assert "plain HTTP is allowed only for localhost tests" in build
    assert "Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256" in build
    assert "/DXB_ONLINE_BASE_URL=$publicBaseUrl" in build
    assert "/DXB_ONLINE_MANIFEST_SHA256=$manifestHash" in build
    assert "AccessKey" not in build
    assert "Secret" not in build


def test_release_installers_use_the_web_favicon_as_the_canonical_icon() -> None:
    offline = (ROOT / "installer" / "xb-svcb.iss").read_text(encoding="utf-8")
    online = ONLINE_SCRIPT.read_text(encoding="utf-8")
    spec = (ROOT / "installer" / "xb-svcb-app.spec").read_text(encoding="utf-8")

    assert "SetupIconFile=..\\web\\public\\favicon.ico" in offline
    assert 'Source: "..\\web\\public\\favicon.ico"' in offline
    assert "SetupIconFile=..\\web\\public\\favicon.ico" in online
    assert 'ICON = ROOT / "web" / "public" / "favicon.ico"' in spec
    assert "assets\\icon\\xb-svcb.ico" not in offline
    assert "assets" not in spec.split("ICON =", 1)[1].splitlines()[0]


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell installer build")
@pytest.mark.parametrize("flag", ["-Help", "-h", "--help"])
def test_online_installer_build_help_exits_before_release_checks(
    tmp_path: Path, flag: str
) -> None:
    script = tmp_path / "build-online.ps1"
    script.write_bytes(ONLINE_BUILD.read_bytes())

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            flag,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage: .\\installer\\build-online.ps1" in result.stdout
    assert "-BaseUrl" in result.stdout
    assert "Online installer validation passed" not in result.stdout
