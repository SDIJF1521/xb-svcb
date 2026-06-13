"""XB-SVCB 桌面应用入口。

以 pywebview 为核心启动 GUI 窗口，并把后端应用服务通过 JS 桥暴露给前端：
- 开发模式：加载 Vite 开发服务器 (默认 http://localhost:5173)，支持热更新。
- 生产模式：加载前端构建产物 web/dist/index.html，并由 pywebview 内置 http server 提供静态资源。

后端采用分层（应用层）架构：
    api (表现/桥接) → application (用例服务) → domain (实体) ← infrastructure (工具/存储)

启动方式：
    uv run python main.py            # 生产模式，加载 web/dist
    uv run python main.py --dev      # 开发模式，加载 Vite dev server
"""

from __future__ import annotations

import os
import sys

import webview

import config
from api import build_api


def is_dev() -> bool:
    return "--dev" in sys.argv or os.environ.get("XB_DEV") == "1"


def resolve_url() -> str:
    if is_dev():
        return os.environ.get("XB_DEV_URL", "http://localhost:5173")

    if not config.DIST_INDEX.exists():
        raise FileNotFoundError(
            f"未找到前端构建产物：{config.DIST_INDEX}\n"
            "请先在 web 目录执行 `npm run build`，或使用 `python main.py --dev` 启动开发模式。"
        )
    return str(config.DIST_INDEX)


def main() -> None:
    dev = is_dev()
    url = resolve_url()
    api = build_api()

    window = webview.create_window(
        config.APP_TITLE,
        url=url,
        js_api=api,
        width=1360,
        height=880,
        min_size=(1080, 720),
        background_color=config.APP_BG,
        text_select=False,
    )
    # 注入窗口引用，供原生文件对话框使用
    api.set_window(window)

    # 生产模式下用内置 http server 提供静态资源，确保 SPA 路由与资源路径正常。
    webview.start(debug=dev, http_server=not dev)


if __name__ == "__main__":
    main()
