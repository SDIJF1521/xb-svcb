// 商城工作流预览的纯计算逻辑：把节点图排成从左到右的分层 DAG 缩略图。
// 与 WorkflowCanvas 的交互逻辑完全解耦，方便单元测试和复用。

import { translateUiText } from '@/i18n'

export const PREVIEW_NODE_WIDTH = 200
export const PREVIEW_NODE_HEIGHT = 94
export const PREVIEW_RANK_GAP = 64
export const PREVIEW_ROW_GAP = 28
export const PREVIEW_PADDING = 24
export const PREVIEW_TITLE_FONT = 22
export const PREVIEW_SUMMARY_FONT = 17

export interface PreviewNodeLike {
  id: string
  type: string
  x?: number
  y?: number
  params?: Record<string, unknown> | null
}

export interface PreviewEdgeLike {
  id?: string
  from?: { node?: string; port?: string } | null
  to?: { node?: string; port?: string } | null
}

export interface PreviewLayoutNode extends PreviewNodeLike {
  x: number
  y: number
  label: string
  summaryLines: string[]
  color: string
  rank: number
  width: number
  height: number
}

export interface PreviewLayoutEdge {
  id: string
  path: string
}

export interface WorkflowPreviewLayout {
  width: number
  height: number
  nodes: PreviewLayoutNode[]
  edges: PreviewLayoutEdge[]
}

const NODE_LABEL_KEYS: Record<string, string> = {
  input: '输入音频',
  separate: '人声分离',
  dereverb: '去混响净化',
  repair: '人声修复',
  convert: '歌声转换',
  blend: '合唱叠加',
  enhance: 'AI 歌声增强',
  mix: '混音合成',
  merge: '多轨混合',
  concat: '顺序拼接',
  effect: '音频效果',
  trim: '裁剪片段',
  fade: '淡入淡出',
  pitch: '变调',
  stretch: '变速',
  normalize: '响度归一化',
  output: '输出成品',
}

const NODE_COLORS: Record<string, string> = {
  input: '#2f6bff',
  separate: '#00b8cc',
  dereverb: '#0ea5b7',
  repair: '#0284c7',
  convert: '#e11d6f',
  blend: '#db2777',
  enhance: '#0f9f6e',
  mix: '#b45309',
  merge: '#c2410c',
  concat: '#a16207',
  effect: '#7c3aed',
  trim: '#64748b',
  fade: '#64748b',
  pitch: '#9333ea',
  stretch: '#9333ea',
  normalize: '#64748b',
  output: '#6d28d9',
}

function safeText(value: unknown, limit = 40): string {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

function fileName(value: unknown): string {
  return String(value ?? '').split(/[/\\]/).pop() || ''
}

/** 中英文混排的粗略字宽（以 font-size 为 1em 估算）。 */
function charWidth(char: string): number {
  if (/\s/.test(char)) return 0.32
  if (/[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uff00-\uffef]/.test(char)) return 1
  if (/[MW@%&]/.test(char)) return 0.78
  if (/[ilI.,'`!|]/.test(char)) return 0.3
  return 0.56
}

function textWidth(text: string, fontPx: number): number {
  let units = 0
  for (const char of text) units += charWidth(char)
  return units * fontPx
}

/** 单行省略：标题永远不越出卡片。 */
export function fitSingleLine(text: string, maxWidth: number, fontPx: number): string {
  const source = String(text || '')
  if (textWidth(source, fontPx) <= maxWidth) return source
  let result = ''
  for (const char of source) {
    if (textWidth(`${result}${char}…`, fontPx) > maxWidth) break
    result += char
  }
  return `${result.trimEnd()}…`
}

/** 多行换行：中文按字、英文按词，最后一行超长时补省略号。 */
export function wrapText(
  text: string,
  maxWidth: number,
  fontPx: number,
  maxLines: number,
): string[] {
  const source = String(text || '').replace(/\s+/g, ' ').trim()
  if (!source || maxLines <= 0) return []
  const tokens = source.match(/[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uff00-\uffef]|[^\s\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uff00-\uffef]+|\s+/g) || [source]
  const lines: string[] = []
  let current = ''
  const pushLine = () => {
    if (current.trim()) lines.push(current.trim())
    current = ''
  }
  for (const token of tokens) {
    if (/^\s+$/.test(token)) {
      if (current) current += ' '
      continue
    }
    if (textWidth(current + token, fontPx) <= maxWidth) {
      current += token
      continue
    }
    if (textWidth(token, fontPx) <= maxWidth) {
      pushLine()
      current = token
      continue
    }
    // 超长英文单词 / 哈希：单独成行并省略，避免把模型名从中间断成两行。
    pushLine()
    current = fitSingleLine(token, maxWidth, fontPx)
    pushLine()
  }
  pushLine()
  if (lines.length <= maxLines) return lines
  const kept = lines.slice(0, maxLines)
  kept[maxLines - 1] = fitSingleLine(`${kept[maxLines - 1]}…`, maxWidth, fontPx)
  return kept
}

export function previewNodeLabel(type: string): string {
  return translateUiText(NODE_LABEL_KEYS[type] || type || '节点')
}

export function previewNodeColor(type: string): string {
  return NODE_COLORS[type] || '#7c93b8'
}

/** 节点卡片第二行：只展示与理解工作流有关的关键参数。 */
export function summarizeNodeParams(node: PreviewNodeLike): string {
  const params = node.params || {}
  switch (node.type) {
    case 'separate':
    case 'dereverb': {
      const engine = String(params.engine || 'uvr').toLowerCase() === 'pymss' ? 'PyMSS' : 'UVR'
      const model = safeText(fileName(params.model).replace(/\.[^.]+$/, ''), 26)
      return model ? `${engine} · ${model}` : engine
    }
    case 'convert':
      return safeText(
        params.model_name || fileName(params.model_id).replace(/\.[^.]+$/, '') || '选择声音模型',
        26,
      )
    case 'enhance': {
      const level = String(params.level || 'basic').toLowerCase()
      return level === 'advanced' ? '高级增强' : level === 'standard' ? '标准增强' : '基础增强'
    }
    case 'effect':
      return safeText(params.effect || '效果处理', 26)
    case 'trim':
      return `${Number(params.start || 0).toFixed(1)}s – ${Number(params.end || 0).toFixed(1)}s`
    case 'fade':
      return `淡入 ${Number(params.fade_in || 0).toFixed(1)}s · 淡出 ${Number(params.fade_out || 0).toFixed(1)}s`
    case 'pitch':
      return `${Number(params.semitones || 0) >= 0 ? '+' : ''}${Number(params.semitones || 0)} 半音`
    case 'stretch':
      return `${Number(params.speed || 1).toFixed(2)}x 速度`
    case 'normalize':
      return `${Number(params.target_lufs || -14).toFixed(1)} LUFS`
    case 'output':
      return safeText(params.file_template || '成品输出', 30)
    default:
      return ''
  }
}

interface _NodeBox {
  id: string
  type: string
  label: string
  summaryLines: string[]
  color: string
  rank: number
  x: number
  y: number
}

const COMPACT_NODE_WIDTH = 58
const COMPACT_NODE_HEIGHT = 32
const COMPACT_COLUMN_GAP = 10
const COMPACT_ROW_GAP = 20
const COMPACT_PADDING = 14
const COMPACT_MAX_COLUMNS = 7
const COMPACT_MAX_NODES = 12

/** 用 Kahn 拓扑分层；环上残留节点放到最后一层，保证预览不会卡死。 */
function assignRanks(nodeIds: string[], children: Map<string, string[]>, parents: Map<string, string[]>): Map<string, number> {
  const rank = new Map<string, number>(nodeIds.map((id) => [id, 0]))
  const indegree = new Map<string, number>(nodeIds.map((id) => [id, (parents.get(id) || []).length]))
  const queue = nodeIds.filter((id) => (indegree.get(id) || 0) === 0)
  const visited = new Set<string>()
  while (queue.length) {
    const id = queue.shift()!
    visited.add(id)
    for (const child of children.get(id) || []) {
      rank.set(child, Math.max(rank.get(child) || 0, (rank.get(id) || 0) + 1))
      indegree.set(child, (indegree.get(child) || 1) - 1)
      if ((indegree.get(child) || 0) === 0 && !visited.has(child)) queue.push(child)
    }
  }
  const maxRank = Math.max(0, ...nodeIds.map((id) => rank.get(id) || 0))
  for (const id of nodeIds) {
    if (!visited.has(id)) rank.set(id, maxRank + 1)
  }
  return rank
}

/**
 * 分层布局：按拓扑排序从左到右排布，并用父节点重心排序减少连线交叉。
 * 不再使用画布里的原始 x/y（工作流可能被手工拖得很散），只把它们当作并列节点的次序兜底。
 */
export function buildWorkflowPreviewLayout(
  nodes: PreviewNodeLike[] | null | undefined,
  edges: PreviewEdgeLike[] | null | undefined,
): WorkflowPreviewLayout {
  const unique = new Map<string, PreviewNodeLike>()
  for (const node of nodes || []) {
    if (!node || typeof node.id !== 'string' || !node.type || unique.has(node.id)) continue
    unique.set(node.id, node)
  }
  const source = [...unique.values()]
  if (!source.length) return { width: 520, height: 220, nodes: [], edges: [] }

  const children = new Map<string, string[]>()
  const parents = new Map<string, string[]>()
  const validEdges: PreviewEdgeLike[] = []
  for (const edge of edges || []) {
    const from = String(edge?.from?.node || '')
    const to = String(edge?.to?.node || '')
    if (!unique.has(from) || !unique.has(to) || from === to) continue
    validEdges.push(edge)
    children.set(from, [...(children.get(from) || []), to])
    parents.set(to, [...(parents.get(to) || []), from])
  }

  const rank = assignRanks(
    source.map((node) => node.id),
    children,
    parents,
  )
  const groups = new Map<number, PreviewNodeLike[]>()
  for (const node of source) {
    const level = rank.get(node.id) || 0
    groups.set(level, [...(groups.get(level) || []), node])
  }
  const ranks = [...groups.keys()].sort((a, b) => a - b)
  const orderIndex = new Map<string, number>()

  for (const level of ranks) {
    const group = groups.get(level) || []
    const scored = group.map((node) => {
      const parentIds = (parents.get(node.id) || []).filter(
        (id) => (rank.get(id) || 0) < level && orderIndex.has(id),
      )
      const barycenter = parentIds.length
        ? parentIds.reduce((sum, id) => sum + (orderIndex.get(id) || 0), 0) / parentIds.length
        : Number.POSITIVE_INFINITY
      return {
        node,
        barycenter,
        originY: Number(node.y) || 0,
        originX: Number(node.x) || 0,
      }
    })
    scored.sort((a, b) => {
      if (a.barycenter !== b.barycenter) {
        if (a.barycenter === Number.POSITIVE_INFINITY) return 1
        if (b.barycenter === Number.POSITIVE_INFINITY) return -1
        return a.barycenter - b.barycenter
      }
      if (a.originY !== b.originY) return a.originY - b.originY
      if (a.originX !== b.originX) return a.originX - b.originX
      return a.node.id.localeCompare(b.node.id)
    })
    const ordered = scored.map((item) => item.node)
    groups.set(level, ordered)
    ordered.forEach((node, index) => orderIndex.set(node.id, index))
  }

  const maxRows = Math.max(...ranks.map((level) => (groups.get(level) || []).length))
  const width =
    PREVIEW_PADDING * 2 +
    ranks.length * PREVIEW_NODE_WIDTH +
    Math.max(0, ranks.length - 1) * PREVIEW_RANK_GAP
  const height =
    PREVIEW_PADDING * 2 +
    maxRows * PREVIEW_NODE_HEIGHT +
    Math.max(0, maxRows - 1) * PREVIEW_ROW_GAP

  const boxes: _NodeBox[] = []
  const positioned = new Map<string, _NodeBox>()
  for (const level of ranks) {
    const group = groups.get(level) || []
    const groupHeight =
      group.length * PREVIEW_NODE_HEIGHT + Math.max(0, group.length - 1) * PREVIEW_ROW_GAP
    const startY = PREVIEW_PADDING + (height - PREVIEW_PADDING * 2 - groupHeight) / 2
    group.forEach((node, index) => {
      const box: _NodeBox = {
        id: node.id,
        type: node.type,
        label: fitSingleLine(
          previewNodeLabel(node.type),
          PREVIEW_NODE_WIDTH - 34,
          PREVIEW_TITLE_FONT,
        ),
        summaryLines: wrapText(
          summarizeNodeParams(node),
          PREVIEW_NODE_WIDTH - 34,
          PREVIEW_SUMMARY_FONT,
          2,
        ),
        color: previewNodeColor(node.type),
        rank: level,
        x: PREVIEW_PADDING + level * (PREVIEW_NODE_WIDTH + PREVIEW_RANK_GAP),
        y: startY + index * (PREVIEW_NODE_HEIGHT + PREVIEW_ROW_GAP),
      }
      boxes.push(box)
      positioned.set(node.id, box)
    })
  }

  const laidOutEdges: PreviewLayoutEdge[] = []
  validEdges.forEach((edge, index) => {
    const from = positioned.get(String(edge.from?.node || ''))
    const to = positioned.get(String(edge.to?.node || ''))
    if (!from || !to) return
    const x1 = from.x + PREVIEW_NODE_WIDTH
    const y1 = from.y + PREVIEW_NODE_HEIGHT / 2
    const x2 = to.x
    const y2 = to.y + PREVIEW_NODE_HEIGHT / 2
    let path: string
    if (x2 > x1) {
      const dx = Math.max(38, (x2 - x1) / 2)
      path = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`
    } else {
      // 环 / 同层连线：从下方绕回，避免穿过节点卡片。
      const bend = PREVIEW_NODE_HEIGHT + 26
      path = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + 46).toFixed(1)} ${(y1 + bend).toFixed(1)}, ${(x2 - 46).toFixed(1)} ${(y2 + bend).toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`
    }
    laidOutEdges.push({
      id: String(edge.id || `${edge.from?.node}-${edge.to?.node}-${index}`),
      path,
    })
  })

  return {
    width,
    height,
    nodes: boxes.map((box) => ({
      id: box.id,
      type: box.type,
      label: box.label,
      summaryLines: box.summaryLines,
      color: box.color,
      rank: box.rank,
      x: box.x,
      y: box.y,
      width: PREVIEW_NODE_WIDTH,
      height: PREVIEW_NODE_HEIGHT,
    })),
    edges: laidOutEdges,
  }
}

/**
 * 列表缩略图布局：每个拓扑层级一列，最多两行，节点块明显大于整图缩放。
 * 完整 DAG 缩放后节点会小到只剩色点，因此在卡片里改用「分层徽章」表示。
 */
export function buildCompactWorkflowPreviewLayout(
  nodes: PreviewNodeLike[] | null | undefined,
  edges: PreviewEdgeLike[] | null | undefined,
): WorkflowPreviewLayout {
  const unique = new Map<string, PreviewNodeLike>()
  for (const node of nodes || []) {
    if (!node || typeof node.id !== 'string' || !node.type || unique.has(node.id)) continue
    unique.set(node.id, node)
  }
  const source = [...unique.values()]
  if (!source.length) return { width: 320, height: 112, nodes: [], edges: [] }

  const children = new Map<string, string[]>()
  const parents = new Map<string, string[]>()
  const validEdges: PreviewEdgeLike[] = []
  for (const edge of edges || []) {
    const from = String(edge?.from?.node || '')
    const to = String(edge?.to?.node || '')
    if (!unique.has(from) || !unique.has(to) || from === to) continue
    validEdges.push(edge)
    children.set(from, [...(children.get(from) || []), to])
    parents.set(to, [...(parents.get(to) || []), from])
  }
  const rank = assignRanks(
    source.map((node) => node.id),
    children,
    parents,
  )
  const selected = [...source]
    .sort((a, b) => {
      const rankDiff = (rank.get(a.id) || 0) - (rank.get(b.id) || 0)
      if (rankDiff !== 0) return rankDiff
      const yDiff = (Number(a.y) || 0) - (Number(b.y) || 0)
      if (yDiff !== 0) return yDiff
      return a.id.localeCompare(b.id)
    })
    .slice(0, COMPACT_MAX_NODES)
  const shown = new Map(selected.map((node) => [node.id, node]))
  const maxRank = Math.max(...selected.map((node) => rank.get(node.id) || 0))
  const columns = Math.min(COMPACT_MAX_COLUMNS, maxRank + 1)
  const grouped = new Map<number, PreviewNodeLike[]>()
  for (const node of selected) {
    const column = Math.min(columns - 1, rank.get(node.id) || 0)
    grouped.set(column, [...(grouped.get(column) || []), node])
  }
  const width =
    COMPACT_PADDING * 2 +
    columns * COMPACT_NODE_WIDTH +
    Math.max(0, columns - 1) * COMPACT_COLUMN_GAP
  const height =
    COMPACT_PADDING * 2 +
    2 * COMPACT_NODE_HEIGHT +
    COMPACT_ROW_GAP
  const areaHeight = height - COMPACT_PADDING * 2
  const positioned = new Map<string, { x: number; y: number }>()
  for (const [column, group] of grouped) {
    const ordered = [...group].sort((a, b) => {
      const rankDiff = (rank.get(a.id) || 0) - (rank.get(b.id) || 0)
      if (rankDiff !== 0) return rankDiff
      return (Number(a.y) || 0) - (Number(b.y) || 0)
    })
    const groupHeight =
      ordered.length * COMPACT_NODE_HEIGHT +
      Math.max(0, ordered.length - 1) * COMPACT_ROW_GAP
    const startY = COMPACT_PADDING + Math.max(0, (areaHeight - groupHeight) / 2)
    ordered.slice(0, 2).forEach((node, row) => {
      positioned.set(node.id, {
        x:
          COMPACT_PADDING +
          column * (COMPACT_NODE_WIDTH + COMPACT_COLUMN_GAP),
        y: startY + row * (COMPACT_NODE_HEIGHT + COMPACT_ROW_GAP),
      })
    })
  }

  const laidOutEdges: PreviewLayoutEdge[] = []
  validEdges.forEach((edge, index) => {
    const fromId = String(edge.from?.node || '')
    const toId = String(edge.to?.node || '')
    const from = positioned.get(fromId)
    const to = positioned.get(toId)
    if (!from || !to || !shown.has(fromId) || !shown.has(toId)) return
    const x1 = from.x + COMPACT_NODE_WIDTH
    const y1 = from.y + COMPACT_NODE_HEIGHT / 2
    const x2 = to.x
    const y2 = to.y + COMPACT_NODE_HEIGHT / 2
    let path: string
    if (from.x === to.x) {
      // 同一列（分层压缩后）：竖直连接，避免绕出卡片底部的大回环。
      const cx = from.x + COMPACT_NODE_WIDTH / 2
      const startY = to.y > from.y ? from.y + COMPACT_NODE_HEIGHT : from.y
      const endY = to.y > from.y ? to.y : to.y + COMPACT_NODE_HEIGHT
      path = `M ${cx.toFixed(1)} ${startY.toFixed(1)} C ${(cx + 26).toFixed(1)} ${startY.toFixed(1)}, ${(cx + 26).toFixed(1)} ${endY.toFixed(1)}, ${cx.toFixed(1)} ${endY.toFixed(1)}`
    } else if (x2 > x1) {
      const dx = Math.max(14, (x2 - x1) / 2)
      path = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`
    } else {
      const bend = COMPACT_NODE_HEIGHT + 18
      path = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + 24).toFixed(1)} ${(y1 + bend).toFixed(1)}, ${(x2 - 24).toFixed(1)} ${(y2 + bend).toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`
    }
    laidOutEdges.push({
      id: String(edge.id || `${fromId}-${toId}-${index}`),
      path,
    })
  })

  return {
    width,
    height,
    nodes: selected
      .filter((node) => positioned.has(node.id))
      .map((node) => {
        const point = positioned.get(node.id)!
        return {
          id: node.id,
          type: node.type,
          label: '',
          summaryLines: [],
          color: previewNodeColor(node.type),
          rank: rank.get(node.id) || 0,
          x: point.x,
          y: point.y,
          width: COMPACT_NODE_WIDTH,
          height: COMPACT_NODE_HEIGHT,
        }
      }),
    edges: laidOutEdges,
  }
}
