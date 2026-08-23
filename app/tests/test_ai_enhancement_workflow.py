from pathlib import Path
from types import SimpleNamespace

import config
from application.conversion_service import ConversionService, default_steps_ai_enhancement
from application.work_service import WorkService
from infrastructure.storage import ListRepository, SettingsStore


class _QueuedConversion:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, work_id: str) -> None:
        self.started.append(work_id)


class _UnusedModels:
    pass


class _FakeFfmpeg:
    available = True

    def probe_duration(self, _path: Path) -> float:
        return 125.0

    def adaptive_mix_profile(self, _vocals: Path, _instrumental: Path) -> dict[str, float | None]:
        return {
            "vocal_gain_db": 0.0,
            "instrumental_gain_db": 0.0,
            "vocal_lufs": -16.0,
            "instrumental_lufs": -18.0,
        }

    def mix(
        self,
        vocals: Path,
        instrumental: Path,
        output: Path,
        **_kwargs,
    ) -> bool:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(vocals.read_bytes() + instrumental.read_bytes())
        return True

    def convert(self, source: Path, output: Path) -> bool:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.read_bytes())
        return True


class _FakeUvr:
    available = True

    def separate(self, _source: Path, output_dir: Path, _model: str, _device: str):  # noqa: ANN201
        output_dir.mkdir(parents=True, exist_ok=True)
        vocals = output_dir / "vocals.wav"
        instrumental = output_dir / "instrumental.wav"
        vocals.write_bytes(b"reference-vocal")
        instrumental.write_bytes(b"instrumental")
        return SimpleNamespace(vocals=vocals, instrumental=instrumental, simulated=False)


class _FakeEnhancer:
    available = True

    def __init__(self) -> None:
        self.reference: Path | None = None

    def enhance(self, source: Path, output: Path, **kwargs) -> Path:  # noqa: ANN003
        self.reference = kwargs.get("reference")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"enhanced-" + source.read_bytes())
        return output


def _paths(tmp_path: Path, monkeypatch) -> ListRepository:  # noqa: ANN001
    data = tmp_path / "data"
    monkeypatch.setattr(config, "WORKS_DIR", data / "works")
    monkeypatch.setattr(config, "WORKS_DB", data / "works.json")
    monkeypatch.setattr(config, "SETTINGS_DB", data / "settings.json")
    return ListRepository(config.WORKS_DB)


def test_create_ai_enhancement_requires_original_and_completed_work(tmp_path: Path, monkeypatch) -> None:
    repo = _paths(tmp_path, monkeypatch)
    conversion = _QueuedConversion()
    target = tmp_path / "cover.wav"
    target.write_bytes(b"cover")
    original = tmp_path / "original.wav"
    original.write_bytes(b"original")
    repo.add(
        {
            "id": "wrk_parent",
            "title": "测试翻唱",
            "model": "RVC A",
            "model_id": "rvc-a",
            "status": "done",
            "output_path": str(target),
            "converted_path": str(target),
            "duration": "02:05",
            "mode": "single",
        }
    )
    service = WorkService(
        repo,
        conversion,
        _UnusedModels(),
        SettingsStore(config.SETTINGS_DB),
    )

    work = service.create(
        {
            "workflow": "ai_enhancement",
            "target_work_id": "wrk_parent",
            "original_audio_path": str(original),
            "vocal_enhancement": {"enabled": True, "level": "advanced"},
        }
    )

    assert work["workflow"] == "ai_enhancement"
    assert work["parent_work_id"] == "wrk_parent"
    assert work["original_audio_path"] == str(original)
    assert [step["key"] for step in work["steps"]] == [
        "reference",
        "cover_vocal",
        "enhance",
        "mix",
    ]
    assert conversion.started == [work["id"]]


def test_ai_enhancement_uses_original_reference_and_creates_playable_work(tmp_path: Path, monkeypatch) -> None:
    repo = _paths(tmp_path, monkeypatch)
    original = tmp_path / "original.wav"
    original.write_bytes(b"original")
    cover = tmp_path / "cover.wav"
    cover.write_bytes(b"cover-mix")
    cover_vocal = tmp_path / "cover-vocal.wav"
    cover_vocal.write_bytes(b"cover-vocal")
    enhancer = _FakeEnhancer()
    work_id = "wrk_enhance"
    repo.add(
        {
            "id": work_id,
            "title": "测试翻唱 (AI 增强)",
            "model": "RVC A · AI 增强",
            "model_id": "rvc-a",
            "status": "queue",
            "progress": 0,
            "duration": "—",
            "format": "—",
            "size": "—",
            "created_at": "2026-08-20T12:00:00",
            "source_path": str(original),
            "original_audio_path": str(original),
            "parent_work_id": "wrk_parent",
            "target_output_path": str(cover),
            "target_vocal_path": str(cover_vocal),
            "params": {"device": "auto", "uvr_model": "MDX-Net"},
            "workflow": "ai_enhancement",
            "vocal_enhancement": {
                "enabled": True,
                "level": "advanced",
                "pitch_correction": 0.5,
                "timing_alignment": 0.6,
                "timbre_focus": 0.6,
                "ai_eq": 0.5,
                "ai_compressor": 0.4,
                "ai_exciter": 0.2,
                "stereo_width": 0.3,
                "loudness_envelope": 0.5,
            },
            "steps": default_steps_ai_enhancement(),
            "mode": "single",
        }
    )
    service = ConversionService(
        repo,
        _FakeFfmpeg(),
        _FakeUvr(),
        SimpleNamespace(sovits=None),
        enhancer,
    )

    service._run_ai_enhancement(work_id)

    work = repo.get(work_id)
    assert work is not None
    assert work["status"] == "done"
    assert work["progress"] == 100
    assert Path(work["output_path"]).is_file()
    assert enhancer.reference == Path(work["reference_vocals_path"])
    assert all(step["status"] == "done" for step in work["steps"])
    assert work["duration"] == "02:05"


def test_create_ai_enhancement_accepts_user_imported_target_audio(tmp_path: Path, monkeypatch) -> None:
    repo = _paths(tmp_path, monkeypatch)
    conversion = _QueuedConversion()
    target = tmp_path / "imported-cover.mp3"
    target.write_bytes(b"imported-cover")
    original = tmp_path / "original.wav"
    original.write_bytes(b"original")
    service = WorkService(
        repo,
        conversion,
        _UnusedModels(),
        SettingsStore(config.SETTINGS_DB),
    )

    work = service.create(
        {
            "workflow": "ai_enhancement",
            "target_audio_path": str(target),
            "original_audio_path": str(original),
            "vocal_enhancement": {"enabled": True, "level": "basic"},
        }
    )

    assert work["parent_work_id"] is None
    assert work["target_output_path"] == str(target)
    assert work["source_path"] == str(original)
    assert conversion.started == [work["id"]]
