/**
 * MIDI 子编辑器的纯计算工具（钢琴卷帘坐标、吸附、音符归一化）。
 *
 * 组件只负责画与交互，所有「时间 ↔ 像素、音高 ↔ 行、拖动/拉伸后落到哪里」的
 * 计算都放在这里，方便单测，也保证前后端对音符边界的理解一致。
 */

export interface MidiNote {
  id: string
  start: number
  end: number
  pitch: number
  detune: number
}

/** 任何「有时间、有音高」的音符（音高重绘音符与编曲音符共用的几何接口）。 */
export interface NoteLike {
  start: number
  end: number
  pitch: number
}

export const MIDI_PITCH_MIN = 24
export const MIDI_PITCH_MAX = 108
export const MIDI_MIN_NOTE_SECONDS = 0.03
export const MIDI_DEFAULT_GRID = 0.1
export const MIDI_GRID_OPTIONS = [0.02, 0.05, 0.1, 0.25, 0.5] as const
/** 最小可点击宽度：短音符按真实时长画会小到点不中，命中与显示都按这个下限。 */
export const MIDI_MIN_NOTE_PX = 7
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

export function clampPitch(pitch: number): number {
  const value = Number.isFinite(pitch) ? pitch : 60
  return Math.min(MIDI_PITCH_MAX, Math.max(MIDI_PITCH_MIN, Math.round(value)))
}

export function clampDetune(detune: number): number {
  const value = Number.isFinite(detune) ? detune : 0
  return Math.min(99, Math.max(-99, Math.round(value)))
}

export function noteName(pitch: number): string {
  const index = Math.round(pitch)
  const name = NOTE_NAMES[((index % 12) + 12) % 12]
  const octave = Math.floor(index / 12) - 1
  return `${name}${octave}`
}

export function isBlackKey(pitch: number): boolean {
  return NOTE_NAMES[((Math.round(pitch) % 12) + 12) % 12]?.includes('#') ?? false
}

/** 吸附到网格；grid <= 0 时不吸附。 */
export function snapTime(time: number, grid: number): number {
  if (!Number.isFinite(time)) return 0
  if (!(grid > 0)) return Math.max(0, time)
  return Math.round(time / grid) * grid
}

export function clampTime(time: number, duration: number): number {
  if (!Number.isFinite(time)) return 0
  return Math.min(Math.max(0, duration), Math.max(0, time))
}

/** 音符区间内的合法边界：至少保留最小长度。 */
export function clampNoteSpan(
  start: number,
  end: number,
  duration: number,
): { start: number; end: number } {
  const limit = Math.max(MIDI_MIN_NOTE_SECONDS, duration)
  let left = clampTime(start, limit)
  let right = clampTime(end, limit)
  if (right - left < MIDI_MIN_NOTE_SECONDS) {
    right = Math.min(limit, left + MIDI_MIN_NOTE_SECONDS)
    left = Math.max(0, right - MIDI_MIN_NOTE_SECONDS)
  }
  return { start: round(left), end: round(right) }
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000
}

export function normalizeNote(note: Partial<MidiNote>, duration: number, index = 0): MidiNote | null {
  const span = clampNoteSpan(Number(note.start ?? 0), Number(note.end ?? 0), duration)
  if (span.end - span.start < MIDI_MIN_NOTE_SECONDS) return null
  return {
    id: String(note.id || `midi_${index + 1}`),
    start: span.start,
    end: span.end,
    pitch: clampPitch(Number(note.pitch ?? 60)),
    detune: clampDetune(Number(note.detune ?? 0)),
  }
}

/** 归一化整串音符：排序、去重叠、去重 ID。 */
export function normalizeNotes(notes: Partial<MidiNote>[], duration: number): MidiNote[] {
  const cleaned: MidiNote[] = []
  for (let index = 0; index < notes.length; index += 1) {
    const note = normalizeNote(notes[index] ?? {}, duration, index)
    if (note) cleaned.push(note)
  }
  cleaned.sort((a, b) => a.start - b.start || a.pitch - b.pitch)
  const used = new Set<string>()
  cleaned.forEach((note, index) => {
    if (used.has(note.id)) note.id = `midi_${index + 1}`
    used.add(note.id)
  })
  for (let index = 0; index < cleaned.length - 1; index += 1) {
    const current = cleaned[index]!
    const next = cleaned[index + 1]!
    if (current.end > next.start) current.end = Math.max(current.start + MIDI_MIN_NOTE_SECONDS, next.start)
  }
  return cleaned.filter((note) => note.end - note.start >= MIDI_MIN_NOTE_SECONDS)
}

export function createNote(
  start: number,
  pitch: number,
  duration: number,
  grid: number,
  length = 0.25,
): MidiNote {
  const left = snapTime(clampTime(start, duration), grid)
  const span = clampNoteSpan(left, left + Math.max(MIDI_MIN_NOTE_SECONDS, length), duration)
  return {
    id: `midi_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    start: span.start,
    end: span.end,
    pitch: clampPitch(pitch),
    detune: 0,
  }
}

/** 拖动音符主体：同时改时间与音高，撞到片段边界时保持音符长度。 */
export function moveNote(
  note: MidiNote,
  deltaSeconds: number,
  deltaPitch: number,
  duration: number,
  grid: number,
): MidiNote {
  const length = Math.max(MIDI_MIN_NOTE_SECONDS, note.end - note.start)
  const limit = Math.max(0, duration - length)
  const left = snapTime(clampTime(note.start + deltaSeconds, limit), grid)
  const span = clampNoteSpan(Math.min(left, limit), Math.min(duration, left + length), duration)
  return { ...note, start: span.start, end: span.end, pitch: clampPitch(note.pitch + deltaPitch) }
}

/** 拖动左右边缘：只改起止时间。 */
export function resizeNote(
  note: MidiNote,
  edge: 'start' | 'end',
  time: number,
  duration: number,
  grid: number,
): MidiNote {
  const target = snapTime(clampTime(time, duration), grid)
  if (edge === 'start') {
    const span = clampNoteSpan(Math.min(target, note.end - MIDI_MIN_NOTE_SECONDS), note.end, duration)
    return { ...note, start: span.start, end: span.end }
  }
  const span = clampNoteSpan(note.start, Math.max(target, note.start + MIDI_MIN_NOTE_SECONDS), duration)
  return { ...note, start: span.start, end: span.end }
}

/** 自动音域：围绕实际音符上下各留一个八度，最少两个八度；无音符时用默认音域。 */
export function pitchBounds(
  notes: MidiNote[],
  minimum = 48,
  maximum = 84,
): { min: number; max: number } {
  if (!notes.length) return { min: minimum, max: maximum }
  let noteLow = Infinity
  let noteHigh = -Infinity
  for (const note of notes) {
    if (note.pitch < noteLow) noteLow = note.pitch
    if (note.pitch > noteHigh) noteHigh = note.pitch
  }
  let low = Math.max(MIDI_PITCH_MIN, noteLow - 12)
  let high = Math.min(MIDI_PITCH_MAX, noteHigh + 12)
  const minimumSpan = 24
  if (high - low < minimumSpan) {
    const centre = (noteLow + noteHigh) / 2
    low = Math.max(MIDI_PITCH_MIN, Math.floor(centre - minimumSpan / 2))
    high = Math.min(MIDI_PITCH_MAX, low + minimumSpan)
    if (high - low < minimumSpan) low = Math.max(MIDI_PITCH_MIN, high - minimumSpan)
  }
  return { min: low, max: high }
}

/** 命中测试：返回点击位置下最上层的音符（后添加的优先）。 */
export function noteAtTimePitch(
  notes: MidiNote[],
  time: number,
  pitch: number,
  tolerance = 0.1,
): MidiNote | undefined {
  for (let index = notes.length - 1; index >= 0; index -= 1) {
    const note = notes[index]!
    if (note.pitch !== pitch) continue
    if (time >= note.start - tolerance && time <= note.end + tolerance) return note
  }
  return undefined
}

export function timeToX(time: number, pxPerSecond: number): number {
  return time * pxPerSecond
}

export function xToTime(x: number, pxPerSecond: number): number {
  if (!(pxPerSecond > 0)) return 0
  return x / pxPerSecond
}

export function pitchToY(pitch: number, topPitch: number, rowHeight: number): number {
  return (topPitch - pitch) * rowHeight
}

export function yToPitch(y: number, topPitch: number, rowHeight: number): number {
  if (!(rowHeight > 0)) return topPitch
  return topPitch - Math.floor(y / rowHeight)
}

export function noteRect(
  note: NoteLike,
  topPitch: number,
  rowHeight: number,
  pxPerSecond: number,
  minWidth = MIDI_MIN_NOTE_PX,
): { x: number; y: number; width: number; height: number } {
  const x = timeToX(note.start, pxPerSecond)
  const width = Math.max(minWidth, timeToX(note.end - note.start, pxPerSecond))
  return { x, y: pitchToY(note.pitch, topPitch, rowHeight), width, height: rowHeight - 1 }
}

/** 按画布坐标命中音符（后添加的优先，带少量容差，短音符也能点中）。 */
export function noteAtPoint<T extends NoteLike>(
  notes: T[],
  x: number,
  y: number,
  topPitch: number,
  rowHeight: number,
  pxPerSecond: number,
  padding = 2,
  minWidth = MIDI_MIN_NOTE_PX,
): T | undefined {
  for (let index = notes.length - 1; index >= 0; index -= 1) {
    const note = notes[index]!
    const rect = noteRect(note, topPitch, rowHeight, pxPerSecond, minWidth)
    if (
      x >= rect.x - padding &&
      x <= rect.x + rect.width + padding &&
      y >= rect.y - padding &&
      y <= rect.y + rect.height + padding
    ) {
      return note
    }
  }
  return undefined
}

/** 命中音符的左右边缘（用于拉伸）；太窄的音符不做边缘命中，避免拖不动。 */
export function noteEdgeAt(
  note: NoteLike,
  x: number,
  topPitch: number,
  rowHeight: number,
  pxPerSecond: number,
  edgeWidth = 6,
  minWidth = MIDI_MIN_NOTE_PX,
): 'start' | 'end' | 'move' {
  const rect = noteRect(note, topPitch, rowHeight, pxPerSecond, minWidth)
  if (rect.width < edgeWidth * 2 + 4) return 'move'
  if (x - rect.x <= edgeWidth) return 'start'
  if (rect.x + rect.width - x <= edgeWidth) return 'end'
  return 'move'
}

export function quantizeNotes(
  notes: MidiNote[],
  ids: string[],
  grid: number,
  duration: number,
): MidiNote[] {
  const selected = new Set(ids)
  return notes.map((note) => {
    if (!selected.has(note.id)) return note
    const left = snapTime(note.start, grid)
    const length = Math.max(MIDI_MIN_NOTE_SECONDS, note.end - note.start)
    const span = clampNoteSpan(left, left + length, duration)
    return { ...note, start: span.start, end: span.end }
  })
}

export function transposeNotes(notes: MidiNote[], ids: string[], semitones: number): MidiNote[] {
  const selected = new Set(ids)
  return notes.map((note) =>
    selected.has(note.id) ? { ...note, pitch: clampPitch(note.pitch + semitones) } : note,
  )
}

/** 多选整体平移：偏移量按整组可移动范围裁剪，保持音符之间相对关系。 */
export function moveNotes(
  notes: MidiNote[],
  ids: string[],
  deltaSeconds: number,
  deltaPitch: number,
  duration: number,
  grid: number,
): MidiNote[] {
  const selected = new Set(ids)
  const group = notes.filter((note) => selected.has(note.id))
  if (!group.length) return notes
  const minStart = Math.min(...group.map((note) => note.start))
  const maxEnd = Math.max(...group.map((note) => note.end))
  const limited = Math.min(Math.max(deltaSeconds, -minStart), Math.max(0, duration - maxEnd))
  const shifted = snapTime(limited, grid)
  const bounded = Math.min(Math.max(shifted, -minStart), Math.max(0, duration - maxEnd))
  const lowest = Math.min(...group.map((note) => note.pitch))
  const highest = Math.max(...group.map((note) => note.pitch))
  const pitchShift = Math.min(
    Math.max(deltaPitch, MIDI_PITCH_MIN - lowest),
    MIDI_PITCH_MAX - highest,
  )
  return notes.map((note) =>
    selected.has(note.id)
      ? {
          ...note,
          start: round(clampTime(note.start + bounded, duration)),
          end: round(clampTime(note.end + bounded, duration)),
          pitch: clampPitch(note.pitch + pitchShift),
        }
      : note,
  )
}

/** 复制选中的音符（返回深拷贝，粘贴时再生成新 ID）。 */
export function copyNotes(notes: MidiNote[], ids: string[]): MidiNote[] {
  const selected = new Set(ids)
  return notes
    .filter((note) => selected.has(note.id))
    .map((note) => ({ ...note }))
    .sort((a, b) => a.start - b.start || a.pitch - b.pitch)
}

/** 把剪贴板音符粘贴到指定时间点，整体不越界并重新编号。 */
export function pasteNotes(
  clipboard: MidiNote[],
  atTime: number,
  duration: number,
): MidiNote[] {
  if (!clipboard.length) return []
  const anchor = Math.min(...clipboard.map((note) => note.start))
  const shift = Math.max(0, atTime - anchor)
  const longest = Math.max(...clipboard.map((note) => note.end - note.start))
  const bounded = Math.min(shift, Math.max(0, duration - longest))
  const stamp = Date.now().toString(36)
  return clipboard.map((note, index) => ({
    ...note,
    id: `midi_${stamp}_${index + 1}`,
    start: round(note.start + bounded),
    end: round(Math.min(duration, note.end + bounded)),
  }))
}

/** 让某段时长正好铺满画布宽度的缩放值。 */
export function fitZoom(duration: number, width: number, minimum = 24, maximum = 640): number {
  if (!(duration > 0) || !(width > 0)) return minimum
  return Math.min(maximum, Math.max(minimum, Math.round(width / duration)))
}

/** 试听播放头：秒 → 画布 x（超出范围时返回 null）。 */
export function playheadX(seconds: number, pxPerSecond: number, duration: number): number | null {
  if (!Number.isFinite(seconds) || seconds < 0 || seconds > duration) return null
  return timeToX(seconds, pxPerSecond)
}

/* --------------------------------------------------------------------------
 * MIDI 编曲（多乐器音序器）
 *
 * 音高重绘（上面的 MidiNote）关注的是「把演唱修到某个半音 + 音分」；
 * 编曲关注的是「从零写谱」：多声部、每声部一件乐器、音符带力度。
 * 这一段的计算全部是纯函数，组件只负责画。
 * ----------------------------------------------------------------------- */

export interface MidiComposeNote {
  id: string
  start: number
  end: number
  pitch: number
  velocity: number
}

export interface MidiPart {
  id: string
  name: string
  instrument: number
  drum: boolean
  channel: number
  volume: number
  pan: number
  mute: boolean
  solo: boolean
  color: string
  notes: MidiComposeNote[]
}

export interface MidiSession {
  version: number
  tempo: number
  time_signature: number[]
  parts: MidiPart[]
  name?: string
  loop?: boolean
  metronome?: boolean
}

export const COMPOSE_PITCH_MIN = 0
export const COMPOSE_PITCH_MAX = 127
export const COMPOSE_MIN_NOTE_SECONDS = 0.02
export const COMPOSE_DEFAULT_VELOCITY = 100
export const COMPOSE_MIN_TEMPO = 20
export const COMPOSE_MAX_TEMPO = 400
export const COMPOSE_DEFAULT_TEMPO = 120
export const TIME_SIGNATURE_CHOICES: ReadonlyArray<readonly [number, number]> = [
  [2, 4],
  [3, 4],
  [4, 4],
  [5, 4],
  [6, 8],
  [7, 8],
  [3, 8],
  [12, 8],
]
export const PART_COLORS = [
  '#5ec2ff',
  '#ffb454',
  '#8ee36b',
  '#ff7a9c',
  '#b98cff',
  '#4fd8c8',
  '#ffd166',
  '#7fa6ff',
] as const

/**
 * GM 音色表（128 个）。后端也会下发同一份目录，这里内嵌一份兜底实现：
 * 无论后端是否可用、是否是浏览器 mock，乐器选择器都必须显示**具体乐器名**，
 * 不能退化成「钢琴 1 / 贝斯 2」这种带编号的占位名。
 */
const GM_NAMES_ZH = [
  '原声大钢琴', '明亮钢琴', '电钢琴（大）', '酒吧钢琴', '电钢琴 1', '电钢琴 2', '大键琴', '击弦古钢琴',
  '钢片琴', '钟琴', '八音盒', '颤音琴', '马林巴', '木琴', '管钟', '洋琴',
  '拉杆风琴', '打击风琴', '摇滚风琴', '教堂管风琴', '簧风琴', '手风琴', '口琴', '探戈手风琴',
  '尼龙弦吉他', '钢弦吉他', '爵士电吉他', '清音电吉他', '闷音电吉他', '过载吉他', '失真吉他', '吉他泛音',
  '原声贝斯', '指弹电贝斯', '拨片电贝斯', '无品贝斯', '击弦贝斯 1', '击弦贝斯 2', '合成贝斯 1', '合成贝斯 2',
  '小提琴', '中提琴', '大提琴', '低音提琴', '颤弓弦乐', '拨弦弦乐', '管弦竖琴', '定音鼓',
  '弦乐合奏 1', '弦乐合奏 2', '合成弦乐 1', '合成弦乐 2', '人声合唱「啊」', '人声「呜」', '合成人声', '管弦乐重音',
  '小号', '长号', '大号', '弱音小号', '圆号', '铜管组', '合成铜管 1', '合成铜管 2',
  '高音萨克斯', '中音萨克斯', '次中音萨克斯', '低音萨克斯', '双簧管', '英国管', '大管', '单簧管',
  '短笛', '长笛', '竖笛', '排箫', '吹瓶', '尺八', '哨笛', '陶笛',
  '主音 1（方波）', '主音 2（锯齿）', '主音 3（汽笛风琴）', '主音 4（气声）', '主音 5（查朗）', '主音 6（人声）', '主音 7（五度）', '主音 8（贝斯＋主音）',
  '铺底 1（新世纪）', '铺底 2（温暖）', '铺底 3（复合成）', '铺底 4（合唱）', '铺底 5（弓弦）', '铺底 6（金属）', '铺底 7（光环）', '铺底 8（扫频）',
  '特效 1（雨）', '特效 2（原声背景）', '特效 3（水晶）', '特效 4（氛围）', '特效 5（明亮）', '特效 6（妖怪）', '特效 7（回声）', '特效 8（科幻）',
  '西塔琴', '班卓琴', '三味线', '古筝', '卡林巴', '风笛', '民谣提琴', '唢呐',
  '铃铛', '阿哥哥铃', '钢鼓', '木鱼', '太鼓', '旋律嗵鼓', '合成鼓', '反镲',
  '吉他品噪', '呼吸声', '海浪', '鸟鸣', '电话铃', '直升机', '掌声', '枪声',
] as const

const GM_NAMES_EN = [
  'Acoustic Grand Piano', 'Bright Acoustic Piano', 'Electric Grand Piano', 'Honky-tonk Piano',
  'Electric Piano 1', 'Electric Piano 2', 'Harpsichord', 'Clavinet',
  'Celesta', 'Glockenspiel', 'Music Box', 'Vibraphone', 'Marimba', 'Xylophone', 'Tubular Bells', 'Dulcimer',
  'Drawbar Organ', 'Percussive Organ', 'Rock Organ', 'Church Organ', 'Reed Organ', 'Accordion', 'Harmonica',
  'Tango Accordion',
  'Acoustic Guitar (nylon)', 'Acoustic Guitar (steel)', 'Electric Guitar (jazz)', 'Electric Guitar (clean)',
  'Electric Guitar (muted)', 'Overdriven Guitar', 'Distortion Guitar', 'Guitar Harmonics',
  'Acoustic Bass', 'Electric Bass (finger)', 'Electric Bass (pick)', 'Fretless Bass',
  'Slap Bass 1', 'Slap Bass 2', 'Synth Bass 1', 'Synth Bass 2',
  'Violin', 'Viola', 'Cello', 'Contrabass', 'Tremolo Strings', 'Pizzicato Strings', 'Orchestral Harp', 'Timpani',
  'String Ensemble 1', 'String Ensemble 2', 'Synth Strings 1', 'Synth Strings 2', 'Choir Aahs', 'Voice Oohs',
  'Synth Voice', 'Orchestra Hit',
  'Trumpet', 'Trombone', 'Tuba', 'Muted Trumpet', 'French Horn', 'Brass Section', 'Synth Brass 1', 'Synth Brass 2',
  'Soprano Sax', 'Alto Sax', 'Tenor Sax', 'Baritone Sax', 'Oboe', 'English Horn', 'Bassoon', 'Clarinet',
  'Piccolo', 'Flute', 'Recorder', 'Pan Flute', 'Blown Bottle', 'Shakuhachi', 'Whistle', 'Ocarina',
  'Lead 1 (square)', 'Lead 2 (sawtooth)', 'Lead 3 (calliope)', 'Lead 4 (chiff)', 'Lead 5 (charang)',
  'Lead 6 (voice)', 'Lead 7 (fifths)', 'Lead 8 (bass + lead)',
  'Pad 1 (new age)', 'Pad 2 (warm)', 'Pad 3 (polysynth)', 'Pad 4 (choir)', 'Pad 5 (bowed)', 'Pad 6 (metallic)',
  'Pad 7 (halo)', 'Pad 8 (sweep)',
  'FX 1 (rain)', 'FX 2 (soundtrack)', 'FX 3 (crystal)', 'FX 4 (atmosphere)', 'FX 5 (brightness)', 'FX 6 (goblins)',
  'FX 7 (echoes)', 'FX 8 (sci-fi)',
  'Sitar', 'Banjo', 'Shamisen', 'Koto', 'Kalimba', 'Bag pipe', 'Fiddle', 'Shanai',
  'Tinkle Bell', 'Agogo', 'Steel Drums', 'Woodblock', 'Taiko Drum', 'Melodic Tom', 'Synth Drum', 'Reverse Cymbal',
  'Guitar Fret Noise', 'Breath Noise', 'Seashore', 'Bird Tweet', 'Telephone Ring', 'Helicopter', 'Applause', 'Gunshot',
] as const

/** 16 个音色族（program 每 8 个一族）。 */
export const GM_FAMILIES: ReadonlyArray<{ id: string; name: string; name_en: string; programs: number[] }> = [
  { id: 'piano', name: '钢琴', name_en: 'Piano' },
  { id: 'chromatic', name: '色彩打击', name_en: 'Chromatic Percussion' },
  { id: 'organ', name: '风琴', name_en: 'Organ' },
  { id: 'guitar', name: '吉他', name_en: 'Guitar' },
  { id: 'bass', name: '贝斯', name_en: 'Bass' },
  { id: 'strings', name: '弦乐', name_en: 'Strings' },
  { id: 'ensemble', name: '合奏', name_en: 'Ensemble' },
  { id: 'brass', name: '铜管', name_en: 'Brass' },
  { id: 'reed', name: '簧管', name_en: 'Reed' },
  { id: 'pipe', name: '吹管', name_en: 'Pipe' },
  { id: 'lead', name: '合成主音', name_en: 'Synth Lead' },
  { id: 'pad', name: '合成铺底', name_en: 'Synth Pad' },
  { id: 'fx', name: '合成特效', name_en: 'Synth Effects' },
  { id: 'ethnic', name: '民族乐器', name_en: 'Ethnic' },
  { id: 'percussive', name: '打击乐', name_en: 'Percussive' },
  { id: 'sfx', name: '音效', name_en: 'Sound Effects' },
].map((family, index) => ({
  ...family,
  programs: Array.from({ length: 8 }, (_, offset) => index * 8 + offset),
}))

export interface GmInstrument {
  program: number
  name_zh: string
  name_en: string
  family: string
  family_zh: string
}

/** 128 个 GM 乐器（索引即 program）。 */
export const GM_INSTRUMENTS: ReadonlyArray<GmInstrument> = GM_NAMES_ZH.map((nameZh, index) => ({
  program: index,
  name_zh: nameZh,
  name_en: GM_NAMES_EN[index] || nameZh,
  family: GM_FAMILIES[Math.floor(index / 8)]?.id || 'piano',
  family_zh: GM_FAMILIES[Math.floor(index / 8)]?.name || '钢琴',
}))

/** 把任意 program 收敛到合法范围。 */
export function clampProgram(program: number): number {
  const value = Number.isFinite(program) ? Math.round(program) : 0
  return Math.min(127, Math.max(0, value))
}

/** program → 具体乐器名（中文）。 */
export function instrumentName(program: number): string {
  return GM_INSTRUMENTS[clampProgram(program)]?.name_zh || '原声大钢琴'
}

/** program → 所属音色族名。 */
export function instrumentFamilyName(program: number): string {
  return GM_INSTRUMENTS[clampProgram(program)]?.family_zh || '钢琴'
}

/** 兼容旧名字：兜底也返回具体乐器名，不再出现「钢琴 1」这类编号占位。 */
export function fallbackInstrumentLabel(program: number): string {
  return instrumentName(program)
}

/* --------------------------------------------------------------------------
 * 架子鼓（GM 打击乐）
 *
 * MIDI 鼓组没有音高，只有鼓件：第 10 通道上 35~81 每个音高对应一件打击乐器。
 * 钢琴卷帘在鼓组声部里显示鼓件名、并把新音符吸附到真实鼓件上。
 * ----------------------------------------------------------------------- */

export type DrumGroup = 'kick' | 'snare' | 'rim' | 'clap' | 'hat' | 'hat_open' | 'tom' | 'crash' | 'ride' | 'perc'

export interface DrumPiece {
  pitch: number
  name_zh: string
  group: DrumGroup
  group_zh: string
}

// (pitch, 名称, 分组)
const DRUM_RAW: ReadonlyArray<readonly [number, string, DrumGroup]> = [
  [35, '底鼓 2', 'kick'],
  [36, '底鼓 1', 'kick'],
  [37, '军鼓边击', 'rim'],
  [38, '军鼓 1', 'snare'],
  [39, '拍手', 'clap'],
  [40, '军鼓 2', 'snare'],
  [41, '落地嗵鼓（低）', 'tom'],
  [42, '闭合踩镲', 'hat'],
  [43, '落地嗵鼓（高）', 'tom'],
  [44, '踩镲踏板', 'hat'],
  [45, '低音通鼓', 'tom'],
  [46, '开音踩镲', 'hat_open'],
  [47, '中低通鼓', 'tom'],
  [48, '中高通鼓', 'tom'],
  [49, '吊镲 1', 'crash'],
  [50, '高音通鼓', 'tom'],
  [51, '叮叮镲 1', 'ride'],
  [52, '中国镲', 'crash'],
  [53, '叮叮镲铃', 'ride'],
  [54, '铃鼓', 'perc'],
  [55, '水镲', 'crash'],
  [56, '牛铃', 'perc'],
  [57, '吊镲 2', 'crash'],
  [58, '颤音板', 'perc'],
  [59, '叮叮镲 2', 'ride'],
  [60, '邦戈鼓（高）', 'perc'],
  [61, '邦戈鼓（低）', 'perc'],
  [62, '康加鼓（闷）', 'perc'],
  [63, '康加鼓（开）', 'perc'],
  [64, '康加鼓（低）', 'perc'],
  [65, '天巴鼓（高）', 'perc'],
  [66, '天巴鼓（低）', 'perc'],
  [67, '阿哥哥（高）', 'perc'],
  [68, '阿哥哥（低）', 'perc'],
  [69, '沙锤（卡巴萨）', 'perc'],
  [70, '沙铃', 'perc'],
  [71, '短哨', 'perc'],
  [72, '长哨', 'perc'],
  [73, '短刮胡', 'perc'],
  [74, '长刮胡', 'perc'],
  [75, '响木', 'perc'],
  [76, '木鱼（高）', 'perc'],
  [77, '木鱼（低）', 'perc'],
  [78, '库伊卡（闷）', 'perc'],
  [79, '库伊卡（开）', 'perc'],
  [80, '三角铁（闷）', 'perc'],
  [81, '三角铁（开）', 'perc'],
]

const DRUM_GROUP_LABELS: Record<DrumGroup, string> = {
  kick: '底鼓',
  snare: '军鼓',
  rim: '边击',
  clap: '拍手',
  hat: '踩镲',
  hat_open: '开镲',
  tom: '通鼓',
  crash: '吊镲',
  ride: '叮叮镲',
  perc: '小打',
}

export const DRUM_PIECES: ReadonlyArray<DrumPiece> = DRUM_RAW.map(([pitch, nameZh, group]) => ({
  pitch,
  name_zh: nameZh,
  group,
  group_zh: DRUM_GROUP_LABELS[group],
}))

export const DRUM_PITCH_MIN = DRUM_PIECES[0]?.pitch ?? 35
export const DRUM_PITCH_MAX = DRUM_PIECES[DRUM_PIECES.length - 1]?.pitch ?? 81
/** 新建鼓组声部时的默认起始鼓件：军鼓（最容易听见）。 */
export const DRUM_DEFAULT_PITCH = 38

const DRUM_BY_PITCH = new Map<number, DrumPiece>(DRUM_PIECES.map((piece) => [piece.pitch, piece]))

export function isDrumPitch(pitch: number): boolean {
  return DRUM_BY_PITCH.has(Math.round(Number(pitch) || 0))
}

export function drumPiece(pitch: number): DrumPiece | undefined {
  return DRUM_BY_PITCH.get(Math.round(Number(pitch) || 0))
}

/** 音高 → 鼓件名；不在鼓组表里时回落到最接近的鼓件。 */
export function drumName(pitch: number): string {
  const piece = DRUM_BY_PITCH.get(nearestDrumPitch(pitch))
  return piece?.name_zh || '军鼓 1'
}

/** 最近的鼓件音高：鼓组里新建/拖动音符都吸附到真实鼓件上。 */
export function nearestDrumPitch(pitch: number): number {
  const target = Number.isFinite(pitch) ? pitch : DRUM_DEFAULT_PITCH
  let best = DRUM_PIECES[0]!.pitch
  let bestDistance = Infinity
  for (const piece of DRUM_PIECES) {
    const distance = Math.abs(piece.pitch - target)
    if (distance < bestDistance) {
      best = piece.pitch
      bestDistance = distance
    }
  }
  return best
}

export function drumGroupLabel(pitch: number): string {
  const piece = DRUM_BY_PITCH.get(nearestDrumPitch(pitch))
  return piece?.group_zh || '小打'
}

/**
 * 一段最基础的 4/4 摇滚节奏：底鼓 1、3 拍，军鼓 2、4 拍，八分闭合踩镲。
 * 用于鼓组声部的「填充基本节奏」。
 */
export function basicDrumBeat(
  secondsPerBeat: number,
  options: { bars?: number; start?: number; velocity?: number } = {},
): MidiComposeNote[] {
  const beat = Math.max(0.05, Number(secondsPerBeat) || 0.5)
  const bars = Math.max(1, Math.round(options.bars ?? 2))
  const start = Math.max(0, Number(options.start) || 0)
  const velocity = Math.max(1, Math.min(127, Math.round(options.velocity ?? 112)))
  const notes: MidiComposeNote[] = []
  const stamp = Date.now().toString(36)
  const add = (offsetBeats: number, pitch: number, lengthBeats: number, vel: number) => {
    const begin = start + offsetBeats * beat
    notes.push({
      id: `cd_${stamp}_${notes.length}`,
      start: round(begin),
      end: round(begin + Math.max(0.02, lengthBeats * beat)),
      pitch,
      velocity: clampVelocity(vel),
    })
  }
  for (let beatIndex = 0; beatIndex < bars * 4; beatIndex += 1) {
    const inBar = beatIndex % 4
    if (inBar === 0 || inBar === 2) add(beatIndex, 36, 0.25, velocity)
    if (inBar === 1 || inBar === 3) add(beatIndex, 38, 0.25, velocity - 6)
    add(beatIndex, 42, 0.2, Math.max(40, velocity - 34))
    add(beatIndex + 0.5, 42, 0.2, Math.max(36, velocity - 44))
  }
  return notes
}

/** 网格细分：beats 以四分音符为 1 拍（和主流 DAW 的 1/4、1/8 标记一致）。 */
export interface GridDivision {
  id: string
  label: string
  beats: number
  triplet?: boolean
}

export const GRID_DIVISIONS: readonly GridDivision[] = [
  { id: 'bar', label: '1 小节', beats: 4 },
  { id: '1/2', label: '1/2', beats: 2 },
  { id: '1/4', label: '1/4', beats: 1 },
  { id: '1/8', label: '1/8', beats: 0.5 },
  { id: '1/8t', label: '1/8T', beats: 1 / 3, triplet: true },
  { id: '1/16', label: '1/16', beats: 0.25 },
  { id: '1/16t', label: '1/16T', beats: 1 / 6, triplet: true },
  { id: '1/32', label: '1/32', beats: 0.125 },
  { id: 'off', label: '关闭', beats: 0 },
]

export function clampComposePitch(pitch: number): number {
  const value = Number.isFinite(pitch) ? pitch : 60
  return Math.min(COMPOSE_PITCH_MAX, Math.max(COMPOSE_PITCH_MIN, Math.round(value)))
}

export function clampVelocity(velocity: number): number {
  const value = Number.isFinite(velocity) ? velocity : COMPOSE_DEFAULT_VELOCITY
  return Math.min(127, Math.max(1, Math.round(value)))
}

export function clampTempo(tempo: number): number {
  const value = Number.isFinite(tempo) ? tempo : COMPOSE_DEFAULT_TEMPO
  return Math.min(COMPOSE_MAX_TEMPO, Math.max(COMPOSE_MIN_TEMPO, Math.round(value * 100) / 100))
}

export function secondsPerBeat(tempo: number): number {
  return 60 / Math.max(1, clampTempo(tempo))
}

/** 网格细分 → 秒；`off` 返回 0（不吸附）。 */
export function gridStepSeconds(tempo: number, division: GridDivision | string): number {
  const found =
    typeof division === 'string' ? GRID_DIVISIONS.find((item) => item.id === division) : division
  const beats = found?.beats ?? 0
  if (!(beats > 0)) return 0
  return secondsPerBeat(tempo) * beats
}

export function barSeconds(tempo: number, signature: number[] | readonly number[]): number {
  const numerator = Math.max(1, Number(signature?.[0]) || 4)
  const denominator = Math.max(1, Number(signature?.[1]) || 4)
  // 拍号 3/4 → 每小节 3 个四分音符；6/8 → 每小节 3 个四分音符。
  const quarters = (numerator * 4) / denominator
  return secondsPerBeat(tempo) * quarters
}

export function timeSignatureLabel(signature: number[] | readonly number[]): string {
  return `${Number(signature?.[0]) || 4}/${Number(signature?.[1]) || 4}`
}

/** 时间 → 小节/拍标签（1 起算），用于刻度尺。 */
export function barBeatLabel(
  time: number,
  tempo: number,
  signature: number[] | readonly number[],
): string {
  const bar = Math.max(0, barSeconds(tempo, signature))
  if (!(bar > 0)) return '1:1'
  const barIndex = Math.floor(time / bar)
  const beatLength = secondsPerBeat(tempo)
  const beat = beatLength > 0 ? Math.floor((time - barIndex * bar) / beatLength) + 1 : 1
  return `${barIndex + 1}:${beat}`
}

export function createComposeNote(
  start: number,
  pitch: number,
  duration: number,
  length: number,
  velocity = COMPOSE_DEFAULT_VELOCITY,
): MidiComposeNote {
  const limit = Math.max(COMPOSE_MIN_NOTE_SECONDS, duration)
  const left = Math.min(Math.max(0, start), Math.max(0, limit - COMPOSE_MIN_NOTE_SECONDS))
  const right = Math.min(limit, left + Math.max(COMPOSE_MIN_NOTE_SECONDS, length))
  return {
    id: `cn_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
    start: round(left),
    end: round(Math.max(right, left + COMPOSE_MIN_NOTE_SECONDS)),
    pitch: clampComposePitch(pitch),
    velocity: clampVelocity(velocity),
  }
}

export function createPart(
  index: number,
  options: { instrument?: number; drum?: boolean; name?: string; color?: string } = {},
): MidiPart {
  const drum = !!options.drum
  const instrument = drum ? 0 : Math.max(0, Math.min(127, Math.round(options.instrument ?? 0)))
  return {
    id: `part_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}${index}`,
    name: (options.name || (drum ? '鼓组' : `声部 ${index + 1}`)).slice(0, 48),
    instrument,
    drum,
    channel: drum ? 9 : index % 16 === 9 ? 0 : index % 16,
    volume: 1,
    pan: 0,
    mute: false,
    solo: false,
    color: options.color || PART_COLORS[index % PART_COLORS.length]!,
    notes: [],
  }
}

export function sortNotes<T extends { start: number; pitch: number }>(notes: T[]): T[] {
  return notes.slice().sort((a, b) => a.start - b.start || a.pitch - b.pitch)
}

export function sessionNoteCount(session: MidiSession | null | undefined): number {
  return (session?.parts || []).reduce((total, part) => total + (part.notes?.length ?? 0), 0)
}

export function sessionDuration(parts: MidiPart[] | MidiSession | null | undefined): number {
  const list = Array.isArray(parts) ? parts : parts?.parts || []
  let end = 0
  for (const part of list) {
    for (const note of part.notes || []) {
      if (note.end > end) end = note.end
    }
  }
  return end
}

export function partBounds(part: MidiPart): { start: number; end: number } | null {
  if (!part.notes?.length) return null
  let start = Infinity
  let end = 0
  for (const note of part.notes) {
    if (note.start < start) start = note.start
    if (note.end > end) end = note.end
  }
  return Number.isFinite(start) && end > start ? { start, end } : null
}

/** 所有声部的音高范围 → 钢琴卷帘的显示音域（上下各留一点余量）。 */
export function sessionPitchRange(
  parts: MidiPart[],
  minimum = 36,
  maximum = 96,
): { min: number; max: number } {
  let low = Infinity
  let high = -Infinity
  for (const part of parts || []) {
    for (const note of part.notes || []) {
      if (note.pitch < low) low = note.pitch
      if (note.pitch > high) high = note.pitch
    }
  }
  if (!Number.isFinite(low) || !Number.isFinite(high)) return { min: minimum, max: maximum }
  const min = Math.min(minimum, Math.max(COMPOSE_PITCH_MIN, low - 6))
  const max = Math.max(maximum, Math.min(COMPOSE_PITCH_MAX, high + 6))
  return { min, max }
}

/** 力度 → 音符块的不透明度/亮度，让卷帘一眼能看出轻重。 */
export function velocityAlpha(velocity: number): number {
  return 0.42 + (clampVelocity(velocity) / 127) * 0.58
}

/** 编曲音符的命中测试（按声部颜色区分，优先返回上层声部）。 */
export function composeNoteAtPoint(
  parts: MidiPart[],
  x: number,
  y: number,
  topPitch: number,
  rowHeight: number,
  pxPerSecond: number,
  padding = 2,
  minWidth = MIDI_MIN_NOTE_PX,
): { part: MidiPart; note: MidiComposeNote } | undefined {
  for (let partIndex = parts.length - 1; partIndex >= 0; partIndex -= 1) {
    const part = parts[partIndex]!
    if (part.mute) continue
    for (let index = part.notes.length - 1; index >= 0; index -= 1) {
      const note = part.notes[index]!
      const rect = noteRect(note, topPitch, rowHeight, pxPerSecond, minWidth)
      if (
        x >= rect.x - padding &&
        x <= rect.x + rect.width + padding &&
        y >= rect.y - padding &&
        y <= rect.y + rect.height + padding
      ) {
        return { part, note }
      }
    }
  }
  return undefined
}

/** 多声部整体平移：同时改时间与音高，保持组内相对关系并夹在时间轴内。 */
export function moveComposeNotes(
  parts: MidiPart[],
  idSet: Set<string>,
  deltaSeconds: number,
  deltaPitch: number,
  duration: number,
  step: number,
): MidiPart[] {
  const selected = parts.flatMap((part) =>
    part.notes.filter((note) => idSet.has(note.id)).map((note) => ({ part, note })),
  )
  if (!selected.length) return parts
  const minStart = Math.min(...selected.map((item) => item.note.start))
  const maxEnd = Math.max(...selected.map((item) => item.note.end))
  const lowest = Math.min(...selected.map((item) => item.note.pitch))
  const highest = Math.max(...selected.map((item) => item.note.pitch))
  const limited = Math.min(Math.max(deltaSeconds, -minStart), Math.max(0, duration - maxEnd))
  const shifted = step > 0 ? snapTime(limited, step) : limited
  const bounded = Math.min(Math.max(shifted, -minStart), Math.max(0, duration - maxEnd))
  const pitchShift = Math.min(
    Math.max(deltaPitch, COMPOSE_PITCH_MIN - lowest),
    COMPOSE_PITCH_MAX - highest,
  )
  return parts.map((part) => ({
    ...part,
    notes: part.notes.map((note) =>
      idSet.has(note.id)
        ? {
            ...note,
            start: round(clampTime(note.start + bounded, duration)),
            end: round(clampTime(note.end + bounded, duration)),
            pitch: clampComposePitch(note.pitch + pitchShift),
          }
        : note,
    ),
  }))
}

/** 拖左右边缘改长度。 */
export function resizeComposeNote(
  note: MidiComposeNote,
  edge: 'start' | 'end',
  time: number,
  duration: number,
  step: number,
): MidiComposeNote {
  const target = step > 0 ? snapTime(clampTime(time, duration), step) : clampTime(time, duration)
  if (edge === 'start') {
    const start = Math.min(Math.max(0, target), note.end - COMPOSE_MIN_NOTE_SECONDS)
    return { ...note, start: round(start), end: round(note.end) }
  }
  const end = Math.max(Math.min(duration, target), note.start + COMPOSE_MIN_NOTE_SECONDS)
  return { ...note, start: round(note.start), end: round(end) }
}

/** 量化：start 吸附到网格，长度保持；strength 为 0~1 的吸附强度（0.5 = 只走一半）。 */
export function quantizeComposeNotes(
  notes: MidiComposeNote[],
  step: number,
  duration: number,
  strength = 1,
): MidiComposeNote[] {
  if (!(step > 0)) return notes
  const amount = Math.min(1, Math.max(0, strength))
  return notes.map((note) => {
    const snapped = snapTime(note.start, step)
    const start = clampTime(note.start + (snapped - note.start) * amount, duration)
    const length = Math.max(COMPOSE_MIN_NOTE_SECONDS, note.end - note.start)
    return {
      ...note,
      start: round(start),
      end: round(Math.min(Math.max(duration, start + COMPOSE_MIN_NOTE_SECONDS), start + length)),
    }
  })
}

export function scaleNoteVelocity(
  notes: MidiComposeNote[],
  factor: number,
  offset = 0,
): MidiComposeNote[] {
  return notes.map((note) => ({
    ...note,
    velocity: clampVelocity(note.velocity * factor + offset),
  }))
}

/** 人性化：时间和力度都加一点随机偏移，避免机械感。 */
export function humanizeNotes(
  notes: MidiComposeNote[],
  timing: number,
  velocityRange: number,
  duration: number,
  random: () => number = Math.random,
): MidiComposeNote[] {
  return notes.map((note) => {
    const shift = (random() * 2 - 1) * Math.max(0, timing)
    const start = clampTime(note.start + shift, duration)
    const length = Math.max(COMPOSE_MIN_NOTE_SECONDS, note.end - note.start)
    const jitter = Math.round((random() * 2 - 1) * Math.max(0, velocityRange))
    return {
      ...note,
      start: round(start),
      end: round(Math.min(duration, start + length)),
      velocity: clampVelocity(note.velocity + jitter),
    }
  })
}

/** 连奏：把每个音的结束时间拉到下一个音开始处（可留一点空隙）。 */
export function legatoNotes(
  notes: MidiComposeNote[],
  step: number,
  gap = 0.02,
  maxLength = 4,
): MidiComposeNote[] {
  const ordered = sortNotes(notes)
  return ordered.map((note, index) => {
    const next = ordered[index + 1]
    if (!next) return note
    const limit = Math.min(next.start - gap, note.start + maxLength * Math.max(0.05, step || 0.25))
    if (limit <= note.start + COMPOSE_MIN_NOTE_SECONDS) return note
    return { ...note, end: round(Math.max(note.end, limit)) }
  })
}

export function transposeComposeNotes(
  notes: MidiComposeNote[],
  semitones: number,
): MidiComposeNote[] {
  return notes.map((note) => ({ ...note, pitch: clampComposePitch(note.pitch + semitones) }))
}

/** 在指定时间点切开音符；返回两段（点不到就返回 null）。 */
export function splitNoteAt(
  note: MidiComposeNote,
  time: number,
): [MidiComposeNote, MidiComposeNote] | null {
  if (!(time > note.start + COMPOSE_MIN_NOTE_SECONDS)) return null
  if (!(time < note.end - COMPOSE_MIN_NOTE_SECONDS)) return null
  const stamp = Date.now().toString(36)
  return [
    { ...note, id: `${note.id}_a${stamp}`, end: round(time) },
    { ...note, id: `${note.id}_b${stamp}`, start: round(time) },
  ]
}

/** 复制选中的音符并整体后移（返回新音符，调用方负责并进声部）。 */
export function duplicateNotes(
  notes: MidiComposeNote[],
  idSet: Set<string>,
  offset: number,
  duration: number,
): MidiComposeNote[] {
  const stamp = Date.now().toString(36)
  return notes
    .filter((note) => idSet.has(note.id))
    .map((note, index) => {
      const length = note.end - note.start
      const start = Math.min(Math.max(0, note.start + offset), Math.max(0, duration - length))
      return {
        ...note,
        id: `${note.id}_c${stamp}${index}`,
        start: round(start),
        end: round(Math.min(duration, start + length)),
      }
    })
}

/** 删除选中音符。 */
export function removeNotes(notes: MidiComposeNote[], idSet: Set<string>): MidiComposeNote[] {
  return notes.filter((note) => !idSet.has(note.id))
}

/** 声部是否发声（考虑独奏/静音），供预览与渲染提示使用。 */
export function isPartAudible(parts: MidiPart[], part: MidiPart): boolean {
  const soloed = parts.some((item) => item.solo)
  if (soloed) return !!part.solo
  return !part.mute
}

/** 拍号 / 速度 → 「每小节多少秒」，给刻度尺与循环区间用。 */
export function sessionBarSeconds(session: MidiSession | null | undefined): number {
  return barSeconds(session?.tempo ?? COMPOSE_DEFAULT_TEMPO, session?.time_signature ?? [4, 4])
}

/** 会话归一化：容错后端/导入文件里缺字段的情况，组件可以放心直接用。 */
export function normalizeSession(
  raw: Partial<MidiSession> | null | undefined,
  duration: number,
): MidiSession {
  const limit = Math.max(COMPOSE_MIN_NOTE_SECONDS, Number(duration) || 60)
  const signature = (() => {
    const candidate = raw?.time_signature || [4, 4]
    const numerator = Number(candidate[0]) || 4
    const denominator = Number(candidate[1]) || 4
    const match = TIME_SIGNATURE_CHOICES.find(
      (item) => item[0] === numerator && item[1] === denominator,
    )
    return match ? [match[0], match[1]] : [4, 4]
  })()
  const parts = (raw?.parts || []).map((part, index) => {
    const notes = sortNotes(
      (part.notes || [])
        .map((note, noteIndex) => {
          const start = clampTime(Number(note.start) || 0, limit)
          const end = clampTime(Number(note.end) || 0, limit)
          if (end - start < COMPOSE_MIN_NOTE_SECONDS) return null
          return {
            id: String(note.id || `cn_${index}_${noteIndex}`),
            start: round(start),
            end: round(end),
            pitch: clampComposePitch(Number(note.pitch) || 60),
            velocity: clampVelocity(Number(note.velocity) || COMPOSE_DEFAULT_VELOCITY),
          }
        })
        .filter((note): note is MidiComposeNote => note !== null),
    )
    return {
      ...createPart(index, {
        instrument: Number(part.instrument) || 0,
        drum: !!part.drum,
        name: String(part.name || ''),
        color: String(part.color || ''),
      }),
      ...part,
      id: String(part.id || `part_${index + 1}`),
      notes: !!part.drum
        ? notes.map((note) =>
            isDrumPitch(note.pitch) ? note : { ...note, pitch: nearestDrumPitch(note.pitch) },
          )
        : notes,
      color: String(part.color || PART_COLORS[index % PART_COLORS.length]!),
      volume: Math.min(2, Math.max(0, Number(part.volume ?? 1) || 0)),
      pan: Math.min(1, Math.max(-1, Number(part.pan ?? 0) || 0)),
      mute: !!part.mute,
      solo: !!part.solo,
      drum: !!part.drum,
      channel: !!part.drum ? 9 : Math.min(15, Math.max(0, Number(part.channel) || 0)),
      instrument: Math.min(127, Math.max(0, Math.round(Number(part.instrument) || 0))),
    } as MidiPart
  })
  return {
    version: 1,
    tempo: clampTempo(Number(raw?.tempo) || COMPOSE_DEFAULT_TEMPO),
    time_signature: signature,
    parts: parts.length ? parts : [createPart(0)],
    name: String(raw?.name || ''),
    loop: !!raw?.loop,
    metronome: !!raw?.metronome,
  }
}

