"""ModelScope（魔搭社区）模型上传 worker（在 .venv-hub 中以子进程方式运行）。

由主程序通过 ``config.HUB_PYTHON`` 启动；只有「上传」需要 modelscope SDK，
搜索 / 下载 / 校验令牌都在主程序里走纯 HTTP，不经过本 worker。

调用约定：
    python hub_worker.py --action upload --token <ms令牌> --model-id <owner/name>
        --dir <本地模型目录> [--chinese-name <中文名>] [--visibility 5]

成功时最后一行输出 ``HUB_OK <json>``（含仓库地址）；失败时打印 ``HUB_ERR <msg>`` 并非零退出。
另支持 ``--action whoami`` 用 SDK 校验令牌并返回用户名（备用，主程序通常用 HTTP 校验）。
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="XB-SVCB ModelScope 上传 worker")
    p.add_argument("--action", default="upload", choices=["upload", "whoami"])
    p.add_argument("--token", required=True, help="ModelScope 访问令牌")
    p.add_argument("--model-id", default="", help="目标仓库 owner/name（上传必填）")
    p.add_argument("--dir", default="", help="待上传的本地模型目录（上传必填）")
    p.add_argument("--chinese-name", default="", help="模型中文名（可选）")
    p.add_argument("--visibility", type=int, default=5, help="可见性：1私有 5公开")
    return p


def _emit_ok(payload: dict) -> int:
    print("HUB_OK " + json.dumps(payload, ensure_ascii=False))
    return 0


def _emit_err(msg: str) -> int:
    print("HUB_ERR " + " ".join(str(msg).splitlines()))
    return 1


def main() -> int:
    args = _build_parser().parse_args()
    try:
        from modelscope.hub.api import HubApi
    except Exception as exc:  # noqa: BLE001 - 缺少 SDK 时给出明确提示
        return _emit_err(f"未安装 modelscope SDK：{exc}")

    api = HubApi()
    try:
        api.login(args.token)
    except Exception as exc:  # noqa: BLE001
        return _emit_err(f"登录失败（请检查访问令牌）：{exc}")

    if args.action == "whoami":
        try:
            from modelscope.hub.api import ModelScopeConfig

            name, email = ModelScopeConfig.get_user_info()
            return _emit_ok({"username": name or "", "email": email or ""})
        except Exception as exc:  # noqa: BLE001
            return _emit_err(f"获取用户信息失败：{exc}")

    if not args.model_id or not args.dir:
        return _emit_err("上传缺少 --model-id 或 --dir")

    import os

    folder = args.dir
    if not os.path.isdir(folder):
        return _emit_err(f"上传目录不存在：{folder}")
    files = sorted(
        f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))
    )
    if not files:
        return _emit_err("上传目录为空")

    # 1) 创建仓库（已存在则忽略错误，继续上传覆盖）
    try:
        from modelscope.hub.constants import Licenses, ModelVisibility  # noqa: F401

        visibility = args.visibility or ModelVisibility.PUBLIC
        api.create_model(
            model_id=args.model_id,
            visibility=visibility,
            license=Licenses.APACHE_V2,
            chinese_name=args.chinese_name or None,
        )
    except Exception as exc:  # noqa: BLE001 - 仓库已存在等情况不致命
        msg = str(exc)
        if "exist" not in msg.lower() and "已存在" not in msg:
            # 仍尝试上传：部分版本 create 失败但仓库可由 upload 自动创建
            print(f"HUB_WARN create_model: {msg}", flush=True)

    # 2) 逐个文件上传（HTTP 方式，自动处理大文件 LFS，无需本地 git），
    #    每个文件前后打印 HUB_PROGRESS，供父进程更新进度条。
    total = len(files)
    print(f"HUB_PROGRESS 0 {total} 准备上传", flush=True)
    for i, fname in enumerate(files):
        print(f"HUB_PROGRESS {i} {total} {fname}", flush=True)
        try:
            api.upload_file(
                path_or_fileobj=os.path.join(folder, fname),
                path_in_repo=fname,
                repo_id=args.model_id,
                token=args.token,
                commit_message=f"upload {fname} via XB-SVCB",
            )
        except Exception as exc:  # noqa: BLE001
            return _emit_err(f"上传文件失败（{fname}）：{exc}")
    print(f"HUB_PROGRESS {total} {total} 完成", flush=True)

    url = f"https://www.modelscope.cn/models/{args.model_id}"
    return _emit_ok({"url": url, "model_id": args.model_id})


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 兜底，保证错误以 HUB_ERR 形式输出
        sys.exit(_emit_err("worker 异常：" + traceback.format_exc()))
