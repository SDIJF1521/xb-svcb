"""macOS/MPS 配方的平台分支与底模供给校验。

这些用例不依赖真实 GPU、网络或大型权重：底模相关检查全部在临时目录里用
小文件（含真实的 git-lfs 指针内容）构造。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:60d936ec5a566776fc392e69ad8b630d14eb588111233fe313436e200a7b187b\n"
    "size 1268054784\n"
)


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def installer():
    return _load("xb_installer_macos_recipe_test", "install/install.py")


@pytest.fixture(scope="module")
def fetch_assets():
    return _load("xb_fetch_assets_recipe_test", "install/fetch_assets.py")


@pytest.fixture(scope="module")
def macos_recipe():
    return _load("xb_install_macos_recipe_test", "install/install_macos.py")


# --------------------------------------------------------------------------
# git-lfs 指针
# --------------------------------------------------------------------------
def test_pointer_detection_matches_both_implementations(installer, fetch_assets, tmp_path) -> None:
    pointer = tmp_path / "rmvpe.pt"
    pointer.write_text(LFS_POINTER, encoding="utf-8")
    real = tmp_path / "model.bin"
    real.write_bytes(b"\x00" * 64)

    assert installer._is_lfs_pointer(pointer) is True
    assert fetch_assets.is_lfs_pointer(pointer) is True
    assert installer._is_lfs_pointer(real) is False
    assert fetch_assets.is_lfs_pointer(real) is False
    assert fetch_assets.is_lfs_pointer(tmp_path / "missing.pt") is False


def test_usable_asset_rejects_pointer_and_undersized_files(fetch_assets, tmp_path) -> None:
    pointer = tmp_path / "checkpoint_best_legacy_500.pt"
    pointer.write_text(LFS_POINTER, encoding="utf-8")

    assert fetch_assets.is_usable_asset(pointer) is False
    assert fetch_assets.is_usable_asset(pointer, min_bytes=1) is False
    # A large file is accepted without touching pointer detection.
    big = tmp_path / "big.pt"
    big.write_bytes(b"\x00" * 2048)
    assert fetch_assets.is_usable_asset(big, min_bytes=1024) is True
    assert fetch_assets.is_usable_asset(big, min_bytes=4096) is False


def test_copy_bundled_refuses_to_deploy_lfs_pointers(installer, tmp_path, monkeypatch) -> None:
    assets = tmp_path / "assets" / "models" / "pretrain"
    assets.mkdir(parents=True)
    (assets / "rmvpe.pt").write_text(LFS_POINTER, encoding="utf-8")
    config_dir = tmp_path / "assets" / "models" / "pretrain" / "nsf_hifigan"
    config_dir.mkdir()
    (config_dir / "config.json").write_text('{"ok": true}', encoding="utf-8")

    monkeypatch.setattr(installer, "ASSETS_MODELS_DIR", tmp_path / "assets" / "models")
    destination = tmp_path / "out" / "rmvpe.pt"
    destination.parent.mkdir()

    # 指针被拒绝 -> 调用方会走联网下载分支
    assert installer.copy_bundled("pretrain/rmvpe.pt", destination) is False
    assert not destination.exists()

    # 正常的小文件（如 config.json）仍然会被部署
    assert installer.copy_bundled("pretrain/nsf_hifigan", tmp_path / "out" / "nsf_hifigan") is True
    assert (tmp_path / "out" / "nsf_hifigan" / "config.json").is_file()


# --------------------------------------------------------------------------
# 底模清单与 ensure_asset
# --------------------------------------------------------------------------
def _write_manifest(root: Path, assets: list[dict]) -> None:
    path = root / "assets" / "models" / "model-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "xb-svcb.models.v1", "assets": assets}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_inspect_manifest_flags_pointer_assets(fetch_assets, tmp_path) -> None:
    weights = tmp_path / "assets" / "models" / "pretrain" / "rmvpe.pt"
    weights.parent.mkdir(parents=True)
    weights.write_text(LFS_POINTER, encoding="utf-8")
    (tmp_path / "assets" / "models" / "uvr").mkdir(parents=True)
    (tmp_path / "assets" / "models" / "uvr" / "download_checks.json").write_text(
        '{"a": 1}', encoding="utf-8"
    )
    _write_manifest(
        tmp_path,
        [
            {
                "id": "seedvc.rmvpe",
                "engine": "seedvc",
                "source": "assets/models/pretrain/rmvpe.pt",
                "runtime": "assets/models/pretrain/rmvpe.pt",
                "required": True,
                "min_bytes": 300000000,
                "sha256": "0" * 64,
            },
            {
                "id": "uvr.download_checks",
                "engine": "uvr",
                "source": "assets/models/uvr/download_checks.json",
                "runtime": "models/uvr/download_checks.json",
                "required": True,
                "min_bytes": 1,
            },
        ],
    )

    result = fetch_assets.inspect(tmp_path)
    rows = {row["id"]: row for row in result["assets"]}
    assert rows["seedvc.rmvpe"]["status"] == "too_small"
    assert rows["uvr.download_checks"]["status"] in {"ok", "unverified"}
    problems = {row["id"] for row in fetch_assets.problem_rows(result)}
    assert problems == {"seedvc.rmvpe"}


def test_ensure_asset_raises_without_fetcher_and_recovers_with_one(
    fetch_assets, tmp_path
) -> None:
    source = tmp_path / "assets" / "models" / "pretrain" / "rmvpe.pt"
    source.parent.mkdir(parents=True)
    source.write_text(LFS_POINTER, encoding="utf-8")
    entry = {
        "id": "seedvc.rmvpe",
        "engine": "seedvc",
        "source": "assets/models/pretrain/rmvpe.pt",
        "min_bytes": 1024,
    }

    with pytest.raises(fetch_assets.AssetMissingError):
        fetch_assets.ensure_asset(entry, dest_root=tmp_path, fetch=False)

    with pytest.raises(fetch_assets.AssetMissingError, match="没有 .* 的下载方式"):
        fetch_assets.ensure_asset(entry, dest_root=tmp_path)

    def fetcher() -> None:
        source.write_bytes(b"\x01" * 4096)

    assert fetch_assets.ensure_asset(
        entry, dest_root=tmp_path, fetchers={"seedvc": fetcher}
    ) == source


def test_ensure_asset_accepts_a_healthy_file(fetch_assets, tmp_path) -> None:
    source = tmp_path / "assets" / "models" / "pretrain" / "fcpe.pt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"\x02" * 4096)
    entry = {
        "id": "pretrain.fcpe",
        "engine": "pretrain",
        "source": "assets/models/pretrain/fcpe.pt",
        "min_bytes": 1024,
    }

    assert fetch_assets.ensure_asset(entry, dest_root=tmp_path, fetch=False) == source


# --------------------------------------------------------------------------
# 平台分支
# --------------------------------------------------------------------------
def test_macos_recipe_rejects_non_darwin(macos_recipe, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert macos_recipe.macos_supported() is False
    with pytest.raises(RuntimeError, match="macOS"):
        macos_recipe._require_macos()


def test_macos_recipe_accepts_darwin(macos_recipe, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert macos_recipe.macos_supported() is True
    macos_recipe._require_macos()


def test_installer_mps_flag_is_rejected_off_macos(installer, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["install.py", "--mps"])
    assert installer.main() == 2


def test_installer_mps_conflicts_with_windows_stacks(installer, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    for extra in ("--cpu", "--rocm10", "--directml", "--cu126", "--cu128", "--consolidated"):
        monkeypatch.setattr(sys, "argv", ["install.py", "--mps", extra])
        assert installer.main() == 2, extra


def test_macos_recipe_declares_onnx_encoder_by_default() -> None:
    source = (ROOT / "install" / "install_macos.py").read_text(encoding="utf-8")
    # 默认零编译：onnx 编码器 + 可选 fairseq 编译路径
    assert 'SVC_ENCODERS = ("onnx", "fairseq")' in source
    assert "MAC_TORCH_SPECS" in source
    assert "fairseq-fixed==0.12.3.1" in source
    # uv 的共享 sdist 缓存会让 fairseq 编译触发沙箱批量删除保护，必须跳过缓存
    assert '"--no-cache"' in source


# --------------------------------------------------------------------------
# 引擎侧设备解析（MPS）
# --------------------------------------------------------------------------
class _FakeTorchMPS:
    """Minimal torch stand-in for the worker device resolvers."""

    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class _Mps:
        @staticmethod
        def is_available() -> bool:
            return True

    def __init__(self) -> None:
        self.cuda = self._Cuda()
        self.backends = SimpleNamespace(mps=self._Mps())


@pytest.fixture(scope="module")
def pymss_worker():
    return _load("xb_pymss_worker_recipe_test", "app/infrastructure/pymss_worker.py")


def test_pymss_auto_uses_apple_backend(pymss_worker, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorchMPS())
    device, backend = pymss_worker._resolve_device("auto")
    # PyMSS 自己的 auto 在 Apple Silicon 上优先 MLX、失败回退 Torch MPS，
    # 因此这里把 auto 透传，只用探测结果做标注。
    assert device == "auto"
    assert backend in {"mlx", "mps"}


def test_pymss_explicit_mps_requires_a_usable_device(pymss_worker, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorchMPS())
    assert pymss_worker._resolve_device("mps") == ("mps", "mps")

    class _NoMps(_FakeTorchMPS):
        class _Mps:
            @staticmethod
            def is_available() -> bool:
                return False

    monkeypatch.setitem(sys.modules, "torch", _NoMps())
    with pytest.raises(RuntimeError, match="MPS"):
        pymss_worker._resolve_device("mps")


def test_pymss_keeps_rejecting_directml(pymss_worker) -> None:
    with pytest.raises(RuntimeError, match="DirectML"):
        pymss_worker._resolve_device("directml")


@pytest.fixture(scope="module")
def svc_worker():
    return _load("xb_svc_worker_recipe_test", "app/infrastructure/svc_worker.py")


@pytest.fixture(scope="module")
def resolved_device_cls():
    module = _load("xb_inference_device_recipe_test", "app/infrastructure/inference_device.py")
    return module.ResolvedDevice


def _write_svc_config(tmp_path, encoder: str):
    # so-vits 4.x 的 config.json 把 speech_encoder 放在 model 子字典里
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": {"speech_encoder": encoder}}), encoding="utf-8")
    return str(path)


def test_svc_worker_logs_encoder_and_tolerates_missing_onnxruntime(
    svc_worker, resolved_device_cls, tmp_path, capsys
) -> None:
    device = resolved_device_cls(device="mps", backend="mps", name="Apple MPS")
    # onnxruntime 未安装时只提示，不应让整次推理失败
    svc_worker._log_speech_encoder(_write_svc_config(tmp_path, "vec768l12-onnx"), device)
    out = capsys.readouterr().out
    assert "XB_SVC_ENCODER vec768l12-onnx" in out


def test_svc_worker_explains_missing_fairseq_on_apple(
    svc_worker, resolved_device_cls, tmp_path
) -> None:
    device = resolved_device_cls(device="mps", backend="mps", name="Apple MPS")
    config = _write_svc_config(tmp_path, "vec768l12")
    with pytest.raises(RuntimeError, match="fairseq"):
        svc_worker._log_speech_encoder(config, device)


def test_svc_worker_ignores_non_apple_backends(
    svc_worker, resolved_device_cls, tmp_path
) -> None:
    device = resolved_device_cls(device="cuda:0", backend="cuda", name="NVIDIA")
    # CUDA 上保持上游原有行为（fairseq 由环境保证），不抛错
    svc_worker._log_speech_encoder(_write_svc_config(tmp_path, "vec768l12"), device)


def test_svc_worker_reads_top_level_encoder_too(
    svc_worker, resolved_device_cls, tmp_path, capsys
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"speech_encoder": "vec256l9"}), encoding="utf-8")
    device = resolved_device_cls(device="mps", backend="mps", name="Apple MPS")
    try:
        svc_worker._log_speech_encoder(str(path), device)
    except RuntimeError:
        pass  # 该环境没有 fairseq，只要日志缺别漏即可
    assert "XB_SVC_ENCODER vec256l9" in capsys.readouterr().out


# --------------------------------------------------------------------------
# data_home.json 的 Windows 路径不应在 macOS 上被当成相对路径
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_config():
    return _load("xb_app_config_recipe_test", "app/config.py")


def test_usable_data_dir_rejects_windows_paths_on_posix(app_config, monkeypatch) -> None:
    monkeypatch.setattr(app_config.os, "name", "posix")
    assert app_config.usable_data_dir("D:\\XB-SVCB\\.xb_svcb") is None
    assert app_config.usable_data_dir("C:/XB-SVCB") is None
    # 正常路径仍然接受
    assert app_config.usable_data_dir("/tmp/xb-data") == Path("/tmp/xb-data")
    assert app_config.usable_data_dir("relative/data") == Path("relative/data")
    assert app_config.usable_data_dir("") is None
    assert app_config.usable_data_dir(None) is None


def test_usable_data_dir_keeps_windows_paths_on_windows(app_config, monkeypatch) -> None:
    monkeypatch.setattr(app_config.os, "name", "nt")
    parsed = app_config.usable_data_dir("D:\\XB-SVCB\\.xb_svcb")
    assert parsed is not None and str(parsed).endswith(".xb_svcb")


# --------------------------------------------------------------------------
# 分离链：UVR 设备上报与 PyMSS 音轨命名
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def uvr_worker():
    return _load("xb_uvr_worker_recipe_test", "app/infrastructure/uvr_worker.py")


@pytest.fixture(scope="module")
def pymss_worker():
    return _load("xb_pymss_worker_recipe_test", "app/infrastructure/pymss_worker.py")


class _FakeTorchDevice:
    def __init__(self, text: str) -> None:
        self._text = text

    def __str__(self) -> str:  # noqa: D105 - 对齐 torch.device 的 str() 形态
        return self._text


def test_uvr_worker_reports_mps_device(uvr_worker) -> None:
    """Apple Silicon 上 audio-separator 自己会用 MPS，不能上报成 cpu。"""
    torch = SimpleNamespace(version=SimpleNamespace(hip=None))
    assert uvr_worker._torch_backend(torch, _FakeTorchDevice("mps")) == "mps"
    assert uvr_worker._torch_backend(torch, "mps:0") == "mps"
    assert uvr_worker._torch_backend(torch, "privateuseone:0") == "directml"
    assert uvr_worker._torch_backend(torch, "cuda:0") == "cuda"
    assert uvr_worker._torch_backend(torch, "cpu") == "cpu"
    assert uvr_worker._torch_backend(torch, None) == "cpu"
    hip = SimpleNamespace(version=SimpleNamespace(hip="6.2"))
    assert uvr_worker._torch_backend(hip, "cuda:0") == "rocm"


def test_pymss_second_stem_naming_matches_upstream(pymss_worker, tmp_path) -> None:
    """PyMSS 上游把第二轨命名为 instrument（instruments: vocals/instrument）。"""
    (tmp_path / "song_vocals.wav").write_bytes(b"v")
    (tmp_path / "song_instrument.wav").write_bytes(b"i")

    vocal = pymss_worker._find_stem(tmp_path, "vocal")
    instrumental = (
        pymss_worker._find_stem(tmp_path, "instrument")
        or pymss_worker._find_stem(tmp_path, "instrumental")
        or pymss_worker._find_stem(tmp_path, "other")
    )
    assert vocal is not None and vocal.stem == "song_vocals"
    assert instrumental is not None and instrumental.stem == "song_instrument"


# --------------------------------------------------------------------------
# 歌声增强：3.11 环境与 DeepFilterNet3 权重回退
# --------------------------------------------------------------------------
def test_vocal_env_uses_python311(macos_recipe) -> None:
    """deepfilterlib 0.5.6 没有 cp312 wheel，增强环境必须用 3.11。"""
    assert macos_recipe.VOCAL_PYTHON == "3.11"

    calls: dict[str, str] = {}

    class FakeInstaller:
        PYTHON_FOR_ENGINES = "3.12"

        @staticmethod
        def ensure_venv(_uv, _venv, spec):
            calls["venv_spec"] = spec

        @staticmethod
        def venv_python(venv):
            return Path(venv) / "bin" / "python"

        @staticmethod
        def make_pip(_uv, _py, *, component, gpu_stack, python_version):
            calls["pip_spec"] = python_version
            return lambda *args, **kwargs: None

    macos_recipe._pip_python(
        FakeInstaller, "uv", Path("/tmp/venv"), "vocal", macos_recipe.VOCAL_PYTHON
    )
    assert calls == {"venv_spec": "3.11", "pip_spec": "3.11"}

    # 未指定时仍沿用引擎统一版本
    macos_recipe._pip_python(FakeInstaller, "uv", Path("/tmp/venv"), "svc")
    assert calls["venv_spec"] == "3.12"


def test_deepfilter_model_falls_back_to_download(installer, monkeypatch, tmp_path) -> None:
    """自带权重是 git-lfs 指针时必须改为联网获取，而不是直接报错。"""
    model_root = tmp_path / "models" / "vocal-enhancement"
    monkeypatch.setattr(installer, "VOCAL_MODELS_DIR", model_root)
    monkeypatch.setattr(installer, "copy_bundled", lambda rel, dest: False)
    monkeypatch.setattr(installer, "run", lambda *args, **kwargs: None)
    fetched: dict[str, Path] = {}

    def fake_fetch(model_dir: Path) -> None:
        fetched["dir"] = model_dir
        (model_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (model_dir / "config.ini").write_text("sr=48000\n", encoding="utf-8")
        (model_dir / "checkpoints" / "model_120.ckpt.best").write_bytes(
            b"\x00" * installer.DEEPFILTER_CHECKPOINT_MIN_BYTES
        )

    monkeypatch.setattr(installer, "_fetch_deepfilter_bundle", fake_fetch)

    resolved = installer._prepare_vocal_deepfilter_model("python")

    assert fetched["dir"] == model_root / "DeepFilterNet3"
    assert resolved == fetched["dir"]


def test_deepfilter_bundle_urls_include_official_source(installer) -> None:
    urls = installer.DEEPFILTER_MODEL_URLS
    assert urls, "必须至少有一个官方下载源"
    assert all(u.startswith("https://") for u in urls)
    assert any("Rikorose/DeepFilterNet" in u for u in urls)
    assert any("DeepFilterNet3.zip" in u for u in urls)


def test_fetch_fcpe_model_skips_ready_file(installer, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(installer, "PRETRAIN_DIR", tmp_path)
    (tmp_path / "fcpe.pt").write_bytes(b"\x00" * installer.FCPE_MIN_BYTES)
    calls: list[object] = []
    monkeypatch.setattr(installer, "download", lambda urls, dest: calls.append(urls))

    assert installer.fetch_fcpe_model() is True
    assert calls == [], "已有可用权重时不应再联网"


def test_fetch_fcpe_model_downloads_and_degrades(installer, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(installer, "PRETRAIN_DIR", tmp_path)
    seen: dict[str, list[str]] = {}

    def fake_download(urls, dest):
        seen["urls"] = list(urls)
        Path(dest).write_bytes(b"\x00" * installer.FCPE_MIN_BYTES)

    monkeypatch.setattr(installer, "download", fake_download)
    assert installer.fetch_fcpe_model() is True
    assert any("fcpe.pt" in url for url in seen["urls"])

    def boom(urls, dest):
        raise RuntimeError("网络不可用")

    (tmp_path / "fcpe.pt").unlink()
    monkeypatch.setattr(installer, "download", boom)
    # 缺失只降级（应用回退 CREPE），不抛错
    assert installer.fetch_fcpe_model() is False


def test_fetch_fcpe_model_rejects_incomplete_download(installer, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(installer, "PRETRAIN_DIR", tmp_path)
    monkeypatch.setattr(
        installer,
        "download",
        lambda urls, dest: Path(dest).write_bytes(b"ptr"),  # 模拟只拿到指针
    )
    assert installer.fetch_fcpe_model() is False


# --------------------------------------------------------------------------
# 数据目录闸门：跨平台路径不得就地生成脏目录（例如 D:\XB-SVCB\.xb_svcb）
# --------------------------------------------------------------------------
def test_data_dir_rejection_reason(app_config, monkeypatch) -> None:
    monkeypatch.setattr(app_config.os, "name", "posix")
    assert app_config.data_dir_rejection_reason("D:\\XB-SVCB\\.xb_svcb") is not None
    assert "Windows" in str(app_config.data_dir_rejection_reason("C:/XB-SVCB"))
    assert app_config.data_dir_rejection_reason("/tmp/xb-data") is None
    assert app_config.data_dir_rejection_reason("relative/data") is None
    assert app_config.data_dir_rejection_reason(None) is not None

    monkeypatch.setattr(app_config.os, "name", "nt")
    assert app_config.data_dir_rejection_reason("D:\\XB-SVCB\\.xb_svcb") is None


def test_apply_data_dir_refuses_cross_platform_path(app_config, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_config.os, "name", "posix")
    monkeypatch.chdir(tmp_path)
    before = app_config.DATA_DIR

    with pytest.warns(RuntimeWarning):
        app_config._apply_data_dir(Path("D:\\XB-SVCB\\.xb_svcb"))

    assert app_config.DATA_DIR == before, "拒绝后必须保留原有数据目录"
    assert not Path("D:\\XB-SVCB").exists(), "不得就地生成跨平台路径目录"


def test_read_data_home_file_ignores_cross_platform_pointer(
    app_config, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(app_config.os, "name", "posix")
    pointer = tmp_path / "data_home.json"
    pointer.write_text(
        json.dumps({"data_dir": "D:\\XB-SVCB\\.xb_svcb"}), encoding="utf-8"
    )
    assert app_config._read_data_home_file(pointer) is None

    native = tmp_path / "native"
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"data_dir": str(native)}), encoding="utf-8")
    row = app_config._read_data_home_file(ok)
    assert row is not None and row[0] == native.resolve()


def test_bridge_rejects_cross_platform_target(app_config) -> None:
    """界面与 HTTP API 传入的路径字符串同样要走同一个闸门。"""
    sys.path.insert(0, str(ROOT / "app"))
    try:
        from api.bridge import Api
    except Exception as exc:  # noqa: BLE001 - 缺少桌面依赖时跳过
        pytest.skip(f"无法导入 api.bridge: {exc}")

    target, error = Api._resolve_data_dir_target(
        Api, "D:\\XB-SVCB\\.xb_svcb", app_config.DATA_DIR
    )
    assert target is None
    assert error and "Windows" in error
