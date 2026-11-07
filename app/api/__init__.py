"""表现层：暴露给前端（pywebview JS 桥）的 API 接口。

本层只做参数转换与用例编排，具体依赖由组合根 ``app/composition.py`` 注入。
"""

from .bridge import Api

__all__ = ["Api"]
