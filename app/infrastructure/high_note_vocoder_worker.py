"""高音声码器补偿：用 F0 条件化神经声码器重建高音区的超高频带。

高音保护的流程是「保共振峰降调 → 模型推理 → 升回原调」。降调让模型能唱出来，
但升回原调只能靠 Praat PSOLA：极高音上 PSOLA 会把谐波结构糊成气声，甚至出现
窄带哨音；模型本身的声码器也不会在它没学过的音高上产生自然谐波。这就是
「高音保护只解决能不能唱，没解决唱得像不像」的部分不足。

本 worker 在已确认的高音区里再合成一次超高频带：

* 音高（F0）取自升调后的模型输出，保证与最终成品同调；
* 频谱包络取自原始干声（分离后的人声），它保留了该音高上的自然谐波与气声细节；
* 声码器优先使用 Snake-HiFiGAN（Snake 激活在高频谐波上更完整），没有对应权重时
  退回随包的 NSF-HiFiGAN；
* 只取交叉频点（默认 6 kHz）以上的频带，按局部响度对齐后按 ``wet`` 比例混回，
  交叉频点以下、以及未确认的高音区完全保持原样。

反例必须可回退：任一区段如果出现电平异常、气声过强或新的窄带高频峰，该区段就
不采纳；全部区段都被拒绝时不写出输出文件，调用方沿用升调结果。

权重查找顺序（任一目录内需要 ``config.json`` + 权重文件）：

    XB_HIGH_NOTE_VOCODER_DIR  →  <数据目录>/models/pretrain/nsf_snake_hifigan
    → <assets>/models/pretrain/nsf_snake_hifigan → <so-vits>/pretrain/nsf_snake_hifigan
    → 同名目录的 snake_hifigan / nsf-snake-hifigan 变体
    → <assets>/models/pretrain/nsf_hifigan（随包 fallback）

架构由 checkpoint 的键自动识别（含 ``snakes.`` / ``snake_post.`` 即为 Snake 版），
因此放入 Snake-HiFiGAN 权重后无需改代码。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_DEFAULT_BAND_HZ = 6000.0
_DEFAULT_WET = 0.75
_DEFAULT_FADE_SECONDS = 0.045
_DEFAULT_REGION_PAD_SECONDS = 0.10
_MIN_REGION_SECONDS = 0.12
_MAX_REGION_SECONDS = 15.0
_MAX_TOTAL_SECONDS = 45.0
_F0_FRAME = 1024
_F0_HOP = 256
_F0_MIN_CLARITY = 0.45


# ---------------------------------------------------------------- 基础读写


class _Attr(dict):
    """同时支持 ``h["key"]`` 与 ``h.key`` 的配置容器（引擎侧用法不一致）。"""

    def __getattr__(self, name: str):  # noqa: ANN401 - 透传任意配置键
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - 只在配置缺键时触发
            raise AttributeError(name) from exc


def _read_audio(path: Path):
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(str(path), always_2d=True, dtype="float64")
    if data.size == 0 or rate <= 0:
        raise RuntimeError(f"音频为空：{path}")
    return np.asarray(data, dtype=np.float64), int(rate)


def _write_audio(path: Path, data, rate: int) -> None:
    import numpy as np
    import soundfile as sf

    values = np.asarray(data, dtype=np.float64)
    if values.ndim == 1:
        values = values[:, None]
    values = np.clip(np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0), -1.0, 1.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), values, int(rate), subtype="PCM_16")


def _resample(data, source_rate: int, target_rate: int):
    if source_rate == target_rate:
        return data
    import librosa
    import numpy as np

    values = np.asarray(data, dtype=np.float32)
    if values.ndim == 1:
        values = values[:, None]
    moved = librosa.resample(
        values.T, orig_sr=int(source_rate), target_sr=int(target_rate), axis=-1
    )
    return np.asarray(moved.T, dtype=np.float64)


def _mono(data):
    import numpy as np

    values = np.asarray(data, dtype=np.float64)
    if values.ndim == 1:
        return values
    return values.mean(axis=1)


def _parse_regions(path: Path | None, duration: float) -> list[tuple[float, float]]:
    if path is None or not Path(path).is_file():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("regions") or []
    regions: list[tuple[float, float]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            start, end = item.get("start"), item.get("end")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            start, end = item[0], item[1]
        else:
            continue
        try:
            left, right = float(start), float(end)
        except (TypeError, ValueError):
            continue
        left, right = max(0.0, left), min(float(duration), right)
        if right > left:
            regions.append((left, right))
    merged: list[tuple[float, float]] = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# ---------------------------------------------------------------- 频带处理


def _band_split(values, rate: int, cutoff: float, *, high: bool):
    """零相位二阶节滤波器分频；采样点太少时退化为直通。"""
    import numpy as np

    audio = np.asarray(values, dtype=np.float64)
    nyquist = max(1.0, rate / 2.0)
    normalized = min(0.99, max(0.001, float(cutoff) / nyquist))
    if audio.size < 64:
        return audio.copy()
    try:
        from scipy.signal import butter, sosfiltfilt

        sos = butter(6, normalized, btype="high" if high else "low", output="sos")
        padlen = min(audio.shape[0] - 1, 3 * (2 * sos.shape[0] + 1))
        if padlen < 1:
            return audio.copy()
        return sosfiltfilt(sos, audio, axis=0, padlen=padlen)
    except (ImportError, ValueError):
        # 没有 scipy 时的兜底：FFT 硬分频，只为保证不中断流程。
        spectrum = np.fft.rfft(audio, axis=0)
        freqs = np.fft.rfftfreq(audio.shape[0], 1.0 / rate)
        mask = freqs >= float(cutoff) if high else freqs < float(cutoff)
        if audio.ndim > 1:
            mask = mask[:, None]
        return np.fft.irfft(spectrum * mask, n=audio.shape[0], axis=0)


def _frame_rms(values, frame: int, hop: int):
    import numpy as np

    audio = np.asarray(values, dtype=np.float64).reshape(-1)
    if audio.size < frame:
        audio = np.pad(audio, (0, frame - audio.size))
    count = 1 + (audio.size - frame) // hop
    index = np.arange(frame)[None, :] + hop * np.arange(count)[:, None]
    frames = audio[index]
    return np.sqrt(np.mean(frames * frames, axis=1))


def _smooth(values, window: int):
    import numpy as np

    audio = np.asarray(values, dtype=np.float64).reshape(-1)
    if audio.size < 3 or window <= 1:
        return audio.copy()
    window = int(min(window, audio.size))
    kernel = np.ones(window, dtype=np.float64) / float(window)
    padded = np.pad(audio, (window // 2, window - 1 - window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: audio.size]


def _gain_curve(reference, synth, frame: int, hop: int):
    """按局部响度对齐的增益曲线，限制在 ±8 dB 内避免抽吸。"""
    import numpy as np

    reference_rms = _frame_rms(reference, frame, hop)
    synth_rms = _frame_rms(synth, frame, hop)
    count = min(reference_rms.size, synth_rms.size)
    if count <= 0:
        return np.ones(1, dtype=np.float64)
    ratio = reference_rms[:count] / np.maximum(synth_rms[:count], 1e-9)
    ratio = np.clip(ratio, 0.40, 2.50)
    ratio = _smooth(_smooth(ratio, 5), 5)
    return ratio


def _spread(curve, length: int):
    import numpy as np

    values = np.asarray(curve, dtype=np.float64).reshape(-1)
    if values.size == 0 or length <= 0:
        return np.ones(max(0, length), dtype=np.float64)
    if values.size == 1 or length == 1:
        return np.full(length, float(np.median(values)), dtype=np.float64)
    source_axis = np.linspace(0.0, 1.0, values.size)
    target_axis = np.linspace(0.0, 1.0, length)
    return np.interp(target_axis, source_axis, values)


def _band_metrics(values, rate: int, cutoff: float) -> dict[str, float]:
    """超高频带的电平、谱平坦度与窄带突出度（用于验收）。

    ``prominence`` 是「最强频点 / 邻域平均」的比值，而不是「最强频点 / 带内中位数」：
    干净的谐波列每个峰相对邻域只高几倍，真正的 PSOLA 哨音是孤立窄峰，会高出十几倍。
    用邻域比值才能区分「更清晰」和「更尖锐」。
    """
    import numpy as np

    audio = np.asarray(values, dtype=np.float64).reshape(-1)
    if audio.size < 256:
        return {"rms": 0.0, "flatness": 1.0, "prominence": 1.0}
    rms = float(np.sqrt(np.mean(audio * audio)))
    try:
        from scipy.signal import welch

        segment = min(1024, max(256, audio.size // 2))
        freqs, power = welch(audio, fs=rate, nperseg=segment)
    except (ImportError, ValueError):
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size))) ** 2
        freqs = np.fft.rfftfreq(audio.size, 1.0 / rate)
        power = spectrum
    band = (freqs >= float(cutoff)) & (freqs <= rate / 2.0)
    band_power = np.asarray(power[band], dtype=np.float64)
    band_power = np.where(np.isfinite(band_power) & (band_power > 0.0), band_power, 0.0)
    if band_power.size < 12:
        return {"rms": rms, "flatness": 1.0, "prominence": 1.0, "peak_count": 0}
    positive = band_power[band_power > 0.0]
    flatness = 1.0
    if positive.size >= 8:
        flatness = float(
            np.exp(np.mean(np.log(positive))) / max(np.mean(positive), 1e-30)
        )
    window = int(max(3, min(band_power.size // 4, band_power.size // 12)))
    kernel = np.ones(window, dtype=np.float64) / float(window)
    neighborhood = np.maximum(np.convolve(band_power, kernel, mode="same"), 1e-30)
    prominence = float(np.max(band_power / neighborhood))
    # 统计突出于邻域的谱峰个数：谐波列有很多个峰，PSOLA 哨音通常只有一两个。
    local_max = np.zeros(band_power.size, dtype=bool)
    if band_power.size >= 3:
        local_max[1:-1] = (
            (band_power[1:-1] > band_power[:-2]) & (band_power[1:-1] >= band_power[2:])
        )
    peak_count = int(
        np.count_nonzero(local_max & (band_power > neighborhood * 1.5))
    )
    return {
        "rms": rms,
        "flatness": min(1.0, flatness),
        "prominence": prominence,
        "peak_count": peak_count,
    }


# ---------------------------------------------------------------- 音高与 mel


def _estimate_f0(mono, rate: int, *, fmin: float, fmax: float):
    """归一化自相关基频探针，返回 (逐帧 F0, 逐帧清晰度)。"""
    import numpy as np

    audio = np.asarray(mono, dtype=np.float64)
    if audio.size < _F0_FRAME:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)
    frame, hop = _F0_FRAME, _F0_HOP
    count = 1 + (audio.size - frame) // hop
    index = np.arange(frame)[None, :] + hop * np.arange(count)[:, None]
    frames = audio[index]
    frames = frames - frames.mean(axis=1, keepdims=True)
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    peak = float(np.max(energy)) if energy.size else 0.0
    usable = energy >= max(1e-6, peak * 0.03)
    min_lag = max(2, int(round(rate / max(60.0, float(fmax)))))
    max_lag = min(frame - 2, int(round(rate / max(50.0, float(fmin)))))
    if max_lag <= min_lag + 2:
        return np.zeros(count, dtype=np.float64), np.zeros(count, dtype=np.float64)
    window = np.hanning(frame)
    spectra = np.fft.rfft(frames * window, n=2 * frame, axis=1)
    correlation = np.fft.irfft(spectra * np.conj(spectra), axis=1)
    baseline = np.maximum(correlation[:, :1], 1e-12)
    normalized = correlation / baseline
    lags = np.arange(min_lag, max_lag + 1)
    band = normalized[:, lags]
    best = np.argmax(band, axis=1)
    clarity = band[np.arange(count), best]
    f0 = np.zeros(count, dtype=np.float64)
    voiced = usable & (clarity >= 0.30)
    f0[voiced] = rate / lags[best[voiced]].astype(np.float64)
    f0[(f0 < float(fmin)) | (f0 > float(fmax))] = 0.0
    return f0, np.clip(clarity, 0.0, 1.0)


def _pick_f0(
    primary,
    primary_clarity,
    secondary,
    secondary_clarity,
    *,
    fmin: float,
    fmax: float,
):
    """优先用成品调性，缺失帧用干声兜底；越界帧按八度修正。"""
    import numpy as np

    target = np.asarray(primary, dtype=np.float64).copy()
    clarity = np.asarray(primary_clarity, dtype=np.float64)
    fallback = np.asarray(secondary, dtype=np.float64)
    fallback_clarity = np.asarray(secondary_clarity, dtype=np.float64)
    if target.size == 0:
        target = fallback.copy()
        clarity = fallback_clarity.copy()
    else:
        if fallback.size == target.size:
            missing = (target <= 0.0) | (clarity < _F0_MIN_CLARITY)
            target[missing] = fallback[missing]
            clarity[missing] = fallback_clarity[missing]
    low = max(40.0, float(fmin) * 0.75)
    high = min(6000.0, max(low * 2.0, float(fmax)))
    for index in range(target.size):
        value = float(target[index])
        if not math.isfinite(value) or value <= 0.0:
            target[index] = 0.0
            continue
        while value < low and value * 2.0 <= high:
            value *= 2.0
        while value > high and value / 2.0 >= low:
            value /= 2.0
        target[index] = value if low <= value <= high else 0.0
    return target, clarity


def _hold_unvoiced(f0, clarity):
    """清音帧沿用邻近浊音音高，避免声码器在区内断裂。"""
    import numpy as np

    values = np.asarray(f0, dtype=np.float64).copy()
    strengths = np.asarray(clarity, dtype=np.float64)
    if values.size == 0:
        return values
    voiced = np.flatnonzero((values > 0.0) & (strengths >= _F0_MIN_CLARITY))
    if voiced.size == 0:
        return values
    filled = values.copy()
    for index in range(filled.size):
        if filled[index] > 0.0:
            continue
        nearest = voiced[np.argmin(np.abs(voiced - index))]
        filled[index] = values[nearest]
    return filled


# ---------------------------------------------------------------- 声码器


def _find_weight_files(weights_dir: Path) -> tuple[Path, Path]:
    config_path = weights_dir / "config.json"
    if not config_path.is_file():
        raise RuntimeError(f"声码器配置缺失：{config_path}")
    candidates: list[Path] = []
    plain = weights_dir / "model"
    if plain.is_file():
        candidates.append(plain)
    for pattern in ("*.pth", "*.pt", "*.ckpt"):
        candidates.extend(sorted(weights_dir.glob(pattern)))
    if not candidates:
        raise RuntimeError(f"声码器权重缺失：{weights_dir}")
    candidates.sort(key=lambda item: item.stat().st_size, reverse=True)
    return config_path, candidates[0]


def _generator_hparams(config: dict) -> _Attr:
    hps = dict(config)
    mel_bins = int(
        hps.get("inter_channels")
        or hps.get("num_mels")
        or hps.get("n_mels")
        or 0
    )
    if mel_bins <= 0:
        raise RuntimeError("声码器配置缺少 num_mels / inter_channels")
    hps["inter_channels"] = mel_bins
    hps["gin_channels"] = int(hps.get("gin_channels") or 0)
    for key, default in (
        ("n_fft", 2048),
        ("win_size", 2048),
        ("hop_size", 512),
        ("fmin", 40.0),
        ("fmax", 16000.0),
        ("sampling_rate", 44100),
    ):
        hps.setdefault(key, default)
    return _Attr(hps)


def _import_generator_class(snake: bool, repos: list[Path]):
    """按需把引擎仓库放进 sys.path，再导入对应的 Generator 实现。"""
    roots = [str(path) for path in repos if path and Path(path).is_dir()]
    for root in reversed(roots):
        if root not in sys.path:
            sys.path.insert(0, root)
    if snake:
        from vdecoder.hifiganwithsnake.models import Generator  # type: ignore
    else:
        try:
            from vdecoder.hifigan.models import Generator  # type: ignore
        except ImportError:  # DDSP 随包的 NSF-HiFiGAN 实现
            from nsf_hifigan.models import Generator  # type: ignore
    return Generator


def _looks_snake(state_dict) -> bool:
    for key in state_dict:
        name = str(key)
        if name.startswith("snakes.") or name.startswith("snake_post."):
            return True
    return False


def load_generator(weights_dir: Path, repos: list[Path], device: str):
    """加载 F0 条件化声码器，返回 (generator, architecture, hparams, weights)。"""
    import torch

    config_path, weights_path = _find_weight_files(Path(weights_dir))
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"声码器配置无法解析：{config_path}（{exc}）") from exc
    if not isinstance(config, dict):
        raise RuntimeError(f"声码器配置格式异常：{config_path}")

    checkpoint = torch.load(str(weights_path), map_location="cpu", weights_only=False)
    state = checkpoint
    if isinstance(checkpoint, dict):
        for key in ("generator", "model", "state_dict"):
            nested = checkpoint.get(key)
            if isinstance(nested, dict) and nested:
                state = nested
                break
    if not isinstance(state, dict) or not state:
        raise RuntimeError(f"声码器权重格式异常：{weights_path}")

    architecture = "snake-hifigan" if _looks_snake(state) else "nsf-hifigan"
    hps = _generator_hparams(config)
    generator_class = _import_generator_class(architecture == "snake-hifigan", repos)
    generator = generator_class(hps)
    missing, unexpected = generator.load_state_dict(state, strict=False)
    # 说话人条件（cond.*）由 so-vits 的 Generator 声明，但随包/pc 权重没有 spk
    # 嵌入。本 worker 不做说话人混合，缺这两项是预期结果，不视为权重不匹配。
    missing = [name for name in missing if not str(name).startswith("cond.")]
    unexpected = [name for name in unexpected if not str(name).startswith("cond.")]
    if missing:
        raise RuntimeError(f"声码器权重不匹配，缺少 {len(missing)} 项（例如 {missing[0]}）")
    if unexpected:
        raise RuntimeError(
            f"声码器权重与架构不符，多出 {len(unexpected)} 项（例如 {unexpected[0]}）"
        )
    torch_device = torch.device(device)
    if torch_device.type == "cuda" and not torch.cuda.is_available():
        torch_device = torch.device("cpu")
    generator.eval()
    generator.to(torch_device)
    if hasattr(generator, "remove_weight_norm"):
        try:
            generator.remove_weight_norm()
        except Exception:  # noqa: BLE001 - 已移除或架构不支持时忽略
            pass
    return generator, architecture, hps, weights_path


def _forward(generator, mel, f0, *, snake: bool):
    """与上游 Generator.forward 等价，但不注入说话人条件（本工具无 spk 嵌入）。"""
    import torch
    import torch.nn.functional as F

    f0 = generator.f0_upsamp(f0[:, None]).transpose(1, 2)
    harmonic_source, _noise, _uv = generator.m_source(f0, generator.upp)
    harmonic_source = harmonic_source.transpose(1, 2)
    x = generator.conv_pre(mel)
    for index in range(generator.num_upsamples):
        if snake:
            x = generator.snakes[index](x)
        else:
            x = F.leaky_relu(x, 0.1)
        x = generator.ups[index](x)
        x = x + generator.noise_convs[index](harmonic_source)
        stacked = None
        for kernel in range(generator.num_kernels):
            block = generator.resblocks[index * generator.num_kernels + kernel](x)
            stacked = block if stacked is None else stacked + block
        x = stacked / generator.num_kernels
    if snake:
        x = generator.snake_post(x)
    else:
        x = F.leaky_relu(x, 0.1)
    x = generator.conv_post(x)
    return torch.tanh(x)


def _mel_basis(rate: int, hps: _Attr):
    import torch

    key = (rate, int(hps.n_fft), int(hps.inter_channels), float(hps.fmin), float(hps.fmax))
    cached = _mel_basis.cache.get(key)  # type: ignore[attr-defined]
    if cached is not None:
        return cached
    import librosa

    basis = librosa.filters.mel(
        sr=int(rate),
        n_fft=int(hps.n_fft),
        n_mels=int(hps.inter_channels),
        fmin=float(hps.fmin),
        fmax=float(hps.fmax),
    )
    tensor = torch.from_numpy(basis).float()
    _mel_basis.cache[key] = tensor  # type: ignore[attr-defined]
    return tensor


_mel_basis.cache = {}  # type: ignore[attr-defined]


def synthesize(generator, hps: _Attr, mono, rate: int, f0_frames, device: str):
    """mel（来自干声包络）+ F0 → 波形；返回与输入等长的 float32 数组。"""
    import numpy as np
    import torch

    audio = np.asarray(mono, dtype=np.float32).reshape(-1)
    if audio.size < 64:
        return np.zeros_like(audio)
    n_fft = int(hps.n_fft)
    hop = int(hps.hop_size)
    win = int(hps.win_size)
    window = torch.hann_window(win, device=device)
    signal = torch.from_numpy(audio).float().to(device)[None, :]
    spectrum = torch.stft(
        signal,
        n_fft=n_fft,
        hop_length=hop,
        win_length=win,
        window=window,
        center=True,
        return_complex=True,
    ).abs()
    basis = _mel_basis(rate, hps).to(device)
    mel = torch.log(torch.clamp(basis @ spectrum, min=1e-5))
    frames = mel.shape[-1]
    curve = np.asarray(f0_frames, dtype=np.float64).reshape(-1)
    if curve.size == 0:
        return np.zeros_like(audio)
    if curve.size != frames:
        source_axis = np.linspace(0.0, 1.0, curve.size)
        curve = np.interp(np.linspace(0.0, 1.0, frames), source_axis, curve)
    f0_tensor = torch.from_numpy(curve.astype(np.float32)).to(device)[None, :]
    with torch.no_grad():
        wav = _forward(generator, mel, f0_tensor, snake=hps.get("_snake", False))
    output = wav[0, 0].detach().float().cpu().numpy()
    if output.size == audio.size:
        return output
    if output.size > audio.size:
        return output[: audio.size]
    padded = np.zeros(audio.size, dtype=np.float32)
    padded[: output.size] = output
    return padded


# ---------------------------------------------------------------- 主流程


def _region_result(
    start: float,
    end: float,
    status: str,
    *,
    reason: str = "",
    **extra,
) -> dict:
    payload = {
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "status": status,
    }
    if reason:
        payload["reason"] = reason
    payload.update(extra)
    return payload


def _accept_region(reference_high, synth_high, rate: int, cutoff: float) -> tuple[bool, str, dict]:
    import numpy as np

    reference = _band_metrics(reference_high, rate, cutoff)
    synth = _band_metrics(synth_high, rate, cutoff)
    if reference["rms"] <= 1.0e-5:
        return False, "原高频近似静音", {"reference": reference, "synth": synth}
    if synth["rms"] <= 1.0e-7:
        return False, "声码器未产生高频", {"reference": reference, "synth": synth}
    delta_db = 20.0 * float(
        np.log10(max(synth["rms"], 1e-12) / max(reference["rms"], 1e-12))
    )
    if delta_db < -12.0 or delta_db > 12.0:
        return False, f"电平差异 {delta_db:.1f}dB 超出范围", {
            "reference": reference,
            "synth": synth,
            "level_delta_db": round(delta_db, 2),
        }
    if synth["flatness"] > max(0.55, reference["flatness"] * 1.35):
        return False, "高频气声过强", {
            "reference": reference,
            "synth": synth,
            "level_delta_db": round(delta_db, 2),
        }
    # 窄带哨音：单个孤立峰远高于邻域，而高频谐波列虽然峰很尖但数量多。
    # 只有「突出且峰数很少」才拒绝，避免把更清晰的谐波误判成哨音。
    peak_limit = max(reference["prominence"] * 2.0, 12.0)
    if synth["prominence"] > peak_limit and synth["peak_count"] < 4:
        return False, "出现新的窄带高频峰", {
            "reference": reference,
            "synth": synth,
            "level_delta_db": round(delta_db, 2),
        }
    return True, "ok", {
        "reference": reference,
        "synth": synth,
        "level_delta_db": round(delta_db, 2),
    }


def refine(
    *,
    rendered: Path,
    dry: Path | None,
    regions: list[tuple[float, float]],
    output: Path,
    band_hz: float = _DEFAULT_BAND_HZ,
    wet: float = _DEFAULT_WET,
    min_f0: float = 300.0,
    max_f0: float = 2400.0,
    weights_dir: Path | None = None,
    repos: list[Path] | None = None,
    device: str = "cpu",
    region_pad: float = _DEFAULT_REGION_PAD_SECONDS,
) -> dict:
    import numpy as np

    report: dict = {
        "applied": False,
        "reason": "",
        "band_hz": round(float(band_hz), 1),
        "wet": round(float(wet), 3),
        "device": device,
        "architecture": "",
        "weights": "",
        "region_count": 0,
        "applied_seconds": 0.0,
        "regions": [],
    }
    if not regions:
        report["reason"] = "没有需要补偿的高音区"
        return report
    if weights_dir is None:
        report["reason"] = "未找到声码器权重"
        return report

    rendered_audio, rendered_rate = _read_audio(Path(rendered))
    duration = rendered_audio.shape[0] / float(rendered_rate)
    dry_audio = None
    if dry is not None and Path(dry).is_file():
        try:
            dry_raw, dry_rate = _read_audio(Path(dry))
            dry_audio = _resample(dry_raw, dry_rate, rendered_rate)
            tolerance = max(int(rendered_rate * 0.05), int(rendered_audio.shape[0] * 0.02))
            if abs(dry_audio.shape[0] - rendered_audio.shape[0]) > tolerance:
                dry_audio = None
                report["dry_alignment"] = "干声与成品时长不一致，已忽略包络来源"
            else:
                report["dry_alignment"] = "ok"
        except (OSError, RuntimeError) as exc:
            dry_audio = None
            report["dry_alignment"] = f"干声读取失败：{exc}"

    scoped: list[tuple[float, float]] = []
    total = 0.0
    for start, end in regions:
        left = max(0.0, float(start) - float(region_pad))
        right = min(duration, float(end) + float(region_pad))
        if right - left < _MIN_REGION_SECONDS:
            report["regions"].append(
                _region_result(start, end, "skipped", reason="区段过短")
            )
            continue
        if right - left > _MAX_REGION_SECONDS:
            right = left + _MAX_REGION_SECONDS
        if total + (right - left) > _MAX_TOTAL_SECONDS:
            report["regions"].append(
                _region_result(start, end, "skipped", reason="超出单次补偿总时长预算")
            )
            continue
        total += right - left
        scoped.append((left, right))

    if not scoped:
        report["reason"] = "没有可处理的区段"
        return report

    generator, architecture, hps, weights_path = load_generator(
        Path(weights_dir), list(repos or []), device
    )
    hps["_snake"] = architecture == "snake-hifigan"
    report["architecture"] = architecture
    report["weights"] = str(weights_path)

    rate = rendered_rate
    mono_rendered = _mono(rendered_audio)
    mixed = rendered_audio.copy()
    applied_seconds = 0.0
    fade = max(1, int(round(rate * _DEFAULT_FADE_SECONDS)))
    frame_window = max(1, fade * 2)

    for left, right in scoped:
        begin = int(round(left * rate))
        finish = min(int(round(right * rate)), rendered_audio.shape[0])
        if finish - begin < max(64, fade):
            report["regions"].append(
                _region_result(left, right, "skipped", reason="采样点不足")
            )
            continue
        reference_segment = mono_rendered[begin:finish]
        dry_segment = (
            _mono(dry_audio[begin:finish]) if dry_audio is not None else reference_segment
        )
        reference_f0, reference_clarity = _estimate_f0(
            reference_segment, rate, fmin=min_f0, fmax=max_f0
        )
        dry_f0, dry_clarity = _estimate_f0(
            dry_segment, rate, fmin=min_f0, fmax=max_f0
        )
        f0_curve, _clarity = _pick_f0(
            reference_f0,
            reference_clarity,
            dry_f0,
            dry_clarity,
            fmin=min_f0,
            fmax=max_f0,
        )
        voiced_ratio = float(np.mean(f0_curve > 0.0)) if f0_curve.size else 0.0
        if voiced_ratio < 0.15:
            report["regions"].append(
                _region_result(
                    left,
                    right,
                    "skipped",
                    reason="区段内没有稳定浊音音高",
                    voiced_ratio=round(voiced_ratio, 3),
                )
            )
            continue
        f0_curve = _hold_unvoiced(f0_curve, _clarity)
        mel_source = dry_segment if np.any(dry_segment != 0.0) else reference_segment
        synth = synthesize(generator, hps, mel_source, rate, f0_curve, device)
        synth = np.asarray(synth, dtype=np.float64).reshape(-1)
        if synth.size < reference_segment.size:
            synth = np.pad(synth, (0, reference_segment.size - synth.size))
        synth = synth[: reference_segment.size]

        reference_high = _band_split(
            reference_segment, rate, float(band_hz), high=True
        )
        synth_high = _band_split(synth, rate, float(band_hz), high=True)
        accepted, reason, metrics = _accept_region(
            reference_high, synth_high, rate, float(band_hz)
        )
        median_f0 = float(np.median(f0_curve[f0_curve > 0.0])) if voiced_ratio else 0.0
        if not accepted:
            report["regions"].append(
                _region_result(
                    left,
                    right,
                    "rejected",
                    reason=reason,
                    f0_hz=round(median_f0, 1),
                    **metrics,
                )
            )
            continue

        low = _band_split(rendered_audio[begin:finish], rate, float(band_hz), high=False)
        reference_band = _band_split(
            rendered_audio[begin:finish], rate, float(band_hz), high=True
        )
        gain = _spread(
            _gain_curve(reference_segment, synth, _F0_FRAME, _F0_HOP),
            reference_segment.size,
        )
        blended = low + (1.0 - float(wet)) * reference_band + float(wet) * (
            gain[:, None] * synth_high[:, None]
        )
        # 区段两端淡入淡出，避免与未处理部分产生接缝。
        if blended.shape[0] > frame_window:
            ramp = np.sin(np.linspace(0.0, np.pi / 2.0, frame_window)) ** 2
            blended[:frame_window] = (
                rendered_audio[begin : begin + frame_window] * (1.0 - ramp[:, None])
                + blended[:frame_window] * ramp[:, None]
            )
            blended[-frame_window:] = (
                blended[-frame_window:] * ramp[::-1, None]
                + rendered_audio[finish - frame_window : finish]
                * (1.0 - ramp[::-1, None])
            )
        mixed[begin:finish] = blended
        applied_seconds += reference_segment.size / float(rate)
        report["regions"].append(
            _region_result(
                left,
                right,
                "applied",
                f0_hz=round(median_f0, 1),
                voiced_ratio=round(voiced_ratio, 3),
                **metrics,
            )
        )

    report["region_count"] = len(scoped)
    report["applied_seconds"] = round(applied_seconds, 3)
    applied = [item for item in report["regions"] if item["status"] == "applied"]
    if not applied:
        report["reason"] = "所有区段均未通过验收，保留升调结果"
        return report

    peak_before = float(np.max(np.abs(rendered_audio))) if rendered_audio.size else 0.0
    peak_after = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    ceiling = max(0.995, peak_before * 1.02)
    if peak_after > ceiling:
        mixed = mixed * (ceiling / max(peak_after, 1e-9))
        report["peak_limited"] = round(peak_after, 3)
    _write_audio(Path(output), mixed, rate)
    _validate_render(Path(rendered), Path(output))
    report["applied"] = True
    return report


def _validate_render(source: Path, destination: Path) -> None:
    """输出必须与升调结果等长、等声道、等采样率，且不能被削顶成静音。"""
    import numpy as np

    if not destination.is_file() or destination.stat().st_size <= 44:
        raise RuntimeError("输出文件为空")
    source_audio, source_rate = _read_audio(source)
    output_audio, output_rate = _read_audio(destination)
    if source_rate != output_rate:
        raise RuntimeError("采样率发生变化")
    if source_audio.shape[1] != output_audio.shape[1]:
        raise RuntimeError("声道数发生变化")
    limit = max(int(round(source_rate * 0.02)), 64)
    if abs(output_audio.shape[0] - source_audio.shape[0]) > limit:
        raise RuntimeError("输出时长异常")
    if not np.isfinite(output_audio).all():
        raise RuntimeError("输出包含非法数值")
    source_rms = float(np.sqrt(np.mean(np.square(source_audio))))
    output_rms = float(np.sqrt(np.mean(np.square(output_audio))))
    if source_rms > 1.0e-4 and output_rms < source_rms * 0.5:
        raise RuntimeError("输出能量异常衰减")


def _default_repos() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    engines = root / "engines"
    return [engines / "so-vits-svc", engines / "ddsp-svc"]


def main() -> int:
    parser = argparse.ArgumentParser(description="高音声码器超高频带补偿")
    parser.add_argument("--input", required=True, help="升回原调后的模型输出")
    parser.add_argument("--output", required=True, help="补偿后的输出（需已有目录）")
    parser.add_argument("--dry-source", default="", help="原始干声，提供高频包络")
    parser.add_argument("--regions-json", default="", help="需要补偿的高音区 JSON")
    parser.add_argument("--report-json", default="", help="处理报告 JSON")
    parser.add_argument("--weights-dir", default="", help="声码器权重目录")
    parser.add_argument("--band-hz", type=float, default=_DEFAULT_BAND_HZ)
    parser.add_argument("--wet", type=float, default=_DEFAULT_WET)
    parser.add_argument("--min-f0", type=float, default=300.0)
    parser.add_argument("--max-f0", type=float, default=2400.0)
    parser.add_argument("--region-pad", type=float, default=_DEFAULT_REGION_PAD_SECONDS)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--repo", action="append", default=[], help="引擎仓库根目录，可重复")
    args = parser.parse_args()

    rendered = Path(args.input)
    output = Path(args.output)
    report_path = Path(args.report_json) if args.report_json else None
    repo_paths = [Path(item) for item in args.repo if item] or _default_repos()
    weights_dir = Path(args.weights_dir) if args.weights_dir else None
    report: dict = {"applied": False, "reason": "未执行", "regions": []}
    try:
        if not rendered.is_file():
            raise RuntimeError(f"输入文件不存在：{rendered}")
        audio, rate = _read_audio(rendered)
        duration = audio.shape[0] / float(rate)
        regions = _parse_regions(
            Path(args.regions_json) if args.regions_json else None, duration
        )
        report = refine(
            rendered=rendered,
            dry=Path(args.dry_source) if args.dry_source else None,
            regions=regions,
            output=output,
            band_hz=float(args.band_hz),
            wet=float(args.wet),
            min_f0=float(args.min_f0),
            max_f0=float(args.max_f0),
            weights_dir=weights_dir,
            repos=repo_paths,
            device=args.device,
            region_pad=float(args.region_pad),
        )
    except Exception as exc:  # noqa: BLE001 - 结果以报告返回，调用方必须能回退
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        report = {
            "applied": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "regions": report.get("regions") or [],
        }
        print(f"HIGH_NOTE_VOCODER_ERR\t{exc}", flush=True)

    if report_path is not None:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"HIGH_NOTE_VOCODER_WARN\t报告写入失败: {exc}", flush=True)

    applied = report.get("regions") or []
    applied_count = sum(1 for item in applied if item.get("status") == "applied")
    print(
        "HIGH_NOTE_VOCODER\t"
        f"{'ok' if report.get('applied') else 'skip'}\t"
        f"{report.get('architecture') or '-'}\t"
        f"{applied_count}/{len(applied)}\t"
        f"{report.get('applied_seconds') or 0.0}s\t"
        f"{report.get('reason') or ''}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
