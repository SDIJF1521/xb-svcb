"""Regression tests for the API module's multi-key and public-address settings."""

from __future__ import annotations

import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

import config
from api.http_server import HttpApiServer, create_http_app
from infrastructure.storage import SettingsStore


class _Facade:
    """Minimal facade used by contract tests."""

    def get_system_status(self):
        return {"ready": True, "tools": []}

    def list_models(self):
        return [{"id": "model-1", "name": "Test", "framework": "rvc"}]

    def get_default_model(self):
        return "model-1"


class MultiApiKeyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = _Facade()
        self.primary = "primary_api_key_0123456789"
        self.secondary = "secondary_api_key_0123456789"
        self.expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.app = create_http_app(
            self.facade,
            [
                {"id": "primary", "name": "Primary", "key": self.primary, "enabled": True},
                {"id": "secondary", "name": "Secondary", "key": self.secondary, "enabled": True},
                {"id": "expired", "name": "Expired", "key": "expired_api_key_0123456789", "enabled": True, "expires_at": self.expired},
                {"id": "disabled", "name": "Disabled", "key": "disabled_api_key_0123456789", "enabled": False},
            ],
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_each_enabled_unexpired_key_can_call_protected_api(self) -> None:
        for key in (self.primary, self.secondary):
            response = self.client.get("/api/v1/models", headers={"X-API-Key": key})
            self.assertEqual(response.status_code, 200)

    def test_disabled_and_expired_keys_are_rejected(self) -> None:
        for key in ("disabled_api_key_0123456789", "expired_api_key_0123456789"):
            response = self.client.get("/api/v1/models", headers={"X-API-Key": key})
            self.assertEqual(response.status_code, 401)

    def test_legacy_single_key_is_still_supported(self) -> None:
        key = "legacy_api_key_0123456789"
        app = create_http_app(self.facade, key)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/models", headers={"X-API-Key": key}).status_code, 200)


class HttpApiSettingsTests(unittest.TestCase):
    def _server(self, settings: SettingsStore) -> HttpApiServer:
        # Keep public-IP probing deterministic in unit tests.
        return HttpApiServer(_Facade(), settings)

    def test_legacy_config_migrates_to_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            legacy_key = "legacy_api_key_0123456789"
            settings.set("http_api", {"scope": "lan", "port": 8765, "api_key": legacy_key})
            with patch.object(HttpApiServer, "_detect_public_ip", return_value="192.0.2.10"):
                status = self._server(settings).status()
            self.assertEqual(len(status["api_keys"]), 1)
            self.assertEqual(status["api_keys"][0]["key"], legacy_key)
            self.assertEqual(settings.get("http_api")["api_keys"][0]["key"], legacy_key)

    def test_key_lifecycle_and_expiry_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            with patch.object(HttpApiServer, "_detect_public_ip", return_value="192.0.2.10"):
                server = self._server(settings)
                created = server.add_key({"name": "Temporary", "expires_at": "2030-01-02T03:04:05+08:00"})
                self.assertTrue(created["ok"], created)
                key_id = created["created"]["id"]
                self.assertEqual(created["created"]["expires_at"], "2030-01-01T19:04:05Z")
                updated = server.update_key(key_id, {"enabled": False, "expires_at": None})
                self.assertTrue(updated["ok"], updated)
                self.assertFalse(updated["updated"]["enabled"])
                self.assertIsNone(updated["updated"]["expires_at"])
                regenerated = server.regenerate_key(key_id)
                self.assertTrue(regenerated["ok"], regenerated)
                self.assertNotEqual(regenerated["updated"]["key"], created["created"]["key"])
                deleted = server.delete_key(key_id)
                self.assertTrue(deleted["ok"], deleted)
                self.assertEqual(server.delete_key("key_default")["ok"], False)

    def test_config_keeps_listener_local_and_formats_public_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            with patch.object(HttpApiServer, "_detect_public_ip", return_value="192.0.2.10"):
                server = self._server(settings)
                result = server.configure(
                    {
                        "scope": "lan",
                        "port": 8765,
                        "public_ip": "198.51.100.10",
                        "public_domain": "https://api.example.test/",
                    }
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["host"], "0.0.0.0")
            self.assertEqual(result["public_ip"], "198.51.100.10")
            self.assertTrue(result["public_ip_custom"])
            self.assertEqual(result["public_domain"], "api.example.test")
            self.assertIn("http://198.51.100.10:8765", result["base_urls"])
            self.assertIn("http://api.example.test:8765", result["base_urls"])
            self.assertEqual(result["docs_url"], "http://api.example.test:8765/docs")
            self.assertEqual(result["redoc_url"], "http://api.example.test:8765/redoc")
            self.assertNotEqual(result["host"], result["public_ip"])

    def test_docs_fall_back_without_domain_and_local_scope_stays_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            with patch.object(HttpApiServer, "_detect_public_ip", return_value="192.0.2.10"):
                server = self._server(settings)
                without_domain = server.configure(
                    {"scope": "lan", "port": 8760, "public_ip": "198.51.100.10", "public_domain": ""}
                )
                self.assertEqual(without_domain["docs_url"], "http://127.0.0.1:8760/docs")
                local = server.configure(
                    {"scope": "local", "port": 8761, "public_ip": "198.51.100.10", "public_domain": "api.example.test"}
                )
                self.assertEqual(local["docs_url"], "http://127.0.0.1:8761/docs")
                self.assertEqual(local["redoc_url"], "http://127.0.0.1:8761/redoc")

    def test_ipv6_public_url_is_formatted_for_browsers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            server = self._server(settings)
            status = server.configure(
                {"scope": "lan", "port": 8762, "public_ip": "2001:db8::10", "public_domain": ""}
            )
            self.assertIn("http://[2001:db8::10]:8762", status["base_urls"])
            self.assertEqual(status["docs_url"], "http://127.0.0.1:8762/docs")

    def test_open_docs_uses_configured_domain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            server = self._server(settings)
            server.configure({"scope": "lan", "port": 8763, "public_domain": "api.example.test"})
            with patch.object(server, "_is_running", return_value=True), patch(
                "api.http_server.webbrowser.open", return_value=True
            ) as open_browser:
                self.assertTrue(server.open_docs("docs"))
            open_browser.assert_called_once_with("http://api.example.test:8763/docs")

    def test_requested_ports_can_start_and_answer_locally(self) -> None:
        """Check that the requested ports bind and answer locally."""
        for port in (8765, 8760, 8761, 8762, 8763):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as temp:
                settings = SettingsStore(Path(temp) / "settings.json")
                server = self._server(settings)
                started = server.start(
                    {
                        "scope": "lan",
                        "port": port,
                        "public_ip": "198.51.100.10",
                        "public_domain": "api.example.test",
                    }
                )
                try:
                    self.assertTrue(started["ok"], started)
                    self.assertEqual(started["host"], "0.0.0.0")
                    response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
                    self.assertEqual(response.status_code, 200)
                finally:
                    stopped = server.stop()
                    self.assertTrue(stopped["ok"], stopped)
    def test_invalid_public_address_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            with patch.object(HttpApiServer, "_detect_public_ip", return_value="192.0.2.10"):
                server = self._server(settings)
                self.assertFalse(server.configure({"public_ip": "not-an-ip"})["ok"])
                self.assertFalse(server.configure({"public_domain": "bad domain"})["ok"])


if __name__ == "__main__":
    unittest.main()
