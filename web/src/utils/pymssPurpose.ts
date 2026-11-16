import type { PymssModel } from '@/api'

/**
 * 归一化 PyMSS 模型的用途：优先用后端的 purpose 字段，
 * 部分模型没有该字段时用分类文案兜底推断，供筛选与默认模型挑选共用。
 */
export function pymssPurposeKey(model: PymssModel): string {
  const purpose = String(model.purpose || '')
  if (purpose) return purpose
  const text = [
    model.category_label,
    model.primary_category_label,
    model.secondary_category_label,
    model.purpose_label,
    model.target_stem,
  ]
    .filter(Boolean)
    .join(' ')
  if (/混响|回声|reverb|echo/i.test(text)) return 'dereverb'
  if (/和声|伴唱|合唱|harmony|backing|bve/i.test(text)) return 'harmony_removal'
  if (/人声|人聲|vocal/i.test(text)) return 'vocal_separation'
  return ''
}

/** 按用途挑选一个 PyMSS 模型：优先已下载的，其次目录顺序，最后用兜底名。 */
export function preferredPymssModel(models: PymssModel[], purpose: string, fallback: string): string {
  const list = models || []
  const matched = list.filter((model) => pymssPurposeKey(model) === purpose)
  const downloaded = matched.find((model) => model.downloaded !== false)
  if (downloaded) return downloaded.name
  if (matched.length) return matched[0]!.name
  return list[0]?.name || fallback
}
