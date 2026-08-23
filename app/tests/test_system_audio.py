from __future__ import annotations

import numpy as np

from infrastructure.system_audio import SystemAudioWriter


class FakePlayer:
    def __init__(self) -> None:
        self.blocks: list[np.ndarray] = []

    def play(self, audio) -> None:  # noqa: ANN001
        self.blocks.append(np.asarray(audio, dtype=np.float32).copy())


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
