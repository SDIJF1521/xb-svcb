"""macOS（Apple Silicon / PyTorch MPS）运行环境搭建。

用法（项目根目录）：

    python3.12 install/install.py --mps
    python3.12 install/install.py --mps --only seedvc ddsp
    python3.12 install/install.py --mps --svc-encoder fairseq

设计要点
--------
* 只使用 PyPI 上自带 MPS 的 macOS arm64 wheel；Windows 平台锁文件与
  ``uv pip compile --python-platform windows`` 完全不参与本流程。
* 每个引擎使用隔离环境（与既有 CPU / DirectML 布局一致），并把解释器
  路由写入 ``runtime.json``，由 ``app/config.py`` 的清单解析读取。
* So-VITS-SVC 默认只装 ONNX 语音编码器所需的 onnxruntime（零本地编译）；
  ``--svc-encoder fairseq`` 才额外从 sdist 编译 fairseq-fixed。
* 平台无关的步骤（app / plugins / web / hub / models）直接复用
  ``install.py`` 的实现，避免两套逻辑漂移。
"""

from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from pathlib import Path
from typing import Any

MPS_STACK = "mps"
# Torch pair validated on Apple silicon for this project's engine stacks.
# PyPI's macOS arm64 wheels already contain the MPS backend.
MAC_TORCH_SPECS = ("torch==2.7.1", "torchaudio==2.7.1")
# DeepFilterNet 的 Rust 原生库 deepfilterlib 0.5.6 只发布了 cp38/39/310/311 的
# wheel（含 macosx_11_0_arm64），3.12 下没有任何预编译包：uv 会退回源码编译，
# 并要求 Rust/maturin 工具链。增强环境本身是隔离环境，单独用 3.11 就能直接吃
# 官方 arm64 wheel，避免为了一个可选功能给整机装 Rust。
VOCAL_PYTHON = "3.11"
FAIRSEQ_SPEC = "fairseq-fixed==0.12.3.1"
SVC_ENCODERS = ("onnx", "fairseq")

_INSTALLER: Any = None


def _load_sibling(name: str, filename: str) -> Any:
    """Load a sibling installer module exactly once."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"无法加载 {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _installer() -> Any:
    """Load ``install.py`` as a library (same approach as prepare_wheelhouse)."""
    global _INSTALLER
    if _INSTALLER is None:
        _INSTALLER = _load_sibling("xb_installer_macos_base", "install.py")
    return _INSTALLER


def macos_supported() -> bool:
    """Return whether this host matches the macOS/MPS recipe."""
    return sys.platform == "darwin"


def _require_macos() -> None:
    if not macos_supported():
        raise RuntimeError("--mps 安装配方仅支持 macOS（Apple Silicon）")


def _machine_note() -> str:
    machine = platform.machine() or "unknown"
    if machine != "arm64":
        return (
            f"当前架构为 {machine}；Apple MPS 只在 Apple Silicon(arm64) 上可用，"
            "安装会继续，但推理需要退回 CPU"
        )
    return f"Apple Silicon {machine}"


def _pip_python(
    ins: Any,
    uv: str,
    venv: Path,
    component: str,
    python_version: str | None = None,
):
    """Create the isolated venv and return ``(python, pip)``."""
    spec = python_version or ins.PYTHON_FOR_ENGINES
    # ensure_venv 在解释器版本不符时会自动重建，因此换版本不需要人工清理旧环境。
    ins.ensure_venv(uv, venv, spec)
    py = str(ins.venv_python(venv))
    pip = ins.make_pip(
        uv,
        py,
        component=component,
        gpu_stack=MPS_STACK,
        python_version=spec,
    )
    return py, pip


def _verify_mps(py: str, label: str, ins: Any) -> None:
    """Report whether this environment can reach Apple's GPU backend."""
    check = (
        "import torch;"
        "print('TORCH', torch.__version__, bool(torch.backends.mps.is_available()))"
    )
    probe = ins.subprocess.run(
        [py, "-c", check],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    lines = (probe.stdout or "").strip().splitlines()
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(f"{label} 环境导入 torch 失败：{detail[0] if detail else '无输出'}")
    line = lines[-1] if lines else ""
    if line.endswith("True"):
        print(ins.c("g", f"    {label} MPS 可用：{line}"))
        return
    print(
        ins.c(
            "y",
            f"    {label} 未探测到 MPS（{line or '无输出'}）；"
            "推理会退回 CPU，请检查 macOS 版本与 PyTorch 构建",
        )
    )


def _filtered_requirements(ins: Any, src: Path, *, deny: set[str], overrides: dict) -> Path:
    return ins._filter_requirements(src, extra_deny=deny, overrides=overrides)


def _python312_overrides(ins: Any, *, with_fairseq: bool = False) -> dict[str, str]:
    """Python 3.12 兼容覆盖。

    ``install.py`` 的固定覆盖里含 ``fairseq -> fairseq-fixed==0.12.3.1``；由于
    ``_filter_requirements`` 会把未出现在源文件里的覆盖项追加进去，直接沿用
    会让 SeedVC / DDSP 这类**不需要 fairseq** 的引擎也被迫本地编译一次。
    """
    overrides = dict(ins.PYTHON312_REQ_OVERRIDES)
    if not with_fairseq:
        overrides.pop("fairseq", None)
    return overrides


def _install_fairseq(ins: Any, uv: str, py: str, component: str) -> None:
    """从 sdist 编译安装 fairseq-fixed（Apple Silicon 上已实测可编译）。

    必须加 ``--no-cache``：uv 的共享 sdist 缓存在 macOS 上会让 bdist_wheel 的
    构建目录清理触发沙箱批量删除保护，表现为误导性的
    "Failed to build fairseq-fixed"。跳过缓存即可正常产出 wheel。
    """
    ins.uv_pip_install(
        uv,
        py,
        "--no-cache",
        FAIRSEQ_SPEC,
        component=component,
        gpu_stack=MPS_STACK,
        python_version=ins.PYTHON_FOR_ENGINES,
    )


# --------------------------------------------------------------------------
# 各步骤
# --------------------------------------------------------------------------
def step_uvr(ins: Any, uv: str) -> None:
    ins.hr("UVR 人声分离环境 .venv-uvr（audio-separator）")
    py, pip = _pip_python(ins, uv, ins.UVR_VENV, "uvr")
    pip("setuptools<81", "wheel")
    # audio-separator 只声明 torch>=2.3，解析器会拉到最新版（实测 2.14.1），
    # 与随后单独安装的 torchaudio 形成版本错配；所以先让它解析依赖，再回落
    # 到已验证的 MPS 组合（PyPI macOS arm64 wheel，自带 MPS/CoreML 提供器）。
    pip(f"audio-separator[cpu]=={ins.AUDIO_SEPARATOR_VER}")
    pip(*MAC_TORCH_SPECS)
    # uvr_lib_v5 会无条件 import 下面两个包，但 audio-separator 没有声明它们
    # （audioread 过去由 librosa<0.10 顺带带进来，现在不再有）。
    pip("audioread", "filetype")
    # audio-separator 0.44.2 仍用 librosa<1.0 的 get_duration(filename=...)，而
    # 解析器会拉到 librosa 1.0（该参数已移除）——分离进行到取时长时会报
    # “get_duration() got an unexpected keyword argument 'filename'”。
    pip("librosa<1.0")
    # audio-separator 会顺带拉入与新版 torch 绑定的 torchvision；回落 torch 后它
    # 已失效（import 报 operator torchvision::nms does not exist），而
    # audio-separator 自身并不使用它，直接清掉以免留下坏包。
    try:
        ins.run([uv, "pip", "uninstall", "--python", py, "torchvision"])
    except Exception as exc:  # noqa: BLE001 - 环境清理失败不影响推理
        print(ins.c("y", f"    torchvision 清理跳过（{exc}）"))
    _verify_mps(py, "UVR", ins)
    ins.run(
        [
            py,
            "-c",
            "import torchaudio; from audio_separator.separator import Separator; "
            "print('UVR OK', torchaudio.__version__)",
        ]
    )
    print(ins.c("g", "UVR 分离环境就绪（Apple MPS / CoreML 自动探测）"))


def step_pymss(ins: Any, uv: str) -> None:
    ins.hr("PyMSS 分离环境 .venv-pymss")
    py, pip = _pip_python(ins, uv, ins.PYMSS_VENV, "pymss")
    pip("setuptools<81", "wheel")
    pip(*MAC_TORCH_SPECS)
    pip(f"pymss=={ins.PYMSS_VERSION}")
    # MLX 是 PyMSS 在 Apple Silicon 上的首选后端（auto 时优先），MPS 作为回退。
    # 它要求 macOS 14+，装不上时不影响 MPS 路径。
    try:
        pip("mlx")
    except Exception as exc:  # noqa: BLE001 - optional accelerator
        print(ins.c("y", f"    mlx 未安装（{exc}）；PyMSS 将使用 Torch MPS"))
    _verify_mps(py, "PyMSS", ins)
    ins.run([py, "-c", "from pymss import MSSeparator; print('PyMSS OK', MSSeparator.__name__)"])
    print(ins.c("g", "PyMSS 环境就绪；请在模型管理页选择并下载分离模型"))


def step_svc(ins: Any, uv: str, encoder: str) -> None:
    encoder = encoder if encoder in SVC_ENCODERS else "onnx"
    ins.hr(f"So-VITS-SVC 推理环境 engines/so-vits-svc + .venv-svc（{encoder} 编码器）")
    ins.fetch_sovits()
    py, pip = _pip_python(ins, uv, ins.SVC_VENV, "svc")
    pip("setuptools<81", "wheel")
    pip(*MAC_TORCH_SPECS)

    # torch/torchaudio/fairseq 由本流程自行管理：requirements 里的 fairseq==0.12.2
    # 在 Python 3.12 上无法安装，且 ONNX 编码器根本不需要它。
    deny = {"torch", "torchaudio", "torchvision", "fairseq", "fairseq-fixed"}
    req_win = ins.SOVITS_DIR / "requirements_win.txt"
    req = req_win if req_win.is_file() else ins.SOVITS_DIR / "requirements.txt"
    if not req.is_file():
        raise RuntimeError("未找到 so-vits-svc requirements.txt，请检查引擎源码")
    # fairseq 一律不通过 requirements 安装：uv 的共享 sdist 缓存会让 bdist_wheel
    # 的清理触发沙箱批量删除保护，必须走 _install_fairseq()（带 --no-cache）。
    filtered = _filtered_requirements(
        ins,
        req,
        deny=deny,
        overrides=_python312_overrides(ins),
    )
    pip("-r", str(filtered))
    # so-vits-svc 的声码器加载路径会 import matplotlib，但它不在 requirements 中。
    pip("matplotlib")
    # FCPE 音高预测器的运行时依赖（与 Windows 流程一致）。
    pip(*ins.SVC_FCPE_RUNTIME_DEPS)

    if encoder == "onnx":
        # ONNX 语音编码器不需要 fairseq，也不需要本地编译。
        pip("onnxruntime")
    else:
        _install_fairseq(ins, uv, py, "svc")
    _verify_mps(py, "So-VITS-SVC", ins)
    check = (
        "import onnxruntime,torch;"
        "print('ONNX', onnxruntime.get_available_providers())"
    )
    ins.run([py, "-c", check])
    ins.run(
        [py, "-c", "import utils; print('SVC utils OK', utils.f0_bin)"],
        cwd=ins.SOVITS_DIR,
    )
    if encoder == "onnx":
        print(
            ins.c(
                "g",
                "So-VITS-SVC 环境就绪（ONNX 语音编码器；推理时把模型配置的 "
                "speech_encoder 设为 vec768l12-onnx 即可免除 fairseq）",
            )
        )
    else:
        print(ins.c("g", "So-VITS-SVC 环境就绪（fairseq 语音编码器）"))


def step_rvc(ins: Any, uv: str) -> None:
    ins.hr("RVC 推理环境 .venv-rvc（rvc-python）")
    py, pip = _pip_python(ins, uv, ins.RVC_VENV, "rvc")
    pip("setuptools<81", "wheel")
    pip(*MAC_TORCH_SPECS)
    # rvc-python 的 hubert 加载器只有 fairseq 路径（wheel 内没有 onnx hubert），
    # 因此 RVC 必须本地编译 fairseq。
    _install_fairseq(ins, uv, py, "rvc")
    # 复用安装器的 3.12 兼容配方（平台无关的 py3-none-any wheel）：
    # 它把 fairseq==0.12.2/faiss-cpu==1.7.3/numpy<=1.23.5 等旧钉死替换为可用版本。
    rvc_wheel = ins._prepare_rvc_compat(MPS_STACK)
    pip(str(rvc_wheel))
    ins.seed_rvc_base_models(ins.venv_python(ins.RVC_VENV))
    _verify_mps(py, "RVC", ins)
    ins.run([py, "-c", "import fairseq, rvc_python; print('RVC deps OK')"])
    print(ins.c("g", "RVC 推理环境就绪（Apple MPS，rvc-python 自动使用 fp32）"))


def step_seedvc(ins: Any, uv: str) -> None:
    ins.hr("SeedVC 推理环境 engines/seed-vc + .venv-seedvc")
    ins.fetch_seedvc()
    py, pip = _pip_python(ins, uv, ins.SEEDVC_VENV, "seedvc")
    pip("setuptools<81", "wheel")
    pip(*MAC_TORCH_SPECS)

    req = ins.SEEDVC_DIR / "requirements.txt"
    if not req.is_file():
        raise RuntimeError("未找到 Seed-VC requirements.txt，请检查引擎源码")
    # 上游 requirements-mac.txt 用 --extra-index-url 拉 CUDA 版 torch，在
    # Apple Silicon 上不可用；这里沿用 Windows 流程的剔除与覆盖规则，
    # torch 由本流程自行安装。
    deny = set(ins.SEEDVC_REQ_DENY) | {"webrtcvad", "torch"}
    filtered = _filtered_requirements(
        ins, req, deny=deny, overrides=_python312_overrides(ins)
    )
    pip("-r", str(filtered))
    ins.seed_seedvc_base_models(ins.venv_python(ins.SEEDVC_VENV))
    _verify_mps(py, "SeedVC", ins)
    ins.run(
        [py, "-c", "import torch,transformers; print('SeedVC deps OK', transformers.__version__)"]
    )
    print(ins.c("g", "SeedVC 推理环境就绪（Apple MPS，worker 会对 MPS 关闭 fp16）"))


def step_ddsp(ins: Any, uv: str) -> None:
    ins.hr("DDSP-SVC 推理环境 engines/ddsp-svc + .venv-ddsp")
    ins.fetch_ddsp()
    py, pip = _pip_python(ins, uv, ins.DDSP_VENV, "ddsp")
    pip("setuptools<81", "wheel")
    pip(*MAC_TORCH_SPECS)

    req = ins.DDSP_DIR / "requirements.txt"
    if not req.is_file():
        raise RuntimeError("未找到 DDSP-SVC requirements.txt，请检查引擎源码")
    deny = set(ins.DDSP_REQ_DENY) | {"torch", "torchaudio", "torchvision", "fairseq"}
    overrides = {
        **_python312_overrides(ins),
        **ins.DDSP_REQ_OVERRIDES,
    }
    filtered = _filtered_requirements(ins, req, deny=deny, overrides=overrides)
    pip("-r", str(filtered))
    ins.seed_ddsp_base_models()
    _verify_mps(py, "DDSP-SVC", ins)
    ins._verify_ddsp_hubert(py)
    print(ins.c("g", "DDSP-SVC 推理环境就绪（Transformers HuBERT，无 fairseq 依赖）"))


def step_vocal(ins: Any, uv: str) -> None:
    ins.hr("AI 歌声增强环境 .venv-vocal（DeepFilterNet + Pedalboard）")
    py, pip = _pip_python(ins, uv, ins.VOCAL_VENV, "vocal", VOCAL_PYTHON)
    # deepfilternet==0.5.6 要求 packaging<24，而 wheel>=0.47 要求 >=24；
    # 该环境只装预编译 wheel，运行时不需要 wheel 包，因此不安装它。
    pip("setuptools<81")
    pip(*MAC_TORCH_SPECS)
    pip(
        "torchlibrosa==0.1.0",
        "PyYAML",
        "packaging==23.2",
        "deepfilternet[soundfile]==0.5.6",
        "pedalboard==0.9.24",
        "praat-parselmouth==0.4.6",
    )
    ins._prepare_vocal_deepfilter_model(py)
    (ins.VOCAL_MODELS_DIR / "runtime.ready").write_text(
        "deepfilternet=0.5.6\npedalboard=0.9.24\npraat-parselmouth=0.4.6\n",
        encoding="ascii",
    )
    ins.run([py, "-c", "import df.enhance, pedalboard; print('Vocal deps OK')"])
    print(ins.c("g", "AI 歌声增强环境与模型就绪（CPU 运行；DeepFilterNet 无 MPS 后端）"))


def step_models(ins: Any, uv: str, *, engines: set[str] | None = None) -> None:
    """底模部署 + LFS 指针校验。

    源码签出里 ``assets/models/**`` 是 git-lfs 指针；安装器会拒绝部署指针
    并改为联网下载，这里再做一次清单级复核，确保引擎拿到的是真实权重。
    ``engines`` 用于把下载范围收敛到本次安装的引擎，避免为只装 SVC 的用户
    额外拉取数百 MB 的 UVR 模型。
    """
    ins.hr("底模 + UVR 模型（自带优先，缺失才联网下载）")
    ins.step_models(uv, require_fcpe=False)
    fetch_assets = _load_sibling("xb_fetch_assets_macos", "fetch_assets.py")
    uvr_python = ins.venv_python(ins.UVR_VENV)
    remaining = fetch_assets.fetch_missing(
        ins.ROOT,
        engines=engines,
        uv=uv,
        extra_uvr_python=uvr_python if ins._path_is_file(uvr_python) else None,
    )
    # 判据用「运行时位置」而不是「发布包自带位置」：发布包里的某些大文件
    # （例如 1.2GB 的 ContentVec）在源码签出中拿不到，但安装器的官方回退来源
    # 已能满足引擎读取；能否推理取决于运行时位置。
    runtime_bad = fetch_assets.runtime_report(ins.ROOT, engines=engines)
    if runtime_bad:
        detail = "、".join(f"{row.get('engine')}:{row.get('id')}" for row in runtime_bad)
        raise RuntimeError(
            f"底模运行时校验未通过（{len(runtime_bad)} 项：{detail}）；"
            "可在有网络的环境执行 python3.12 install/fetch_assets.py --fetch 重试"
        )
    if remaining:
        detail = "、".join(f"{row.get('engine')}:{row.get('id')}" for row in remaining)
        print(
            ins.c(
                "y",
                f"    注意：发布包自带资产仍有 {len(remaining)} 项无法在源码签出中复现"
                f"（{detail}）；运行时位置已就绪，不影响推理",
            )
        )
    print(ins.c("g", "底模运行时位置全部可用（非 LFS 指针，且满足清单最小体积）"))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def _model_engines(chosen: list[str]) -> set[str]:
    """底模清单按引擎归类；把下载范围收敛到本次真正安装的引擎。

    ContentVec / RMVPE 在清单里归属 ddsp / seedvc，但 so-vits 与 RVC 也依赖
    它们，因此只要装了任一歌声引擎就一并校验这两个引擎的资产；UVR 模型只在
    用户确实安装分离环境时才拉取。
    """
    needed: set[str] = set()
    if {"svc", "rvc", "seedvc", "ddsp"} & set(chosen):
        needed |= {"seedvc", "ddsp"}
    if "uvr" in chosen:
        needed.add("uvr")
    return needed


def _macos_steps(ins: Any, encoder: str, chosen: list[str]) -> dict:
    engines = _model_engines(chosen)
    return {
        "app": lambda uv, _stack: ins.step_app(uv),
        "plugins": lambda uv, _stack: ins.step_plugins(uv),
        "web": lambda _uv, _stack: ins.step_web(),
        "uvr": lambda uv, _stack: step_uvr(ins, uv),
        "pymss": lambda uv, _stack: step_pymss(ins, uv),
        "svc": lambda uv, _stack: step_svc(ins, uv, encoder),
        "rvc": lambda uv, _stack: step_rvc(ins, uv),
        "seedvc": lambda uv, _stack: step_seedvc(ins, uv),
        "ddsp": lambda uv, _stack: step_ddsp(ins, uv),
        "vocal": lambda uv, _stack: step_vocal(ins, uv),
        "hub": lambda uv, stack: ins.step_hub(uv, stack),
        "models": lambda uv, _stack: step_models(ins, uv, engines=engines),
    }


def _write_routes(ins: Any, installed: set[str]) -> None:
    """Persist the interpreters that ``app/config.py`` resolves from runtime.json."""
    candidates = {
        "uvr": ins.UVR_VENV,
        "pymss": ins.PYMSS_VENV,
        "svc": ins.SVC_VENV,
        "rvc": ins.RVC_VENV,
        "seedvc": ins.SEEDVC_VENV,
        "ddsp": ins.DDSP_VENV,
        "vocal": ins.VOCAL_VENV,
        "hub": ins.HUB_VENV,
        "plugins": ins.PLUGIN_VENV,
    }
    routes: dict[str, Path] = {}
    for component, venv in candidates.items():
        if component not in installed and component != "plugins":
            continue
        python = ins.venv_python(venv)
        if ins._path_is_file(python):
            routes[component] = python
    if not routes:
        print(ins.c("y", "    没有可写入的运行时路由"))
        return
    ins.update_runtime_manifest_routes(MPS_STACK, routes, layout="isolated")
    print(ins.c("g", f"    已写入 runtime.json 路由：{', '.join(sorted(routes))}"))


def run_macos_install(
    *,
    root: Path | None = None,
    selected: list[str] | None = None,
    encoder: str = "onnx",
    verify: bool = True,
) -> int:
    """macOS/MPS 环境搭建主流程。"""
    _require_macos()
    ins = _installer()
    if root is not None:
        ins._derive_paths(root)

    ins.hr("XB-SVCB 安装器 · macOS (Apple MPS)")
    print(f"安装根目录: {ins.ROOT}")
    print(f"平台: {_machine_note()}")
    print(f"Torch: {' '.join(MAC_TORCH_SPECS)}（PyPI macOS arm64 wheel，自带 MPS）")
    print(f"So-VITS-SVC 语音编码器: {encoder}")

    ins._configure_runtime_layout(consolidated=False, gpu_stack=MPS_STACK)
    order = ins.ORDER
    chosen = [item for item in order if not selected or item in selected]
    if not chosen:
        print(ins.c("r", "未选择任何步骤"))
        return 2
    steps = _macos_steps(ins, encoder, chosen)

    installed: set[str] = set()
    results: list[tuple[str, str]] = []
    ins.installer_progress(5, "Resolving macOS runtime root")
    uv = ins.ensure_uv()
    print(f"uv: {uv}")
    ins.installer_progress(15, "uv package manager is ready")

    total = max(1, len(chosen))
    for index, name in enumerate(chosen, start=1):
        step = steps.get(name)
        if step is None:
            results.append((name, "skip"))
            continue
        ins.installer_progress(15 + (index * 80) // total, f"Running macOS step: {name}")
        try:
            step(uv, MPS_STACK)
            installed.add(name)
            results.append((name, "ok"))
        except Exception as exc:  # noqa: BLE001 - 单步失败不阻断其余步骤
            print(ins.c("r", f"[{name}] 失败: {exc}"))
            results.append((name, "fail"))

    if "app" in chosen or "plugins" in chosen:
        # The plugin runtime route is useful even when only the app env was built.
        installed.add("plugins")

    try:
        _write_routes(ins, installed)
    except (OSError, ValueError, RuntimeError) as exc:
        print(ins.c("r", f"写入 runtime.json 失败: {exc}"))
        results.append(("runtime.json", "fail"))

    ins.hr("安装结果汇总")
    label = {"ok": ins.c("g", "成功"), "fail": ins.c("r", "失败"), "skip": ins.c("y", "跳过")}
    for name, status in results:
        print(f"  {name:<10} {label[status]}")

    if verify and "app" in installed:
        app_python = ins.venv_python(ins.APP_DIR / ".venv")
        if ins._path_is_file(app_python):
            print("启动应用：")
            print(ins.c("g", f"  {app_python} {ins.APP_DIR / 'main.py'}"))
            print(ins.c("g", f"  开发模式：{app_python} {ins.APP_DIR / 'main.py'} --dev"))

    if any(status == "fail" for _, status in results):
        print(ins.c("y", "\n有步骤失败。可单独重试，例如: python3.12 install/install.py --mps --only svc"))
        ins.installer_progress(100, "macOS runtime finished with errors")
        return 1

    ins.installer_progress(100, "macOS runtime complete")
    ins.hr("全部完成")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone entry: ``python install/install_macos.py --only svc``."""
    ins = _installer()
    parser = argparse.ArgumentParser(description="XB-SVCB macOS (Apple MPS) 环境搭建")
    parser.add_argument("--root", default=None, help="安装根目录；默认取脚本上级目录")
    parser.add_argument("--only", nargs="+", choices=ins.ORDER, help="只执行指定步骤")
    parser.add_argument(
        "--svc-encoder",
        default="onnx",
        choices=SVC_ENCODERS,
        help="So-VITS-SVC 语音编码器：onnx（默认，无需 fairseq）或 fairseq（需本地编译）",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else None
    return run_macos_install(root=root, selected=args.only, encoder=args.svc_encoder)


if __name__ == "__main__":
    raise SystemExit(main())
