"""底模供给与完整性校验（源码签出 / macOS 场景共用）。

背景：源码签出（``git clone``）里 ``assets/models/**`` 是 **git-lfs 指针**
（约 130 字节），安装器若直接复制，就会得到一个"看起来装好了、真正加载时
才失败"的环境。本工具按 ``assets/models/model-manifest.json`` 逐条检查，
识别指针与体积不足的文件，并把缺失项交给安装器既有的下载流程
（HuggingFace 镜像 / GitHub Release 镜像 / audio-separator）补齐，最后用
清单里的 ``sha256`` 与 ``min_bytes`` 复核。

用法::

    python3.12 install/fetch_assets.py --list-missing
    python3.12 install/fetch_assets.py --verify-only --verify-hash
    python3.12 install/fetch_assets.py --fetch --only uvr seedvc ddsp
    python3.12 install/fetch_assets.py --fetch --uvr-python .venv-uvr/bin/python

退出码：``--strict`` 下存在必需资产异常时为 1，否则 0。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

ROOT_DEFAULT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = Path("assets/models/model-manifest.json")
LFS_POINTER_MARKER = b"version https://git-lfs.github.com/spec/v1"
_LFS_POINTER_MAX_BYTES = 4096
_CHUNK = 1024 * 1024
BAD_STATUSES = {"missing", "too_small", "hash_mismatch", "invalid_path", "error"}

# HuggingFace 快照（镜像由安装器的 hf_urls() 负责前缀拼接）。清单里的
# sha256 才是最终判据：URL 失效时这里会明确报错，而不会静默留下坏文件。
# 仓库 id 与 Seed-VC 的配置一致（configs/v2/vc_wrapper.yaml 的
# tokenizer_name: openai/whisper-small 等）。
SEEDVC_HF_FILES: dict[str, str] = {
    "assets/models/seedvc/whisper-small/config.json":
        "/openai/whisper-small/resolve/main/config.json",
    "assets/models/seedvc/whisper-small/preprocessor_config.json":
        "/openai/whisper-small/resolve/main/preprocessor_config.json",
    "assets/models/seedvc/whisper-small/model.safetensors":
        "/openai/whisper-small/resolve/main/model.safetensors",
    "assets/models/seedvc/bigvgan_v2_44khz_128band_512x/config.json":
        "/nvidia/bigvgan_v2_44khz_128band_512x/resolve/main/config.json",
    "assets/models/seedvc/bigvgan_v2_44khz_128band_512x/bigvgan_generator.pt":
        "/nvidia/bigvgan_v2_44khz_128band_512x/resolve/main/bigvgan_generator.pt",
}
# campplus 音色编码器随 Seed-VC 仓库分发（仓库根目录），克隆后直接复制即可，
# 不必依赖 HuggingFace（该文件在 HF 侧不可直接下载）。
SEEDVC_REPO_CAMPPUS = Path("engines/seed-vc/campplus_cn_common.bin")

# 某些自带资产可以用引擎目录里**已经下载好的同一份权重**回填（内容一致、
# 清单里的 sha256 也一致），这样源码签出不必再下一次几百 MB。
ENGINE_SIDE_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "assets/models/pretrain/rmvpe.pt": (
        "engines/so-vits-svc/pretrain/rmvpe.pt",
        "engines/seed-vc/checkpoints/rmvpe.pt",
        "engines/ddsp-svc/pretrain/rmvpe/model.pt",
    ),
    "assets/models/pretrain/checkpoint_best_legacy_500.pt": (
        "engines/seed-vc/checkpoints/campplus_cn_common.bin",
    ),
}


class AssetMissingError(RuntimeError):
    """必需的底模缺失或不可用。"""


# --------------------------------------------------------------------------
# 文件判定
# --------------------------------------------------------------------------
def is_lfs_pointer(path: Path) -> bool:
    """判断文件是否是 git-lfs 指针（小文件 + LFS 规范头）。"""
    try:
        if not path.is_file() or path.stat().st_size > _LFS_POINTER_MAX_BYTES:
            return False
        with path.open("rb") as handle:
            head = handle.read(_LFS_POINTER_MAX_BYTES)
    except OSError:
        return False
    return LFS_POINTER_MARKER in head


def is_usable_asset(path: Path, *, min_bytes: int = 0) -> bool:
    """文件存在、不是 LFS 指针，且不小于清单要求的最小体积。"""
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < max(0, int(min_bytes)):
            return False
    except OSError:
        return False
    return not is_lfs_pointer(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# 清单
# --------------------------------------------------------------------------
def _assets_module() -> Any:
    """复用应用侧的清单检查逻辑，避免出现第二套判断规则。"""
    app_dir = ROOT_DEFAULT / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from infrastructure import model_assets  # noqa: PLC0415 - 延迟导入

    return model_assets


def load_manifest(root: Path) -> dict[str, Any]:
    path = root.resolve() / MANIFEST_RELATIVE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        return {}
    return data


def inspect(root: Path, *, verify_hash: bool = False) -> dict[str, Any]:
    return _assets_module().inspect_manifest(root, "source", verify_hash)


def problem_rows(result: dict[str, Any], *, engines: set[str] | None = None) -> list[dict[str, Any]]:
    rows = []
    for row in result.get("assets", []):
        if engines and row.get("engine") not in engines:
            continue
        if row.get("status") in BAD_STATUSES:
            rows.append(row)
    return rows


def runtime_report(
    root: Path, *, engines: set[str] | None = None, verify_hash: bool = False
) -> list[dict[str, Any]]:
    """按「安装后各引擎真正读取的位置」检查，这才是能否推理的判据。

    自带资产清单里的 source 描述的是发布包内容；源码签出可能拿不到同一份文件
    （例如安装包内 1.2GB 的 ContentVec），但运行时位置已由安装器的官方回退
    来源满足时，引擎依然可用。
    """
    result = _assets_module().inspect_manifest(root, "runtime", verify_hash)
    return problem_rows(result, engines=engines)


def materialize_engine_equivalents(root: Path) -> list[str]:
    """用引擎目录里已下载好的同源权重回填自带资产位置。返回回填的相对路径。

    仅在自带位置不可用、且引擎侧副本通过清单体积要求时执行，避免无意义拷贝。
    """
    root = root.resolve()
    manifest = load_manifest(root)
    filled: list[str] = []
    for entry in manifest.get("assets", []):
        source = entry.get("source")
        if not isinstance(source, str):
            continue
        candidates = ENGINE_SIDE_EQUIVALENTS.get(source)
        if not candidates:
            continue
        minimum = int(entry.get("min_bytes") or 0)
        destination = root / source
        if is_usable_asset(destination, min_bytes=minimum):
            continue
        origin = next(
            (
                root / candidate
                for candidate in candidates
                if is_usable_asset(root / candidate, min_bytes=minimum)
            ),
            None,
        )
        if origin is None:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink()
        shutil.copy2(origin, destination)
        filled.append(source)
        print(f"    已用引擎侧副本回填：{source} <- {origin.relative_to(root)}")
    return filled


# --------------------------------------------------------------------------
# 供给
# --------------------------------------------------------------------------
def _installer() -> Any:
    path = Path(__file__).with_name("install.py")
    spec = importlib.util.spec_from_file_location("xb_installer_fetch_assets", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"无法加载安装器：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ensure_asset(
    entry: dict[str, Any],
    *,
    dest_root: Path,
    verify: bool = True,
    fetch: bool = True,
    fetchers: dict[str, Callable[[], None]] | None = None,
) -> Path:
    """按清单条目供给单个底模，返回可用的自带文件路径。

    典型的 ``entry`` 来自 ``model-manifest.json``：``source`` 是相对项目根的
    路径，``min_bytes``/``sha256`` 是完整性要求。本地文件不可用（缺失、仍是
    LFS 指针、体积不足或哈希不符）时，若提供 ``fetchers`` 则尝试联网补齐，
    补齐后重新校验；仍然不可用则抛 ``AssetMissingError``。
    """
    dest_root = dest_root.resolve()
    raw_source = entry.get("source")
    if not isinstance(raw_source, str) or not raw_source.strip():
        raise AssetMissingError(f"{entry.get('id') or 'asset'} 缺少 source 字段")
    source = dest_root / raw_source
    minimum = int(entry.get("min_bytes") or 0)
    expected = str(entry.get("sha256") or "").strip().lower()

    def usable() -> bool:
        if not is_usable_asset(source, min_bytes=minimum):
            return False
        return not (verify and expected and _sha256(source) != expected)

    if usable():
        return source

    if not fetch:
        raise AssetMissingError(f"{raw_source} 不可用（缺失 / LFS 指针 / 体积不足 / 哈希不符）")

    engine = str(entry.get("engine") or "")
    fetcher = (fetchers or {}).get(engine)
    if fetcher is None:
        raise AssetMissingError(f"{raw_source} 不可用，且没有 {engine or '未知引擎'} 的下载方式")
    fetcher()
    if not usable():
        raise AssetMissingError(f"{raw_source} 下载后仍未通过完整性校验")
    return source


def _download_hf(ins: Any, root: Path, mapping: dict[str, str]) -> list[str]:
    """逐个下载 HuggingFace 快照，单项失败不阻断其余文件。返回失败列表。"""
    failures: list[str] = []
    for relative, hf_path in mapping.items():
        dest = root / relative
        if is_usable_asset(dest):
            print(f"    已可用，跳过：{relative}")
            continue
        if dest.is_file():
            # ``download()`` skips any existing non-empty file, so a git-lfs
            # stub would otherwise survive as a "successful" download.
            print(f"    现有文件不可用（LFS 指针/残缺），先删除：{relative}")
            dest.unlink(missing_ok=True)
        try:
            ins.download(ins.hf_urls(hf_path), dest)
        except Exception as exc:  # noqa: BLE001 - 换下一个文件继续
            print(f"    下载失败（{exc}）：{relative}")
            failures.append(relative)
            continue
        if is_lfs_pointer(dest):  # pragma: no cover - defensive
            failures.append(relative)
            Path(dest).unlink(missing_ok=True)
    return failures


def _fetch_seedvc(ins: Any, root: Path) -> None:
    # campplus 先尝试用 Seed-VC 仓库自带的副本（无需外网）。
    campplus = root / "assets/models/seedvc/campplus_cn_common.bin"
    repo_copy = root / SEEDVC_REPO_CAMPPUS
    if not is_usable_asset(campplus) and repo_copy.is_file():
        print(f"  · SeedVC campplus（来自仓库副本 {SEEDVC_REPO_CAMPPUS}）")
        campplus.parent.mkdir(parents=True, exist_ok=True)
        ins._link_or_copy_model(repo_copy, campplus)
    print("  · SeedVC 快照（HuggingFace）")
    failures = _download_hf(ins, root, SEEDVC_HF_FILES)
    if failures:
        raise AssetMissingError("以下 SeedVC 快照下载失败：" + "、".join(failures))


def _fetch_pretrain(ins: Any, uv: str, root: Path) -> None:
    print("  · ContentVec / NSF-HiFiGAN / RMVPE / FCPE / UVR（安装器既有流程）")
    ins.step_models(uv, require_fcpe=False)


def _fetch_ddsp(ins: Any, uv: str, root: Path) -> None:
    _fetch_pretrain(ins, uv, root)
    ins.seed_ddsp_base_models()


def fetch_missing(
    root: Path,
    *,
    engines: set[str] | None = None,
    uv: str | None = None,
    extra_uvr_python: Path | None = None,
) -> list[dict[str, Any]]:
    """把清单里缺失的底模补齐，返回仍然异常的清单条目。"""
    ins = _installer()
    ins._derive_paths(root.resolve())
    if extra_uvr_python is not None and extra_uvr_python.is_file():
        # audio-separator 下载 UVR 模型需要 UVR 环境的解释器。
        ins.UVR_PYTHON = extra_uvr_python
    uv_bin = uv or ins.ensure_uv()
    fetchers: dict[str, Callable[[], None]] = {
        "pretrain": lambda: _fetch_pretrain(ins, uv_bin, root),
        "uvr": lambda: _fetch_pretrain(ins, uv_bin, root),
        "seedvc": lambda: _fetch_seedvc(ins, root),
        "ddsp": lambda: _fetch_ddsp(ins, uv_bin, root),
    }
    materialize_engine_equivalents(root)
    before = inspect(root)
    pending = problem_rows(before, engines=engines)
    if not pending:
        print(ins.c("g", "所有清单资产均已可用，无需下载"))
        return []

    print(ins.c("b", f"待补齐资产 {len(pending)} 项："))
    for row in pending:
        print(f"  - [{row.get('status')}] {row.get('engine')}: {row.get('id')}")

    engines_to_fetch = {row.get("engine") or "" for row in pending}
    for engine in ("uvr", "pretrain", "seedvc", "ddsp"):
        if engine not in engines_to_fetch:
            continue
        fetcher = fetchers.get(engine)
        if fetcher is None:
            continue
        try:
            fetcher()
        except Exception as exc:  # noqa: BLE001 - 单项失败不阻断其余资产
            print(ins.c("r", f"  {engine} 补齐失败: {exc}"))

    after = inspect(root)
    remaining = problem_rows(after, engines=engines)
    if remaining:
        print(ins.c("y", f"仍有 {len(remaining)} 项不可用："))
        for row in remaining:
            print(f"  - [{row.get('status')}] {row.get('engine')}: {row.get('id')}")
    else:
        print(ins.c("g", "底模已全部可用"))
    return remaining


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB 底模供给与校验")
    parser.add_argument("--root", type=Path, default=ROOT_DEFAULT, help="项目根目录")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=["uvr", "seedvc", "ddsp"],
        help="只处理指定引擎的资产",
    )
    parser.add_argument("--list-missing", action="store_true", help="只列出异常资产")
    parser.add_argument("--verify-only", action="store_true", help="只校验，不下载")
    parser.add_argument("--verify-hash", action="store_true", help="同时校验清单中的 SHA-256")
    parser.add_argument("--fetch", action="store_true", help="补齐缺失资产")
    parser.add_argument("--uv", default=None, help="uv 可执行文件路径；默认自动探测")
    parser.add_argument("--uvr-python", type=Path, default=None, help="UVR 环境解释器（下载 UVR 模型用）")
    parser.add_argument("--strict", action="store_true", help="存在必需资产异常时返回非零")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    engines = set(args.only) if args.only else None
    if not load_manifest(root):
        print(f"模型清单不存在或 schema 不匹配: {root / MANIFEST_RELATIVE}")
        return 1

    if args.fetch:
        remaining = fetch_missing(
            root,
            engines=engines,
            uv=args.uv,
            extra_uvr_python=args.uvr_python,
        )
        result = inspect(root, verify_hash=args.verify_hash)
        if args.json:
            print(json.dumps({**result, "problems": remaining}, ensure_ascii=False, indent=2))
        return 1 if (remaining and args.strict) else 0

    result = inspect(root, verify_hash=args.verify_hash)
    rows = problem_rows(result, engines=engines)
    if args.json:
        print(json.dumps({**result, "problems": rows}, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            f"底模检查 [source]：{summary.get('ok', 0)} 可用，"
            f"{summary.get('missing', 0)} 异常，{summary.get('unverified', 0)} 未做哈希校验"
        )
        for row in result.get("assets", []):
            if engines and row.get("engine") not in engines:
                continue
            print(f"  [{row.get('status')}] {row.get('engine')}: {row.get('id')}")
    if args.list_missing or args.verify_only:
        return 1 if (rows and args.strict) else 0
    return 0 if not args.strict or not rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
