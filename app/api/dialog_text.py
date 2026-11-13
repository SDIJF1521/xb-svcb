"""原生文件对话框文案的多语言支持。

pywebview 打开的系统对话框由后端直接弹出，前端拿不到它的标题与文件类型
名称，所以这里记录前端当前的界面语言（``set_ui_locale``），在弹出对话框前
把标题和文件类型名称翻译成对应语言。

扩展名筛选部分 ``(*.wav;*.mp3)`` 保持原样，只翻译前面的名称，避免改动
Windows / macOS 依赖的筛选语法。
"""

from __future__ import annotations

import re

SUPPORTED_LOCALES = ("zh-CN", "en-US", "ja-JP")

_EN: dict[str, str] = {
    # 标题
    "导出实时翻唱": "Export realtime cover",
    "选择主题背景图片或 MP4 动态壁纸": "Choose a theme background image or MP4 wallpaper",
    "选择 XB-SVCB 用户数据目录": "Choose the XB-SVCB user data folder",
    "选择模型权重文件": "Choose a model weight file",
    "选择模型配置文件": "Choose a model config file",
    "选择 RVC 检索特征文件": "Choose an RVC index file",
    "选择模型试听音频": "Choose model preview audio",
    "选择模型截图": "Choose model screenshots",
    "选择歌曲音频": "Choose song audio",
    "选择多个歌曲音频": "Choose multiple song audio files",
    "选择歌词文件": "Choose a lyrics file",
    "选择效果器插件": "Choose an effect plugin",
    "选择 VST3 插件目录": "Choose a VST3 plugin folder",
    "选择 XB-SVCB 插件包": "Choose an XB-SVCB plugin bundle",
    "导出工作流文件": "Export workflow file",
    "导入工作流文件": "Import workflow file",
    "导出翻唱作品": "Export cover",
    "导出音频编辑工程": "Export audio editing project",
    "导出音轨音频": "Export track audio",
    "导出编辑器人声": "Export editor vocal",
    "导出编辑器混音": "Export editor mix",
    "导入 MIDI 文件": "Import MIDI file",
    "导入 MIDI 到声部": "Import MIDI into part",
    "导出 MIDI 文件": "Export MIDI file",
    # 默认文件名 / 默认工程名
    "实时翻唱.wav": "Realtime cover.wav",
    "音频编辑工程": "Audio editing project",
    "音频编辑": "Audio edit",
    "音轨": "Track",
    # 文件类型名称
    "背景媒体": "Background media",
    "图片": "Images",
    "MP4 视频": "MP4 video",
    "所有文件": "All files",
    "全部文件": "All files",
    "模型权重": "Model weights",
    "配置文件": "Config files",
    "RVC 检索特征": "RVC index",
    "音频文件": "Audio files",
    "歌词文件": "Lyrics files",
    "VST3 效果器插件": "VST3 effect plugins",
    "效果器插件": "Effect plugins",
    "XB-SVCB 插件包": "XB-SVCB plugin bundle",
    "工作流文件": "Workflow files",
    "MIDI 文件": "MIDI files",
}

_JA: dict[str, str] = {
    # タイトル
    "导出实时翻唱": "リアルタイムカバーを書き出し",
    "选择主题背景图片或 MP4 动态壁纸": "テーマの背景画像またはMP4壁紙を選択",
    "选择 XB-SVCB 用户数据目录": "XB-SVCBのユーザーデータフォルダを選択",
    "选择模型权重文件": "モデルの重みファイルを選択",
    "选择模型配置文件": "モデルの設定ファイルを選択",
    "选择 RVC 检索特征文件": "RVCインデックスファイルを選択",
    "选择模型试听音频": "モデルの試聴音声を選択",
    "选择模型截图": "モデルのスクリーンショットを選択",
    "选择歌曲音频": "楽曲の音声を選択",
    "选择多个歌曲音频": "複数の楽曲音声を選択",
    "选择歌词文件": "歌詞ファイルを選択",
    "选择效果器插件": "エフェクトプラグインを選択",
    "选择 VST3 插件目录": "VST3プラグインのフォルダを選択",
    "选择 XB-SVCB 插件包": "XB-SVCBプラグインパッケージを選択",
    "导出工作流文件": "ワークフローファイルを書き出し",
    "导入工作流文件": "ワークフローファイルをインポート",
    "导出翻唱作品": "カバー作品を書き出し",
    "导出音频编辑工程": "音声編集プロジェクトを書き出し",
    "导出音轨音频": "トラック音声を書き出し",
    "导出编辑器人声": "エディターのボーカルを書き出し",
    "导出编辑器混音": "エディターのミックスを書き出し",
    "导入 MIDI 文件": "MIDIファイルをインポート",
    "导入 MIDI 到声部": "MIDIをパートにインポート",
    "导出 MIDI 文件": "MIDIファイルを書き出し",
    # 既定のファイル名 / プロジェクト名
    "实时翻唱.wav": "リアルタイムカバー.wav",
    "音频编辑工程": "音声編集プロジェクト",
    "音频编辑": "音声編集",
    "音轨": "トラック",
    # ファイルの種類
    "背景媒体": "背景メディア",
    "图片": "画像",
    "MP4 视频": "MP4動画",
    "所有文件": "すべてのファイル",
    "全部文件": "すべてのファイル",
    "模型权重": "モデルの重み",
    "配置文件": "設定ファイル",
    "RVC 检索特征": "RVCインデックス",
    "音频文件": "音声ファイル",
    "歌词文件": "歌詞ファイル",
    "VST3 效果器插件": "VST3エフェクトプラグイン",
    "效果器插件": "エフェクトプラグイン",
    "XB-SVCB 插件包": "XB-SVCBプラグインパッケージ",
    "工作流文件": "ワークフローファイル",
    "MIDI 文件": "MIDIファイル",
}

_TABLES: dict[str, dict[str, str]] = {"en-US": _EN, "ja-JP": _JA}

# "名称 (*.ext;*.ext)"：名称里不含括号，扩展名部分不含括号
_FILE_TYPE = re.compile(r"^(?P<label>[^()]+?)\s*\((?P<spec>[^()]*)\)\s*$")


def normalize_locale(value: str | None) -> str:
    """把前端传来的语言标记收敛到受支持的三选一。"""
    text = str(value or "").strip()
    return text if text in SUPPORTED_LOCALES else "zh-CN"


def translate_dialog_text(text: str, locale: str | None) -> str:
    """按当前界面语言翻译对话框标题 / 默认名。

    支持 ``"导出翻唱作品 · WAV"`` 这种「固定前缀 · 变量后缀」的形式，只翻译前缀。
    """
    source = str(text or "")
    table = _TABLES.get(normalize_locale(locale))
    if not table or not source:
        return source
    direct = table.get(source)
    if direct:
        return direct
    head, separator, tail = source.partition(" · ")
    if separator:
        translated = table.get(head)
        if translated:
            return f"{translated} · {tail}"
    return source


def translate_file_type(value: str, locale: str | None) -> str:
    """翻译 ``名称 (*.ext;...)`` 中的名称，保持扩展名筛选语法不变。"""
    source = str(value or "").strip()
    match = _FILE_TYPE.match(source)
    if not match:
        return translate_dialog_text(source, locale)
    label = translate_dialog_text(match.group("label").strip(), locale)
    spec = match.group("spec").strip()
    return f"{label} ({spec})" if spec else label
