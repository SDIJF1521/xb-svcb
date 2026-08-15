import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from application.plugin_service import PluginService
from infrastructure.storage import SettingsStore


MANIFEST = {
    "id": "example.quick-cover",
    "name": "Quick Cover",
    "version": "1.0.0",
    "pages": [{"id": "start", "title": "Start", "fields": []}],
    "actions": [{
        "id": "create", "label": "Create", "type": "create_work",
        "payload": {"title": "{{title}}", "params": {"pitch": "{{pitch}}"}},
    }],
    "workflow": {"before_create": {"params": {"f0_method": "rmvpe", "unknown": "no"}}},
}

HYBRID_MANIFEST = {
    "id": "example.hybrid-plugin",
    "name": "Hybrid Plugin",
    "version": "1.0.0",
    "runtime": "hybrid",
    "python": {"entry": "plugin.py"},
    "permissions": ["python.execute", "filesystem.data"],
    "pages": [{"id": "home", "title": "Home", "fields": []}],
    "actions": [{"id": "hello", "label": "Hello", "type": "python", "handler": "hello"}],
}

FRONTEND_MANIFEST = {
    "id": "example.frontend-page",
    "name": "Frontend Page",
    "version": "1.0.0",
    "runtime": "frontend",
    "frontend": {"entry": "frontend/index.html"},
    "permissions": [],
    "pages": [],
    "actions": [{"id": "hello", "label": "Hello", "type": "message", "message": "hello {{name}}"}],
}


class PluginServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.plugins = Path(self.temp.name) / "plugins"
        self.plugins.mkdir()
        self.settings = SettingsStore(Path(self.temp.name) / "settings.json")
        self.patch = patch.object(config, "PLUGINS_DIR", self.plugins)
        self.data_patch = patch.object(config, "PLUGIN_DATA_DIR", Path(self.temp.name) / "plugin-data")
        self.patch.start()
        self.data_patch.start()
        self.service = PluginService(self.settings)

    def tearDown(self):
        self.patch.stop()
        self.data_patch.stop()
        self.temp.cleanup()

    def install_manifest(self):
        bundle = Path(self.temp.name) / "plugin.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(MANIFEST))
        result = self.service.install_bundle(str(bundle))
        self.assertTrue(result["ok"])

    def test_install_bundle_uses_manifest_id_directory(self):
        bundle = Path(self.temp.name) / "plugin.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(MANIFEST))
        result = self.service.install_bundle(str(bundle))
        self.assertTrue(result["ok"], result)
        target = self.plugins / MANIFEST["id"]
        self.assertEqual(Path(result["plugin"]["path"]), target)
        self.assertTrue((target / "xb-svcb-plugin.json").is_file())
        self.assertIn(str(target), result["message"])

    def test_install_bundle_bytes_uses_same_install_flow(self):
        bundle = Path(self.temp.name) / "plugin.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(MANIFEST))
        result = self.service.install_bundle_bytes("upload.xbplugin", bundle.read_bytes())
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.plugins / MANIFEST["id"] / "xb-svcb-plugin.json").is_file())

    def test_plugin_requires_global_and_individual_enablement(self):
        self.install_manifest()
        self.assertFalse(self.service.list()[0]["enabled"])
        self.assertFalse(self.service.run_action("example.quick-cover", "create", {})["ok"])
        self.service.configure({"enabled": True})
        self.service.set_enabled("example.quick-cover", True)
        result = self.service.run_action("example.quick-cover", "create", {"title": "A \"quote\"", "pitch": 3})
        self.assertTrue(result["ok"])
        self.assertEqual(result["payload"]["title"], "A \"quote\"")
        self.assertEqual(result["payload"]["params"]["pitch"], 3)

    def test_workflow_only_adds_allowlisted_missing_params(self):
        self.install_manifest()
        self.service.configure({"enabled": True})
        self.service.set_enabled("example.quick-cover", True)
        payload = self.service.apply_before_create({"params": {"f0_method": "harvest"}})
        self.assertEqual(payload["params"]["f0_method"], "harvest")
        self.assertNotIn("unknown", payload["params"])

    def test_rejects_zip_path_traversal(self):
        bundle = Path(self.temp.name) / "unsafe.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(MANIFEST))
            archive.writestr("../outside.txt", "bad")
        result = self.service.install_bundle(str(bundle))
        self.assertFalse(result["ok"])

    def test_frontend_entry_and_assets_are_served_after_enablement(self):
        bundle = Path(self.temp.name) / "frontend.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(FRONTEND_MANIFEST))
            archive.writestr("frontend/index.html", "<h1>custom page</h1>")
            archive.writestr("frontend/style.css", "body { color: red; }")
        result = self.service.install_bundle(str(bundle))
        self.assertTrue(result["ok"], result)
        self.service.configure({"enabled": True})
        self.assertTrue(self.service.set_enabled("example.frontend-page", True))
        document = self.service.frontend_document("example.frontend-page")
        self.assertTrue(document["ok"], document)
        self.assertIn("custom page", document["html"])
        asset = self.service.frontend_asset_data("example.frontend-page", "frontend/style.css")
        self.assertTrue(asset["ok"], asset)
        self.assertEqual(asset["mime"], "text/css")
        self.assertTrue(asset["data"].startswith("data:text/css;base64,"))
        self.assertFalse(self.service.frontend_asset_data("example.frontend-page", "../settings.json")["ok"])

    def test_frontend_entry_must_exist_when_installing(self):
        bundle = Path(self.temp.name) / "missing-frontend.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(FRONTEND_MANIFEST))
        result = self.service.install_bundle(str(bundle))
        self.assertFalse(result["ok"])

    def test_fetch_market_accepts_nonebot2_style_json5(self):
        self.settings.set(
            "plugin_market_url",
            "https://raw.githubusercontent.com/example/repo/main/assets/plugins.json5",
        )
        payload = """
        [
          {
            "module_name": "xb_plugin_demo",
            "project_link": "xb-plugin-demo",
            "author_id": 42,
            "desc": "Demo plugin",
            "tags": [{"label": "cover", "color": "#00f0ff"}],
            "is_official": true,
            "bundle_url": "https://github.com/example/repo/releases/download/v1/demo.xbplugin",
          },
        ]
        """

        class Response:
            url = "https://raw.githubusercontent.com/example/repo/main/assets/plugins.json5"
            text = payload

            def raise_for_status(self):
                return None

        with patch("application.plugin_service.httpx.get", return_value=Response()):
            result = self.service.fetch_market()

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["id"], "xb_plugin_demo")
        self.assertEqual(item["module_name"], "xb_plugin_demo")
        self.assertEqual(item["project_link"], "xb-plugin-demo")
        self.assertEqual(item["description"], "Demo plugin")
        self.assertEqual(item["author"], "42")
        self.assertTrue(item["is_official"])
        self.assertEqual(item["tags"][0]["label"], "cover")
        self.assertTrue(item["bundle_url"].endswith("demo.xbplugin"))

    def test_hybrid_plugin_runs_python_action_and_hook(self):
        bundle = Path(self.temp.name) / "hybrid.xbplugin"
        source = """
from xb_svcb_plugin import ActionResult, Plugin

plugin = Plugin("example.hybrid-plugin")

@plugin.action("hello")
def hello(ctx, values):
    ctx.config["calls"] = int(ctx.config.get("calls", 0)) + 1
    ctx.save_config()
    return ActionResult.message_result(f"hello {values.get('name')} #{ctx.config['calls']}")

@plugin.before_create
def add_defaults(ctx, payload):
    payload.setdefault("params", {}).setdefault("pitch", 2)
    return payload
"""
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(HYBRID_MANIFEST))
            archive.writestr("plugin.py", source)
        result = self.service.install_bundle(str(bundle))
        self.assertTrue(result["ok"], result)
        self.service.configure({"enabled": True})
        self.assertTrue(self.service.set_enabled("example.hybrid-plugin", True))
        action = self.service.run_action("example.hybrid-plugin", "hello", {"name": "XB"})
        self.assertTrue(action["ok"], action)
        self.assertEqual(action["message"], "hello XB #1")
        payload = self.service.apply_before_create({"params": {}})
        self.assertEqual(payload["params"]["pitch"], 2)

    def test_python_plugin_with_broken_entry_cannot_be_enabled(self):
        broken = {**HYBRID_MANIFEST, "id": "example.broken-plugin"}
        bundle = Path(self.temp.name) / "broken.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(broken))
            archive.writestr("plugin.py", "raise RuntimeError('broken plugin')")
        self.assertTrue(self.service.install_bundle(str(bundle))["ok"])
        self.service.configure({"enabled": True})
        self.assertFalse(self.service.set_enabled("example.broken-plugin", True))
        item = next(item for item in self.service.list() if item["id"] == "example.broken-plugin")
        self.assertFalse(item["enabled"])

    def test_python_package_entry_supports_relative_imports(self):
        manifest = {
            **HYBRID_MANIFEST,
            "id": "example.package-plugin",
            "python": {"entry": "package_plugin/__init__.py"},
        }
        bundle = Path(self.temp.name) / "package.xbplugin"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("xb-svcb-plugin.json", json.dumps(manifest))
            archive.writestr("package_plugin/message.py", "TEXT = 'package works'")
            archive.writestr(
                "package_plugin/__init__.py",
                "from xb_svcb_plugin import Plugin\nfrom .message import TEXT\n"
                "plugin = Plugin('example.package-plugin')\n"
                "@plugin.action('hello')\ndef hello(ctx, values): return TEXT\n",
            )
        self.assertTrue(self.service.install_bundle(str(bundle))["ok"])
        self.service.configure({"enabled": True})
        self.assertTrue(self.service.set_enabled("example.package-plugin", True))
        result = self.service.run_action("example.package-plugin", "hello", {})
        self.assertEqual(result.get("message"), "package works")


if __name__ == "__main__":
    unittest.main()
