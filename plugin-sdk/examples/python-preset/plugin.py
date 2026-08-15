from xb_svcb_plugin import Plugin, PluginContext


plugin = Plugin("example.python-preset")


@plugin.on_enable
def enabled(ctx: PluginContext) -> None:
    ctx.config.setdefault("runs", 0)
    ctx.save_config()


@plugin.before_create
def apply_preset(ctx: PluginContext, payload: dict) -> dict:
    params = payload.setdefault("params", {})
    params.setdefault("f0_method", "rmvpe")
    params.setdefault("device", "auto")
    ctx.config["runs"] = int(ctx.config.get("runs", 0)) + 1
    ctx.save_config()
    return payload
