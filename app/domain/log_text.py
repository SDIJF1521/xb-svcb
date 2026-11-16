"""运行日志的多语言输出。

日志文件由 Python 直接写入磁盘，用户排查问题时看到的就是文件内容，所以这里
在写入前按界面语言翻译，而不是只在前端面板里翻译。

翻译表与前端 ``web/src/i18n/extraPhrases.ts`` 里的日志规则保持同一套中文原文：
前端那份用于「旧日志 / 后端未翻译时」的兜底，这里这份保证**文件本身**可读。
已经翻译过的英文 / 日文再走一遍也不会有变化（不再含中文），因此可以安全重复调用。
"""

from __future__ import annotations

import re

SUPPORTED_LOCALES = ("zh-CN", "en-US", "ja-JP")

# ---------------------------------------------------------------- 静态整行

_EN_EXACT: dict[str, str] = {
    "高音保护已关闭：保留手动 F0、滤波半径和辅音保护参数": "High-pitch protection off: manual F0, filter radius and consonant protection are kept",
    "普通模式：保留默认 F0、滤波半径和辅音保护参数": "Normal mode: default F0, filter radius and consonant protection are kept",
    "当前高音保护组件不支持失配区间限制，跳过本次保护以保留原始结果": "The high-pitch protection component cannot limit mismatch ranges; skipping this pass to keep the original result",
    "高音保护未找到稳定高音区：整轨原样保留": "High-pitch protection found no stable high region: the track is kept as-is",
    "当前高音恢复组件不支持失配区间限制，跳过恢复以保留模型输出": "The high-pitch restore component cannot limit mismatch ranges; skipping restore to keep the model output",
    "高音保护完成：仅对记录的高音区域升回原调并补偿响度": "High-pitch protection complete: only the recorded high regions were restored and loudness compensated",
    "高音保护升调失败，沿用模型输出": "High-pitch restore failed; keeping the model output",
    "原曲参考去混响降级：沿用 UVR 分离人声": "Reference dereverb fell back to the UVR-separated vocal",
    "分离降级：直接使用源音频作为人声（无伴奏）": "Separation fallback: using the source audio as the vocal (no instrumental)",
    "分离降级：直接使用输入音频作为人声": "Separation fallback: using the input audio as the vocal",
    "去混响降级：沿用原始人声": "Dereverb fallback: keeping the original vocal",
    "去混响降级：沿用输入人声": "Dereverb fallback: keeping the input vocal",
    "去混响跳过：未找到去混响模型": "Skipping dereverb: no dereverb model found",
    "跳过去混响：未找到去混响模型": "Skipping dereverb: no dereverb model found",
    "去混响跳过：PyMSS 环境未就绪": "Skipping dereverb: the PyMSS environment is not ready",
    "人声修复跳过：DeepFilterNet3 环境未就绪": "Skipping vocal repair: the DeepFilterNet3 environment is not ready",
    "F0 提取跳过/失败（不影响后续推理，推理内部会再算一次）": "F0 extraction skipped or failed (inference computes it again internally)",
    "模型推理完成": "Model inference complete",
    "人声合并流程：跳过伴奏混音，输出转换后人声": "Vocal-merge flow: skipping the instrumental mix and outputting the converted vocal",
    "人声合并流程：跳过伴奏混音，输出合并后人声": "Vocal-merge flow: skipping the instrumental mix and outputting the merged vocal",
    "混音失败：ffmpeg 合并人声+伴奏未成功，回退为仅干声": "Mix failed: ffmpeg could not merge vocal and instrumental; falling back to the dry vocal",
    "无可用伴奏，输出仅干声": "No instrumental available; outputting the dry vocal only",
    "无可用伴奏，输出仅人声": "No instrumental available; outputting the vocal only",
    "任务完成 ✅": "Task complete ✅",
    "=== 完成：可编辑人声片段已准备 ===": "=== Done: editable vocal clips are ready ===",
    "交叉淡化失败，退回硬拼接": "Crossfade failed; falling back to a hard splice",
    "人声合并失败/降级：使用整轨结果或原始人声": "Vocal merge failed or degraded: using the full-track result or the original vocal",
    "合唱叠加失败，沿用第一路输入": "Harmony stacking failed; keeping the first input",
    "AI 歌声增强跳过：环境未就绪": "Skipping AI vocal enhancement: the environment is not ready",
    "混音失败，输出原始人声": "Mix failed; outputting the original vocal",
    "多轨混合失败，沿用第一路输入": "Multi-track merge failed; keeping the first input",
    "顺序拼接失败，沿用第一段输入": "Sequential concat failed; keeping the first segment",
    "音频效果跳过：未选择效果或 ffmpeg 不可用": "Skipping audio effects: none selected or ffmpeg is unavailable",
    "裁剪跳过：未提供有效结束时间": "Skipping trim: no valid end time provided",
    "裁剪失败，沿用输入": "Trim failed; keeping the input",
    "淡入淡出失败，沿用输入": "Fade failed; keeping the input",
    "变调失败，沿用输入": "Pitch shift failed; keeping the input",
    "变速失败，沿用输入": "Time stretch failed; keeping the input",
    "响度归一化失败，沿用输入": "Loudness normalization failed; keeping the input",
}

_JA_EXACT: dict[str, str] = {
    "高音保护已关闭：保留手动 F0、滤波半径和辅音保护参数": "高音保護はオフ：手動F0・フィルター半径・子音保護の設定を保持します",
    "普通模式：保留默认 F0、滤波半径和辅音保护参数": "通常モード：既定のF0・フィルター半径・子音保護を保持します",
    "当前高音保护组件不支持失配区间限制，跳过本次保护以保留原始结果": "現在の高音保護コンポーネントは不一致区間の制限に対応していません。元の結果を保つため今回の保護をスキップします",
    "高音保护未找到稳定高音区：整轨原样保留": "高音保護で安定した高音区間が見つかりません。トラックはそのまま保持します",
    "当前高音恢复组件不支持失配区间限制，跳过恢复以保留模型输出": "現在の高音復元コンポーネントは不一致区間の制限に対応していません。モデル出力を保つため復元をスキップします",
    "高音保护完成：仅对记录的高音区域升回原调并补偿响度": "高音保護が完了：記録した高音区間のみ元の音程へ戻し、音量を補正しました",
    "高音保护升调失败，沿用模型输出": "高音の復元に失敗しました。モデル出力をそのまま使用します",
    "原曲参考去混响降级：沿用 UVR 分离人声": "参照用デリバーブがフォールバック：UVR分離ボーカルを使用します",
    "分离降级：直接使用源音频作为人声（无伴奏）": "分離フォールバック：元音声をそのままボーカルとして使用します（伴奏なし）",
    "分离降级：直接使用输入音频作为人声": "分離フォールバック：入力音声をそのままボーカルとして使用します",
    "去混响降级：沿用原始人声": "デリバーブのフォールバック：元のボーカルを使用します",
    "去混响降级：沿用输入人声": "デリバーブのフォールバック：入力ボーカルを使用します",
    "去混响跳过：未找到去混响模型": "デリバーブをスキップ：デリバーブモデルが見つかりません",
    "跳过去混响：未找到去混响模型": "デリバーブをスキップ：デリバーブモデルが見つかりません",
    "去混响跳过：PyMSS 环境未就绪": "デリバーブをスキップ：PyMSS環境の準備ができていません",
    "人声修复跳过：DeepFilterNet3 环境未就绪": "ボーカル修復をスキップ：DeepFilterNet3環境の準備ができていません",
    "F0 提取跳过/失败（不影响后续推理，推理内部会再算一次）": "F0抽出をスキップまたは失敗（推論には影響せず、内部で再計算します）",
    "模型推理完成": "モデル推論が完了しました",
    "人声合并流程：跳过伴奏混音，输出转换后人声": "ボーカル統合フロー：伴奏ミックスをスキップし、変換後のボーカルを出力します",
    "人声合并流程：跳过伴奏混音，输出合并后人声": "ボーカル統合フロー：伴奏ミックスをスキップし、統合後のボーカルを出力します",
    "混音失败：ffmpeg 合并人声+伴奏未成功，回退为仅干声": "ミックスに失敗：ffmpegでボーカルと伴奏を結合できませんでした。ドライボーカルのみ出力します",
    "无可用伴奏，输出仅干声": "伴奏がないため、ドライボーカルのみ出力します",
    "无可用伴奏，输出仅人声": "伴奏がないため、ボーカルのみ出力します",
    "任务完成 ✅": "タスク完了 ✅",
    "=== 完成：可编辑人声片段已准备 ===": "=== 完了：編集可能なボーカルクリップを準備しました ===",
    "交叉淡化失败，退回硬拼接": "クロスフェードに失敗しました。ハード接続に切り替えます",
    "人声合并失败/降级：使用整轨结果或原始人声": "ボーカル統合に失敗またはフォールバック：トラック全体の結果か元のボーカルを使用します",
    "合唱叠加失败，沿用第一路输入": "ハモリ重ねに失敗しました。1系統目の入力を使用します",
    "AI 歌声增强跳过：环境未就绪": "AIボーカル強化をスキップ：環境の準備ができていません",
    "混音失败，输出原始人声": "ミックスに失敗しました。元のボーカルを出力します",
    "多轨混合失败，沿用第一路输入": "マルチトラック統合に失敗しました。1系統目の入力を使用します",
    "顺序拼接失败，沿用第一段输入": "順次結合に失敗しました。1つ目の区間を使用します",
    "音频效果跳过：未选择效果或 ffmpeg 不可用": "オーディオエフェクトをスキップ：エフェクト未選択かffmpegが利用できません",
    "裁剪跳过：未提供有效结束时间": "トリムをスキップ：有効な終了時間が指定されていません",
    "裁剪失败，沿用输入": "トリムに失敗しました。入力をそのまま使用します",
    "淡入淡出失败，沿用输入": "フェードに失敗しました。入力をそのまま使用します",
    "变调失败，沿用输入": "移調に失敗しました。入力をそのまま使用します",
    "变速失败，沿用输入": "タイムストレッチに失敗しました。入力をそのまま使用します",
    "响度归一化失败，沿用输入": "ラウドネス正規化に失敗しました。入力をそのまま使用します",
}


# ---------------------------------------------------------------- 带参数的行

_EN_RULES: list[tuple[str, str]] = [
    # 日志头
    (r"^=== (.+) \(自定义工作流\) ===$", "=== %s (custom workflow) ==="),
    (r"^=== (.+) \(多模型混合\) ===$", "=== %s (multi-model mix) ==="),
    (r"^开始时间: (.+)$", "Started at: %s"),
    (r"^工作流: (.+)$", "Workflow: %s"),
    (r"^参数: (.+)$", "Parameters: %s"),
    (r"^原始歌曲: (.+)$", "Original song: %s"),
    (r"^待增强作品: (.+)$", "Target work: %s"),
    # 节点开始
    (r"^\[(\d+)/(\d+)\] 输入音频 开始$", "[%s/%s] Input audio started"),
    (r"^\[(\d+)/(\d+)\] 人声分离 开始$", "[%s/%s] Vocal separation started"),
    (r"^\[(\d+)/(\d+)\] 去混响净化 开始$", "[%s/%s] Dereverb cleanup started"),
    (r"^\[(\d+)/(\d+)\] 人声修复 开始$", "[%s/%s] Vocal repair started"),
    (r"^\[(\d+)/(\d+)\] 歌声转换 开始$", "[%s/%s] Voice conversion started"),
    (r"^\[(\d+)/(\d+)\] 人声合唱叠加 开始$", "[%s/%s] Vocal harmony stacking started"),
    (r"^\[(\d+)/(\d+)\] AI 歌声增强 开始$", "[%s/%s] AI vocal enhancement started"),
    (r"^\[(\d+)/(\d+)\] 混音合成 开始$", "[%s/%s] Mixdown started"),
    (r"^\[(\d+)/(\d+)\] 多轨混合 开始$", "[%s/%s] Multi-track merge started"),
    (r"^\[(\d+)/(\d+)\] 顺序拼接 开始$", "[%s/%s] Sequential concat started"),
    (r"^\[(\d+)/(\d+)\] 音频效果 开始$", "[%s/%s] Audio effects started"),
    (r"^\[(\d+)/(\d+)\] 裁剪片段 开始$", "[%s/%s] Trim started"),
    (r"^\[(\d+)/(\d+)\] 淡入淡出 开始$", "[%s/%s] Fade started"),
    (r"^\[(\d+)/(\d+)\] 变调 开始$", "[%s/%s] Pitch shift started"),
    (r"^\[(\d+)/(\d+)\] 变速 开始$", "[%s/%s] Time stretch started"),
    (r"^\[(\d+)/(\d+)\] 响度归一化 开始$", "[%s/%s] Loudness normalization started"),
    (r"^\[(\d+)/(\d+)\] 输出成品 开始$", "[%s/%s] Final output started"),
    # 分离 / 推理
    (r"^\[(\d+)/(\d+)\] 人声分离开始（PyMSS 可用）$", "[%s/%s] Vocal separation started (PyMSS ready)"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（PyMSS 未就绪）$", "[%s/%s] Vocal separation started (PyMSS not ready)"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（UVR 可用）$", "[%s/%s] Vocal separation started (UVR ready)"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（UVR 降级模式）$", "[%s/%s] Vocal separation started (UVR fallback mode)"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（PyMSS (.+)）$", "[%s/%s] Vocal separation started (PyMSS %s)"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（UVR (.+)）$", "[%s/%s] Vocal separation started (UVR %s)"),
    (r"^\[(\d+)/(\d+)\] 跳过前期分离，直接使用源音频: (.+)$", "[%s/%s] Skipping pre-separation; using the source audio: %s"),
    (r"^\[(\d+)/(\d+)\] 跳过前期分离，直接使用源音频$", "[%s/%s] Skipping pre-separation; using the source audio"),
    (r"^\[(\d+)/(\d+)\] 推理输入已准备: (.+)$", "[%s/%s] Inference input ready: %s"),
    (r"^\[(\d+)/(\d+)\] (.+) 开始$", "[%s/%s] %s started"),
    (r"^源文件: (.+) \| 时长: (.+)s \| 设备: (.+)$", "Source: %s | Duration: %ss | Device: %s"),
    (r"^源音频已统一转码: (.+)$", "Source audio transcoded: %s"),
    (r"^源音频: (.+) → (.+)$", "Source audio: %s → %s"),
    (r"^分离引擎/模型: (.+) / (.+)$", "Separation engine/model: %s / %s"),
    (r"^分离设备: (.+)$", "Separation device: %s"),
    (r"^去混响设备: (.+)$", "Dereverb device: %s"),
    (r"^去混响净化开始（PyMSS / (.+)）$", "Dereverb cleanup started (PyMSS / %s)"),
    (r"^去混响净化后人声: (.+)$", "Vocal after dereverb cleanup: %s"),
    (r"^去混响后人声: (.+)$", "Vocal after dereverb: %s"),
    (r"^PyMSS 去混响模型: (.+)$", "PyMSS dereverb model: %s"),
    (r"^去混响模型: (.+)$", "Dereverb model: %s"),
    (r"^去混响失败，沿用输入: (.+)$", "Dereverb failed; keeping the input: %s"),
    (r"^人声修复失败，沿用输入: (.+)$", "Vocal repair failed; keeping the input: %s"),
    (r"^人声: (.+) \| 伴奏: (.+)$", "Vocal: %s | Instrumental: %s"),
    (r"^人声: (.+)$", "Vocal: %s"),
    (r"^伴奏: (.+)$", "Instrumental: %s"),
    (r"^AI Vocal 参考干声（前期处理完成）: (.+)$", "AI Vocal reference dry signal (preprocessing done): %s"),
    (r"^原曲去混响参考人声: (.+)$", "Reference dereverb vocal: %s"),
    (r"^原曲参考人声: (.+)$", "Reference vocal: %s"),
    (r"^复用翻唱作品干声: (.+)$", "Reusing the cover dry vocal: %s"),
    (r"^从翻唱成品分离人声: (.+)$", "Separating the vocal from the cover output: %s"),
    (r"^AI 人声修复跳过：输入不存在 (.+)$", "AI vocal repair skipped: input not found %s"),
    (r"^(.+)进入 DeepFilterNet3 修复，并保护高频辅音与高音泛音$", "Handing %s to DeepFilterNet3 repair with high-frequency consonant and overtone protection"),
    (r"^(.+)修复完成: (.+)$", "%s repair complete: %s"),
    (r"^(.+)修复失败，沿用未修复人声: (.+)$", "%s repair failed; keeping the unrepaired vocal: %s"),
    (r"^高音保护降调失败，沿用原始推理输入（峰值 F0=(.+)Hz）$", "High-pitch lowering failed; keeping the original inference input (peak F0=%sHz)"),
    (r"^AI 歌声增强完成: (.+)$", "AI vocal enhancement complete: %s"),
    (r"^AI 增强任务完成: (.+)$", "AI enhancement complete: %s"),
    (r"^AI 增强任务失败: (.+)$", "AI enhancement failed: %s"),
    (r"^模型整轨推理失败，相关句回退原始人声：(.+)$", "Full-track inference failed; affected phrases fall back to the original vocal: %s"),
    # 效果 / 合成
    (r"^合唱叠加 (\d+) 路转换人声$", "Harmony stacking: %s converted vocal tracks"),
    (r"^多轨混合 (\d+) 路音频$", "Multi-track merge: %s audio tracks"),
    (r"^顺序拼接 (\d+) 段音频$", "Sequential concat: %s audio segments"),
    (r"^音频效果: (.+)$", "Audio effect: %s"),
    (r"^音频效果失败，沿用输入: (.+)$", "Audio effect failed; keeping the input: %s"),
    (r"^淡入 (.+)s / 淡出 (.+)s$", "Fade in %ss / fade out %ss"),
    (r"^变调 ([+-]?\d+) 半音$", "Pitch shift %s semitones"),
    (r"^变速 (.+)x$", "Time stretch %sx"),
    (r"^响度归一化到 (.+) LUFS$", "Loudness normalized to %s LUFS"),
    (r"^保存节点接入 (\d+) 路音轨$", "Output node received %s tracks"),
    # 结束
    (r"^工作流任务完成 ✅（共保存 (\d+) 路音轨）$", "Workflow complete ✅ (%s tracks saved)"),
    (r"^工作流任务失败 ❌: (.+)$", "Workflow failed ❌: %s"),
    (r"^任务失败 ❌: (.+)$", "Task failed ❌: %s"),
]

_JA_RULES: list[tuple[str, str]] = [
    (r"^=== (.+) \(自定义工作流\) ===$", "=== %s（カスタムワークフロー）==="),
    (r"^=== (.+) \(多模型混合\) ===$", "=== %s（マルチモデルミックス）==="),
    (r"^开始时间: (.+)$", "開始時間：%s"),
    (r"^工作流: (.+)$", "ワークフロー：%s"),
    (r"^参数: (.+)$", "パラメータ：%s"),
    (r"^原始歌曲: (.+)$", "元の楽曲：%s"),
    (r"^待增强作品: (.+)$", "強化対象の作品：%s"),
    (r"^\[(\d+)/(\d+)\] 输入音频 开始$", "[%s/%s] 入力音声を開始"),
    (r"^\[(\d+)/(\d+)\] 人声分离 开始$", "[%s/%s] ボーカル分離を開始"),
    (r"^\[(\d+)/(\d+)\] 去混响净化 开始$", "[%s/%s] デリバーブ処理を開始"),
    (r"^\[(\d+)/(\d+)\] 人声修复 开始$", "[%s/%s] ボーカル修復を開始"),
    (r"^\[(\d+)/(\d+)\] 歌声转换 开始$", "[%s/%s] 歌声変換を開始"),
    (r"^\[(\d+)/(\d+)\] 人声合唱叠加 开始$", "[%s/%s] ハモリ重ねを開始"),
    (r"^\[(\d+)/(\d+)\] AI 歌声增强 开始$", "[%s/%s] AIボーカル強化を開始"),
    (r"^\[(\d+)/(\d+)\] 混音合成 开始$", "[%s/%s] ミックスを開始"),
    (r"^\[(\d+)/(\d+)\] 多轨混合 开始$", "[%s/%s] マルチトラック統合を開始"),
    (r"^\[(\d+)/(\d+)\] 顺序拼接 开始$", "[%s/%s] 順次結合を開始"),
    (r"^\[(\d+)/(\d+)\] 音频效果 开始$", "[%s/%s] オーディオエフェクトを開始"),
    (r"^\[(\d+)/(\d+)\] 裁剪片段 开始$", "[%s/%s] トリムを開始"),
    (r"^\[(\d+)/(\d+)\] 淡入淡出 开始$", "[%s/%s] フェードを開始"),
    (r"^\[(\d+)/(\d+)\] 变调 开始$", "[%s/%s] 移調を開始"),
    (r"^\[(\d+)/(\d+)\] 变速 开始$", "[%s/%s] タイムストレッチを開始"),
    (r"^\[(\d+)/(\d+)\] 响度归一化 开始$", "[%s/%s] ラウドネス正規化を開始"),
    (r"^\[(\d+)/(\d+)\] 输出成品 开始$", "[%s/%s] 最終出力を開始"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（PyMSS 可用）$", "[%s/%s] ボーカル分離を開始（PyMSS 準備完了）"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（PyMSS 未就绪）$", "[%s/%s] ボーカル分離を開始（PyMSS 未準備）"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（UVR 可用）$", "[%s/%s] ボーカル分離を開始（UVR 準備完了）"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（UVR 降级模式）$", "[%s/%s] ボーカル分離を開始（UVR フォールバック）"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（PyMSS (.+)）$", "[%s/%s] ボーカル分離を開始（PyMSS %s）"),
    (r"^\[(\d+)/(\d+)\] 人声分离开始（UVR (.+)）$", "[%s/%s] ボーカル分離を開始（UVR %s）"),
    (r"^\[(\d+)/(\d+)\] 跳过前期分离，直接使用源音频: (.+)$", "[%s/%s] 事前分離をスキップし、元音声を使用：%s"),
    (r"^\[(\d+)/(\d+)\] 跳过前期分离，直接使用源音频$", "[%s/%s] 事前分離をスキップし、元音声を使用"),
    (r"^\[(\d+)/(\d+)\] 推理输入已准备: (.+)$", "[%s/%s] 推論入力の準備が完了：%s"),
    (r"^\[(\d+)/(\d+)\] (.+) 开始$", "[%s/%s] %s を開始"),
    (r"^源文件: (.+) \| 时长: (.+)s \| 设备: (.+)$", "ソース：%s | 長さ：%s秒 | デバイス：%s"),
    (r"^源音频已统一转码: (.+)$", "ソース音声を変換済み：%s"),
    (r"^源音频: (.+) → (.+)$", "ソース音声：%s → %s"),
    (r"^分离引擎/模型: (.+) / (.+)$", "分離エンジン/モデル：%s / %s"),
    (r"^分离设备: (.+)$", "分離デバイス：%s"),
    (r"^去混响设备: (.+)$", "デリバーブデバイス：%s"),
    (r"^去混响净化开始（PyMSS / (.+)）$", "デリバーブ処理を開始（PyMSS / %s）"),
    (r"^去混响净化后人声: (.+)$", "デリバーブ処理後のボーカル：%s"),
    (r"^去混响后人声: (.+)$", "デリバーブ後のボーカル：%s"),
    (r"^PyMSS 去混响模型: (.+)$", "PyMSSデリバーブモデル：%s"),
    (r"^去混响模型: (.+)$", "デリバーブモデル：%s"),
    (r"^去混响失败，沿用输入: (.+)$", "デリバーブに失敗。入力を使用：%s"),
    (r"^人声修复失败，沿用输入: (.+)$", "ボーカル修復に失敗。入力を使用：%s"),
    (r"^人声: (.+) \| 伴奏: (.+)$", "ボーカル：%s | 伴奏：%s"),
    (r"^人声: (.+)$", "ボーカル：%s"),
    (r"^伴奏: (.+)$", "伴奏：%s"),
    (r"^AI Vocal 参考干声（前期处理完成）: (.+)$", "AI Vocal参照ドライ音声（前処理完了）：%s"),
    (r"^原曲去混响参考人声: (.+)$", "参照用デリバーブボーカル：%s"),
    (r"^原曲参考人声: (.+)$", "参照ボーカル：%s"),
    (r"^复用翻唱作品干声: (.+)$", "カバー作品のドライボーカルを再利用：%s"),
    (r"^从翻唱成品分离人声: (.+)$", "カバー完成音声からボーカルを分離：%s"),
    (r"^AI 人声修复跳过：输入不存在 (.+)$", "AIボーカル修復をスキップ：入力が見つかりません %s"),
    (r"^(.+)进入 DeepFilterNet3 修复，并保护高频辅音与高音泛音$", "%s をDeepFilterNet3修復へ渡し、高域の子音と倍音を保護します"),
    (r"^(.+)修复完成: (.+)$", "%s修復が完了：%s"),
    (r"^(.+)修复失败，沿用未修复人声: (.+)$", "%s修復に失敗。未修復のボーカルを使用：%s"),
    (r"^高音保护降调失败，沿用原始推理输入（峰值 F0=(.+)Hz）$", "高音保護の移調に失敗。元の推論入力を使用（ピークF0=%sHz）"),
    (r"^AI 歌声增强完成: (.+)$", "AIボーカル強化が完了：%s"),
    (r"^AI 增强任务完成: (.+)$", "AI強化タスクが完了：%s"),
    (r"^AI 增强任务失败: (.+)$", "AI強化タスクに失敗：%s"),
    (r"^模型整轨推理失败，相关句回退原始人声：(.+)$", "トラック全体の推論に失敗。該当フレーズは元のボーカルへ戻します：%s"),
    (r"^合唱叠加 (\d+) 路转换人声$", "ハモリ重ね：変換済みボーカル %s 系統"),
    (r"^多轨混合 (\d+) 路音频$", "マルチトラック統合：音声 %s 系統"),
    (r"^顺序拼接 (\d+) 段音频$", "順次結合：音声 %s 区間"),
    (r"^音频效果: (.+)$", "オーディオエフェクト：%s"),
    (r"^音频效果失败，沿用输入: (.+)$", "オーディオエフェクトに失敗。入力を使用：%s"),
    (r"^淡入 (.+)s / 淡出 (.+)s$", "フェードイン %s秒 / フェードアウト %s秒"),
    (r"^变调 ([+-]?\d+) 半音$", "移調 %s半音"),
    (r"^变速 (.+)x$", "タイムストレッチ %s倍"),
    (r"^响度归一化到 (.+) LUFS$", "ラウドネスを %s LUFS に正規化"),
    (r"^保存节点接入 (\d+) 路音轨$", "出力ノードに %s トラックを接続"),
    (r"^工作流任务完成 ✅（共保存 (\d+) 路音轨）$", "ワークフロー完了 ✅（%s トラックを保存）"),
    (r"^工作流任务失败 ❌: (.+)$", "ワークフロー失敗 ❌：%s"),
    (r"^任务失败 ❌: (.+)$", "タスク失敗 ❌：%s"),
]


def _compiled(rules: list[tuple[str, str]]) -> list[tuple[re.Pattern[str], str]]:
    """把 ``%s`` 占位换成正则反向引用 ``\\g<n>``。

    占位数量和捕获组数量不一致的规则会被跳过（日志翻译出错不该拖垮启动）；
    ``app/tests/test_log_text.py`` 会断言所有规则都成功编译。
    """
    compiled: list[tuple[re.Pattern[str], str]] = []
    for pattern, replacement in rules:
        regex = re.compile(pattern)
        chunks = replacement.split("%s")
        if len(chunks) - 1 != regex.groups:
            continue
        built = chunks[0]
        for index, chunk in enumerate(chunks[1:], start=1):
            built += f"\\g<{index}>" + chunk
        compiled.append((regex, built))
    return compiled


_COMPILED = {
    "en-US": _compiled(_EN_RULES),
    "ja-JP": _compiled(_JA_RULES),
}
_EXACT = {"en-US": _EN_EXACT, "ja-JP": _JA_EXACT}

_CHINESE = re.compile(r"[\u4e00-\u9fff]")


def normalize_locale(value: object) -> str:
    """把界面语言收敛到受支持的三选一。"""
    text = str(value or "").strip()
    return text if text in SUPPORTED_LOCALES else "zh-CN"


def translate_line(text: str, locale: str) -> str:
    """翻译单行日志；没有对应词条时原样返回，保留首尾空白。"""
    if not text or normalize_locale(locale) == "zh-CN":
        return text
    match = re.match(r"^(\s*)(.*?)(\s*)$", text, re.S)
    if not match:
        return text
    prefix, core, suffix = match.group(1), match.group(2), match.group(3)
    if not core or not _CHINESE.search(core):
        return text
    table = _EXACT[locale]
    direct = table.get(core)
    if direct:
        return f"{prefix}{direct}{suffix}"
    for pattern, replacement in _COMPILED[locale]:
        if pattern.match(core):
            return f"{prefix}{pattern.sub(replacement, core, count=1)}{suffix}"
    return text


def translate_log_text(text: str, locale: str) -> str:
    """逐行翻译日志文本（保留换行与缩进）。"""
    if not text or normalize_locale(locale) == "zh-CN":
        return text
    return "\n".join(translate_line(line, locale) for line in text.split("\n"))
