from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np
import pytest

from application.conversion_service import ConversionService
from application.realtime_cover_service import RealtimeCoverService
from domain import InferenceParams
from infrastructure.uvr_tool import SeparationResult


class FakeModels:
    def __init__(self, records: dict[str, dict]) -> None:
        self.records = records

    def get(self, model_id: str):  # noqa: ANN201
        return self.records.get(model_id)


class FakeEngine:
    available = True

    def __init__(self) -> None:
        self.open_count = 0

    def open_realtime_session(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        self.open_count += 1
        return FakePersistentSession()

    def infer(self, *, vocals: Path, out_path: Path, **_kwargs) -> Path:  # noqa: ANN003
        out_path.write_bytes(vocals.read_bytes())
        return out_path


class FakePersistentSession:
    def infer(self, vocals: Path, out_path: Path) -> Path:
        out_path.write_bytes(vocals.read_bytes())
        return out_path

    def close(self) -> None:
        return None


class FakeRegistry:
    def __init__(self) -> None:
        self.engine = FakeEngine()

    def for_framework(self, _framework: str) -> FakeEngine:
        return self.engine


class FakeFfmpeg:
    available = True

    def probe_duration(self, _source: Path) -> float:
        return 18.0

    @staticmethod
    def _write(dst: Path, value: bytes = b"RIFFmock") -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(value)
        return True

    def slice(self, _src: Path, _start: float, _end: float, dst: Path, **_kwargs) -> bool:
        return self._write(dst)

    def pad_or_trim(self, src: Path, dst: Path, _seconds: float) -> bool:
        return self._write(dst, src.read_bytes())

    def convert(self, src: Path, dst: Path, *_args, **_kwargs) -> bool:
        return self._write(dst, src.read_bytes())

    def silence(self, dst: Path, _duration: float) -> bool:
        return self._write(dst)

    def mix_vocals(self, inputs: list[Path], dst: Path) -> bool:
        return self._write(dst, b"".join(path.read_bytes() for path in inputs))

    def mix(self, vocals: Path, music: Path, dst: Path, **_kwargs) -> bool:
        return self._write(dst, vocals.read_bytes() + music.read_bytes())

    def concat(self, parts: list[Path], dst: Path) -> bool:
        return self._write(dst, b"".join(path.read_bytes() for path in parts))


class FakeUvr:
    def separate(self, _source: Path, out_dir: Path, *_args) -> SeparationResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        vocals = out_dir / "vocals.wav"
        music = out_dir / "instrumental.wav"
        vocals.write_bytes(b"vocals")
        music.write_bytes(b"music")
        return SeparationResult(vocals=vocals, instrumental=music)


class FakePymss(FakeUvr):
    available = True

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def separate(self, source: Path, out_dir: Path, *args, **kwargs) -> SeparationResult:
        self.calls.append((source, out_dir, args, kwargs))
        return super().separate(source, out_dir)



def _record(tmp_path: Path, model_id: str, framework: str = "rvc") -> dict:
    model = tmp_path / f"{model_id}.pth"
    model.write_bytes(b"model")
    config = tmp_path / f"{model_id}.yml"
    config.write_text("model: test", encoding="utf-8")
    return {
        "id": model_id,
        "name": model_id,
        "framework": framework,
        "main_model": {"path": str(model)},
        "main_config": {"path": str(config)},
    }


def _service(tmp_path: Path) -> RealtimeCoverService:
    records = {
        "rvc-a": _record(tmp_path, "rvc-a"),
        "seed-b": _record(tmp_path, "seed-b", "seed-vc"),
    }
    return RealtimeCoverService(
        FakeModels(records),  # type: ignore[arg-type]
        FakeFfmpeg(),  # type: ignore[arg-type]
        FakeUvr(),  # type: ignore[arg-type]
        FakeRegistry(),  # type: ignore[arg-type]
    )


def test_realtime_cover_produces_fixed_timeline_chunks(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("application.realtime_cover_service.config.TEMP_DIR", tmp_path / "temp")
    source = tmp_path / "song.wav"
    source.write_bytes(b"song")
    service = _service(tmp_path)

    status = service.start(
        {
            "source_path": str(source),
            "mode": "single",
            "model_id": "rvc-a",
            "params": {"device": "auto"},
            "chunk_seconds": 8,
            "buffer_seconds": 8,
        }
    )
    for _ in range(100):
        status = service.status(status["id"])
        if status["status"] in {"done", "failed"}:
            break
        time.sleep(0.01)

    assert status["status"] == "done"
    assert status["ready_chunks"] == 3
    assert status["ready_seconds"] == 18.0
    assert Path(status["output_path"]).is_file()
    last = service.chunk(status["id"], 2)
    assert last["ok"] is True
    assert last["start"] == 16.0
    assert last["end"] == 18.0
    assert last["audio"].startswith("data:audio/wav;base64,")
    assert service._engines.engine.open_count == 1  # type: ignore[attr-defined]  # noqa: SLF001


def test_file_realtime_can_use_pymss_separation(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("application.realtime_cover_service.config.TEMP_DIR", tmp_path / "temp")
    monkeypatch.setattr(
        "application.realtime_cover_service.config.pymss_model_ready",
        lambda _model: True,
    )
    source = tmp_path / "song.wav"
    source.write_bytes(b"song")
    pymss = FakePymss()
    service = RealtimeCoverService(
        FakeModels({
            "rvc-a": _record(tmp_path, "rvc-a"),
            "seed-b": _record(tmp_path, "seed-b", "seed-vc"),
        }),  # type: ignore[arg-type]
        FakeFfmpeg(),  # type: ignore[arg-type]
        FakeUvr(),  # type: ignore[arg-type]
        FakeRegistry(),  # type: ignore[arg-type]
        pymss,  # type: ignore[arg-type]
    )

    status = service.start(
        {
            "source_path": str(source),
            "mode": "single",
            "model_id": "rvc-a",
            "params": {
                "device": "auto",
                "preprocess_engine": "pymss",
                "pymss_model": "demo.ckpt",
            },
            "chunk_seconds": 8,
            "buffer_seconds": 8,
        }
    )
    for _ in range(100):
        status = service.status(status["id"])
        if status["status"] in {"done", "failed"}:
            break
        time.sleep(0.01)

    assert status["status"] == "done"
    assert status["separator_engine"] == "pymss"
    assert status["separator_model"] == "demo.ckpt"
    assert pymss.calls


def test_realtime_cover_rejects_multiple_models(tmp_path: Path) -> None:
    service = _service(tmp_path)
    source = tmp_path / "song.wav"
    source.write_bytes(b"song")
    with pytest.raises(ValueError, match="只支持单个"):
        service.start(
            {
                "source_path": str(source),
                "mode": "single",
                "models": [
                    {"model_id": "rvc-a", "params": {"device": "auto"}},
                    {"model_id": "seed-b", "params": {"device": "auto", "reference_audio": str(source)}},
                ],
                "chunk_seconds": 8,
                "buffer_seconds": 8,
            }
        )


def test_system_audio_requires_separate_routing_devices(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="不能相同"):
        service.start_system(
            {
                "input_device": "same",
                "output_device": "same",
                "model_id": "rvc-a",
            }
        )


def test_system_silent_block_bypasses_uvr(tmp_path: Path) -> None:
    class ExplodingSeparator:
        def infer(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError("silent blocks must not invoke UVR")

    service = _service(tmp_path)
    prepared = service._prepare_system_block(  # type: ignore[attr-defined]  # noqa: SLF001
        tmp_path,
        ExplodingSeparator(),
        [[0.0, 0.0]] * 8,
        8,
        0,
        8,
    )

    assert prepared["silent"] is True
    assert not (tmp_path / "system_input_000000.wav").exists()


def test_system_silent_block_ignores_non_silent_overlap(tmp_path: Path) -> None:
    class ExplodingSeparator:
        def infer(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError("only the current source interval determines silence")

    service = _service(tmp_path)
    captured = [[0.5, 0.5], [0.25, 0.25], *([[0.0, 0.0]] * 8)]
    prepared = service._prepare_system_block(  # type: ignore[attr-defined]  # noqa: SLF001
        tmp_path,
        ExplodingSeparator(),
        captured,
        10,
        1,
        8,
        output_frames=8,
        overlap_frames=2,
    )

    assert prepared["silent"] is True
    assert prepared["overlap_frames"] == 2
    assert prepared["length"] == 1.0
    assert not (tmp_path / "system_input_000001.wav").exists()


def test_system_timing_profiles_default_to_live_latency() -> None:
    separated = RealtimeCoverService._system_timing_profile(  # type: ignore[attr-defined]  # noqa: SLF001
        {}, "rvc", True
    )
    assert separated["chunk_seconds"] == 1.5
    assert separated["prebuffer_blocks"] == 1
    assert separated["max_lag_blocks"] == 2
    assert separated["low_latency"] is True

    direct = RealtimeCoverService._system_timing_profile(  # type: ignore[attr-defined]  # noqa: SLF001
        {}, "rvc", False
    )
    assert direct["chunk_seconds"] == 0.5
    assert direct["low_latency"] is True

    legacy = RealtimeCoverService._system_timing_profile(  # type: ignore[attr-defined]  # noqa: SLF001
        {"chunk_seconds": 8, "prebuffer_blocks": 4, "latency_mode": "quality"},
        "rvc",
        True,
    )
    assert legacy["chunk_seconds"] == 4.0
    assert legacy["prebuffer_blocks"] == 4
    assert legacy["low_latency"] is False


def test_direct_vocal_block_skips_uvr_and_reuses_captured_audio(tmp_path: Path) -> None:
    service = _service(tmp_path)
    captured = np.full((16, 2), 0.08, dtype=np.float32)

    prepared = service._prepare_system_block(  # type: ignore[attr-defined]  # noqa: SLF001
        tmp_path,
        None,
        captured,
        16,
        0,
        8000,
    )

    assert prepared["direct"] is True
    assert prepared["separated"] == prepared["raw"]
    assert Path(prepared["raw"]).is_file()
    assert "accompaniment" not in prepared


def test_realtime_dropout_recovery_uses_model_render_for_loudness_and_adaptive_shift(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    service = _service(tmp_path)
    source = tmp_path / "source.wav"
    output = tmp_path / "render.wav"
    _write_test_wav(source, np.full((1600, 1), 0.1, dtype=np.float32), 16000)
    calls: list[dict[str, object]] = []
    issue = {
        "start": 0.8,
        "end": 1.1,
        "source_f0_hz": 1200.0,
        "bad_frames": 20,
        "bad_regions": [{"start": 0.8, "end": 1.1}],
    }
    detections = iter([issue, None])

    def detect(*_args):  # noqa: ANN002, ANN201
        return next(detections)

    def infer(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"baseline" if destination == output else b"retry")

    def prepare(_source: Path, destination: Path, *_args, **kwargs):  # noqa: ANN002, ANN201
        calls.append({"kind": "prepare", "semitones": kwargs["semitones"]})
        destination.write_bytes(b"guarded")
        return destination, -int(kwargs["semitones"])

    def pitch_shift(_source: Path, destination: Path, semitones: int, **kwargs):
        calls.append(
            {
                "kind": "restore",
                "semitones": semitones,
                "loudness_source": kwargs.get("loudness_source"),
            }
        )
        destination.write_bytes(b"restored")
        return True

    def merge(_baseline: Path, _guarded: Path, destination: Path, *_args, **_kwargs):
        destination.write_bytes(b"merged")
        return destination

    monkeypatch.setattr(ConversionService, "_detect_model_dropout", detect)
    monkeypatch.setattr(ConversionService, "_guard_candidate_has_new_hf_peak", lambda *_args: False)
    monkeypatch.setattr(ConversionService, "_merge_guarded_regions", merge)
    service._prepare_pitch_guard = prepare
    service._pitch_shift = pitch_shift

    rendered, history = service._infer_with_dropout_recovery(
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=1,
        ),
        model={"framework": "rvc"},
        infer=infer,
        log_file=tmp_path / "run.log",
    )

    assert rendered.name == "render_guarded_merged_retry1.wav"
    assert len(history) == 2
    assert calls[0] == {"kind": "prepare", "semitones": 15}
    assert calls[1] == {
        "kind": "restore",
        "semitones": 15,
        "loudness_source": output.with_name("render_dropout_retry1.wav"),
    }


def test_realtime_dropout_recovery_rejects_whistle_candidate(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path)
    source = tmp_path / "source.wav"
    output = tmp_path / "render.wav"
    _write_test_wav(source, np.full((1600, 1), 0.1, dtype=np.float32), 16000)
    issue = {
        "start": 0.5,
        "end": 0.9,
        "source_f0_hz": 920.0,
        "bad_frames": 12,
        "bad_regions": [{"start": 0.5, "end": 0.9}],
    }
    detections = iter([issue, None])

    def detect(*_args):  # noqa: ANN002, ANN201
        return next(detections)

    def infer(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"baseline" if destination == output else b"retry")

    def prepare(_source: Path, destination: Path, *_args, **_kwargs):  # noqa: ANN002
        destination.write_bytes(b"guarded")
        return destination, -9

    def restore(_source: Path, destination: Path, *_args, **_kwargs):  # noqa: ANN002
        destination.write_bytes(b"restored")
        return True

    def merge(_baseline: Path, _guarded: Path, destination: Path, *_args, **_kwargs):
        destination.write_bytes(b"whistle-candidate")
        return destination

    monkeypatch.setattr(ConversionService, "_detect_model_dropout", detect)
    monkeypatch.setattr(ConversionService, "_guard_candidate_has_new_hf_peak", lambda *_args: True)
    monkeypatch.setattr(ConversionService, "_merge_guarded_regions", merge)
    service._prepare_pitch_guard = prepare
    service._pitch_shift = lambda *_args, **_kwargs: True

    rendered, history = service._infer_with_dropout_recovery(
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=1,
        ),
        model={"framework": "rvc"},
        infer=infer,
        log_file=tmp_path / "run.log",
    )

    assert rendered == output
    assert output.read_bytes() == b"baseline"
    assert len(history) == 2


def test_realtime_dropout_recovery_keeps_first_render_when_all_retries_fail(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    service = _service(tmp_path)
    source = tmp_path / "source.wav"
    output = tmp_path / "render.wav"
    _write_test_wav(source, np.full((1600, 1), 0.1, dtype=np.float32), 16000)
    issue = {
        "start": 0.5,
        "end": 0.9,
        "source_f0_hz": 920.0,
        "bad_frames": 20,
        "bad_regions": [{"start": 0.5, "end": 0.9}],
    }

    def infer(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"baseline" if destination == output else b"retry")

    def prepare(_source: Path, destination: Path, *_args, **_kwargs):  # noqa: ANN002
        destination.write_bytes(b"guarded")
        return destination, -9

    def merge(_baseline: Path, _guarded: Path, destination: Path, *_args, **_kwargs):
        destination.write_bytes(b"retry")
        return destination

    monkeypatch.setattr(ConversionService, "_detect_model_dropout", lambda *_args: issue)
    monkeypatch.setattr(ConversionService, "_guard_candidate_has_new_hf_peak", lambda *_args: False)
    monkeypatch.setattr(ConversionService, "_merge_guarded_regions", merge)
    service._prepare_pitch_guard = prepare
    service._pitch_shift = lambda *_args, **_kwargs: True
    rendered, history = service._infer_with_dropout_recovery(
        source=source,
        output=output,
        params=InferenceParams(
            high_pitch_threshold=800.0,
            manual_params_enabled=True,
            high_pitch_guard_rounds=2,
        ),
        model={"framework": "rvc"},
        infer=infer,
        log_file=tmp_path / "run.log",
    )

    assert rendered == output
    assert output.read_bytes() == b"baseline"
    assert len(history) == 3


def _write_test_wav(path: Path, values: np.ndarray, sample_rate: int) -> None:
    data = np.asarray(values, dtype=np.float32)
    pcm = np.clip(data, -1.0, 1.0)
    pcm = np.rint(pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(int(pcm.shape[1] if pcm.ndim > 1 else 1))
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def test_system_non_silent_block_finishes_cleanup_without_guard_variable_error(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    sample_rate = 8000
    frames = 160
    values = np.full((frames, 2), 0.08, dtype=np.float32)
    raw = tmp_path / "raw.wav"
    separated = tmp_path / "separated.wav"
    accompaniment = tmp_path / "accompaniment.wav"
    rendered = tmp_path / "rendered.wav"
    for path in (raw, separated, accompaniment):
        _write_test_wav(path, values, sample_rate)

    class Worker:
        def infer(self, _source: Path, destination: Path, **_kwargs) -> None:
            _write_test_wav(destination, values, sample_rate)

    class Writer:
        def __init__(self) -> None:
            self.blocks = []

        def write(self, block, **_kwargs) -> None:  # noqa: ANN001
            self.blocks.append(np.asarray(block))

    writer = Writer()
    session = {
        "models": [{"params": {"auto_high_pitch_guard": False}}],
        "sample_rate": sample_rate,
        "vocal_gain_db": 0.0,
        "instrumental_gain_db": 0.0,
        "directory": str(tmp_path),
        "status": "live",
        "ready_chunks": 0,
        "processed_seconds": 0.0,
        "ready_seconds": 0.0,
        "realtime_factor": None,
        "message": "",
    }
    prepared = {
        "raw": raw,
        "separated": separated,
        "accompaniment": accompaniment,
        "rendered": rendered,
        "captured": values,
        "frames": frames,
        "overlap_frames": 0,
        "length": frames / sample_rate,
        "captured_at": time.monotonic() - 0.2,
    }

    service._render_system_block(
        session,
        Worker(),
        writer,
        prepared,
        time.monotonic(),
        np,
    )

    assert len(writer.blocks) == 1
    assert writer.blocks[0].shape == (frames, 2)
    assert session["ready_chunks"] == 1
    assert session["latency_ms"] >= 150
    assert session["block_ms"] is not None
    assert session["realtime_factor"] is not None
    assert not raw.exists()
    assert not separated.exists()
    assert not accompaniment.exists()

@pytest.mark.parametrize("render_rate", [40000, 44100, 48000])
def test_read_pcm16_fills_the_whole_block_at_every_render_rate(
    tmp_path: Path, render_rate: int
) -> None:
    sample_rate = 44100
    frames = int(sample_rate * 0.5)
    seconds = 0.5
    t = np.arange(int(round(render_rate * seconds))) / render_rate
    values = np.column_stack([0.5 * np.sin(2 * np.pi * 440.0 * t)] * 2)
    source = tmp_path / f"render_{render_rate}.wav"
    _write_test_wav(source, values, render_rate)

    data = RealtimeCoverService._read_pcm16(source, sample_rate, frames)

    assert data.shape == (frames, 2)
    # A 48 kHz render into a 44.1 kHz session used to read only 92% of the
    # block, so the tail became zero padding inside every live block.
    assert float(np.max(np.abs(data[-64:]))) > 0.1
    crossings = np.count_nonzero(np.diff(np.signbit(data[:, 0])))
    assert abs((crossings / 2.0) / seconds - 440.0) < 12.0


def test_system_block_outputs_silence_instead_of_dry_vocal_when_model_collapses(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    sample_rate = 8000
    frames = 160
    loud = np.full((frames, 2), 0.2, dtype=np.float32)
    silent = np.zeros((frames, 2), dtype=np.float32)
    raw = tmp_path / "raw.wav"
    separated = tmp_path / "separated.wav"
    rendered = tmp_path / "rendered.wav"
    for path in (raw, separated):
        _write_test_wav(path, loud, sample_rate)
    _write_test_wav(rendered, silent, sample_rate)

    class Worker:
        def infer(self, _source: Path, destination: Path, **_kwargs) -> None:
            _write_test_wav(destination, silent, sample_rate)

    class Writer:
        def __init__(self) -> None:
            self.blocks = []

        def write(self, block, **_kwargs) -> None:  # noqa: ANN001
            self.blocks.append(np.asarray(block))

    writer = Writer()
    session = {
        "models": [{"params": {"auto_high_pitch_guard": False}}],
        "sample_rate": sample_rate,
        "vocal_gain_db": 0.0,
        "instrumental_gain_db": 0.0,
        "directory": str(tmp_path),
        "status": "live",
        "ready_chunks": 0,
        "processed_seconds": 0.0,
        "ready_seconds": 0.0,
        "realtime_factor": None,
        "message": "",
    }
    prepared = {
        "raw": raw,
        "separated": separated,
        "rendered": rendered,
        "direct": True,
        "captured": loud,
        "frames": frames,
        "overlap_frames": 0,
        "length": frames / sample_rate,
        "captured_at": time.monotonic() - 0.2,
    }

    service._render_system_block(
        session,
        Worker(),
        writer,
        prepared,
        time.monotonic(),
        np,
    )

    assert len(writer.blocks) == 1
    # A collapsed render must not fall back to the dry separated vocal; that
    # would play the untouched original singer through the live output.
    assert float(np.max(np.abs(writer.blocks[0]))) == 0.0
    log_text = (tmp_path / "realtime-system.log").read_text(encoding="utf-8")
    assert "输出静音而不是原唱人声" in log_text

def test_crop_wav_tail_keeps_only_the_newest_samples(tmp_path: Path) -> None:
    source = tmp_path / "block.wav"
    values = np.column_stack([np.arange(1000, dtype=np.float32) / 2000.0] * 2)
    _write_test_wav(source, values, 8000)

    RealtimeCoverService._crop_wav_tail(source, 400)  # noqa: SLF001

    with wave.open(str(source), "rb") as handle:
        assert handle.getnframes() == 400
        data = np.frombuffer(handle.readframes(400), dtype="<i2").astype(np.float32) / 32768.0
    assert abs(float(data.reshape(-1, 2)[0, 0]) - 600 / 2000.0) < 0.001


class _EchoSeparator:
    """Copies its input to both stems so the live-window alignment can be asserted."""

    def __init__(self) -> None:
        self.seen_frames = 0

    def infer(
        self,
        source: Path,
        vocals: Path,
        timeout: float = 0.0,  # noqa: ARG002
        instrumental: str = "",
    ) -> None:
        with wave.open(str(source), "rb") as handle:
            params = handle.getparams()
            payload = handle.readframes(handle.getnframes())
            self.seen_frames = int(handle.getnframes())
        for target in (vocals, Path(instrumental)):
            with wave.open(str(target), "wb") as handle:
                handle.setparams(params)
                handle.writeframes(payload)


def test_prepare_system_block_crops_separator_lookback_to_the_live_window(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    sample_rate = 8000
    block, overlap, context = 400, 40, 800
    keep = overlap + block
    total = context + keep
    captured = np.full((total, 2), 0.1, dtype=np.float32)
    captured[-1, :] = 0.9
    separator = _EchoSeparator()

    prepared = service._prepare_system_block(  # noqa: SLF001
        tmp_path,
        separator,
        captured,
        total,
        0,
        sample_rate,
        output_frames=block,
        overlap_frames=overlap,
        keep_frames=keep,
    )

    assert separator.seen_frames == total
    assert prepared["frames"] == keep
    assert prepared["overlap_frames"] == overlap
    assert prepared["captured"].shape[0] == keep
    assert abs(float(prepared["captured"][-1, 0]) - 0.9) < 1e-6
    for key in ("separated", "accompaniment"):
        with wave.open(str(prepared[key]), "rb") as handle:
            assert handle.getnframes() == keep
