import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import config
from api.http_server import (
    HttpApiServer,
    _hydrate_editor_project,
    _public_editor_project,
    create_http_app,
)
from infrastructure.storage import SettingsStore


class _Models:
    def __init__(self) -> None:
        self.items = {
            "model_svc": {
                "id": "model_svc",
                "name": "Test SVC",
                "type": "SVC",
                "framework": "so-vits-svc",
                "sample_rate": "44.1 kHz",
                "size": "100 MB",
                "main_model": {"path": "D:/secret/model.pth"},
            },
            "model_seed": {
                "id": "model_seed",
                "name": "Test SeedVC",
                "type": "SeedVC",
                "framework": "seed-vc",
            },
        }

    def get(self, model_id: str):
        return self.items.get(model_id)


class _Facade:
    def __init__(self, audio_path: Path | None = None) -> None:
        self._models = _Models()
        self.audio_path = audio_path
        self.created_payload = None
        self.work = {
            "id": "wrk_test",
            "title": "Test (AI 翻唱)",
            "model": "Test SVC",
            "model_id": "model_svc",
            "framework": "so-vits-svc",
            "status": "queue",
            "progress": 0,
            "created_at": "2026-07-23T12:00:00",
            "steps": [],
            "source_path": "D:/secret/song.wav",
            "main_model_path": "D:/secret/model.pth",
        }

    def get_system_status(self):
        return {"ready": True, "tools": []}

    def list_models(self):
        return list(self._models.items.values())

    def get_default_model(self):
        return "model_svc"

    def list_works(self):
        return [dict(self.work)]

    def get_work(self, work_id: str):
        return dict(self.work) if work_id == self.work["id"] else None

    def create_work(self, payload):
        self.created_payload = payload
        return dict(self.work)

    def get_inference_queue(self):
        return {"running": False, "pending": [], "size": 0}

    def retry_work(self, work_id: str):
        return work_id == self.work["id"]

    def _stem_path(self, work_id: str, stem: str):
        if work_id == self.work["id"] and stem == "output":
            return self.audio_path
        return None


class HttpApiContractTests(unittest.TestCase):
    API_KEY = "test_api_key_0123456789abcdef"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp.name) / "uploads"
        self.facade = _Facade()
        self.app = create_http_app(self.facade, self.API_KEY)
        self.client = TestClient(self.app)
        self.headers = {"X-API-Key": self.API_KEY}
        self.upload_patch = patch.object(config, "API_UPLOADS_DIR", self.upload_dir)
        self.upload_patch.start()

    def tearDown(self) -> None:
        self.client.close()
        self.upload_patch.stop()
        self.temp.cleanup()

    def test_health_is_public_and_protected_routes_require_key(self) -> None:
        health = self.client.get("/health")
        protected = self.client.get("/api/v1/models")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["version"], config.APP_VERSION)
        self.assertEqual(protected.status_code, 401)

    def test_models_do_not_expose_local_model_paths(self) -> None:
        response = self.client.get("/api/v1/models", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_id"], "model_svc")
        self.assertNotIn("main_model", payload["items"][0])
        self.assertNotIn("path", str(payload))

    def test_upload_can_be_used_to_create_job(self) -> None:
        upload = self.client.post(
            "/api/v1/uploads",
            headers=self.headers,
            files={"file": ("song.wav", b"RIFF-test-audio", "audio/wav")},
        )
        self.assertEqual(upload.status_code, 201)
        upload_id = upload.json()["upload_id"]

        created = self.client.post(
            "/api/v1/jobs",
            headers=self.headers,
            json={
                "source_upload_id": upload_id,
                "model_id": "model_svc",
                "params": {"pitch": 2, "device": "auto"},
            },
        )

        self.assertEqual(created.status_code, 202)
        self.assertTrue(Path(self.facade.created_payload["source_path"]).is_file())
        self.assertEqual(self.facade.created_payload["params"]["pitch"], 2)
        self.assertNotIn("source_path", created.json())
        self.assertNotIn("main_model_path", created.json())

    def test_upload_larger_than_multipart_memory_threshold_is_accepted(self) -> None:
        content = b"a" * (3 * 1024 * 1024)

        response = self.client.post(
            "/api/v1/uploads",
            headers=self.headers,
            files={"file": ("long.flac", content, "audio/flac")},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["size"], len(content))
        stored = list(self.upload_dir.glob(f"{response.json()['upload_id']}.*"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].stat().st_size, len(content))

    def test_seedvc_job_requires_reference_audio(self) -> None:
        source = Path(self.temp.name) / "source.wav"
        source.write_bytes(b"RIFF")

        response = self.client.post(
            "/api/v1/jobs",
            headers=self.headers,
            json={"source_path": str(source), "model_id": "model_seed"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("reference_upload_id", response.json()["detail"])

    def test_multi_model_job_supports_chorus_and_uploaded_seedvc_reference(self) -> None:
        source = self.client.post(
            "/api/v1/uploads",
            headers=self.headers,
            files={"file": ("song.wav", b"RIFF-song", "audio/wav")},
        ).json()
        reference = self.client.post(
            "/api/v1/uploads",
            headers=self.headers,
            files={"file": ("reference.wav", b"RIFF-reference", "audio/wav")},
        ).json()

        response = self.client.post(
            "/api/v1/jobs",
            headers=self.headers,
            json={
                "source_upload_id": source["upload_id"],
                "mode": "multi",
                "workflow": "auto_vocal_merge",
                "models": [
                    {"model_id": "model_svc", "params": {"pitch": 1}},
                    {
                        "model_id": "model_seed",
                        "reference_upload_id": reference["upload_id"],
                    },
                ],
                "segments": [
                    {
                        "start": 0,
                        "end": 8.5,
                        "model_ids": ["model_svc", "model_seed"],
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 202, response.text)
        payload = self.facade.created_payload
        self.assertEqual(payload["mode"], "multi")
        self.assertEqual(payload["workflow"], "auto_vocal_merge")
        self.assertEqual(payload["segments"][0]["model_ids"], ["model_svc", "model_seed"])
        self.assertTrue(Path(payload["models"][1]["params"]["reference_audio"]).is_file())
        self.assertNotIn("source_path", response.json())

    def test_batch_jobs_rejects_more_than_fifty_requests(self) -> None:
        response = self.client.post(
            "/api/v1/jobs/batch",
            headers=self.headers,
            json={"jobs": [{} for _ in range(51)]},
        )

        self.assertEqual(response.status_code, 422)

    def test_batch_jobs_validate_all_items_before_creating_any_task(self) -> None:
        source = Path(self.temp.name) / "source.wav"
        source.write_bytes(b"RIFF")

        response = self.client.post(
            "/api/v1/jobs/batch",
            headers=self.headers,
            json={
                "jobs": [
                    {"source_path": str(source), "model_id": "model_svc"},
                    {"source_path": str(source), "model_id": "missing_model"},
                ]
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertIsNone(self.facade.created_payload)

    def test_editor_public_dto_hides_paths_and_save_restores_server_fields(self) -> None:
        stored = {
            "id": "edt_test",
            "title": "Editor",
            "tracks": [
                {
                    "id": "trk_test",
                    "name": "Voice",
                    "type": "vocal",
                    "clips": [
                        {
                            "id": "clp_test",
                            "name": "Clip",
                            "file": r"D:\secret\voice.wav",
                            "start": 0.0,
                            "end": 2.0,
                            "offset": 0.0,
                            "volume": 1.0,
                            "mute": False,
                            "locked": False,
                            "fade_in": 0.0,
                            "fade_out": 0.0,
                            "effects": [
                                {
                                    "id": "fx_test",
                                    "type": "plugin",
                                    "enabled": True,
                                    "params": {"path": r"D:\secret\effect.vst3", "mix": 0.5},
                                }
                            ],
                            "metadata": {"source_path": r"D:\secret\source.wav"},
                        }
                    ],
                }
            ],
            "roles": [],
            "duration": 2.0,
            "sample_rate": 44100,
            "waveform_cache": {},
            "metadata": {"source_path": r"D:\secret\source.wav"},
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        public = _public_editor_project(stored)
        self.assertNotIn("D:\\secret", str(public))
        clip = public["tracks"][0]["clips"][0]
        self.assertEqual(
            clip["audio_url"],
            "/api/v1/editor/projects/edt_test/clips/clp_test/audio",
        )
        clip["volume"] = 0.75

        hydrated = _hydrate_editor_project(public, stored, "edt_test")
        restored_clip = hydrated["tracks"][0]["clips"][0]
        self.assertEqual(restored_clip["file"], r"D:\secret\voice.wav")
        self.assertEqual(restored_clip["effects"][0]["params"]["path"], r"D:\secret\effect.vst3")
        self.assertEqual(restored_clip["volume"], 0.75)
        self.assertNotIn("audio_url", restored_clip)
        self.assertNotIn("render_url", hydrated)

    def test_generated_audio_can_be_downloaded_with_key(self) -> None:
        audio = Path(self.temp.name) / "output.wav"
        audio.write_bytes(b"RIFF-output")
        self.facade.audio_path = audio
        self.facade.work["status"] = "done"

        missing_key = self.client.get("/api/v1/jobs/wrk_test/audio")
        response = self.client.get(
            "/api/v1/jobs/wrk_test/audio", headers=self.headers
        )

        self.assertEqual(missing_key.status_code, 401)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"RIFF-output")
        self.assertEqual(response.headers["content-type"], "audio/wav")

    def test_openapi_documents_every_inference_and_route_parameter(self) -> None:
        schema = self.client.get("/openapi.json").json()
        components = schema["components"]["schemas"]
        inference = components["InferenceParamsRequest"]["properties"]
        expected_inference_fields = {
            "pitch",
            "f0_method",
            "device",
            "uvr_model",
            "diffusion_ratio",
            "speaker",
            "index_rate",
            "rms_mix",
            "protect",
            "filter_radius",
            "rvc_version",
            "reference_audio",
            "ddsp_infer_steps",
            "ddsp_formant_shift",
        }

        self.assertEqual(set(inference), expected_inference_fields)
        for name, field in inference.items():
            self.assertTrue(field.get("description"), name)
            self.assertIn("default", field, name)
        self.assertEqual(
            inference["device"]["enum"],
            ["auto", "cuda", "rocm", "directml", "cpu"],
        )
        self.assertEqual(inference["pitch"]["minimum"], -12)
        self.assertEqual(inference["pitch"]["maximum"], 12)
        self.assertEqual(
            inference["f0_method"]["enum"],
            ["rmvpe", "crepe", "harvest", "pm", "fcpe", "dio", "parselmouth"],
        )

        job_fields = components["JobCreateRequest"]["properties"]
        for name, field in job_fields.items():
            self.assertTrue(field.get("description"), name)

        route_parameters = [
            ("/api/v1/models/{model_id}", "get", "model_id"),
            ("/api/v1/uploads/{upload_id}", "delete", "upload_id"),
            ("/api/v1/jobs", "get", "limit"),
            ("/api/v1/jobs/{job_id}", "get", "job_id"),
            ("/api/v1/jobs/{job_id}/retry", "post", "job_id"),
            ("/api/v1/jobs/{job_id}/audio", "get", "job_id"),
            ("/api/v1/jobs/{job_id}/audio", "get", "stem"),
        ]
        for path, method, parameter_name in route_parameters:
            parameters = schema["paths"][path][method]["parameters"]
            parameter = next(item for item in parameters if item["name"] == parameter_name)
            self.assertTrue(parameter.get("description"), f"{method.upper()} {path} {parameter_name}")

        upload_body_ref = schema["paths"]["/api/v1/uploads"]["post"]["requestBody"][
            "content"
        ]["multipart/form-data"]["schema"]["$ref"]
        upload_body = components[upload_body_ref.rsplit("/", 1)[-1]]["properties"]
        self.assertTrue(upload_body["file"].get("description"))

        expected_responses = {
            ("/health", "get"): "HealthResponse",
            ("/api/v1/system", "get"): "SystemResponse",
            ("/api/v1/models", "get"): "ModelListResponse",
            ("/api/v1/models/{model_id}", "get"): "ModelResponse",
            ("/api/v1/uploads", "post"): "UploadResponse",
            ("/api/v1/uploads/{upload_id}", "delete"): "DeleteUploadResponse",
            ("/api/v1/jobs", "get"): "JobListResponse",
            ("/api/v1/jobs", "post"): "JobResponse",
            ("/api/v1/jobs/queue", "get"): "QueueResponse",
            ("/api/v1/jobs/{job_id}", "get"): "JobResponse",
            ("/api/v1/jobs/{job_id}/retry", "post"): "RetryResponse",
            ("/api/v1/jobs/batch", "post"): "JobBatchResponse",
            ("/api/v1/editor/projects", "get"): "EditorProjectListResponse",
            ("/api/v1/editor/projects", "post"): "EditorProjectResponse",
            ("/api/v1/editor/projects/{project_id}", "get"): "EditorProjectResponse",
        }
        for (path, method), model_name in expected_responses.items():
            operation = schema["paths"][path][method]
            success = next(
                response
                for status, response in operation["responses"].items()
                if status.startswith("2")
            )
            response_ref = success["content"]["application/json"]["schema"]["$ref"]
            self.assertEqual(response_ref, f"#/components/schemas/{model_name}")

    def test_openapi_uses_go_cqhttp_layout_and_includes_complete_workflow(self) -> None:
        schema = self.client.get("/openapi.json").json()
        overview = schema["info"]["description"]

        self.assertIn("## 公共请求头", overview)
        self.assertIn("## 完整示例：生成一首 AI 翻唱", overview)
        for fragment in (
            "/api/v1/uploads",
            "/api/v1/models",
            "/api/v1/jobs",
            "while True:",
            "job['result_url']",
            "requests.delete",
        ):
            self.assertIn(fragment, overview)
        workflow_example = overview.split("```python", 1)[1].split("```", 1)[0]
        compile(workflow_example, "<openapi-workflow-example>", "exec")

        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                if method not in {"get", "post", "delete"}:
                    continue
                description = operation["description"]
                self.assertIn(f"method: `{method.upper()}`", description, path)
                self.assertIn("参数:", description, path)
                self.assertIn("| 参数名 | 类型 | 必填 | 默认值 | 说明 |", description, path)
                self.assertIn("返回:", description, path)
                self.assertIn("响应数据:", description, path)
                self.assertIn("| 字段名 | 类型 | 说明 |", description, path)

        for path in (
            "/api/v1/jobs/batch",
            "/api/v1/jobs/history",
            "/api/v1/jobs/presets",
            "/api/v1/editor/projects",
            "/api/v1/editor/projects/{project_id}/audio",
            "/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/rerun",
        ):
            self.assertIn(path, schema["paths"])

        create_job_doc = schema["paths"]["/api/v1/jobs"]["post"]["description"]
        for parameter in (
            "source_upload_id",
            "reference_upload_id",
            "params.pitch",
            "params.device",
            "params.index_rate",
            "params.ddsp_infer_steps",
        ):
            self.assertIn(f"`{parameter}`", create_job_doc)
        self.assertIn("请求示例:", create_job_doc)
        self.assertIn("没有固定文件大小上限", schema["paths"]["/api/v1/uploads"]["post"]["description"])


class HttpApiServerLifecycleTests(unittest.TestCase):
    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_server_is_manual_and_releases_port_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(Path(temp) / "settings.json")
            server = HttpApiServer(_Facade(), settings)
            port = self._free_port()

            initial = server.status()
            self.assertFalse(initial["running"])

            started = server.start({"scope": "local", "port": port})
            self.assertTrue(started["ok"], started.get("error"))
            self.assertTrue(started["running"])
            self.assertTrue(server.test()["ok"])

            stopped = server.stop()
            self.assertTrue(stopped["ok"], stopped.get("error"))
            self.assertFalse(stopped["running"])
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
