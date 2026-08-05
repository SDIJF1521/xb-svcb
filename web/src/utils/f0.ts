const BASE_F0_METHODS = ['rmvpe', 'crepe', 'harvest', 'pm']
const HIGH_RANGE_F0_METHODS = [...BASE_F0_METHODS, 'fcpe']

export function f0MethodsForFramework(framework?: string): readonly string[] {
  const normalized = framework || 'so-vits-svc'
  if (normalized === 'seed-vc') return []
  if (normalized === 'so-vits-svc' || normalized === 'ddsp-svc') {
    return HIGH_RANGE_F0_METHODS
  }
  return BASE_F0_METHODS
}

export function normalizeF0Method(framework: string | undefined, method: string): string {
  const normalized = String(method || '').trim().toLowerCase()
  return f0MethodsForFramework(framework).includes(normalized) ? normalized : 'rmvpe'
}
