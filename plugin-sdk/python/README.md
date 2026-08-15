# XB-SVCB Python Plugin SDK

Python 或混合插件使用的零依赖 SDK。宿主运行时会自动提供该模块；本地开发时安装：

```powershell
pip install -e plugin-sdk\python
```

```python
from xb_svcb_plugin import ActionResult, Plugin, PluginContext

plugin = Plugin("com.example.plugin")

@plugin.action("hello")
def hello(ctx: PluginContext, values: dict):
    return ActionResult.message_result(f"你好，{values.get('name', '朋友')}")

@plugin.before_create
def before_create(ctx: PluginContext, payload: dict):
    payload.setdefault("params", {}).setdefault("f0_method", "rmvpe")
    return payload
```
