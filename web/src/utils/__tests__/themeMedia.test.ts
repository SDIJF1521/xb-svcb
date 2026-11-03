import { describe, expect, it } from 'vitest'

import { detectThemeImageFormat } from '@/utils/themeMedia'

function bytes(value: string): Uint8Array {
  return Uint8Array.from(value, (char) => char.charCodeAt(0))
}

describe('theme media format detection', () => {
  it('detects a HEIC image even when its filename and MIME type claim PNG', () => {
    const header = bytes('\0\0\0\x1cftypheic\0\0\0\0mif1heicmiaf')

    expect(detectThemeImageFormat(header)).toBe('heif')
  })

  it('distinguishes browser-native image signatures', () => {
    expect(detectThemeImageFormat(Uint8Array.from([0xff, 0xd8, 0xff, 0xe0]))).toBe('jpeg')
    expect(detectThemeImageFormat(Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe('png')
    expect(detectThemeImageFormat(bytes('GIF89a'))).toBe('gif')
  })
})
