from xb_svcb_plugin import ActionResult, Plugin, PluginContext


plugin = Plugin("example.hybrid-assistant")


@plugin.action("create_cover")
async def create_cover(ctx: PluginContext, values: dict) -> ActionResult:
    style = values.get("style", "natural")
    pitch = 1 if style == "bright" else 0
    return ActionResult.create_work(
        {
            "source_path": values.get("source_path", ""),
            "model_id": values.get("model_id", ""),
            "title": values.get("title", "混合插件翻唱"),
            "workflow": "auto_mix",
            "params": {"pitch": pitch, "f0_method": "rmvpe"},
        }
    )
