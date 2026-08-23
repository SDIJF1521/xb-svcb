"""Windows system-audio capture and output through WASAPI loopback.

The source application is routed to a loopback/virtual-cable endpoint. The
realtime service receives the mixed signal from that one endpoint, separates
the vocal stem, converts it, and writes the reconstructed mix to the output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import queue
import threading
import warnings


@dataclass(frozen=True)
class SystemAudioDevice:
    id: str
    name: str
    kind: str
    loopback: bool = False
    system_mix: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "loopback": self.loopback,
            "system_mix": self.system_mix,
        }


def _is_system_mix_input(name: str, loopback: bool) -> bool:
    """Identify loopback/virtual mix endpoints while excluding microphones."""
    if loopback:
        return True
    normalized = name.casefold()
    microphone_markers = ("microphone", "mic", "麦克风", "麦克风阵列", "headset")
    if any(marker in normalized for marker in microphone_markers):
        return False
    markers = (
        "virtual", "cable", "voicemeeter", "stereo mix", "what u hear",
        "waveout", "loopback", "回环", "立体声混音", "虚拟音频", "虚拟线路",
    )
    return any(marker in normalized for marker in markers)


def _soundcard():
    try:
        import soundcard  # type: ignore[import-not-found]
    except ImportError:
        return None
    return soundcard


def available() -> bool:
    return _soundcard() is not None


def list_devices() -> list[dict[str, Any]]:
    soundcard = _soundcard()
    if soundcard is None:
        return []
    result: list[dict[str, Any]] = []
    try:
        microphones = soundcard.all_microphones(include_loopback=True)
        for item in microphones:
            name = str(getattr(item, "name", "") or "").strip()
            if not name:
                continue
            loopback = bool(getattr(item, "isloopback", False))
            result.append(
                SystemAudioDevice(
                    id=name,
                    name=name,
                    kind="input",
                    loopback=loopback,
                    system_mix=_is_system_mix_input(name, loopback),
                ).public()
            )
        for item in soundcard.all_speakers():
            name = str(getattr(item, "name", "") or "").strip()
            if name:
                result.append(SystemAudioDevice(id=name, name=name, kind="output").public())
    except Exception:  # noqa: BLE001 - device enumeration is best effort
        return []
    return result


class SystemAudioReader:
    """Small blocking reader used by the realtime cover worker."""

    def __init__(self, device_name: str, sample_rate: int, channels: int = 2) -> None:
        soundcard = _soundcard()
        if soundcard is None:
            raise RuntimeError("未安装 Windows 系统音频采集依赖 soundcard")
        microphones = soundcard.all_microphones(include_loopback=True)
        selected = next(
            (item for item in microphones if str(getattr(item, "name", "")) == device_name),
            None,
        )
        if selected is None:
            raise RuntimeError("系统混合音频输入不存在，请选择 QQ 音乐所在的虚拟音频线")
        blocksize = max(1024, round(sample_rate * 0.25))
        self._recorder = selected.recorder(
            samplerate=sample_rate,
            channels=channels,
            blocksize=blocksize,
        )

    def __enter__(self) -> "SystemAudioReader":
        self._recorder.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self._recorder.__exit__(exc_type, exc, tb)

    def read(self, frames: int):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="data discontinuity in recording")
            return self._recorder.record(numframes=frames)


class SystemAudioWriter:
    """Blocking speaker writer for the processed system-audio stream."""

    def __init__(
        self,
        device_name: str,
        sample_rate: int,
        channels: int = 2,
        prebuffer_blocks: int = 0,
        crossfade_frames: int = 0,
    ) -> None:
        soundcard = _soundcard()
        if soundcard is None:
            raise RuntimeError("未安装 Windows 系统音频输出依赖 soundcard")
        speakers = soundcard.all_speakers()
        selected = next(
            (item for item in speakers if str(getattr(item, "name", "")) == device_name),
            None,
        )
        if selected is None:
            raise RuntimeError("系统音频输出设备不存在")
        self._player = selected.player(samplerate=sample_rate, channels=channels)
        self._prebuffer_blocks = max(0, int(prebuffer_blocks))
        self._crossfade_frames = max(0, int(crossfade_frames))
        self._pending_tail: Any | None = None
        self._queue: queue.Queue[Any] | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "SystemAudioWriter":
        self._player.__enter__()
        if self._prebuffer_blocks:
            self._queue = queue.Queue(maxsize=max(4, self._prebuffer_blocks * 4))
            self._thread = threading.Thread(target=self._play_loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._queue is not None:
            self._queue.put(None)
            if self._thread is not None:
                self._thread.join(timeout=15.0)
        else:
            self._flush_tail()
        self._player.__exit__(exc_type, exc, tb)

    def write(self, audio, *, overlap_frames: int = 0) -> None:  # noqa: ANN001
        import numpy as np

        item = (np.asarray(audio, dtype=np.float32).copy(), max(0, int(overlap_frames)))
        if self._queue is None:
            self._play_stitched(*item)
            return
        self._queue.put(item)

    def _play_stitched(self, audio, overlap_frames: int) -> None:  # noqa: ANN001
        """Play one block while crossfading its repeated input context.

        ``audio[:overlap_frames]`` represents the same source time as the
        pending tail from the previous block. Only that duplicated region is
        overlapped, so smoothing a boundary never shortens the stream clock.
        """
        import numpy as np

        block = np.asarray(audio, dtype=np.float32)
        if block.size == 0 or block.shape[0] == 0:
            return
        fade_frames = min(self._crossfade_frames, block.shape[0])
        if fade_frames <= 0:
            self._player.play(block)
            return

        overlap = min(max(0, int(overlap_frames)), block.shape[0])
        unique = block[overlap:]
        pieces: list[Any] = []
        pending = self._pending_tail
        if pending is not None and pending.shape[0]:
            count = min(overlap, pending.shape[0], fade_frames)
            if count:
                if pending.shape[0] > count:
                    pieces.append(pending[:-count])
                phase = np.linspace(0.0, np.pi / 2.0, count, dtype=np.float32)
                shape = (count,) + (1,) * (block.ndim - 1)
                fade_out = np.cos(phase).reshape(shape)
                fade_in = np.sin(phase).reshape(shape)
                pieces.append(pending[-count:] * fade_out + block[:count] * fade_in)
            else:
                pieces.append(pending)

        hold = min(fade_frames, unique.shape[0])
        if unique.shape[0] > hold:
            pieces.append(unique[:-hold])
        self._pending_tail = unique[-hold:].copy() if hold else None
        if pieces:
            self._player.play(np.concatenate(pieces, axis=0))

    def _flush_tail(self) -> None:
        if self._pending_tail is not None and self._pending_tail.shape[0]:
            self._player.play(self._pending_tail)
        self._pending_tail = None

    def _play_loop(self) -> None:
        if self._queue is None:
            return
        buffered: list[Any] = []
        started = False
        while True:
            item = self._queue.get()
            if item is None:
                for pending in buffered:
                    self._play_stitched(*pending)
                while True:
                    try:
                        pending = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if pending is not None:
                        self._play_stitched(*pending)
                self._flush_tail()
                return
            if not started:
                buffered.append(item)
                if len(buffered) < self._prebuffer_blocks:
                    continue
                started = True
                for pending in buffered[:-1]:
                    self._play_stitched(*pending)
                buffered.clear()
            self._play_stitched(*item)
