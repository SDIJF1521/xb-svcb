"""XB-SVCB shared-runtime installer.

This is the explicit NVIDIA shared-layout entry point.  The original
``install.py`` remains available for common component implementations and
legacy/CPU/DirectML installations; this file does not expose an isolated-mode
switch and always builds the selected CUDA126/CUDA128 layout:

  runtimes/core-cu126/128  -> UVR + SeedVC + DDSP-SVC
  runtimes/svc-cu126/128   -> So-VITS-SVC + RVC + Vocal/DeepFilterNet

PyMSS remains an optional isolated add-on because its dependency stack is not
part of either shared runtime.  The low-level component installers are reused
from install.py so fixes to downloading, model staging, and probes stay in
one place; the orchestration and layout policy are intentionally separate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LEGACY_PATH = Path(__file__).with_name("install.py")
SHARED_ORDER = [
    "app",
    "plugins",
    "web",
    "uvr",
    "pymss",
    "svc",
    "rvc",
    "seedvc",
    "ddsp",
    "vocal",
    "hub",
    "models",
]
CORE_COMPONENTS = {"uvr", "seedvc", "ddsp"}
SVC_COMPONENTS = {"svc", "rvc", "vocal"}


def _load_implementation():
    """Load the common component implementation without invoking its CLI."""
    spec = importlib.util.spec_from_file_location("xb_svcb_install_legacy", LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载公共安装实现：{LEGACY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="XB-SVCB 共享运行时安装器（NVIDIA cu126/cu128）"
    )
    parser.add_argument("--root", default=None, help="安装根目录")
    # Keep compatibility switches used by the Inno and batch dispatchers.
    # They select the CUDA wheel stack, never an isolated layout.
    parser.add_argument("--gpu", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cu126", action="store_true", help="使用 40 系及以下 NVIDIA 的 cu126 共享配方")
    parser.add_argument("--cu128", action="store_true", help="使用 Blackwell/cu128 共享配方")
    parser.add_argument("--consolidated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--core-profile", choices=["core-cu128"], default=None)
    parser.add_argument("--preflight-only", action="store_true", help="只做共享依赖解析，不安装环境")
    parser.add_argument(
        "--only",
        choices=SHARED_ORDER,
        nargs="+",
        help="只执行指定步骤；UVR/SeedVC/DDSP 必须一起选择",
    )
    for component in SHARED_ORDER:
        parser.add_argument(f"--skip-{component}", action="store_true")
    return parser


def _selected(args: argparse.Namespace) -> list[str]:
    if args.only:
        return list(dict.fromkeys(args.only))
    return [
        component
        for component in SHARED_ORDER
        if not getattr(args, f"skip_{component}")
    ]


def _resolve_root(raw: str | None) -> Path:
    return Path(raw).expanduser().resolve() if raw else ROOT


def _run_shared(args: argparse.Namespace, impl) -> int:
    root = _resolve_root(args.root)
    impl._derive_paths(root)

    detected = impl.detect_gpu_stack()
    if args.cu128:
        stack = "cu128"
    elif args.cu126:
        stack = "cu126"
    elif detected == "cu128":
        stack = "cu128"
    elif detected == "cu126":
        stack = "cu126"
    else:
        print(f"检测到 GPU 栈 {detected}。共享安装器只支持 NVIDIA cu126/cu128；未修改环境。")
        return 2

    selected = _selected(args)
    selected_set = set(selected)
    if selected_set.intersection(CORE_COMPONENTS) and not CORE_COMPONENTS.issubset(selected_set):
        print("共享核心必须整体安装：请同时选择 uvr seedvc ddsp；不会进行部分修改。")
        return 2

    try:
        if stack == "cu128":
            impl._configure_core_profile(args.core_profile or "core-cu128")
        else:
            # cu126 复用已验证的 NumPy/protobuf/AudioTools 兼容材料，但
            # 不冒充 cu128 的固定 profile；待 cu126 完成独立锁定后再加 profile。
            impl.CORE_PROFILE = None
            impl.CORE_PROFILE_PINS = {}
            impl.CORE_COMPAT_WHEEL = (
                impl.ASSETS_DIR
                / "runtime"
                / "core-cu128"
                / "compat"
                / "descript_audiotools-0.7.2+xb1-py3-none-any.whl"
            )
            impl._validate_core_compat_wheel(impl.CORE_COMPAT_WHEEL)
        impl._configure_runtime_layout(consolidated=True, gpu_stack=stack)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(impl.c("r", f"共享配方初始化失败：{exc}"))
        return 1

    impl.hr("XB-SVCB 共享运行时安装器")
    print(f"安装根目录: {impl.ROOT}")
    print(
        "安装模式: CUDA · "
        + ("Blackwell/50系 (cu128 + torch2.7.1)" if stack == "cu128"
           else "40系及以下 (cu126 + torch2.7.1)")
    )
    print(f"共享核心运行时: {impl.CORE_VENV}")
    print(f"共享 SVC 运行时: {impl.SVC_VENV}")
    wheelhouse = impl._wheelhouse_root()
    if wheelhouse:
        print(impl.c("g", f"自带 whl 目录: {wheelhouse}"))
    else:
        print(impl.c("y", "未检测到自带 whl 目录，将使用在线源。"))

    try:
        impl._guard_shared_runtime_repair(selected_set)
        impl.installer_progress(12, "Preparing uv package manager")
        uv = impl.ensure_uv()
        print(f"uv: {uv}")
        impl.installer_progress(18, "uv package manager is ready")
        impl._preflight_consolidated_runtime(uv, selected_set, stack)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(impl.c("r", str(exc)))
        impl.installer_progress(100, "Shared runtime preflight failed; environment unchanged")
        return 1

    if args.preflight_only:
        if impl.CORE_CONSTRAINTS is None:
            print(impl.c("r", "未选择共享核心，未执行共享依赖预检"))
            return 2
        print(impl.c("g", f"共享依赖预检通过；未安装环境或更新路由：{impl.CORE_CONSTRAINTS}"))
        return 0

    # SVC/RVC/Vocal share one environment but have different intermediate
    # dependency pins. Defer per-component pip-check until all selected steps
    # have completed, then validate the final shared environment once.
    impl.SHARED_INSTALL_IN_PROGRESS = True

    results: list[tuple[str, str]] = []
    selected_count = max(1, len(selected))
    completed = 0
    for component in SHARED_ORDER:
        if component not in selected_set:
            results.append((component, "skip"))
            continue
        impl.installer_progress(
            18 + (completed * 76) // selected_count,
            f"Running shared runtime step: {component}",
        )
        try:
            impl.STEPS[component](uv, stack)
            results.append((component, "ok"))
        except Exception as exc:  # noqa: BLE001 - 汇总所有失败项
            print(impl.c("r", f"[{component}] 失败: {exc}"))
            results.append((component, "fail"))
            if component in CORE_COMPONENTS:
                break
        completed += 1
        impl.installer_progress(
            18 + (completed * 76) // selected_count,
            f"Finished shared runtime step: {component}",
        )

    impl.hr("共享安装结果汇总")
    labels = {"ok": impl.c("g", "成功"), "fail": impl.c("r", "失败"), "skip": impl.c("y", "跳过")}
    for component, status in results:
        print(f"  {component:<8} {labels[status]}")

    if any(status == "fail" for _, status in results):
        print(impl.c("y", "共享环境未完成；请使用同一个共享入口重试，不要切换到旧隔离路径。"))
        impl.installer_progress(100, "Shared runtime finished with errors")
        return 1

    if CORE_COMPONENTS.intersection(selected_set) or SVC_COMPONENTS.intersection(selected_set):
        try:
            if CORE_COMPONENTS.intersection(selected_set):
                core_py = impl.venv_python(impl.CORE_VENV)
                impl.run(impl.uv_cmd(uv, "pip", "check", "--python", str(core_py)))
                recipe_check = impl._recipe_module().check_environment(
                    core_py, impl.CORE_PROFILE, impl.CORE_PROFILE_PINS
                )
                if not recipe_check["ok"]:
                    raise RuntimeError(
                        "共享环境偏离固定配方：" + json.dumps(recipe_check, ensure_ascii=False)
                    )
                impl.run([
                    str(core_py),
                    str(Path(impl.__file__).with_name("audit_runtime.py")),
                    "--root",
                    str(impl.ROOT),
                    "--require-cuda",
                ])
                impl.run([
                    str(core_py),
                    str(Path(impl.__file__).with_name("probe_core_compat.py")),
                    "--root",
                    str(impl.ROOT),
                    "--output",
                    str(impl.ROOT / ".tmp" / "core-compat-installed-probes.json"),
                ])
            if SVC_COMPONENTS.intersection(selected_set):
                svc_py = impl.venv_python(impl.SVC_VENV)
                impl.run(impl.uv_cmd(uv, "pip", "check", "--python", str(svc_py)))
            impl.write_runtime_manifest(stack, {
                component for component, status in results if status == "ok"
            })
        except (OSError, ValueError, RuntimeError, impl.subprocess.SubprocessError) as exc:
            print(impl.c("r", f"共享运行时最终校验失败，未更新 runtime.json：{exc}"))
            impl.installer_progress(100, "Shared runtime validation failed")
            return 1

    impl.installer_progress(100, "Shared runtime environment complete")
    print(impl.c("g", "共享运行环境搭建完成。"))
    return 0


def main() -> int:
    args = _parser().parse_args()
    implementation = _load_implementation()
    return _run_shared(args, implementation)


if __name__ == "__main__":
    raise SystemExit(main())
