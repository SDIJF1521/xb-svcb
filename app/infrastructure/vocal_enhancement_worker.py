"""独立歌声增强 worker：DeepFilterNet -> Pedalboard（基础层/高级层）。

基础层 Vocal Beauty Engine：DeepFilterNet 温和降噪 + 基础美声 EQ
高级层 Vocal AI Model：DeepFilterNet 温和降噪 + 精细母带 EQ + 胶水压缩
（vocalfloor 软衰减 + 去齿音 + 温暖中低频 + presence + 空气感 + 胶水压缩）

VoiceFixer 已移除——它为修复损坏语音录音设计，对高质量 AI 翻唱会破坏
原始音色与伴奏细节，效果反而变差。

高级层设计原则：advanced 应该是"更精细的 basic"，不是"加更多效果"。
AI 翻唱的"AI 感"主要来自频谱细节平滑化与共振峰偏移，应通过精细 EQ
与温和动态控制来缓解，而不是叠加 Distortion/Chorus/Reverb 等效果——
这些效果会让声音"合成器化"，反而加重 AI 感（v3/v9 失败教训）。

- vocalfloor 软衰减：把停顿段的 vocoder 电子底噪压低到 -75dB，但保留
  150ms 指数渐变过渡，避免硬静音的"切断"感，模拟自然声音的渐弱渐强
- 去齿音：缓解 SVC/RVC 在 5–9kHz 的齿音突刺
- 温暖中低频：补偿 AI 翻唱偏薄的音色
- 人声 Presence：提升 3.5kHz 让声音靠前
- 高频空气感：逆转 AI 翻唱的高频衰减（不削高频）
- 胶水压缩：温和动态控制，保留瞬态
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


def _silence_vocalfloor_file(source: Path, output: Path) -> None:
    """文件级包装：读取源音频，做 vocalfloor 软衰减，写出到 output。

    使用 soundfile 读写（Pedalboard 的依赖，已在 .venv-vocal 中），
    保持原始采样率与声道数。
    """
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile/numpy 未安装，请修复 vocal 增强环境") from exc

    audio, sample_rate = sf.read(str(source), always_2d=True)
    audio = audio.T  # soundfile 返回 (frames, channels)，转为 (channels, frames)
    processed = _silence_vocalfloor(audio, sample_rate)
    if processed.ndim == 1:
        processed = processed[np.newaxis, :]
    sf.write(str(output), processed.T, sample_rate)
    if not output.is_file():
        raise RuntimeError("vocalfloor 软衰减未生成输出文件")


def _match_reference(source: Path, reference: Path, output: Path) -> None:
    """频谱包络匹配：让翻唱声音的长期平均频谱跟随原始人声。

    AI 翻唱的 vocoder 会改变频谱形状（高频衰减/失真、共振峰偏移、频谱细节
    平滑化），这是 AI 感的核心来源。本函数提取原始人声的长期平均功率谱，
    计算与翻唱声音的差异 EQ，应用到翻唱声音上，让频谱形状回归自然。

    算法：
    1. 用 librosa.stft 计算原始人声和翻唱声音的长期平均功率谱
    2. 分 10 个对数分布频段聚合能量（80Hz–16kHz，覆盖人声主要频段）
    3. 每频段计算差异：diff_db = 10 * log10(ref_power / src_power)
    4. 限制差异范围 ±6dB（避免过度修正引入失真）
    5. 用 Pedalboard 多个 PeakFilter 构造匹配 EQ
    6. 应用到翻唱声音（保持原始采样率和声道数）

    注意：用"长期平均"不需要时间对齐，因为这是统计特征匹配。即使原始
    人声和翻唱声音长度不完全一致，也能正确反映频谱形状差异。
    """
    try:
        import numpy as np
        import soundfile as sf
        import librosa
        from pedalboard import PeakFilter, Pedalboard
        from pedalboard.io import AudioFile
    except ImportError as exc:
        raise RuntimeError("librosa/pedalboard 未安装，请修复 vocal 增强环境") from exc

    # 读取翻唱声音（source）和原始人声（reference）
    src_audio, src_sr = sf.read(str(source), always_2d=True)
    ref_audio, ref_sr = sf.read(str(reference), always_2d=True)

    # 转单声道用于频谱分析
    src_mono = src_audio.mean(axis=1)
    ref_mono = ref_audio.mean(axis=1)

    # 如果采样率不同，用翻唱声音的采样率作为基准，重采样 reference
    if ref_sr != src_sr:
        ref_mono = librosa.resample(ref_mono, orig_sr=ref_sr, target_sr=src_sr)

    # 计算长期平均功率谱（STFT）
    n_fft = 4096
    hop = 1024
    src_stft = np.abs(librosa.stft(src_mono, n_fft=n_fft, hop_length=hop))
    ref_stft = np.abs(librosa.stft(ref_mono, n_fft=n_fft, hop_length=hop))
    src_power = np.mean(src_stft ** 2, axis=1)
    ref_power = np.mean(ref_stft ** 2, axis=1)

    # 频率轴
    freqs = np.linspace(0, src_sr / 2, n_fft // 2 + 1)

    # 10 个对数分布频段（80Hz–16kHz，覆盖人声主要频段）
    band_centers = [80, 150, 300, 600, 1200, 2500, 5000, 8000, 12000, 16000]

    # 每频段聚合能量并计算差异
    eps = 1e-10
    diff_db_per_band = []
    for fc in band_centers:
        # 频段范围：±1/3 倍频程
        f_low = fc / (2 ** (1 / 6))
        f_high = fc * (2 ** (1 / 6))
        mask = (freqs >= f_low) & (freqs <= f_high)
        if mask.sum() == 0:
            diff_db_per_band.append(0.0)
            continue
        src_band_power = np.mean(src_power[mask])
        ref_band_power = np.mean(ref_power[mask])
        diff_db = 10 * np.log10((ref_band_power + eps) / (src_band_power + eps))
        # 限制 ±6dB
        diff_db = float(np.clip(diff_db, -6.0, 6.0))
        diff_db_per_band.append(diff_db)

    print(f"  频谱匹配差异(dB): {dict(zip(band_centers, [round(d, 2) for d in diff_db_per_band]))}", flush=True)

    # 构造匹配 EQ（多个 PeakFilter）
    eq_filters = []
    for fc, gain_db in zip(band_centers, diff_db_per_band):
        if abs(gain_db) < 0.3:
            continue  # 差异太小，跳过
        # Q=1.0 给出较宽的频段覆盖，避免频段间过度重叠或空洞
        eq_filters.append(PeakFilter(cutoff_frequency_hz=float(fc), gain_db=float(gain_db), q=1.0))

    if not eq_filters:
        # 无需匹配，直接复制
        import shutil
        shutil.copy2(source, output)
        return

    board = Pedalboard(eq_filters)

    # 用 AudioFile 读取 source（保持立体声）
    with AudioFile(str(source), "r") as audio_file:
        sample_rate = audio_file.samplerate
        channels = audio_file.num_channels
        audio = audio_file.read(audio_file.frames)

    processed = board(audio, sample_rate=sample_rate, reset=True)
    with AudioFile(str(output), "w", sample_rate, channels) as audio_file:
        audio_file.write(processed)
    if not output.is_file():
        raise RuntimeError("频谱匹配未生成输出文件")


def _deepfilter(source: Path, output: Path) -> None:
    """DeepFilterNet 轻量降噪：保持原始采样率与声道，限制衰减量。

    DeepFilterNet 默认 sr=48000，对 44100Hz 输入会重采样引入失真。这里读取
    原始采样率后直接用该采样率加载（DeepFilterNet3 支持任意采样率）。
    同时用 ``atten_lim_db=6`` 限制衰减量，避免把伴奏/混响当成噪声去掉。
    """
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio
    except ImportError as exc:
        raise RuntimeError("DeepFilterNet 未安装，请修复 vocal 增强环境") from exc

    import torchaudio

    # 读取原始采样率，避免不必要的重采样
    info = torchaudio.info(str(source))
    orig_sr = info.sample_rate
    # DeepFilterNet3 支持任意采样率，直接用原始采样率加载
    audio, _ = load_audio(str(source), sr=orig_sr)
    model, state, _ = init_df()
    # 限制衰减量（默认 None 会过度处理音乐），保留更多原始音质
    enhanced = enhance(model, state, audio, atten_lim_db=6.0)
    save_audio(str(output), enhanced, orig_sr)
    if not output.is_file():
        raise RuntimeError("DeepFilterNet 未生成输出文件")


def _pedalboard_basic(source: Path, output: Path) -> None:
    """基础层美声 DSP：温和 EQ + 轻压缩，保留动态范围。

    高通去次低频 → 低频厚度 → 温和压缩 → 人声 Presence → 高频空气感 → 限制器
    """
    try:
        from pedalboard import (
            Compressor,
            HighpassFilter,
            HighShelfFilter,
            Limiter,
            LowShelfFilter,
            PeakFilter,
            Pedalboard,
        )
        from pedalboard.io import AudioFile
    except ImportError as exc:
        raise RuntimeError("Pedalboard 未安装，请修复 vocal 增强环境") from exc

    with AudioFile(str(source), "r") as audio_file:
        sample_rate = audio_file.samplerate
        channels = audio_file.num_channels
        audio = audio_file.read(audio_file.frames)

    board = Pedalboard(
        [
            # 温和低切，保留人声基频
            HighpassFilter(cutoff_frequency_hz=50.0),
            # 轻微提升低频厚度
            LowShelfFilter(cutoff_frequency_hz=120.0, gain_db=1.0),
            # 温和压缩，保留动态范围
            Compressor(
                threshold_db=-12.0,
                ratio=1.8,
                attack_ms=25.0,
                release_ms=150.0,
            ),
            # 轻微提升人声 Presence
            PeakFilter(cutoff_frequency_hz=3000.0, gain_db=0.6, q=0.8),
            # 轻微提升高频空气感
            HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=0.6, q=0.7),
            # 防止削波
            Limiter(threshold_db=-1.0, release_ms=80.0),
        ]
    )
    processed = board(audio, sample_rate=sample_rate, reset=True)
    with AudioFile(str(output), "w", sample_rate, channels) as audio_file:
        audio_file.write(processed)
    if not output.is_file():
        raise RuntimeError("Pedalboard 未生成输出文件")


def _silence_vocalfloor(audio: "np.ndarray", sample_rate: int) -> "np.ndarray":
    """基于 RMS 包络的软衰减：把停顿段的 vocalfloor 压低，但保留平滑过渡。

    SVC/RVC 推理在静音段未归零，残留 -35~-45dB 的 vocoder vocalfloor（电子
    底噪），听感为"停顿处 AI 感强"。但人声的停顿不应是"完全静音"——自然
    人声停顿会有呼吸感、轻微残响和衰减尾音，直接归零会显得突兀。

    本函数采用"软衰减"策略：
    - 用 50ms 窗口计算 RMS 包络
    - 停顿段（RMS < -30dB）不做硬静音，而是把底噪压低到 -75dB（约 0.0002）
      这样既消除 vocalfloor 的电子嗡声，又保留极微弱的"空间感"
    - 用 150ms 指数渐入渐出（attack/release）实现平滑过渡，模拟自然声音的
      渐弱渐强，避免"切断"感
    - 在停顿段内不改变原始信号的相对起伏，只做整体幅度压低

    必须在 DeepFilterNet 之前执行——DeepFilterNet 会对静音段做"增强"反而
    把底噪放大，先压低再降噪才能避免底噪被放大。
    """
    import numpy as np

    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    channels, total = audio.shape

    # 50ms 窗口计算 RMS
    win = max(1, int(sample_rate * 0.05))
    n_windows = total // win
    if n_windows < 2:
        return audio if audio.shape[0] > 1 else audio[0]

    # 每窗口 RMS（多声道取均值）
    rms_per_win = np.zeros(n_windows)
    for i in range(n_windows):
        seg = audio[:, i * win:(i + 1) * win]
        rms_per_win[i] = float(np.sqrt(np.mean(seg ** 2)))

    # 转 dB，-30dB 以下判定为停顿段
    eps = 1e-10
    db_per_win = 20 * np.log10(rms_per_win + eps)
    silence_mask = db_per_win < -30.0  # True = 停顿段

    # 目标增益：停顿段压到 -75dB（增益 0.0002），非停顿段保持原样（增益 1.0）
    # 这样既消除 vocalfloor 的电子嗡声，又保留极微弱的空间感，避免突兀静音
    floor_gain = 0.0002  # -75dB，保留极微弱信号
    target_gain = np.where(silence_mask, floor_gain, 1.0)

    # 用 150ms 指数渐变平滑（远大于 30ms，模拟自然声音的渐弱渐强）
    # 一阶低通：gain[i] = alpha * gain[i-1] + (1-alpha) * target[i]
    # 时间常数 150ms 对应 alpha = exp(-win / (sr * 0.15))
    alpha = float(np.exp(-win / (sample_rate * 0.15)))
    smoothed = np.empty_like(target_gain)
    smoothed[0] = target_gain[0]
    for i in range(1, n_windows):
        smoothed[i] = alpha * smoothed[i - 1] + (1 - alpha) * target_gain[i]
    target_gain = np.clip(smoothed, floor_gain, 1.0)

    # 上采样到逐样本增益（用线性插值避免阶跃）
    gain = np.interp(
        np.arange(total),
        np.arange(n_windows) * win + win // 2,
        target_gain,
    )

    # 应用增益（每声道相同）
    processed = audio * gain[np.newaxis, :total]
    return processed if processed.shape[0] > 1 else processed[0]


def _pedalboard_mastering(source: Path, output: Path) -> None:
    """高级层母带 DSP：在基础层之上做更精细的频谱整形与动态控制。

    设计原则：advanced 应该是"更精细的 basic"，不是"加更多效果"。
    AI 翻唱的"AI 感"主要来自频谱细节平滑化与共振峰偏移，应通过
    精细 EQ 与温和动态控制来缓解，而不是叠加 Distortion/Chorus/Reverb
    等效果——这些效果会让声音"合成器化"，反而加重 AI 感。

    v3/v9 失败教训：Chorus/Distortion/Reverb 即使参数压到"勉强可察觉"
    阈值，仍会让声音"散开""发糊""变脏"，用户反馈"高级不如基础"。

    与 basic 的差异：
    - 更精细的 EQ 分段（加去齿音 + 温暖中低频 + presence + 空气感）
    - 更深度的动态控制（胶水压缩 + 限制器）
    - 不加 Distortion/Chorus/Reverb，不削高频

    处理流程：
      1. 高通去次低频
      2. 温和去齿音（5kHz -1dB）
      3. 温暖中低频（200Hz +1.5dB）
      4. 低频厚度（120Hz +0.8dB）
      5. 胶水压缩（温和，保留瞬态）
      6. 人声 Presence（3.5kHz +1dB）
      7. 高频空气感（8kHz +0.8dB，逆转 AI 翻唱高频衰减）
      8. 真峰限制器
    """
    try:
        from pedalboard import (
            Compressor,
            HighpassFilter,
            HighShelfFilter,
            Limiter,
            LowShelfFilter,
            PeakFilter,
            Pedalboard,
        )
        from pedalboard.io import AudioFile
    except ImportError as exc:
        raise RuntimeError("Pedalboard 未安装，请修复 vocal 增强环境") from exc

    with AudioFile(str(source), "r") as audio_file:
        sample_rate = audio_file.samplerate
        channels = audio_file.num_channels
        audio = audio_file.read(audio_file.frames)

    board = Pedalboard(
        [
            # === 1. 高通去次低频 ===
            HighpassFilter(cutoff_frequency_hz=40.0),
            # === 2. 温和去齿音（5kHz -1dB，比 basic 更克制）===
            PeakFilter(cutoff_frequency_hz=5000.0, gain_db=-1.0, q=1.5),
            # === 3. 温暖中低频（200Hz +1.5dB，补偿 AI 翻唱偏薄）===
            PeakFilter(cutoff_frequency_hz=200.0, gain_db=1.5, q=0.8),
            # === 4. 低频厚度（120Hz +0.8dB）===
            LowShelfFilter(cutoff_frequency_hz=120.0, gain_db=0.8),
            # === 5. 胶水压缩（温和，保留瞬态）===
            Compressor(
                threshold_db=-15.0,
                ratio=1.5,
                attack_ms=30.0,
                release_ms=200.0,
            ),
            # === 6. 人声 Presence（3.5kHz +1dB，让声音靠前）===
            PeakFilter(cutoff_frequency_hz=3500.0, gain_db=1.0, q=0.7),
            # === 7. 高频空气感（8kHz +0.8dB，逆转 AI 翻唱高频衰减）===
            HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=0.8, q=0.7),
            # === 8. 真峰限制器（仅防削波）===
            Limiter(threshold_db=-1.0, release_ms=100.0),
        ]
    )
    processed = board(audio, sample_rate=sample_rate, reset=True)
    with AudioFile(str(output), "w", sample_rate, channels) as audio_file:
        audio_file.write(processed)
    if not output.is_file():
        raise RuntimeError("Pedalboard 未生成输出文件")


def run(source: Path, output: Path, level: str, device: str, reference: Path | None = None) -> None:
    if not source.is_file():
        raise RuntimeError(f"输入文件不存在: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="xb-vocal-enhance-") as raw_temp:
        temp = Path(raw_temp)
        # 步骤 0：vocalfloor 软衰减（在 DeepFilterNet 之前，避免底噪被放大）
        silenced = temp / "00_silenced.wav"

        print("[0/3] vocalfloor 软衰减（压低停顿段电子底噪，保留平滑过渡）", flush=True)
        _silence_vocalfloor_file(source, silenced)
        current = silenced

        # 步骤 1：频谱包络匹配（如果有原始人声参考）
        # 以翻唱前的原始人声为参考，让频谱形状回归自然，从根本上缓解 AI 感
        if reference is not None and reference.is_file():
            matched = temp / "01_matched.wav"
            print(f"[1/3] 频谱包络匹配（参考原始人声: {reference.name}）", flush=True)
            _match_reference(current, reference, matched)
            current = matched
        else:
            print("[1/3] 跳过频谱匹配（无原始人声参考）", flush=True)

        # 步骤 2：DeepFilterNet 降噪
        filtered = temp / "02_deepfilter.wav"

        print("[2/3] DeepFilterNet 神经降噪", flush=True)
        _deepfilter(current, filtered)
        current = filtered

        # 步骤 3：Pedalboard DSP
        if level == "advanced":
            print("[3/3] Pedalboard 精细母带 DSP（去齿音 + 温暖中低频 + presence + 空气感 + 胶水压缩）", flush=True)
            dsp_output = temp / "03_mastering.wav"
            _pedalboard_mastering(current, dsp_output)
        else:
            print("[3/3] Pedalboard 基础美声 DSP", flush=True)
            dsp_output = temp / "03_basic.wav"
            _pedalboard_basic(current, dsp_output)

        shutil.copy2(dsp_output, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="XB-SVCB AI 歌声增强 worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--level", choices=("basic", "advanced"), default="basic")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--reference", default=None, help="原始人声参考文件路径（用于频谱包络匹配）")
    args = parser.parse_args()
    try:
        output = Path(args.output)
        output.unlink(missing_ok=True)
        reference = Path(args.reference) if args.reference else None
        run(Path(args.input), output, args.level, args.device, reference)
        print(f"VOCAL_ENHANCE_OK {output}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - worker must return a concise boundary error
        print(f"VOCAL_ENHANCE_ERR {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
