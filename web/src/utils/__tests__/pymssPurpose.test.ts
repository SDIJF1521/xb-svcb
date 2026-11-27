import { describe, expect, it } from 'vitest'

import type { PymssModel } from '@/api'
import { isPymssCoverSeparationModel } from '@/utils/pymssPurpose'

function model(overrides: Partial<PymssModel>): PymssModel {
  return {
    name: 'model.ckpt',
    purpose: 'vocal_separation',
    downloaded: true,
    ...overrides,
  }
}

describe('isPymssCoverSeparationModel', () => {
  it('keeps an instvox/duality model with empty purpose when stems are vocals + instrumental', () => {
    const item = model({
      name: 'melband_roformer_instvox_duality_v2.ckpt',
      purpose: '',
      category_label: '人声 / 人声-伴奏双向分离',
      target_stems: ['vocals', 'instrumental'],
    })

    expect(isPymssCoverSeparationModel(item)).toBe(true)
  })

  it('keeps a vocal-only extraction model', () => {
    const item = model({
      name: 'mel_band_roformer_vocals_v2_gabox.ckpt',
      purpose: '',
      target_stems: ['vocals'],
    })

    expect(isPymssCoverSeparationModel(item)).toBe(true)
  })

  it('rejects a pure instrumental model even if metadata claims both stems', () => {
    const item = model({
      name: 'UVR-MDX-NET-Inst_HQ_4',
      target_stems: ['vocals', 'instrumental'],
    })

    expect(isPymssCoverSeparationModel(item)).toBe(false)
  })

  it('rejects duet / double-singer separation models', () => {
    const item = model({
      name: 'model_mel_band_roformer_ep_0_sdr_7.9319_fixed.ckpt',
      purpose: 'vocal_separation',
      category_label: '人声 / 双人/二重唱分离',
      target_stems: ['vocals'],
    })

    expect(isPymssCoverSeparationModel(item)).toBe(false)
  })

  it('keeps karaoke/backing-vocal extraction models', () => {
    const item = model({
      name: 'mel_band_roformer_karaoke_gabox_v2.ckpt',
      purpose: '',
      category_label: '卡拉OK/和声',
      target_stems: ['backing_vocal'],
    })

    expect(isPymssCoverSeparationModel(item)).toBe(true)
  })

  it('rejects multi-stem, speech and dereverb models', () => {
    expect(
      isPymssCoverSeparationModel(model({ name: 'multi.ckpt', target_stems: ['vocals', 'drums', 'bass', 'other'] })),
    ).toBe(false)
    expect(isPymssCoverSeparationModel(model({ name: 'speech.ckpt', target_stems: ['vocals'] }))).toBe(false)
    expect(
      isPymssCoverSeparationModel(model({ name: 'dereverb.ckpt', purpose: 'dereverb', target_stems: ['vocals', 'instrumental'] })),
    ).toBe(false)
  })

  it('falls back to purpose only when stems are missing', () => {
    expect(isPymssCoverSeparationModel(model({ name: 'legacy_vocal.ckpt', purpose: 'vocal_separation' }))).toBe(true)
    expect(isPymssCoverSeparationModel(model({ name: 'legacy_generic.ckpt', purpose: '' }))).toBe(false)
  })
})
