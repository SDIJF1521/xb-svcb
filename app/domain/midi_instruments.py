"""GM（General MIDI）乐器目录。

MIDI 编曲子编辑器需要「多种乐器」：每个声部（part）选一个 GM 音色，渲染时按音色
族切换合成参数，导出 ``.mid`` 时写入对应的 Program Change。

这里只描述静态目录（128 个音色的中英文名与所属音色族），不涉及任何合成算法，
因此在领域层保持零依赖，前端也可以直接吃同一份结构。
"""

from __future__ import annotations

from typing import Any

# 音色族：GM 的 16 个八音色分组。
FAMILIES: tuple[dict[str, str], ...] = (
    {"id": "piano", "name_zh": "钢琴", "name_en": "Piano"},
    {"id": "chromatic", "name_zh": "色彩打击", "name_en": "Chromatic Percussion"},
    {"id": "organ", "name_zh": "风琴", "name_en": "Organ"},
    {"id": "guitar", "name_zh": "吉他", "name_en": "Guitar"},
    {"id": "bass", "name_zh": "贝斯", "name_en": "Bass"},
    {"id": "strings", "name_zh": "弦乐", "name_en": "Strings"},
    {"id": "ensemble", "name_zh": "合奏", "name_en": "Ensemble"},
    {"id": "brass", "name_zh": "铜管", "name_en": "Brass"},
    {"id": "reed", "name_zh": "簧管", "name_en": "Reed"},
    {"id": "pipe", "name_zh": "吹管", "name_en": "Pipe"},
    {"id": "lead", "name_zh": "合成主音", "name_en": "Synth Lead"},
    {"id": "pad", "name_zh": "合成铺底", "name_en": "Synth Pad"},
    {"id": "fx", "name_zh": "合成特效", "name_en": "Synth Effects"},
    {"id": "ethnic", "name_zh": "民族乐器", "name_en": "Ethnic"},
    {"id": "percussive", "name_zh": "打击乐", "name_en": "Percussive"},
    {"id": "sfx", "name_zh": "音效", "name_en": "Sound Effects"},
)

# 每个音色族里「最适合当默认音色」的 program（0 起的偏移）。
_DEFAULT_OFFSET: dict[str, int] = {
    "piano": 0,
    "chromatic": 4,
    "organ": 3,
    "guitar": 1,
    "bass": 1,
    "strings": 0,
    "ensemble": 0,
    "brass": 0,
    "reed": 2,
    "pipe": 1,
    "lead": 1,
    "pad": 1,
    "fx": 2,
    "ethnic": 3,
    "percussive": 2,
    "sfx": 2,
}

# (英文名, 中文名)，顺序即 GM program 0~127。
_NAMES: tuple[tuple[str, str], ...] = (
    ("Acoustic Grand Piano", "原声大钢琴"),
    ("Bright Acoustic Piano", "明亮钢琴"),
    ("Electric Grand Piano", "电钢琴（大）"),
    ("Honky-tonk Piano", "酒吧钢琴"),
    ("Electric Piano 1", "电钢琴 1"),
    ("Electric Piano 2", "电钢琴 2"),
    ("Harpsichord", "大键琴"),
    ("Clavinet", "击弦古钢琴"),
    ("Celesta", "钢片琴"),
    ("Glockenspiel", "钟琴"),
    ("Music Box", "八音盒"),
    ("Vibraphone", "颤音琴"),
    ("Marimba", "马林巴"),
    ("Xylophone", "木琴"),
    ("Tubular Bells", "管钟"),
    ("Dulcimer", "洋琴"),
    ("Drawbar Organ", "拉杆风琴"),
    ("Percussive Organ", "打击风琴"),
    ("Rock Organ", "摇滚风琴"),
    ("Church Organ", "教堂管风琴"),
    ("Reed Organ", "簧风琴"),
    ("Accordion", "手风琴"),
    ("Harmonica", "口琴"),
    ("Tango Accordion", "探戈手风琴"),
    ("Acoustic Guitar (nylon)", "尼龙弦吉他"),
    ("Acoustic Guitar (steel)", "钢弦吉他"),
    ("Electric Guitar (jazz)", "爵士电吉他"),
    ("Electric Guitar (clean)", "清音电吉他"),
    ("Electric Guitar (muted)", "闷音电吉他"),
    ("Overdriven Guitar", "过载吉他"),
    ("Distortion Guitar", "失真吉他"),
    ("Guitar Harmonics", "吉他泛音"),
    ("Acoustic Bass", "原声贝斯"),
    ("Electric Bass (finger)", "指弹电贝斯"),
    ("Electric Bass (pick)", "拨片电贝斯"),
    ("Fretless Bass", "无品贝斯"),
    ("Slap Bass 1", "击弦贝斯 1"),
    ("Slap Bass 2", "击弦贝斯 2"),
    ("Synth Bass 1", "合成贝斯 1"),
    ("Synth Bass 2", "合成贝斯 2"),
    ("Violin", "小提琴"),
    ("Viola", "中提琴"),
    ("Cello", "大提琴"),
    ("Contrabass", "低音提琴"),
    ("Tremolo Strings", "颤弓弦乐"),
    ("Pizzicato Strings", "拨弦弦乐"),
    ("Orchestral Harp", "管弦竖琴"),
    ("Timpani", "定音鼓"),
    ("String Ensemble 1", "弦乐合奏 1"),
    ("String Ensemble 2", "弦乐合奏 2"),
    ("Synth Strings 1", "合成弦乐 1"),
    ("Synth Strings 2", "合成弦乐 2"),
    ("Choir Aahs", "人声合唱「啊」"),
    ("Voice Oohs", "人声「呜」"),
    ("Synth Voice", "合成人声"),
    ("Orchestra Hit", "管弦乐重音"),
    ("Trumpet", "小号"),
    ("Trombone", "长号"),
    ("Tuba", "大号"),
    ("Muted Trumpet", "弱音小号"),
    ("French Horn", "圆号"),
    ("Brass Section", "铜管组"),
    ("Synth Brass 1", "合成铜管 1"),
    ("Synth Brass 2", "合成铜管 2"),
    ("Soprano Sax", "高音萨克斯"),
    ("Alto Sax", "中音萨克斯"),
    ("Tenor Sax", "次中音萨克斯"),
    ("Baritone Sax", "低音萨克斯"),
    ("Oboe", "双簧管"),
    ("English Horn", "英国管"),
    ("Bassoon", "大管"),
    ("Clarinet", "单簧管"),
    ("Piccolo", "短笛"),
    ("Flute", "长笛"),
    ("Recorder", "竖笛"),
    ("Pan Flute", "排箫"),
    ("Blown Bottle", "吹瓶"),
    ("Shakuhachi", "尺八"),
    ("Whistle", "哨笛"),
    ("Ocarina", "陶笛"),
    ("Lead 1 (square)", "主音 1（方波）"),
    ("Lead 2 (sawtooth)", "主音 2（锯齿）"),
    ("Lead 3 (calliope)", "主音 3（汽笛风琴）"),
    ("Lead 4 (chiff)", "主音 4（气声）"),
    ("Lead 5 (charang)", "主音 5（查朗）"),
    ("Lead 6 (voice)", "主音 6（人声）"),
    ("Lead 7 (fifths)", "主音 7（五度）"),
    ("Lead 8 (bass + lead)", "主音 8（贝斯＋主音）"),
    ("Pad 1 (new age)", "铺底 1（新世纪）"),
    ("Pad 2 (warm)", "铺底 2（温暖）"),
    ("Pad 3 (polysynth)", "铺底 3（复合成）"),
    ("Pad 4 (choir)", "铺底 4（合唱）"),
    ("Pad 5 (bowed)", "铺底 5（弓弦）"),
    ("Pad 6 (metallic)", "铺底 6（金属）"),
    ("Pad 7 (halo)", "铺底 7（光环）"),
    ("Pad 8 (sweep)", "铺底 8（扫频）"),
    ("FX 1 (rain)", "特效 1（雨）"),
    ("FX 2 (soundtrack)", "特效 2（原声背景）"),
    ("FX 3 (crystal)", "特效 3（水晶）"),
    ("FX 4 (atmosphere)", "特效 4（氛围）"),
    ("FX 5 (brightness)", "特效 5（明亮）"),
    ("FX 6 (goblins)", "特效 6（妖怪）"),
    ("FX 7 (echoes)", "特效 7（回声）"),
    ("FX 8 (sci-fi)", "特效 8（科幻）"),
    ("Sitar", "西塔琴"),
    ("Banjo", "班卓琴"),
    ("Shamisen", "三味线"),
    ("Koto", "古筝"),
    ("Kalimba", "卡林巴"),
    ("Bag pipe", "风笛"),
    ("Fiddle", "民谣提琴"),
    ("Shanai", "唢呐"),
    ("Tinkle Bell", "铃铛"),
    ("Agogo", "阿哥哥铃"),
    ("Steel Drums", "钢鼓"),
    ("Woodblock", "木鱼"),
    ("Taiko Drum", "太鼓"),
    ("Melodic Tom", "旋律嗵鼓"),
    ("Synth Drum", "合成鼓"),
    ("Reverse Cymbal", "反镲"),
    ("Guitar Fret Noise", "吉他品噪"),
    ("Breath Noise", "呼吸声"),
    ("Seashore", "海浪"),
    ("Bird Tweet", "鸟鸣"),
    ("Telephone Ring", "电话铃"),
    ("Helicopter", "直升机"),
    ("Applause", "掌声"),
    ("Gunshot", "枪声"),
)

MAX_PROGRAM = len(_NAMES) - 1


def _family_for(program: int) -> dict[str, str]:
    return FAMILIES[min(len(FAMILIES) - 1, program // 8)]


def clamp_program(value: Any) -> int:
    """把任意输入收敛到合法 program；非法值回落 0（大钢琴）。"""
    try:
        program = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_PROGRAM, program))


def instrument(program: Any) -> dict[str, Any]:
    """program → 乐器描述（含中英文名与音色族）。"""
    index = clamp_program(program)
    name_en, name_zh = _NAMES[index]
    family = _family_for(index)
    return {
        "program": index,
        "name_en": name_en,
        "name_zh": name_zh,
        "family": family["id"],
        "family_zh": family["name_zh"],
        "family_en": family["name_en"],
    }


def catalog() -> list[dict[str, Any]]:
    """完整音色表，前端直接拿来做选择器（按音色族分组）。"""
    return [instrument(index) for index in range(len(_NAMES))]


def families() -> list[dict[str, Any]]:
    """音色族 + 每组内的 program 列表，供前端分组下拉。"""
    grouped: dict[str, list[int]] = {family["id"]: [] for family in FAMILIES}
    for index in range(len(_NAMES)):
        grouped[_family_for(index)["id"]].append(index)
    return [
        {
            **family,
            "programs": grouped[family["id"]],
            "default_program": _default_program(family["id"]),
        }
        for family in FAMILIES
    ]


def _default_program(family_id: str) -> int:
    for index, family in enumerate(FAMILIES):
        if family["id"] == family_id:
            return min(MAX_PROGRAM, index * 8 + _DEFAULT_OFFSET.get(family_id, 0))
    return 0


def default_program(family_id: str = "piano") -> int:
    """某音色族的默认音色；给「新增声部」用。"""
    return _default_program(str(family_id or "piano"))


def family_of(program: Any) -> str:
    return instrument(program)["family"]


def name_of(program: Any, *, lang: str = "zh") -> str:
    info = instrument(program)
    return str(info["name_zh"] if lang == "zh" else info["name_en"])


# 默认声部所用的音色：钢琴 / 弦乐 / 贝斯 / 鼓组。
PRESET_INSTRUMENTS: tuple[int, ...] = (0, 48, 33, 0)
