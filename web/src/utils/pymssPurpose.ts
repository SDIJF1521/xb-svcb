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

const FORBIDDEN_STEMS = [
  'male',
  'female',
  'speech',
  'speaker',
  'dialog',
  'duet',
  'bass',
  'drum',
  'guitar',
  'piano',
  'other',
  'multi',
  '男声',
  '女声',
  '语音',
  '说话',
  '和声',
  '卡拉',
  '吉他',
  '贝斯',
  '鼓',
  '钢琴',
  '多轨',
]

function separationStems(model: PymssModel): string[] {
  const values = model.target_stems?.length ? model.target_stems : model.stems || []
  return values
    .map((value) => String(value || '').trim().toLowerCase())
    .filter(Boolean)
}

/**
 * 判断模型是否适合单模型 / 多模型翻唱的人声分离。
 *
 * 目录的 purpose 不可靠：`melband_roformer_instvox_duality` 这类
 * 人声-伴奏双向模型的 purpose 可能为空，但 target_stems 明确是
 * vocals + instrumental。这里优先相信 target_stems，再回退到用途；
 * 双人/二重唱、合唱、男女声、语音、多轨、单乐器模型仍排除；
 * 卡拉OK/和声的 backing_vocal 模型允许参与。
 */
export function isPymssCoverSeparationModel(model: PymssModel): boolean {
  const explicitPurpose = String(model.purpose || '').toLowerCase()
  if (explicitPurpose === 'dereverb' || explicitPurpose === 'harmony_removal') return false
  const inferredPurpose = pymssPurposeKey(model)

  const stems = separationStems(model)
  const name = String(model.name || '').toLowerCase()
  const nameLooksUnsafe =
    /(^|[^a-z0-9])(inst|instrumental|multi|speech|speaker|male|female|duet|guitar|bass|drum|piano)([^a-z0-9]|$)/i.test(
      name,
    )
  const isInstVox = /instvox|inst_vox|instrumental[_-]?vocal|duality/i.test(name)
  const description = [
    model.category_label,
    model.primary_category_label,
    model.secondary_category_label,
    model.purpose_label,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  const descriptionLooksUnsafe =
    /双人|二重唱|对唱|合唱|男女声|男声|女声|语音|说话|多轨|单乐器|混响|回声|duet|duo|chorus|male.?female|speech|speaker|multi|instrument|guitar|bass|drum|piano|reverb|echo|dereverb|deecho|denoise/i.test(
      description,
    )

  // 卡拉OK/和声的 backing_vocal 模型不应被“和声”分类推断误杀；
  // 只有显式 dereverb / harmony_removal 用途才直接排除。
  if (descriptionLooksUnsafe) return false
  if (nameLooksUnsafe && !isInstVox) return false
  if (!stems.length) return inferredPurpose === 'vocal_separation'
  if (stems.length > 2) return false

  const hasVocal = stems.some((stem) => /vocal|voice|人声/.test(stem))
  if (!hasVocal) return false
  if (stems.some((stem) => FORBIDDEN_STEMS.some((word) => stem.includes(word)))) return false

  const hasAccompaniment = stems.some((stem) =>
    /instrument|accompani|inst$|伴奏/.test(stem),
  )
  return stems.length === 1 ? true : hasAccompaniment
}
