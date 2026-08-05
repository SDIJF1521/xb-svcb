import { describe, expect, it } from 'vitest'

import { f0MethodsForFramework, normalizeF0Method } from '@/utils/f0'

describe('F0 framework capabilities', () => {
  it('offers FCPE only for So-VITS-SVC and DDSP-SVC', () => {
    expect(f0MethodsForFramework('so-vits-svc')).toContain('fcpe')
    expect(f0MethodsForFramework('ddsp-svc')).toContain('fcpe')
    expect(f0MethodsForFramework('rvc')).not.toContain('fcpe')
    expect(f0MethodsForFramework('seed-vc')).toEqual([])
  })

  it('falls back to RMVPE when switching FCPE to an incompatible framework', () => {
    expect(normalizeF0Method('so-vits-svc', 'fcpe')).toBe('fcpe')
    expect(normalizeF0Method('ddsp-svc', 'FCPE')).toBe('fcpe')
    expect(normalizeF0Method('rvc', 'fcpe')).toBe('rmvpe')
    expect(normalizeF0Method('seed-vc', 'fcpe')).toBe('rmvpe')
  })
})
