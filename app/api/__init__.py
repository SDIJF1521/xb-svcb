"""表现层：暴露给前端（pywebview JS 桥）的 API 接口。"""

from .bridge import Api, build_api

__all__ = ["Api", "build_api"]
