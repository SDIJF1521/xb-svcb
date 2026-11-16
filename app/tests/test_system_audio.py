from __future__ import annotations

import numpy as np

from infrastructure import system_audio
from infrastructure.system_audio import (
    SystemAudioWriter,
    list_devices,
    paired_playback_name,
)


class FakePlayer:
    def __init__(self) -> None:
        self.blocks: list[np.ndarray] = []

    def play(self, audio) -> None:  # noqa: ANN001
        self.blocks.append(np.asarray(audio, dtype=np.float32).copy())


class FakeSpeaker:
    def __init__(self, name: str) -> None:
        self.name = name

    def player(self, **_kwargs):  # noqa: ANN003, ANN201
        return FakePlayer()


class FakeMicrophone:
    def __init__(self, name: str, loopback: bool = False) -> None:
        self.name = name
        self.isloopback = loopback


class FakeSoundcard:
    def all_microphones(self, include_loopback: bool = True):  # noqa: ANN201, ARG002
        return [
            FakeMicrophone("CABLE Output (VB-Audio Virtual Cable)"),
            FakeMicrophone("麦克风阵列 (Realtek(R) Audio)"),
        ]

    def all_speakers(self):  # noqa: ANN201
        return [
            FakeSpeaker("CABLE Input (VB-Audio Virtual Cable)"),
            FakeSpeaker("扬声器 (Realtek(R) Audio)"),
        ]


def test_virtual_cable_capture_is_exposed_as_output() -> None:
    original = system_audio._soundcard  # noqa: SLF001
    system_audio._soundcard = lambda: FakeSoundcard()  # type: ignore[assignment]  # noqa: SLF001
    try:
        devices = list_devices()
    finally:
        system_audio._soundcard = original  # type: ignore[assignment]  # noqa: SLF001

    virtual = [
        item for item in devices
        if item["kind"] == "output" and item.get("virtual_capture")
    ]
    assert len(virtual) == 1
    assert virtual[0]["id"] == "CABLE Output (VB-Audio Virtual Cable)"
    assert "CABLE Input" in virtual[0]["name"]


def test_virtual_cable_output_writer_resolves_playback_endpoint() -> None:
    original = system_audio._soundcard  # noqa: SLF001
    system_audio._soundcard = lambda: FakeSoundcard()  # type: ignore[assignment]  # noqa: SLF001
    try:
        writer = SystemAudioWriter(
            "CABLE Output (VB-Audio Virtual Cable)",
            44100,
            2,
        )
    finally:
        system_audio._soundcard = original  # type: ignore[assignment]  # noqa: SLF001

    assert writer.resolved_device_name == "CABLE Input (VB-Audio Virtual Cable)"
    assert isinstance(writer._player, FakePlayer)  # noqa: SLF001


def test_paired_playback_name_swaps_cable_roles() -> None:
    speakers = [
        "CABLE Input (VB-Audio Virtual Cable)",
        "CABLE In 16ch (VB-Audio Virtual Cable)",
        "扬声器 (Realtek(R) Audio)",
    ]
    assert (
        paired_playback_name("CABLE Output (VB-Audio Virtual Cable)", speakers)
        == "CABLE Input (VB-Audio Virtual Cable)"
    )
    assert (
        paired_playback_name("CABLE Out 16ch (VB-Audio Virtual Cable)", speakers)
        == "CABLE In 16ch (VB-Audio Virtual Cable)"
    )
    assert paired_playback_name("麦克风阵列 (Realtek(R) Audio)", speakers) is None


def test_writer_crossfades_repeated_context_without_shortening_stream() -> None:
    writer = SystemAudioWriter.__new__(SystemAudioWriter)
    writer._player = FakePlayer()  # type: ignore[attr-defined]  # noqa: SLF001
    writer._crossfade_frames = 3  # type: ignore[attr-defined]  # noqa: SLF001
    writer._pending_tail = None  # type: ignore[attr-defined]  # noqa: SLF001

    first = np.asarray([[0.0], [0.1], [0.2], [0.3], [0.4], [0.5]], dtype=np.float32)
    # The first three samples repeat the same source interval as first[-3:].
    second = np.asarray(
        [[0.35], [0.45], [0.55], [0.6], [0.7], [0.8], [0.9], [1.0], [0.9]],
        dtype=np.float32,
    )

    writer._play_stitched(first, 0)  # type: ignore[attr-defined]  # noqa: SLF001
    writer._play_stitched(second, 3)  # type: ignore[attr-defined]  # noqa: SLF001
    writer._flush_tail()  # type: ignore[attr-defined]  # noqa: SLF001

    rendered = np.concatenate(writer._player.blocks, axis=0)  # type: ignore[attr-defined]  # noqa: SLF001
    assert rendered.shape == (12, 1)
    assert np.allclose(rendered[:3], first[:3])
    # Equal-power endpoints select the old tail first and the repeated new
    # context last, with both contributing to the middle sample.
    assert rendered[3, 0] == first[3, 0]
    assert rendered[5, 0] == second[2, 0]
    assert first[4, 0] < rendered[4, 0] < first[4, 0] + second[1, 0]
    assert np.allclose(rendered[6:], second[3:])


def test_writer_flushes_first_block_tail_on_shutdown() -> None:
    writer = SystemAudioWriter.__new__(SystemAudioWriter)
    writer._player = FakePlayer()  # type: ignore[attr-defined]  # noqa: SLF001
    writer._crossfade_frames = 2  # type: ignore[attr-defined]  # noqa: SLF001
    writer._pending_tail = None  # type: ignore[attr-defined]  # noqa: SLF001
    block = np.arange(6, dtype=np.float32).reshape(-1, 1)

    writer._play_stitched(block, 0)  # type: ignore[attr-defined]  # noqa: SLF001
    writer._flush_tail()  # type: ignore[attr-defined]  # noqa: SLF001

    rendered = np.concatenate(writer._player.blocks, axis=0)  # type: ignore[attr-defined]  # noqa: SLF001
    assert np.array_equal(rendered, block)


def test_writer_flushes_tail_before_discontinuous_block() -> None:
    writer = SystemAudioWriter.__new__(SystemAudioWriter)
    writer._player = FakePlayer()  # type: ignore[attr-defined]  # noqa: SLF001
    writer._crossfade_frames = 2  # type: ignore[attr-defined]  # noqa: SLF001
    writer._pending_tail = None  # type: ignore[attr-defined]  # noqa: SLF001
    first = np.arange(6, dtype=np.float32).reshape(-1, 1)
    second = np.arange(6, 12, dtype=np.float32).reshape(-1, 1)

    writer._play_stitched(first, 0)  # type: ignore[attr-defined]  # noqa: SLF001
    writer._play_stitched(second, 2, discontinuity=True)  # type: ignore[attr-defined]  # noqa: SLF001
    writer._flush_tail()  # type: ignore[attr-defined]  # noqa: SLF001

    rendered = np.concatenate(writer._player.blocks, axis=0)  # type: ignore[attr-defined]  # noqa: SLF001
    # No stale crossfade is applied: the previous tail is flushed, then the
    # whole new block (including its overlap context) is played.
    assert np.array_equal(rendered, np.concatenate((first, second), axis=0))
