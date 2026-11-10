import { describe, expect, it } from 'vitest'

import {
  COMPOSE_MIN_NOTE_SECONDS,
  COMPOSE_PITCH_MAX,
  DRUM_PIECES,
  DRUM_PITCH_MAX,
  DRUM_PITCH_MIN,
  GM_FAMILIES,
  GM_INSTRUMENTS,
  MIDI_MIN_NOTE_PX,
  MIDI_MIN_NOTE_SECONDS,
  basicDrumBeat,
  clampPitch,
  clampProgram,
  composeNoteAtPoint,
  copyNotes,
  createComposeNote,
  createNote,
  createPart,
  drumGroupLabel,
  drumName,
  drumPiece,
  duplicateNotes,
  fallbackInstrumentLabel,
  fitZoom,
  gridStepSeconds,
  humanizeNotes,
  instrumentFamilyName,
  instrumentName,
  isBlackKey,
  isDrumPitch,
  isPartAudible,
  legatoNotes,
  moveComposeNotes,
  moveNote,
  moveNotes,
  nearestDrumPitch,
  normalizeNotes,
  normalizeSession,
  noteAtPoint,
  noteAtTimePitch,
  noteEdgeAt,
  noteName,
  noteRect,
  pasteNotes,
  partBounds,
  pitchBounds,
  pitchToY,
  playheadX,
  quantizeComposeNotes,
  quantizeNotes,
  resizeComposeNote,
  resizeNote,
  scaleNoteVelocity,
  secondsPerBeat,
  sessionDuration,
  sessionNoteCount,
  sessionPitchRange,
  snapTime,
  splitNoteAt,
  timeSignatureLabel,
  transposeNotes,
  barBeatLabel,
  barSeconds,
  yToPitch,
} from '@/utils/midi'
import type { MidiComposeNote, MidiPart } from '@/utils/midi'

describe('midi utils', () => {
  it('maps pitch to note names and black keys', () => {
    expect(noteName(60)).toBe('C4')
    expect(noteName(57)).toBe('A3')
    expect(noteName(61)).toBe('C#4')
    expect(isBlackKey(61)).toBe(true)
    expect(isBlackKey(60)).toBe(false)
    expect(clampPitch(-100)).toBe(24)
    expect(clampPitch(400)).toBe(108)
  })

  it('snaps and clamps time', () => {
    expect(snapTime(0.26, 0.1)).toBeCloseTo(0.3)
    expect(snapTime(0.26, 0)).toBeCloseTo(0.26)
  })

  it('normalizes notes: overlap trimming, id de-duplication, ordering', () => {
    const notes = normalizeNotes(
      [
        { id: 'a', start: 1.0, end: 2.5, pitch: 64, detune: 0 },
        { id: 'a', start: 0.2, end: 1.4, pitch: 60, detune: 0 },
        { start: 2.0, end: 2.02, pitch: 62, detune: 0 },
      ],
      3,
    )
    expect(notes).toHaveLength(2)
    expect(notes[0]!.start).toBeCloseTo(0.2)
    expect(notes[0]!.end).toBeCloseTo(1.0)
    expect(notes[1]!.end).toBeCloseTo(2.5)
    expect(notes[0]!.id).not.toBe(notes[1]!.id)
  })

  it('creates and clamps notes inside the clip', () => {
    const note = createNote(2.94, 61, 3, 0.1, 0.5)
    expect(note.start).toBeCloseTo(2.9)
    expect(note.end).toBeCloseTo(3)
    expect(note.pitch).toBe(61)
    expect(note.end - note.start).toBeGreaterThanOrEqual(MIDI_MIN_NOTE_SECONDS)
  })

  it('moves notes in time and pitch with grid snapping', () => {
    const note = { id: 'n', start: 0.5, end: 1.0, pitch: 60, detune: 0 }
    const moved = moveNote(note, 0.24, 3, 4, 0.1)
    expect(moved.start).toBeCloseTo(0.7)
    expect(moved.end).toBeCloseTo(1.2)
    expect(moved.pitch).toBe(63)

    const pushed = moveNote(note, 10, 0, 4, 0.1)
    expect(pushed.end).toBeCloseTo(4)
    expect(pushed.start).toBeCloseTo(3.5)
  })

  it('resizes notes from either edge without crossing', () => {
    const note = { id: 'n', start: 1, end: 2, pitch: 60, detune: 0 }
    expect(resizeNote(note, 'end', 2.44, 4, 0.1).end).toBeCloseTo(2.4)
    const startEdge = resizeNote(note, 'start', 2.5, 4, 0.1)
    expect(startEdge.start).toBeLessThan(startEdge.end)
    expect(startEdge.end).toBeCloseTo(2)
  })

  it('computes pitch bounds with padding and minimum span', () => {
    expect(pitchBounds([])).toEqual({ min: 48, max: 84 })
    const bounds = pitchBounds([{ id: 'n', start: 0, end: 1, pitch: 70, detune: 0 }])
    expect(bounds.min).toBe(58)
    expect(bounds.max).toBe(82)
    const lowEdge = pitchBounds([{ id: 'n', start: 0, end: 1, pitch: 26, detune: 0 }])
    expect(lowEdge.min).toBe(24)
    expect(lowEdge.max - lowEdge.min).toBeGreaterThanOrEqual(24)
    const wide = pitchBounds([
      { id: 'a', start: 0, end: 1, pitch: 30, detune: 0 },
      { id: 'b', start: 1, end: 2, pitch: 105, detune: 0 },
    ])
    expect(wide.min).toBeLessThanOrEqual(30)
    expect(wide.max).toBeGreaterThanOrEqual(105)
  })

  it('hit-tests notes and maps canvas coordinates', () => {
    const notes = [{ id: 'n', start: 0.5, end: 1, pitch: 60, detune: 0 }]
    expect(noteAtTimePitch(notes, 0.6, 60)?.id).toBe('n')
    expect(noteAtTimePitch(notes, 0.6, 62)).toBeUndefined()

    expect(pitchToY(60, 72, 14)).toBe(168)
    expect(yToPitch(168, 72, 14)).toBe(60)
    const rect = noteRect(notes[0]!, 72, 14, 100)
    expect(rect.x).toBeCloseTo(50)
    expect(rect.width).toBeCloseTo(50)
    expect(rect.y).toBeCloseTo(168)

    expect(playheadX(1.5, 100, 2)).toBeCloseTo(150)
    expect(playheadX(3, 100, 2)).toBeNull()
  })

  it('keeps tiny notes clickable with a minimum width and padding', () => {
    const tiny = [{ id: 'tiny', start: 0.5, end: 0.51, pitch: 60, detune: 0 }]
    const rect = noteRect(tiny[0]!, 72, 14, 100)
    expect(rect.width).toBe(MIDI_MIN_NOTE_PX)
    // 真实宽度 1px，但命中区按最小宽度 + 容差扩开
    expect(noteAtPoint(tiny, rect.x + 3, rect.y + 4, 72, 14, 100)?.id).toBe('tiny')
    expect(noteAtPoint(tiny, rect.x + 40, rect.y + 4, 72, 14, 100)).toBeUndefined()
    expect(noteEdgeAt(tiny[0]!, rect.x + 2, 72, 14, 100)).toBe('move')
  })

  it('hits note edges only when the block is wide enough', () => {
    const wide = { id: 'w', start: 1, end: 2, pitch: 60, detune: 0 }
    const rect = noteRect(wide, 72, 14, 100)
    expect(noteEdgeAt(wide, rect.x + 2, 72, 14, 100)).toBe('start')
    expect(noteEdgeAt(wide, rect.x + rect.width - 2, 72, 14, 100)).toBe('end')
    expect(noteEdgeAt(wide, rect.x + rect.width / 2, 72, 14, 100)).toBe('move')
  })

  it('quantizes, transposes and moves a multi-selection together', () => {
    const notes = [
      { id: 'a', start: 0.13, end: 0.47, pitch: 60, detune: 0 },
      { id: 'b', start: 0.61, end: 0.93, pitch: 64, detune: 0 },
      { id: 'c', start: 2.0, end: 2.4, pitch: 67, detune: 0 },
    ]
    const quantized = quantizeNotes(notes, ['a', 'b'], 0.25, 4)
    expect(quantized[0]!.start).toBeCloseTo(0.25)
    expect(quantized[1]!.start).toBeCloseTo(0.5)
    expect(quantized[2]!.start).toBeCloseTo(2.0)

    const transposed = transposeNotes(notes, ['a', 'b'], 3)
    expect(transposed[0]!.pitch).toBe(63)
    expect(transposed[1]!.pitch).toBe(67)
    expect(transposed[2]!.pitch).toBe(67)

    const moved = moveNotes(notes, ['a', 'b'], 0.5, 2, 4, 0.1)
    expect(moved[0]!.start).toBeCloseTo(0.63)
    expect(moved[1]!.start).toBeCloseTo(1.11)
    expect(moved[0]!.pitch).toBe(62)
    expect(moved[2]!.start).toBeCloseTo(2.0)
  })

  it('clamps a group move inside the clip and keeps relative spacing', () => {
    const notes = [
      { id: 'a', start: 1.0, end: 1.4, pitch: 60, detune: 0 },
      { id: 'b', start: 2.0, end: 2.4, pitch: 62, detune: 0 },
    ]
    const moved = moveNotes(notes, ['a', 'b'], 50, 0, 3, 0.1)
    const gap = moved[1]!.start - moved[0]!.start
    expect(gap).toBeCloseTo(1.0, 5)
    expect(moved[1]!.end).toBeLessThanOrEqual(3 + 1e-6)
  })

  it('copies and pastes with new ids at the requested time', () => {
    const notes = [
      { id: 'a', start: 1.0, end: 1.4, pitch: 60, detune: 0 },
      { id: 'b', start: 1.6, end: 2.0, pitch: 64, detune: 0 },
      { id: 'c', start: 3.0, end: 3.4, pitch: 67, detune: 0 },
    ]
    const copied = copyNotes(notes, ['a', 'b'])
    expect(copied).toHaveLength(2)
    const pasted = pasteNotes(copied, 2.5, 4)
    expect(pasted).toHaveLength(2)
    expect(pasted[0]!.start).toBeCloseTo(2.5)
    expect(pasted[1]!.start).toBeCloseTo(3.1)
    expect(pasted[0]!.id).not.toBe('a')
    const clamped = pasteNotes(copied, 3.9, 4)
    expect(Math.max(...clamped.map((note) => note.end))).toBeLessThanOrEqual(4 + 1e-6)
  })

  it('derives a zoom that fits a span', () => {
    expect(fitZoom(10, 500)).toBe(50)
    expect(fitZoom(10, 20000)).toBe(640)
    expect(fitZoom(1000, 500)).toBe(24)
    expect(fitZoom(0, 500)).toBe(24)
  })
})

describe('MIDI 编曲工具', () => {
  const part = (overrides: Partial<MidiPart> = {}): MidiPart => ({
    ...createPart(0),
    ...overrides,
  })

  it('converts tempo and signature to musical time', () => {
    expect(secondsPerBeat(120)).toBeCloseTo(0.5)
    expect(gridStepSeconds(120, '1/16')).toBeCloseTo(0.125)
    expect(gridStepSeconds(120, '1/8t')).toBeCloseTo(1 / 6)
    expect(gridStepSeconds(120, 'off')).toBe(0)
    expect(barSeconds(120, [4, 4])).toBeCloseTo(2)
    expect(barSeconds(120, [3, 4])).toBeCloseTo(1.5)
    expect(barSeconds(120, [6, 8])).toBeCloseTo(1.5)
    expect(barBeatLabel(0, 120, [4, 4])).toBe('1:1')
    expect(barBeatLabel(2.5, 120, [4, 4])).toBe('2:2')
    expect(timeSignatureLabel([6, 8])).toBe('6/8')
  })

  it('creates notes inside the timeline with clamped velocity', () => {
    const note = createComposeNote(50, 200, 4, 0.5, 400)
    expect(note.start).toBeLessThanOrEqual(4)
    expect(note.end).toBeLessThanOrEqual(4 + 1e-6)
    expect(note.pitch).toBe(COMPOSE_PITCH_MAX)
    expect(note.velocity).toBe(127)
    expect(note.end - note.start).toBeGreaterThanOrEqual(COMPOSE_MIN_NOTE_SECONDS)
  })

  it('quantizes with strength and keeps note length', () => {
    const notes = [{ id: 'a', start: 0.13, end: 0.63, pitch: 60, velocity: 100 }]
    const full = quantizeComposeNotes(notes, 0.25, 4, 1)
    expect(full[0]!.start).toBeCloseTo(0.25)
    expect(full[0]!.end - full[0]!.start).toBeCloseTo(0.5)
    const half = quantizeComposeNotes(notes, 0.25, 4, 0.5)
    expect(half[0]!.start).toBeCloseTo(0.19)
  })

  it('moves a multi-part selection together and clamps at the edges', () => {
    const parts = [
      part({ id: 'p1', notes: [{ id: 'a', start: 1, end: 1.4, pitch: 60, velocity: 90 }] }),
      part({ id: 'p2', notes: [{ id: 'b', start: 2, end: 2.4, pitch: 64, velocity: 90 }] }),
    ]
    const moved = moveComposeNotes(parts, new Set(['a', 'b']), 0.5, 2, 4, 0.1)
    expect(moved[0]!.notes[0]!.start).toBeCloseTo(1.5)
    expect(moved[1]!.notes[0]!.start).toBeCloseTo(2.5)
    expect(moved[0]!.notes[0]!.pitch).toBe(62)
    expect(moved[0]!.notes[0]!.velocity).toBe(90)

    const clamped = moveComposeNotes(parts, new Set(['a', 'b']), 50, 0, 3, 0.1)
    const gap = clamped[1]!.notes[0]!.start - clamped[0]!.notes[0]!.start
    expect(gap).toBeCloseTo(1, 5)
    expect(clamped[1]!.notes[0]!.end).toBeLessThanOrEqual(3 + 1e-6)
  })

  it('resizes, splits and duplicates notes', () => {
    const note = { id: 'a', start: 1, end: 2, pitch: 60, velocity: 100 }
    expect(resizeComposeNote(note, 'end', 2.44, 4, 0.1).end).toBeCloseTo(2.4)
    expect(resizeComposeNote(note, 'start', 3, 4, 0.1).start).toBeLessThan(note.end)
    const split = splitNoteAt(note, 1.5)
    expect(split?.[0].end).toBeCloseTo(1.5)
    expect(split?.[1].start).toBeCloseTo(1.5)
    expect(splitNoteAt(note, 1.0)).toBeNull()
    const duplicated = duplicateNotes([note], new Set(['a']), 2, 8)
    expect(duplicated).toHaveLength(1)
    expect(duplicated[0]!.start).toBeCloseTo(3)
    expect(duplicated[0]!.id).not.toBe('a')
  })

  it('scales velocity, humanizes and applies legato', () => {
    const notes = [
      { id: 'a', start: 0, end: 0.4, pitch: 60, velocity: 100 },
      { id: 'b', start: 0.5, end: 0.9, pitch: 62, velocity: 60 },
    ]
    expect(scaleNoteVelocity(notes, 1.5)[0]!.velocity).toBe(127)
    expect(scaleNoteVelocity(notes, 0.5)[1]!.velocity).toBe(30)
    const humanized = humanizeNotes(notes, 0.02, 10, 4, () => 0.5)
    expect(humanized[0]!.start).toBeCloseTo(0)
    expect(humanized[0]!.velocity).toBe(100)
    const legato = legatoNotes(notes, 0.125)
    expect(legato[0]!.end).toBeGreaterThan(0.4)
    expect(legato[0]!.end).toBeLessThanOrEqual(0.5)
  })

  it('keeps solo/mute semantics for audition', () => {
    const parts = [
      part({ id: 'p1' }),
      part({ id: 'p2', mute: true }),
      part({ id: 'p3', solo: true }),
    ]
    expect(isPartAudible(parts, parts[0]!)).toBe(false)
    expect(isPartAudible(parts, parts[2]!)).toBe(true)
    const noSolo = [parts[0]!, parts[1]!]
    expect(isPartAudible(noSolo, parts[0]!)).toBe(true)
    expect(isPartAudible(noSolo, parts[1]!)).toBe(false)
  })

  it('normalizes a session from the backend', () => {
    const session = normalizeSession(
      {
        tempo: 96,
        time_signature: [3, 4],
        parts: [
          {
            ...createPart(0, { instrument: 40 }),
            notes: [
              { id: 'x', start: 0.1, end: 0.9, pitch: 61.6, velocity: 300 } as MidiComposeNote,
      ],
          },
        ],
      },
      10,
    )
    expect(session.tempo).toBe(96)
    expect(session.time_signature).toEqual([3, 4])
    expect(session.parts).toHaveLength(1)
    expect(session.parts[0]!.instrument).toBe(40)
    expect(session.parts[0]!.notes[0]!.pitch).toBe(62)
    expect(session.parts[0]!.notes[0]!.velocity).toBe(127)
    expect(sessionNoteCount(session)).toBe(1)
    expect(sessionDuration(session)).toBeCloseTo(0.9, 3)
    expect(normalizeSession(null, 10).parts).toHaveLength(1)
  })

  it('keeps notes in sync through session helpers', () => {    const parts = [
      part({
        notes: [
          { id: 'a', start: 0, end: 0.5, pitch: 48, velocity: 90 },
          { id: 'b', start: 0.5, end: 1.0, pitch: 96, velocity: 90 },
        ],
      }),
    ]
    const range = sessionPitchRange(parts, 36, 96)
    expect(range.min).toBe(36)
    expect(range.max).toBe(102)
    expect(partBounds(parts[0]!)).toEqual({ start: 0, end: 1 })
    expect(partBounds(part())).toBeNull()
    // 命中测试：按坐标取声部音符
    const hit = composeNoteAtPoint(parts, 10, pitchToY(48, range.max, 14), range.max, 14, 100)
    expect(hit?.note.id).toBe('a')
  })

  it('音色表给出具体乐器名，不带占位编号', () => {
    expect(GM_INSTRUMENTS).toHaveLength(128)
    const names = GM_INSTRUMENTS.map((item) => item.name_zh)
    expect(new Set(names).size).toBe(128)
    expect(names.every((name) => name.length >= 2)).toBe(true)
    expect(instrumentName(0)).toBe('原声大钢琴')
    expect(instrumentName(40)).toBe('小提琴')
    expect(instrumentName(104)).toBe('西塔琴')
    expect(instrumentName(999)).toBe('枪声')
    expect(instrumentFamilyName(0)).toBe('钢琴')
    expect(instrumentFamilyName(47)).toBe('弦乐')
    expect(fallbackInstrumentLabel(33)).toBe('指弹电贝斯')
    expect(fallbackInstrumentLabel(33)).not.toMatch(/^贝斯\s*\d+$/)
    expect(clampProgram(-10)).toBe(0)
    expect(clampProgram(200)).toBe(127)
    expect(GM_FAMILIES).toHaveLength(16)
    expect(GM_FAMILIES.reduce((total, family) => total + family.programs.length, 0)).toBe(128)
  })
})

describe('架子鼓（GM 打击乐）', () => {
  it('鼓件表覆盖 35~81 且名字具体唯一', () => {
    expect(DRUM_PIECES).toHaveLength(47)
    expect(DRUM_PIECES[0]!.pitch).toBe(35)
    expect(DRUM_PIECES[DRUM_PIECES.length - 1]!.pitch).toBe(81)
    expect(DRUM_PIECES.map((piece) => piece.pitch)).toEqual(
      Array.from({ length: 47 }, (_, index) => 35 + index),
    )
    const names = DRUM_PIECES.map((piece) => piece.name_zh)
    expect(new Set(names).size).toBe(47)
    expect(drumName(36)).toBe('底鼓 1')
    expect(drumName(38)).toBe('军鼓 1')
    expect(drumName(42)).toBe('闭合踩镲')
    expect(drumName(46)).toBe('开音踩镲')
    expect(drumName(49)).toBe('吊镲 1')
    expect(drumGroupLabel(46)).toBe('开镲')
  })

  it('音高吸附到最近的鼓件', () => {
    expect(nearestDrumPitch(36)).toBe(36)
    expect(nearestDrumPitch(36.4)).toBe(36)
    expect(nearestDrumPitch(36.9)).toBe(37)
    expect(nearestDrumPitch(0)).toBe(DRUM_PITCH_MIN)
    expect(nearestDrumPitch(127)).toBe(DRUM_PITCH_MAX)
    expect(isDrumPitch(38)).toBe(true)
    expect(isDrumPitch(100)).toBe(false)
    expect(drumName(100)).toBe('三角铁（开）')
    expect(drumPiece(36)?.group).toBe('kick')
  })

  it('鼓组声部归一化时把音符吸附到鼓件', () => {
    const session = normalizeSession(
      {
        parts: [
          {
            ...createPart(0, { drum: true }),
            notes: [
              { id: 'k', start: 0, end: 0.2, pitch: 36, velocity: 110 },
              { id: 'x', start: 0.5, end: 0.7, pitch: 60.4, velocity: 110 },
              { id: 'y', start: 1, end: 1.2, pitch: 200, velocity: 110 },
            ] as MidiComposeNote[],
          },
        ],
      },
      4,
    )
    const part = session.parts[0]!
    expect(part.drum).toBe(true)
    expect(part.channel).toBe(9)
    expect(part.notes.map((note) => note.pitch)).toEqual([36, 60, 81])
    expect(part.notes.every((note) => isDrumPitch(note.pitch))).toBe(true)
  })

  it('基础节奏包含底鼓/军鼓/踩镲并落在正确的拍子上', () => {
    const beat = 0.5
    const notes = basicDrumBeat(beat, { bars: 1, start: 0, velocity: 110 })
    // 每拍：底鼓或军鼓 1 个 + 闭合踩镲 2 个 = 3 个
    expect(notes).toHaveLength(12)
    const kick = notes.filter((note) => note.pitch === 36).map((note) => note.start)
    const snare = notes.filter((note) => note.pitch === 38).map((note) => note.start)
    const hat = notes.filter((note) => note.pitch === 42)
    expect(kick).toEqual([0, 1])
    expect(snare).toEqual([0.5, 1.5])
    expect(hat).toHaveLength(8)
    expect(hat[1]!.start).toBeCloseTo(0.25)
    expect(notes.every((note) => note.velocity >= 1 && note.velocity <= 127)).toBe(true)

    const shifted = basicDrumBeat(beat, { bars: 2, start: 2 })
    expect(Math.min(...shifted.map((note) => note.start))).toBeCloseTo(2)
  })
})

