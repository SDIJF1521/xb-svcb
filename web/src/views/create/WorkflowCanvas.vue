<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp, Close, Delete, FullScreen, Grid, MagicStick, Plus, RefreshLeft, RefreshRight, Setting, Upload } from '@element-plus/icons-vue'
import { api, type CoverWorkflow, type PymssModel, type WorkflowEdge, type WorkflowGraph, type WorkflowNode, type WorkflowNodeType } from '@/api'
import { translateUiText } from '@/i18n'
import { f0MethodsForFramework } from '@/utils/f0'
import { preferredPymssModel, pymssPurposeKey } from '@/utils/pymssPurpose'
import { trackPreview } from '@/utils/workflowTitle'
import PymssModelPicker from './PymssModelPicker.vue'

interface ModelOption {
  id: string
  name: string
  framework?: string
  /** 模型元数据（含软件检测出的 rvc_version 等）。 */
  metadata?: Record<string, unknown>
}

const props = withDefaults(
  defineProps<{
    models?: ModelOption[]
    uvrModels?: string[]
    pymssVocalModels?: string[]
    pymssHarmonyModels?: string[]
    pymssAllModels?: PymssModel[]
    songName?: string
    runStatus?: string
    runProgress?: number
    runSteps?: { key: string; status: string }[]
  }>(),
  {
    models: () => [],
    uvrModels: () => ['MDX-Net', 'Demucs v4', 'VR Arch'],
    pymssVocalModels: () => [],
    pymssHarmonyModels: () => [],
    pymssAllModels: () => [],
    songName: '',
    runStatus: '',
    runProgress: 0,
    runSteps: () => [],
  },
)

const emit = defineEmits<{
  (e: 'pick-song'): void
  (e: 'run'): void
  (e: 'download-pymss', name: string): void
}>()

const graph = defineModel<WorkflowGraph>({ required: true })

// ---- 节点元数据 ----
interface NodeMeta {
  label: string
  desc: string
  color: string
  inputs: string[]
  outputs: string[]
}

const NODE_META: Record<WorkflowNodeType, NodeMeta> = {
  input: { label: '输入', desc: '整首歌曲源音频', color: '#35a86b', inputs: [], outputs: ['audio'] },
  separate: { label: '人声分离', desc: 'UVR / PyMSS 分离人声与伴奏', color: '#3b82f6', inputs: ['audio'], outputs: ['vocals', 'instrumental'] },
  dereverb: { label: '去混响', desc: '去除混响 / 回声', color: '#8b6dff', inputs: ['audio'], outputs: ['audio'] },
  repair: { label: '人声修复', desc: 'DeepFilterNet3 修复伪影', color: '#14b8a6', inputs: ['audio'], outputs: ['audio'] },
  convert: { label: '歌声转换', desc: '按模型进行歌声转换', color: '#ff4f8b', inputs: ['audio'], outputs: ['audio'] },
  blend: { label: '合唱叠加', desc: '多路转换人声叠加', color: '#f59e0b', inputs: ['audio'], outputs: ['audio'] },
  enhance: { label: '歌声增强', desc: '自然修音 / 音色美化', color: '#35d07f', inputs: ['audio'], outputs: ['audio'] },
  mix: { label: '混音合成', desc: '人声与伴奏重新混音', color: '#e879f9', inputs: ['vocals', 'instrumental'], outputs: ['audio'] },
  output: { label: '保存', desc: '最终翻唱成品', color: '#f59e0b', inputs: ['audio'], outputs: [] },
}

const PORT_LABELS: Record<string, string> = {
  audio: '音频',
  vocals: '人声',
  instrumental: '伴奏',
  other: '其他音轨',
}

/** 端口可读名：stem:<label> 这类动态端口回落为音轨名。 */
function portLabel(port: string): string {
  const key = String(port || '')
  if (PORT_LABELS[key]) return PORT_LABELS[key]
  if (key.startsWith('stem:')) return key.slice(5)
  return key
}

const NODE_W = 268
const portKey = (nodeId: string, side: 'in' | 'out', port: string) => `${nodeId}:${side}:${port}`

// ---- 分离节点输出端口：按模型声明的音轨全量适配 ----
const SEPARATE_BASE_OUTPUTS = ['vocals', 'instrumental']
const SEPARATE_EXTRA_OUTPUTS = ['other', 'audio']
const DEFAULT_STEM_LIMIT = 8

/** 音轨名 → 端口 id（stem:<slug>），slug 规则与后端映射保持一致。 */
function stemPort(stem: string): string {
  const slug = String(stem || '')
    .trim()
    .replace(/[^0-9a-zA-Z_\u4e00-\u9fff]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase()
  return `stem:${slug || 'stem'}`
}

/** 该 PyMSS 模型声明的输出音轨（来自模型 yaml，未下载时为 undefined）。 */
function declaredStems(node: WorkflowNode): string[] {
  if (String(node.params?.engine || 'uvr').toLowerCase() !== 'pymss') return []
  const model = findPymssModel(String(node.params?.model || ''))
  const stems = (model?.stems || []).map((stem) => String(stem)).filter(Boolean)
  return stems
}

/** 主音轨：节点手动指定 → catalog 主音轨 → 声明顺序第一路。 */
function primaryStemOf(node: WorkflowNode): string {
  const stems = declaredStems(node)
  const chosen = String(node.params?.primary_stem || '')
  if (chosen && (!stems.length || stems.some((stem) => stem === chosen))) return chosen
  const model = findPymssModel(String(node.params?.model || ''))
  const fallback = String(model?.primary_stem || '')
  if (fallback) return fallback
  return stems[0] || chosen
}

function looksLikeAccompaniment(stem: string): boolean {
  return /instrument|accompan|karaoke|music|other/i.test(stem)
}

/** 默认展示的端口：音轨不多时全给，太多时只给主音轨 + 伴奏类。 */
function defaultSeparatePorts(node: WorkflowNode): string[] {
  const stems = declaredStems(node)
  if (!stems.length) {
    const model = findPymssModel(String(node.params?.model || ''))
    // 没有模型元数据时退回按用途推断
    if (model && pymssPurposeKey(model) === 'dereverb') return ['audio']
    return [...SEPARATE_BASE_OUTPUTS]
  }
  const primary = primaryStemOf(node)
  if (stems.length <= DEFAULT_STEM_LIMIT) return stems.map(stemPort)
  const accompaniment = stems.find((stem) => looksLikeAccompaniment(stem))
  const ports = [primary ? stemPort(primary) : '', accompaniment ? stemPort(accompaniment) : ''].filter(Boolean)
  return ports.length ? ports : stems.slice(0, DEFAULT_STEM_LIMIT).map(stemPort)
}

/** 分离节点当前可用的输出端口。 */
function separateOutputs(node: WorkflowNode): string[] {
  const choices = separateOutputChoices(node)
  const custom = Array.isArray(node.params?.outputs)
    ? (node.params.outputs as unknown[]).map((port) => String(port)).filter((port) => choices.includes(port))
    : []
  if (custom.length) return custom
  const ports = defaultSeparatePorts(node)
  // 旧工作流可能连在 vocals / audio / instrumental 这些通用别名上，
  // 后端始终会产出它们，保留下来避免升级后被误删。
  for (const edge of edges.value) {
    if (edge.from.node !== node.id) continue
    const port = edge.from.port
    if (ports.includes(port)) continue
    if (SEPARATE_BASE_OUTPUTS.includes(port) || SEPARATE_EXTRA_OUTPUTS.includes(port)) ports.push(port)
  }
  return ports
}

/** 分离节点可勾选的全部端口（模型声明音轨 + 通用端口）。 */
function separateOutputChoices(node: WorkflowNode): string[] {
  const stems = declaredStems(node)
  if (stems.length) {
    const stemPorts = stems.map(stemPort)
    const extra = ['other'].filter((port) => !stemPorts.includes(port))
    return [...stemPorts, ...extra]
  }
  return [...SEPARATE_BASE_OUTPUTS, ...SEPARATE_EXTRA_OUTPUTS]
}

/** 节点实际可用的输出端口。 */
function nodeOutputs(node: WorkflowNode): string[] {
  if (node.type === 'separate') return separateOutputs(node)
  return NODE_META[node.type]?.outputs || []
}

/** 模型输出说明：让用户一眼看出这个模型会产出哪些音轨。 */
function separateOutputHint(node: WorkflowNode): string {
  const ports = separateOutputs(node)
  const all = declaredStems(node).length
  const text = ports.map((port) => translateUiText(portLabel(port))).join(' + ')
  if (all > ports.length) return `${text} +${all - ports.length}`
  return text
}

function isPrimaryPort(node: WorkflowNode, port: string): boolean {
  const stems = declaredStems(node)
  if (!stems.length) return false
  return port === stemPort(primaryStemOf(node))
}

/** 模型没有配置文件（未下载）时给出说明。 */
function separateStemsUnknown(node: WorkflowNode): boolean {
  if (String(node.params?.engine || 'uvr').toLowerCase() !== 'pymss') return false
  return declaredStems(node).length === 0
}

// ---- 默认参数 ----
function defaultParams(type: WorkflowNodeType): Record<string, any> {
  switch (type) {
    case 'separate':
      return { engine: 'uvr', model: 'MDX-Net', device: 'auto' }
    case 'dereverb':
      return { engine: 'uvr', model: 'UVR-DeEcho-DeReverb.pth', device: 'auto' }
    case 'repair':
      return { device: 'auto' }
    case 'convert':
      return {
        model_id: '',
        pitch: 0,
        f0_method: 'rmvpe',
        device: 'auto',
        index_rate: 0.75,
        rms_mix: 0.25,
        diffusion_ratio: 0.5,
        protect: 0.33,
        filter_radius: 3,
        rvc_version: 'v2',
        reference_audio: '',
        ddsp_infer_steps: 50,
        ddsp_formant_shift: 0,
        auto_high_pitch_guard: true,
        high_pitch_guard_rounds: 3,
        f0_filter_threshold: 0.05,
        manual_params_enabled: false,
      }
    case 'blend':
      return {}
    case 'enhance':
      return {
        level: 'basic',
        device: 'auto',
        pitch_correction: 0.45,
        timing_alignment: 0.45,
        timbre_focus: 0.6,
        ai_eq: 0.55,
        ai_compressor: 0.45,
        ai_exciter: 0.25,
        stereo_width: 0.3,
        loudness_envelope: 0.58,
      }
    case 'mix':
      return { enhanced: false }
    case 'output':
      return { file_template: '%filename%_%stem%_%model%' }
    default:
      return {}
  }
}

let seq = 0
const nextId = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}${Math.random().toString(36).slice(2, 5)}`

// ---- 视图状态 ----
const rootEl = ref<HTMLElement | null>(null)
const canvasEl = ref<HTMLElement | null>(null)
const worldEl = ref<HTMLElement | null>(null)
const isMaximized = ref(false)
const panX = ref(60)
const panY = ref(30)
const zoom = ref(1)
const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)
// 仅在点击节点右上角「设置」齿轮时打开检查器，普通点击只选中节点。
const inspectorOpen = ref(false)
const connecting = ref<{ fromNode: string; fromPort: string; x: number; y: number } | null>(null)
const savedWorkflows = ref<CoverWorkflow[]>([])
const portOffsets = ref<Record<string, { x: number; y: number }>>({})

const nodes = computed(() => graph.value.nodes)
const edges = computed(() => graph.value.edges)
const nodeById = (id: string) => nodes.value.find((n) => n.id === id)
const selectedNode = computed(() => nodeById(selectedNodeId.value || '') || null)
const selectedEdge = computed(() => edges.value.find((e) => e.id === selectedEdgeId.value) || null)

const worldStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
  transformOrigin: '0 0',
}))

/** 端口中心相对节点左上角的偏移（世界坐标，由 DOM 实测）。 */
function portPos(node: WorkflowNode, side: 'in' | 'out', port: string) {
  const off = portOffsets.value[portKey(node.id, side, port)]
  return { x: node.x + (off?.x ?? 0), y: node.y + (off?.y ?? 0) }
}

function edgePath(e: WorkflowEdge): string {
  const from = nodeById(e.from.node)
  const to = nodeById(e.to.node)
  if (!from || !to) return ''
  const a = portPos(from, 'out', e.from.port)
  const b = portPos(to, 'in', e.to.port)
  const dx = Math.max(56, Math.abs(b.x - a.x) * 0.5)
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
}

const edgePaths = computed(() =>
  edges.value.map((e) => {
    const from = nodeById(e.from.node)
    const to = nodeById(e.to.node)
    return {
      id: e.id,
      d: edgePath(e),
      a: from ? portPos(from, 'out', e.from.port) : null,
      b: to ? portPos(to, 'in', e.to.port) : null,
    }
  }),
)

const hasInEdge = (nodeId: string, port: string) =>
  edges.value.some((e) => e.to.node === nodeId && e.to.port === port)

const saveInputCount = (node: WorkflowNode) => edges.value.filter((e) => e.to.node === node.id).length

function incomingEdges(node: WorkflowNode): WorkflowEdge[] {
  return edges.value.filter((e) => e.to.node === node.id)
}

function edgeUpstreamLabel(edge: WorkflowEdge): string {
  const from = nodeById(edge.from.node)
  if (!from) return '—'
  const label = translateUiText(NODE_META[from.type].label)
  const port = translateUiText(portLabel(edge.from.port))
  return `${label} · ${port}`
}

// ---- 运行进度 ----
const stepStatus = (nodeId: string): string =>
  props.runSteps.find((s) => s.key === nodeId)?.status || 'wait'

const activeNodeId = computed(
  () => props.runSteps.find((s) => s.status === 'active')?.key || '',
)
const activeStepLabel = computed(() => {
  const node = nodeById(activeNodeId.value)
  return node ? NODE_META[node.type].label : ''
})
const runLabel = computed(() => {
  switch (props.runStatus) {
    case 'queue':
      return translateUiText('排队中')
    case 'running': {
      const current = translateUiText(activeStepLabel.value)
      const base = `${translateUiText('运行中')} ${props.runProgress}%`
      return current ? `${base} · ${translateUiText('当前：')}${current}` : base
    }
    case 'done':
      return translateUiText('运行完成')
    case 'failed':
      return translateUiText('运行失败')
    default:
      return ''
  }
})
const isRunning = computed(() => props.runStatus === 'queue' || props.runStatus === 'running')

/** 让当前执行节点保持在可视区域内（不强制居中以免打扰用户操作）。 */
async function ensureNodeVisible(nodeId: string) {
  const node = nodeById(nodeId)
  const canvas = canvasEl.value
  if (!node || !canvas) return
  await nextTick()
  const el = worldEl.value?.querySelector<HTMLElement>(`[data-node-el="${nodeId}"]`)
  const h = el?.offsetHeight || 160
  const cw = canvas.clientWidth
  const ch = canvas.clientHeight
  const margin = 48
  const left = node.x * zoom.value + panX.value
  const top = node.y * zoom.value + panY.value
  const right = left + NODE_W * zoom.value
  const bottom = top + h * zoom.value
  let dx = 0
  let dy = 0
  if (left < margin) dx = margin - left
  else if (right > cw - margin) dx = cw - margin - right
  if (top < margin) dy = margin - top
  else if (bottom > ch - margin) dy = ch - margin - bottom
  if (dx) panX.value += dx
  if (dy) panY.value += dy
  if (dx || dy) void measurePorts()
}

watch(activeNodeId, (id) => {
  if (id && isRunning.value) void ensureNodeVisible(id)
})

// ---- 端口位置测量 ----
async function measurePorts() {
  await nextTick()
  const world = worldEl.value
  if (!world) return
  const next: Record<string, { x: number; y: number }> = {}
  const z = zoom.value || 1
  for (const node of nodes.value) {
    const nodeEl = world.querySelector<HTMLElement>(`[data-node-el="${node.id}"]`)
    if (!nodeEl) continue
    const nr = nodeEl.getBoundingClientRect()
    nodeEl.querySelectorAll<HTMLElement>('[data-port-key]').forEach((portEl) => {
      const key = portEl.dataset.portKey
      if (!key) return
      const pr = portEl.getBoundingClientRect()
      next[key] = {
        x: (pr.left + pr.width / 2 - nr.left) / z,
        y: (pr.top + pr.height / 2 - nr.top) / z,
      }
    })
  }
  portOffsets.value = next
}

watch(
  () => [nodes.value.length, graph.value.id] as const,
  () => void measurePorts(),
)

// ---- 画布交互 ----
function clientToWorld(clientX: number, clientY: number) {
  const rect = canvasEl.value?.getBoundingClientRect()
  return {
    x: (clientX - (rect?.left || 0) - panX.value) / zoom.value,
    y: (clientY - (rect?.top || 0) - panY.value) / zoom.value,
  }
}

function onWheel(e: WheelEvent) {
  const rect = canvasEl.value?.getBoundingClientRect()
  if (!rect) return
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const worldX = (mx - panX.value) / zoom.value
  const worldY = (my - panY.value) / zoom.value
  const factor = Math.pow(1.0015, -e.deltaY)
  zoom.value = Math.max(0.25, Math.min(3, zoom.value * factor))
  panX.value = mx - worldX * zoom.value
  panY.value = my - worldY * zoom.value
  void measurePorts()
}

function setZoom(next: number) {
  zoom.value = Math.max(0.25, Math.min(3, next))
  void measurePorts()
}

/** 自动缩放平移，让整张工作流刚好铺满画布。 */
async function fitView() {
  const canvas = canvasEl.value
  if (!canvas || !nodes.value.length) return
  await nextTick()
  const cw = canvas.clientWidth
  const ch = canvas.clientHeight
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const node of nodes.value) {
    const el = worldEl.value?.querySelector<HTMLElement>(`[data-node-el="${node.id}"]`)
    const h = el?.offsetHeight || 160
    minX = Math.min(minX, node.x)
    minY = Math.min(minY, node.y)
    maxX = Math.max(maxX, node.x + NODE_W)
    maxY = Math.max(maxY, node.y + h)
  }
  if (!Number.isFinite(minX)) return
  const pad = 70
  const w = maxX - minX + pad * 2
  const h = maxY - minY + pad * 2
  zoom.value = Math.max(0.3, Math.min(1.15, Math.min(cw / w, ch / h)))
  panX.value = (cw - (maxX - minX) * zoom.value) / 2 - minX * zoom.value
  panY.value = (ch - (maxY - minY) * zoom.value) / 2 - minY * zoom.value
  void measurePorts()
}

// ---- 一键整理 ----
const LAYOUT_ROW_GAP = 36
const LAYOUT_COL_GAP = 104
const LAYOUT_MARGIN = 80

function nodeHeightOf(node: WorkflowNode): number {
  const el = worldEl.value?.querySelector<HTMLElement>(`[data-node-el="${node.id}"]`)
  return el?.offsetHeight || 160
}

/** 分层：节点层级 = 上游最长路径长度，无入边的节点为第 0 层。 */
function layoutRanks(): Map<string, number> {
  const rank = new Map<string, number>()
  const preds = new Map<string, string[]>()
  for (const node of nodes.value) rank.set(node.id, 0)
  for (const edge of edges.value) {
    const list = preds.get(edge.to.node)
    if (list) list.push(edge.from.node)
    else preds.set(edge.to.node, [edge.from.node])
  }
  // 固定次数松弛，避免脏数据里的环导致死循环
  const limit = nodes.value.length + 1
  for (let i = 0; i < limit; i += 1) {
    let changed = false
    for (const node of nodes.value) {
      let best = 0
      for (const from of preds.get(node.id) || []) {
        best = Math.max(best, (rank.get(from) ?? 0) + 1)
      }
      if (best > (rank.get(node.id) ?? 0)) {
        rank.set(node.id, best)
        changed = true
      }
    }
    if (!changed) break
  }
  return rank
}

/**
 * 一键整理：按连线依赖分层、从左到右排列，同层纵向居中铺开，
 * 并用重心法做多轮扫描以减少连线交叉，最后自动缩放铺满画布。
 */
async function tidyLayout() {
  if (!nodes.value.length) return
  await nextTick()
  const heights = new Map<string, number>()
  for (const node of nodes.value) heights.set(node.id, nodeHeightOf(node))
  const h = (id: string) => heights.get(id) || 160

  const rank = layoutRanks()
  const columns = new Map<number, WorkflowNode[]>()
  for (const node of nodes.value) {
    const r = rank.get(node.id) ?? 0
    const list = columns.get(r)
    if (list) list.push(node)
    else columns.set(r, [node])
  }
  const ranks = [...columns.keys()].sort((a, b) => a - b)
  const columnIndex = new Map<number, number>()
  ranks.forEach((r, i) => columnIndex.set(r, i))

  const preds = new Map<string, string[]>()
  const succs = new Map<string, string[]>()
  for (const edge of edges.value) {
    if (!preds.has(edge.to.node)) preds.set(edge.to.node, [])
    preds.get(edge.to.node)!.push(edge.from.node)
    if (!succs.has(edge.from.node)) succs.set(edge.from.node, [])
    succs.get(edge.from.node)!.push(edge.to.node)
  }

  // 保留用户当前的相对上下顺序作为初始次序
  const centerY = new Map<string, number>()
  for (const node of nodes.value) centerY.set(node.id, node.y + h(node.id) / 2)
  for (const list of columns.values()) list.sort((a, b) => (centerY.get(a.id) ?? 0) - (centerY.get(b.id) ?? 0))

  // 目标纵坐标先算在临时表里，不改动原节点，保证整理的撤销能完整还原
  const posY = new Map<string, number>()
  const stackColumn = (list: WorkflowNode[]) => {
    const total = list.reduce((sum, n) => sum + h(n.id), 0) + LAYOUT_ROW_GAP * Math.max(0, list.length - 1)
    let y = -total / 2
    for (const node of list) {
      centerY.set(node.id, y + h(node.id) / 2)
      posY.set(node.id, Math.round(y))
      y += h(node.id) + LAYOUT_ROW_GAP
    }
  }

  const averageY = (ids: string[] | undefined, fallback: number) => {
    if (!ids || !ids.length) return fallback
    let sum = 0
    let count = 0
    for (const id of ids) {
      const value = centerY.get(id)
      if (typeof value === 'number') {
        sum += value
        count += 1
      }
    }
    return count ? sum / count : fallback
  }

  // 重心法排序：交替自上而下 / 自下而上扫描，减少交叉连线
  for (let round = 0; round < 4; round += 1) {
    const down = round % 2 === 0
    for (const r of down ? ranks : [...ranks].reverse()) {
      const list = columns.get(r)
      if (!list || list.length < 2) continue
      const ref = down ? preds : succs
      list.sort(
        (a, b) =>
          averageY(ref.get(a.id), centerY.get(a.id) ?? 0) - averageY(ref.get(b.id), centerY.get(b.id) ?? 0),
      )
    }
    for (const r of ranks) {
      const list = columns.get(r)
      if (list) stackColumn(list)
    }
  }

  let minX = Infinity
  let minY = Infinity
  const targets: { node: WorkflowNode; x: number; y: number }[] = []
  for (const node of nodes.value) {
    const col = columnIndex.get(rank.get(node.id) ?? 0) ?? 0
    const x = Math.round(col * (NODE_W + LAYOUT_COL_GAP))
    const y = posY.get(node.id) ?? Math.round(node.y)
    targets.push({ node, x, y })
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
  }
  const shiftX = LAYOUT_MARGIN - (Number.isFinite(minX) ? minX : 0)
  const shiftY = LAYOUT_MARGIN - (Number.isFinite(minY) ? minY : 0)

  // 记录整理前状态，便于 Ctrl+Z 一键还原
  pushHistory()
  for (const target of targets) {
    target.node.x = target.x + shiftX
    target.node.y = target.y + shiftY
  }
  pushHistory()
  void measurePorts()
  await nextTick()
  await fitView()
  ElMessage.success('已自动整理画布节点')
}

const panning = ref<{ startX: number; startY: number; ox: number; oy: number } | null>(null)
function onPanStart(e: PointerEvent) {
  if ((e.target as HTMLElement).closest('.wf-node')) return
  selectedNodeId.value = null
  selectedEdgeId.value = null
  inspectorOpen.value = false
  panning.value = { startX: e.clientX, startY: e.clientY, ox: panX.value, oy: panY.value }
  window.addEventListener('pointermove', onPanMove)
  window.addEventListener('pointerup', onPanEnd)
}
function onPanMove(e: PointerEvent) {
  if (!panning.value) return
  panX.value = panning.value.ox + (e.clientX - panning.value.startX)
  panY.value = panning.value.oy + (e.clientY - panning.value.startY)
}
function onPanEnd() {
  panning.value = null
  window.removeEventListener('pointermove', onPanMove)
  window.removeEventListener('pointerup', onPanEnd)
}

const dragging = ref<{ id: string; ox: number; oy: number; sx: number; sy: number } | null>(null)
function onNodeDragStart(node: WorkflowNode, e: PointerEvent) {
  selectedNodeId.value = node.id
  selectedEdgeId.value = null
  dragging.value = { id: node.id, ox: node.x, oy: node.y, sx: e.clientX, sy: e.clientY }
  window.addEventListener('pointermove', onNodeDragMove)
  window.addEventListener('pointerup', onNodeDragEnd)
}
function onNodeDragMove(e: PointerEvent) {
  const d = dragging.value
  if (!d) return
  const node = nodeById(d.id)
  if (!node) return
  node.x = Math.round((d.ox + (e.clientX - d.sx) / zoom.value) * 10) / 10
  node.y = Math.round((d.oy + (e.clientY - d.sy) / zoom.value) * 10) / 10
}
function onNodeDragEnd() {
  dragging.value = null
  window.removeEventListener('pointermove', onNodeDragMove)
  window.removeEventListener('pointerup', onNodeDragEnd)
  void measurePorts()
}

function onOutputPortDown(node: WorkflowNode, port: string, e: PointerEvent) {
  e.stopPropagation()
  const p = portPos(node, 'out', port)
  connecting.value = { fromNode: node.id, fromPort: port, x: p.x, y: p.y }
  window.addEventListener('pointermove', onConnectMove)
  window.addEventListener('pointerup', onConnectEnd)
}
function onConnectMove(e: PointerEvent) {
  if (!connecting.value) return
  const w = clientToWorld(e.clientX, e.clientY)
  connecting.value.x = w.x
  connecting.value.y = w.y
}
function onConnectEnd(e: PointerEvent) {
  const started = connecting.value
  connecting.value = null
  window.removeEventListener('pointermove', onConnectMove)
  window.removeEventListener('pointerup', onConnectEnd)
  if (!started) return
  const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null
  const portEl = el?.closest?.('[data-port-side="in"]') as HTMLElement | null
  if (!portEl) return
  const targetNode = portEl.dataset.node
  const targetPort = portEl.dataset.port
  if (!targetNode || !targetPort || targetNode === started.fromNode) return
  connectPorts(started.fromNode, started.fromPort, targetNode, targetPort)
}

function connectPorts(fromNode: string, fromPort: string, toNode: string, toPort: string) {
  const sourceNode = nodeById(fromNode)
  if (!sourceNode || !nodeOutputs(sourceNode).includes(fromPort)) return
  const meta = NODE_META[nodeById(toNode)?.type || 'input']
  const multiType = nodeById(toNode)?.type
  // 合唱叠加与保存节点允许一个输入端口接入多路音轨。
  const multi = (multiType === 'blend' || multiType === 'output') && meta.inputs.includes(toPort)
  if (multi) {
    const dup = edges.value.find(
      (e) => e.from.node === fromNode && e.from.port === fromPort && e.to.node === toNode && e.to.port === toPort,
    )
    if (dup) return
  } else {
    const existing = edges.value.find((e) => e.to.node === toNode && e.to.port === toPort)
    if (existing) edges.value.splice(edges.value.indexOf(existing), 1)
  }
  edges.value.push({ id: nextId('e_'), from: { node: fromNode, port: fromPort }, to: { node: toNode, port: toPort } })
}

// ---- 增删 / 复制 ----
const saveNode = () => nodes.value.find((n) => n.type === 'output') || null

function placeNode(type: WorkflowNodeType, at?: { x: number; y: number }): WorkflowNode {
  // 一个工作流只保留一个保存节点，重复添加时选中已有的那个。
  if (type === 'output') {
    const existing = saveNode()
    if (existing) {
      selectedNodeId.value = existing.id
      ElMessage.info('一个工作流只保留一个保存节点')
      return existing
    }
  }
  const cw = canvasEl.value?.clientWidth || 900
  const ch = canvasEl.value?.clientHeight || 560
  const center = at || {
    x: (cw / 2 - panX.value) / zoom.value - NODE_W / 2,
    y: (ch / 2 - panY.value) / zoom.value - 60,
  }
  const node: WorkflowNode = {
    id: nextId('n_'),
    type,
    x: Math.round(center.x),
    y: Math.round(center.y),
    params: defaultParams(type),
  }
  nodes.value.push(node)
  selectedNodeId.value = node.id
  void measurePorts()
  return node
}

/** 删除一条连线；保存节点内被删除的连线对应的音频即视为删除。 */
function removeEdgeById(id: string) {
  const idx = edges.value.findIndex((e) => e.id === id)
  if (idx >= 0) edges.value.splice(idx, 1)
  if (selectedEdgeId.value === id) selectedEdgeId.value = null
  void measurePorts()
}

/** 快捷连线：把某节点的输出音轨接入唯一的保存节点。 */
function toggleSaveLink(node: WorkflowNode, port: string) {
  const target = saveNode() ?? placeNode('output', { x: node.x + NODE_W + 140, y: node.y })
  const toPort = 'audio'
  const existing = edges.value.find(
    (e) => e.from.node === node.id && e.from.port === port && e.to.node === target.id && e.to.port === toPort,
  )
  if (existing) {
    edges.value.splice(edges.value.indexOf(existing), 1)
  } else {
    edges.value.push({ id: nextId('e_'), from: { node: node.id, port }, to: { node: target.id, port: toPort } })
  }
  void measurePorts()
}

function addNode(type: WorkflowNodeType) {
  placeNode(type)
}

function onPaletteDrop(e: DragEvent) {
  const type = e.dataTransfer?.getData('application/x-wf-node') as WorkflowNodeType | ''
  if (!type || !NODE_META[type]) return
  const w = clientToWorld(e.clientX, e.clientY)
  placeNode(type, { x: w.x - NODE_W / 2, y: w.y - 40 })
}

function onPaletteDragStart(e: DragEvent, type: WorkflowNodeType) {
  e.dataTransfer?.setData('application/x-wf-node', type)
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'copy'
}

function removeNode(id: string) {
  const idx = nodes.value.findIndex((n) => n.id === id)
  if (idx < 0) return
  nodes.value.splice(idx, 1)
  for (let i = edges.value.length - 1; i >= 0; i -= 1) {
    const e = edges.value[i]!
    if (e.from.node === id || e.to.node === id) edges.value.splice(i, 1)
  }
  if (selectedNodeId.value === id) selectedNodeId.value = null
  void measurePorts()
}

function moveNode(node: WorkflowNode, dy: number) {
  node.y = Math.round((node.y + dy) * 10) / 10
  void measurePorts()
}

/** 点击节点右上角齿轮：选中并打开设置面板。 */
function focusInspector(node: WorkflowNode) {
  selectedNodeId.value = node.id
  selectedEdgeId.value = null
  inspectorOpen.value = true
}

/** 节点副标题：显示当前选中的模型名，匹配参考设计。 */
function nodeSubtitle(node: WorkflowNode): string {
  switch (node.type) {
    case 'separate':
      return String(node.params?.model || '') || translateUiText('未选择模型')
    case 'convert': {
      const id = String(node.params?.model_id || '')
      return props.models.find((m) => m.id === id)?.name || translateUiText('未选择模型')
    }
    case 'input':
      return props.songName || translateUiText('未选择歌曲')
    case 'dereverb':
      return String(node.params?.model || '') || translateUiText('去混响')
    case 'repair':
      return 'DeepFilterNet3'
    case 'enhance':
      return translateUiText(
        node.params?.level === 'advanced' ? '高级层 Natural Voice' : '基础层 Clean Voice',
      )
    case 'mix':
      return translateUiText('人声 + 伴奏')
    case 'blend':
      return translateUiText('多路合唱')
    default:
      return ''
  }
}

/** 输入来源：显示当前连接到本节点输入的来源。 */
function inputSourceLabel(node: WorkflowNode): string {
  const edge = edges.value.find((e) => e.to.node === node.id && e.to.port === (NODE_META[node.type].inputs[0] || 'audio'))
  if (!edge) return translateUiText('未连接')
  const from = nodeById(edge.from.node)
  if (!from) return translateUiText('未连接')
  return from.type === 'input'
    ? translateUiText('原始输入')
    : `${translateUiText(NODE_META[from.type].label)} · ${translateUiText(portLabel(edge.from.port))}`
}

/** 该输出端口是否已连接到某个「保存」节点。 */
function connectsToSave(nodeId: string, port: string): boolean {
  return edges.value.some(
    (e) => e.from.node === nodeId && e.from.port === port && nodeById(e.to.node)?.type === 'output',
  )
}

/** 保存节点中某条音轨的文件名预览。 */
function trackPreviewFor(edge: WorkflowEdge): string {
  return trackPreview(graph.value, edge, props.songName, props.models)
}

/** 自动把上游最后一段音频输出连接到保存节点。 */
function autoConnectSave(node: WorkflowNode) {
  const meta = NODE_META[node.type]
  const inputPort = meta.inputs[0] || 'audio'
  const hasOut = (n: WorkflowNode) => edges.value.some((e) => e.from.node === n.id)
  const candidates = nodes.value.filter(
    (n) => n.id !== node.id && NODE_META[n.type].outputs.length > 0,
  )
  // 优先：尚未向下游连线的「末端生产者」，其中混音优先、越靠右越优先。
  const dangling = candidates.filter((n) => !hasOut(n))
  const pool = (dangling.length ? dangling : candidates).slice()
  pool.sort((a, b) => {
    const am = a.type === 'mix' ? 1 : 0
    const bm = b.type === 'mix' ? 1 : 0
    if (am !== bm) return bm - am
    return b.x - a.x
  })
  const chosen = pool[0]
  if (!chosen) return
  const outs = NODE_META[chosen.type].outputs
  const outPort = outs.includes('audio') ? 'audio' : outs[0]!
  // 保存节点支持多路音轨，自动连接只补齐缺失的一路，不覆盖已有音轨。
  const dup = edges.value.find(
    (e) => e.from.node === chosen.id && e.from.port === outPort && e.to.node === node.id && e.to.port === inputPort,
  )
  if (dup) return
  edges.value.push({ id: nextId('e_'), from: { node: chosen.id, port: outPort }, to: { node: node.id, port: inputPort } })
  void measurePorts()
}

function deleteSelectedEdge() {
  if (!selectedEdgeId.value) return
  edges.value.splice(edges.value.findIndex((e) => e.id === selectedEdgeId.value), 1)
  selectedEdgeId.value = null
}

function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

function onKeydown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey
  if (mod && e.key.toLowerCase() === 'z') {
    if (isEditableTarget(e.target)) return
    e.preventDefault()
    if (e.shiftKey) redo()
    else undo()
    return
  }
  if (mod && e.key.toLowerCase() === 'y') {
    if (isEditableTarget(e.target)) return
    e.preventDefault()
    redo()
    return
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (isEditableTarget(e.target)) return
    if (selectedEdgeId.value) deleteSelectedEdge()
    else if (selectedNodeId.value) removeNode(selectedNodeId.value)
  }
}

// ---- 撤销 / 重做 ----
const history = ref<string[]>([])
const historyIndex = ref(-1)
let applyingHistory = false
let historyTimer: ReturnType<typeof setTimeout> | null = null

const canUndo = computed(() => historyIndex.value > 0)
const canRedo = computed(() => historyIndex.value < history.value.length - 1)

function snapshotGraph(): string {
  return JSON.stringify({ nodes: graph.value.nodes, edges: graph.value.edges })
}

function pushHistory() {
  const snap = snapshotGraph()
  if (historyIndex.value >= 0 && history.value[historyIndex.value] === snap) return
  history.value = history.value.slice(0, historyIndex.value + 1)
  history.value.push(snap)
  if (history.value.length > 120) history.value.shift()
  historyIndex.value = history.value.length - 1
}

function scheduleHistory() {
  if (applyingHistory) return
  if (historyTimer) clearTimeout(historyTimer)
  historyTimer = setTimeout(() => {
    historyTimer = null
    pushHistory()
  }, 300)
}

function applySnapshot(snap: string) {
  applyingHistory = true
  const data = JSON.parse(snap) as { nodes: WorkflowNode[]; edges: WorkflowEdge[] }
  graph.value = { ...graph.value, nodes: data.nodes, edges: data.edges }
  if (selectedNodeId.value && !graph.value.nodes.some((n) => n.id === selectedNodeId.value)) {
    selectedNodeId.value = null
  }
  selectedEdgeId.value = null
  void nextTick(() => {
    applyingHistory = false
    void measurePorts()
  })
}

function undo() {
  if (!canUndo.value) return
  historyIndex.value -= 1
  const snap = history.value[historyIndex.value]
  if (snap) applySnapshot(snap)
}

function redo() {
  if (!canRedo.value) return
  historyIndex.value += 1
  const snap = history.value[historyIndex.value]
  if (snap) applySnapshot(snap)
}

watch(graph, () => scheduleHistory(), { deep: true })

// ---- 全屏 / 最大化 ----
function toggleMaximize() {
  isMaximized.value = !isMaximized.value
  void nextTick(() => {
    void fitView()
  })
}

// ---- 保存 / 加载 ----
async function refreshWorkflows() {
  try {
    savedWorkflows.value = await api.listCoverWorkflows()
  } catch {
    savedWorkflows.value = []
  }
}

async function saveWorkflow() {
  graph.value.name = (graph.value.name || '').trim() || '未命名工作流'
  try {
    const saved = await api.saveCoverWorkflow(graph.value.name, { ...graph.value })
    graph.value.id = saved.id
    graph.value.updated_at = saved.updated_at
    ElMessage.success('工作流已保存')
    await refreshWorkflows()
  } catch (err) {
    ElMessage.error(`保存失败：${err instanceof Error ? err.message : String(err)}`)
  }
}

async function loadWorkflow(id: string) {
  const wf = savedWorkflows.value.find((w) => w.id === id)
  if (!wf) return
  graph.value = { id: wf.id, name: wf.name, updated_at: wf.updated_at, nodes: wf.nodes, edges: wf.edges }
  normalizeNodes()
  selectedNodeId.value = null
  selectedEdgeId.value = null
  await fitView()
}

async function deleteWorkflow() {
  if (!graph.value.id) return
  try {
    await api.deleteCoverWorkflow(graph.value.id)
    graph.value.id = ''
    ElMessage.success('已删除已保存的工作流')
    await refreshWorkflows()
  } catch {
    ElMessage.error('删除失败')
  }
}

/** 兼容旧版保存的工作流：补齐新增的引擎 / 文件名模板等参数。 */
function normalizeNodes() {
  for (const node of graph.value.nodes) {
    if (!node.params) node.params = {}
    if ((node.type === 'separate' || node.type === 'dereverb') && !node.params.engine) {
      node.params.engine = 'uvr'
    }
    if (node.type === 'separate' && node.params.outputs !== undefined && !Array.isArray(node.params.outputs)) {
      delete node.params.outputs
    }
    if (node.type === 'output' && !node.params.file_template) {
      node.params.file_template = '%filename%_%stem%_%model%'
    }
  }
  // 旧工作流可能连了当前模型并不输出的音轨，载入时静默清理。
  for (const node of graph.value.nodes) {
    if (node.type === 'separate') pruneStalePortEdges(node, true)
  }
}

function newWorkflow() {
  const input: WorkflowNode = { id: nextId('n_'), type: 'input', x: 60, y: 170, params: {} }
  const separate: WorkflowNode = { id: nextId('n_'), type: 'separate', x: 360, y: 120, params: defaultParams('separate') }
  const convert: WorkflowNode = { id: nextId('n_'), type: 'convert', x: 670, y: 40, params: defaultParams('convert') }
  const enhance: WorkflowNode = { id: nextId('n_'), type: 'enhance', x: 670, y: 300, params: defaultParams('enhance') }
  const mix: WorkflowNode = { id: nextId('n_'), type: 'mix', x: 980, y: 170, params: defaultParams('mix') }
  const output: WorkflowNode = { id: nextId('n_'), type: 'output', x: 1280, y: 170, params: defaultParams('output') }
  const edges: WorkflowEdge[] = [
    { id: nextId('e_'), from: { node: input.id, port: 'audio' }, to: { node: separate.id, port: 'audio' } },
    { id: nextId('e_'), from: { node: separate.id, port: 'vocals' }, to: { node: convert.id, port: 'audio' } },
    { id: nextId('e_'), from: { node: separate.id, port: 'instrumental' }, to: { node: mix.id, port: 'instrumental' } },
    { id: nextId('e_'), from: { node: convert.id, port: 'audio' }, to: { node: enhance.id, port: 'audio' } },
    { id: nextId('e_'), from: { node: enhance.id, port: 'audio' }, to: { node: mix.id, port: 'vocals' } },
    { id: nextId('e_'), from: { node: mix.id, port: 'audio' }, to: { node: output.id, port: 'audio' } },
  ]
  graph.value = { id: '', name: '新工作流', updated_at: '', nodes: [input, separate, convert, enhance, mix, output], edges }
  selectedNodeId.value = null
  selectedEdgeId.value = null
  void fitView()
}

const frameworkOptions = [
  { label: 'So-VITS-SVC', value: 'so-vits-svc' },
  { label: 'RVC', value: 'rvc' },
  { label: 'SeedVC', value: 'seed-vc' },
  { label: 'DDSP-SVC', value: 'ddsp-svc' },
]

function frameworkOf(modelId: string): string {
  return props.models.find((m) => m.id === modelId)?.framework || ''
}

/** 歌声转换节点当前模型所属框架，用于只显示该框架相关的参数。 */
function convertFramework(node: WorkflowNode): string {
  return frameworkOf(String(node.params?.model_id || ''))
}

function num(node: WorkflowNode, key: string, fallback = 0): number {
  const value = Number(node.params?.[key])
  return Number.isFinite(value) ? value : fallback
}

/** 软件检测出的 RVC 版本（v1/v2）；未检测到返回空串。 */
function detectedRvcVersion(node: WorkflowNode): string {
  const id = String(node.params?.model_id || '')
  const value = String(
    props.models.find((m) => m.id === id)?.metadata?.rvc_version || '',
  ).toLowerCase()
  return value === 'v1' || value === 'v2' ? value : ''
}

/** RVC 版本展示文案：自动 · vX（无需用户手动选择）。 */
function rvcVersionLabel(node: WorkflowNode): string {
  const version = detectedRvcVersion(node)
  return version ? `${translateUiText('自动')} · ${version}` : translateUiText('自动')
}

/** 高音保护轮次文案：0 = 自动（与单模型全参数保持一致）。 */
function highPitchGuardRoundsText(rounds: number): string {
  const value = Math.max(0, Math.round(rounds || 0))
  return value === 0 ? translateUiText('自动（系统接管）') : `${value} ${translateUiText('轮')}`
}

const DEVICE_OPTIONS = [
  { label: '自动', value: 'auto' },
  { label: 'CUDA', value: 'cuda' },
  { label: 'ROCm', value: 'rocm' },
  { label: 'DirectML', value: 'directml' },
  { label: 'CPU', value: 'cpu' },
]

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  if (!graph.value.nodes?.length) newWorkflow()
  else void fitView()
  normalizeNodes()
  void refreshWorkflows()
  pushHistory()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pointermove', onPanMove)
  window.removeEventListener('pointerup', onPanEnd)
  window.removeEventListener('pointermove', onNodeDragMove)
  window.removeEventListener('pointerup', onNodeDragEnd)
  window.removeEventListener('pointermove', onConnectMove)
  window.removeEventListener('pointerup', onConnectEnd)
})

const paletteEntries = (Object.keys(NODE_META) as WorkflowNodeType[]).map((type) => ({
  type,
  ...NODE_META[type],
}))

// ---- PyMSS 全量模型目录 ----
function findPymssModel(name: string): PymssModel | undefined {
  return props.pymssAllModels.find((m) => m.name === name)
}

function onSeparateEngineChange(node: WorkflowNode) {
  if (node.params.engine === 'pymss') {
    if (!findPymssModel(node.params.model)) {
      node.params.model = preferredPymssModel(props.pymssAllModels, 'vocal_separation', 'bs_roformer_voc_hyperacev2')
    }
  } else if (!props.uvrModels.includes(node.params.model)) {
    node.params.model = props.uvrModels[0] || 'MDX-Net'
  }
  delete node.params.outputs
  pruneStalePortEdges(node)
}

function onDereverbEngineChange(node: WorkflowNode) {
  if (node.params.engine === 'pymss') {
    if (!findPymssModel(node.params.model)) {
      node.params.model = preferredPymssModel(props.pymssAllModels, 'dereverb', 'UVR-DeEcho-DeReverb.pth')
    }
  } else if (!node.params.model || findPymssModel(node.params.model)) {
    node.params.model = 'UVR-DeEcho-DeReverb.pth'
  }
}

// ---- 分离节点输出端口适配 ----
/** 输出端口变化后清理指向已消失端口的连线（该模型不再产出这路音轨）。 */
function pruneStalePortEdges(node: WorkflowNode, quiet = false): number {
  const ports = nodeOutputs(node)
  let removed = 0
  for (let i = edges.value.length - 1; i >= 0; i -= 1) {
    const edge = edges.value[i]
    if (edge && edge.from.node === node.id && !ports.includes(edge.from.port)) {
      edges.value.splice(i, 1)
      removed += 1
    }
  }
  if (!removed) return 0
  if (!quiet) ElMessage.info(`已移除 ${removed} 条失效连线：该模型的输出音轨已变化`)
  void measurePorts()
  return removed
}

/** 切换 PyMSS 模型：输出端口回到「按模型适配」并清理失效连线。 */
function onSeparateModelChange(node: WorkflowNode, model: string) {
  node.params.model = model
  delete node.params.outputs
  pruneStalePortEdges(node)
}

function isSeparateOutputOn(node: WorkflowNode, port: string): boolean {
  return separateOutputs(node).includes(port)
}

/** 手动勾选该模型实际输出的音轨（PyMSS 不同模型输出不一致）。 */
function toggleSeparateOutput(node: WorkflowNode, port: string) {
  const choices = separateOutputChoices(node)
  const current = separateOutputs(node)
  const next = current.includes(port) ? current.filter((item) => item !== port) : [...current, port]
  if (!next.length) {
    ElMessage.warning('至少保留一路输出音轨')
    return
  }
  node.params.outputs = choices.filter((item) => next.includes(item))
  pruneStalePortEdges(node)
}

/** 指定哪一路是该模型的主音轨（决定「人声/音频」端口的实际内容）。 */
function setPrimaryStem(node: WorkflowNode, stem: string) {
  if (!stem) delete node.params.primary_stem
  else node.params.primary_stem = stem
}

function resetSeparateOutputs(node: WorkflowNode) {
  delete node.params.outputs
  pruneStalePortEdges(node)
}

const ENHANCE_CONTROLS: { key: string; label: string }[] = [
  { key: 'pitch_correction', label: '自然修音' },
  { key: 'timing_alignment', label: 'AI 对齐' },
  { key: 'timbre_focus', label: '角色共振峰' },
  { key: 'ai_eq', label: 'AI EQ' },
  { key: 'ai_compressor', label: 'AI Compressor' },
  { key: 'ai_exciter', label: 'AI Exciter' },
  { key: 'stereo_width', label: 'Stereo' },
  { key: 'loudness_envelope', label: '响度包络' },
]
</script>

<template>
  <div ref="rootEl" class="wf" :class="{ 'wf--max': isMaximized }">
    <div class="wf-toolbar">
      <el-input v-model="graph.name" class="wf-name" placeholder="工作流名称" size="small" />
      <el-button round size="small" class="ghost-btn" @click="newWorkflow">
        <el-icon class="el-icon--left"><Plus /></el-icon>新建
      </el-button>
      <el-button round size="small" class="ghost-btn" @click="saveWorkflow">
        <el-icon class="el-icon--left"><Upload /></el-icon>保存
      </el-button>
      <el-select
        :model-value="graph.id"
        size="small"
        class="wf-load"
        placeholder="载入已保存工作流"
        @update:model-value="loadWorkflow"
      >
        <el-option v-for="w in savedWorkflows" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <el-button v-if="graph.id" round size="small" class="ghost-btn" @click="deleteWorkflow">
        <el-icon class="el-icon--left"><Delete /></el-icon>删除已保存
      </el-button>
      <el-button round size="small" class="ghost-btn" :disabled="!canUndo" @click="undo">
        <el-icon class="el-icon--left"><RefreshLeft /></el-icon>撤销
      </el-button>
      <el-button round size="small" class="ghost-btn" :disabled="!canRedo" @click="redo">
        <el-icon class="el-icon--left"><RefreshRight /></el-icon>重做
      </el-button>
      <el-button
        round
        size="small"
        class="ghost-btn"
        :disabled="!nodes.length"
        title="按连线依赖自动排列节点，减少交叉"
        @click="tidyLayout"
      >
        <el-icon class="el-icon--left"><Grid /></el-icon>一键整理
      </el-button>
      <el-button round size="small" class="ghost-btn" @click="toggleMaximize">
        <el-icon class="el-icon--left"><FullScreen /></el-icon>{{ isMaximized ? '退出全屏' : '全屏' }}
      </el-button>
      <span class="wf-hint">拖拽节点入库 · 输出圆点拖到输入圆点连线 · 滚轮缩放 · Ctrl+Z 撤销 / Ctrl+Shift+Z 重做 · Delete 删除</span>
    </div>

    <div class="wf-body">
      <aside class="wf-palette">
        <div class="wf-palette-title">节点</div>
        <button
          v-for="entry in paletteEntries"
          :key="entry.type"
          class="wf-palette-item"
          draggable="true"
          :style="{ '--acc': entry.color }"
          @dragstart="onPaletteDragStart($event, entry.type)"
          @click="addNode(entry.type)"
        >
          <span class="wf-palette-dot"></span>
          <span class="wf-palette-copy">
            <b>{{ entry.label }}</b>
            <small>{{ entry.desc }}</small>
          </span>
        </button>
      </aside>

      <div ref="canvasEl" class="wf-canvas" @wheel.prevent="onWheel" @dragover.prevent @drop.prevent="onPaletteDrop">
        <div ref="worldEl" class="wf-world" :style="worldStyle">
          <div class="wf-bg" @pointerdown="onPanStart" />
          <svg class="wf-svg">
            <g v-for="p in edgePaths" :key="p.id">
              <path
                class="wf-edge-hit"
                :d="p.d"
                :class="{ active: p.id === selectedEdgeId }"
                @pointerdown.stop="selectedEdgeId = p.id; selectedNodeId = null; inspectorOpen = false"
              />
              <path class="wf-edge" :d="p.d" :class="{ active: p.id === selectedEdgeId }" />
              <template v-if="p.a && p.b">
                <circle class="wf-edge-dot" :cx="p.a.x" :cy="p.a.y" r="3.5" />
                <circle class="wf-edge-dot" :cx="p.b.x" :cy="p.b.y" r="3.5" />
              </template>
            </g>
            <path
              v-if="connecting && nodeById(connecting.fromNode) && portOffsets[portKey(connecting.fromNode, 'out', connecting.fromPort)]"
              class="wf-edge wf-edge--temp"
              :d="`M ${portPos(nodeById(connecting.fromNode)!, 'out', connecting.fromPort).x} ${portPos(nodeById(connecting.fromNode)!, 'out', connecting.fromPort).y} C ${connecting.x} ${connecting.y}, ${connecting.x} ${connecting.y}, ${connecting.x} ${connecting.y}`"
            />
          </svg>

          <div
            v-for="node in nodes"
            :key="node.id"
            class="wf-node"
            :class="{
              selected: node.id === selectedNodeId,
              'wf-node--running': stepStatus(node.id) === 'active',
              'wf-node--done': stepStatus(node.id) === 'done',
              'wf-node--failed': stepStatus(node.id) === 'failed',
            }"
            :data-node-el="node.id"
            :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${NODE_W}px`, '--acc': NODE_META[node.type].color }"
            @pointerdown.stop="selectedNodeId = node.id; selectedEdgeId = null; inspectorOpen = false"
          >
            <div class="wf-node-head" @pointerdown.stop="onNodeDragStart(node, $event)">
              <span class="wf-node-badge"></span>
              <span class="wf-node-title">{{ NODE_META[node.type].label }}</span>
              <span v-if="node.type === 'output'" class="wf-node-count">{{ saveInputCount(node) }}</span>
              <span v-if="stepStatus(node.id) === 'active'" class="wf-step-badge running">运行中</span>
              <span v-else-if="stepStatus(node.id) === 'done'" class="wf-step-badge done">✓</span>
              <span v-else-if="stepStatus(node.id) === 'failed'" class="wf-step-badge failed">失败</span>
              <div class="wf-node-actions">
                <button class="wf-ico" title="上移" @pointerdown.stop @click.stop="moveNode(node, -40)">
                  <el-icon><ArrowUp /></el-icon>
                </button>
                <button class="wf-ico" title="下移" @pointerdown.stop @click.stop="moveNode(node, 40)">
                  <el-icon><ArrowDown /></el-icon>
                </button>
                <button class="wf-ico" title="设置" @pointerdown.stop @click.stop="focusInspector(node)">
                  <el-icon><Setting /></el-icon>
                </button>
                <button class="wf-ico" title="删除节点" @pointerdown.stop @click.stop="removeNode(node.id)">
                  <el-icon><Close /></el-icon>
                </button>
              </div>
            </div>
            <div v-if="nodeSubtitle(node)" class="wf-node-subtitle" :title="nodeSubtitle(node)">{{ nodeSubtitle(node) }}</div>

            <div class="wf-node-body">
              <!-- 输入端口行 -->
              <div v-for="port in NODE_META[node.type].inputs" :key="'in-' + port" class="wf-row wf-row--in">
                <span
                  class="wf-dot wf-dot--in"
                  :data-node="node.id"
                  :data-port="port"
                  data-port-side="in"
                  :data-port-key="portKey(node.id, 'in', port)"
                ></span>
                <span class="wf-row-label">{{ translateUiText(portLabel(port)) }}</span>
                <span class="wf-row-status" :class="{ on: hasInEdge(node.id, port) }">
                  {{ hasInEdge(node.id, port) ? '已连接' : '待连接' }}
                </span>
              </div>

              <!-- 内联配置 -->
              <template v-if="node.type === 'input'">
                <div class="wf-file-box">
                  <div class="wf-file-name">{{ props.songName || '未选择歌曲' }}</div>
                  <button class="wf-file-btn" @click.stop="emit('pick-song')">选择歌曲</button>
                </div>
              </template>

              <template v-else-if="node.type === 'separate'">
                <div class="wf-engine-toggle">
                  <button :class="{ active: node.params.engine !== 'pymss' }" @click.stop="node.params.engine = 'uvr'; onSeparateEngineChange(node)">UVR</button>
                  <button :class="{ active: node.params.engine === 'pymss' }" @click.stop="node.params.engine = 'pymss'; onSeparateEngineChange(node)">PyMSS</button>
                </div>
                <div class="wf-stack">
                  <div class="wf-stack-label">模型</div>
                  <PymssModelPicker
                    v-if="node.params.engine === 'pymss'"
                    :model-value="node.params.model"
                    :models="props.pymssAllModels"
                    default-filter="vocal"
                    @update:model-value="onSeparateModelChange(node, $event)"
                    @download="emit('download-pymss', $event)"
                  />
                  <el-select v-else v-model="node.params.model" size="small" class="wf-full" filterable allow-create>
                    <el-option v-for="m in props.uvrModels" :key="m" :label="m" :value="m" />
                  </el-select>
                </div>
                <button v-if="node.params.engine === 'pymss' && findPymssModel(node.params.model)?.downloaded === false" class="wf-file-btn wf-model-download" @click.stop="emit('download-pymss', node.params.model)">下载该模型</button>
                <p class="wf-hint-line">输出音轨：{{ separateOutputHint(node) }}</p>
                <div class="wf-stack">
                  <div class="wf-stack-label">输入来源</div>
                  <div class="wf-source-box">{{ inputSourceLabel(node) }}</div>
                </div>
                <div class="wf-stack">
                  <div class="wf-stack-label">设备</div>
                  <el-select v-model="node.params.device" size="small" class="wf-full"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
                </div>
              </template>

              <template v-else-if="node.type === 'dereverb'">
                <label class="wf-field"><span>引擎</span>
                  <el-select v-model="node.params.engine" size="small" class="wf-mini" @change="onDereverbEngineChange(node)">
                    <el-option label="UVR" value="uvr" /><el-option label="PyMSS" value="pymss" />
                  </el-select>
                </label>
                <label class="wf-field"><span>模型</span>
                  <span v-if="node.params.engine === 'pymss'" class="wf-mini">
                    <PymssModelPicker
                      v-model="node.params.model"
                      :models="props.pymssAllModels"
                      default-filter="dereverb"
                      @download="emit('download-pymss', $event)"
                    />
                  </span>
                  <el-select v-else v-model="node.params.model" size="small" class="wf-mini" filterable allow-create>
                    <el-option label="UVR-DeEcho-DeReverb.pth" value="UVR-DeEcho-DeReverb.pth" />
                  </el-select>
                </label>
                <button v-if="node.params.engine === 'pymss' && findPymssModel(node.params.model)?.downloaded === false" class="wf-file-btn wf-model-download" @click.stop="emit('download-pymss', node.params.model)">下载该模型</button>
                <label class="wf-field"><span>设备</span>
                  <el-select v-model="node.params.device" size="small" class="wf-mini"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
                </label>
              </template>

              <template v-else-if="node.type === 'repair'">
                <label class="wf-field"><span>设备</span>
                  <el-select v-model="node.params.device" size="small" class="wf-mini"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
                </label>
              </template>

              <template v-else-if="node.type === 'convert'">
                <label class="wf-field"><span>模型</span>
                  <el-select v-model="node.params.model_id" size="small" class="wf-mini" filterable placeholder="选择模型">
                    <el-option v-for="m in props.models" :key="m.id" :label="m.name" :value="m.id" />
                  </el-select>
                </label>
                <div v-if="convertFramework(node)" class="wf-field wf-field--flat">
                  <span>框架</span>
                  <span class="wf-badge-pitch">{{ convertFramework(node) }}</span>
                </div>
                <div class="wf-slider">
                  <div class="wf-slider-head">
                    <span>变调（半音）</span>
                    <b>{{ num(node, 'pitch') > 0 ? '+' + num(node, 'pitch') : num(node, 'pitch') }}</b>
                  </div>
                  <el-slider v-model="node.params.pitch" :min="-12" :max="12" :step="1" :show-tooltip="false" />
                </div>
                <label v-if="convertFramework(node) !== 'seed-vc'" class="wf-field"><span>F0</span>
                  <el-select v-model="node.params.f0_method" size="small" class="wf-mini">
                    <el-option v-for="f in f0MethodsForFramework(convertFramework(node))" :key="f" :label="f" :value="f" />
                  </el-select>
                </label>
                <label class="wf-field"><span>设备</span>
                  <el-select v-model="node.params.device" size="small" class="wf-mini"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
                </label>
                <label v-if="convertFramework(node) === 'seed-vc'" class="wf-field"><span>参考音频</span>
                  <el-input v-model="node.params.reference_audio" size="small" placeholder="参考音频路径" />
                </label>

                <el-collapse class="wf-adv">
                  <el-collapse-item title="高级参数">
                    <!-- So-VITS-SVC：主 / 扩散比例 -->
                    <template v-if="convertFramework(node) === 'so-vits-svc'">
                      <div class="wf-slider">
                        <div class="wf-slider-head">
                          <span>主 / 扩散比例</span>
                          <b>{{ Math.round((1 - num(node, 'diffusion_ratio', 0.5)) * 100) }}% / {{ Math.round(num(node, 'diffusion_ratio', 0.5) * 100) }}%</b>
                        </div>
                        <el-slider v-model="node.params.diffusion_ratio" :min="0" :max="1" :step="0.05" :show-tooltip="false" />
                      </div>
                    </template>
                    <!-- RVC 专属 -->
                    <template v-else-if="convertFramework(node) === 'rvc'">
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>检索比率</span><b>{{ num(node, 'index_rate').toFixed(2) }}</b></div>
                        <el-slider v-model="node.params.index_rate" :min="0" :max="1" :step="0.05" :show-tooltip="false" />
                      </div>
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>音量包络</span><b>{{ num(node, 'rms_mix').toFixed(2) }}</b></div>
                        <el-slider v-model="node.params.rms_mix" :min="0" :max="1" :step="0.05" :show-tooltip="false" />
                      </div>
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>清辅音保护</span><b>{{ num(node, 'protect').toFixed(2) }}</b></div>
                        <el-slider v-model="node.params.protect" :min="0" :max="0.5" :step="0.01" :show-tooltip="false" />
                      </div>
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>中值滤波半径</span><b>{{ num(node, 'filter_radius') }}</b></div>
                        <el-slider v-model="node.params.filter_radius" :min="0" :max="7" :step="1" :show-tooltip="false" />
                      </div>
                      <label class="wf-field"><span>RVC 版本</span>
                        <span class="wf-auto-badge">{{ rvcVersionLabel(node) }}</span>
                      </label>
                      <p v-if="!detectedRvcVersion(node)" class="wf-hint-line">未检测到模型版本，将由软件自动推断</p>
                    </template>
                    <!-- SeedVC 专属 -->
                    <template v-else-if="convertFramework(node) === 'seed-vc'">
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>推理质量（扩散）</span><b>{{ num(node, 'diffusion_ratio', 0.5).toFixed(2) }}</b></div>
                        <el-slider v-model="node.params.diffusion_ratio" :min="0" :max="1" :step="0.05" :show-tooltip="false" />
                      </div>
                    </template>
                    <!-- DDSP-SVC 专属 -->
                    <template v-else-if="convertFramework(node) === 'ddsp-svc'">
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>采样步数</span><b>{{ num(node, 'ddsp_infer_steps', 50) }}</b></div>
                        <el-slider v-model="node.params.ddsp_infer_steps" :min="1" :max="200" :step="1" :show-tooltip="false" />
                      </div>
                      <div class="wf-slider">
                        <div class="wf-slider-head"><span>共振峰偏移</span><b>{{ num(node, 'ddsp_formant_shift') }}</b></div>
                        <el-slider v-model="node.params.ddsp_formant_shift" :min="-2" :max="2" :step="0.05" :show-tooltip="false" />
                      </div>
                    </template>
                    <p v-else class="wf-note">选择模型后显示对应框架的高级参数。</p>
                    <!-- 通用：高音保护 -->
                    <label class="wf-check"><el-checkbox v-model="node.params.auto_high_pitch_guard" />高音保护</label>
                    <div v-if="node.params.auto_high_pitch_guard" class="wf-slider">
                      <div class="wf-slider-head"><span>高音保护轮次</span><b>{{ highPitchGuardRoundsText(num(node, 'high_pitch_guard_rounds', 3)) }}</b></div>
                      <el-slider v-model="node.params.high_pitch_guard_rounds" :min="0" :max="8" :step="1" :show-tooltip="false" />
                      <p class="wf-hint-line">{{ num(node, 'high_pitch_guard_rounds', 3) === 0 ? '轮次为 0 时由系统自动接管，行为与普通模式一致' : '每轮失败后会根据实际哑音位置自动降低内部保护起点' }}</p>
                    </div>
                    <div class="wf-slider">
                      <div class="wf-slider-head"><span>F0 过滤阈值</span><b>{{ num(node, 'f0_filter_threshold', 0.05).toFixed(2) }}</b></div>
                      <el-slider v-model="node.params.f0_filter_threshold" :min="0" :max="1" :step="0.01" :show-tooltip="false" />
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </template>

              <template v-else-if="node.type === 'enhance'">
                <label class="wf-field"><span>层级</span>
                  <el-select v-model="node.params.level" size="small" class="wf-mini">
                    <el-option label="基础层" value="basic" /><el-option label="高级层" value="advanced" />
                  </el-select>
                </label>
                <label class="wf-field"><span>设备</span>
                  <el-select v-model="node.params.device" size="small" class="wf-mini"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
                </label>
                <el-collapse class="wf-adv">
                  <el-collapse-item title="增强参数">
                    <label class="wf-field" v-for="c in ENHANCE_CONTROLS" :key="c.key">
                      <span>{{ c.label }}</span>
                      <el-slider v-model="node.params[c.key]" :min="0" :max="1" :step="0.05" :show-tooltip="false" />
                    </label>
                  </el-collapse-item>
                </el-collapse>
              </template>

              <template v-else-if="node.type === 'mix'">
                <label class="wf-field wf-field--flat"><span>AI 动态混音</span>
                  <el-checkbox v-model="node.params.enhanced" size="small" />
                </label>
              </template>

              <template v-else-if="node.type === 'output'">
                <div class="wf-save">
                  <div class="wf-save-head">
                    <span>已选输出</span>
                    <span class="wf-save-count">{{ saveInputCount(node) }}</span>
                  </div>
                  <button class="wf-save-drop" @click.stop="autoConnectSave(node)">将音轨拖到此处保存</button>
                  <div v-for="(edge, i) in incomingEdges(node)" :key="edge.id" class="wf-save-item">
                    <div class="wf-save-row">
                      <span class="wf-save-tag" :class="{ primary: i === 0 }">{{ i === 0 ? '主输出' : '音轨 ' + (i + 1) }}</span>
                      <span class="wf-save-src">{{ edgeUpstreamLabel(edge) }}</span>
                      <button class="wf-save-del" title="删除该音频（断开与保存节点的连线）" @pointerdown.stop @click.stop="removeEdgeById(edge.id)">
                        <el-icon><Close /></el-icon>
                      </button>
                    </div>
                    <div class="wf-save-preview-label">文件名称预览</div>
                    <div class="wf-save-preview">{{ trackPreviewFor(edge) }}</div>
                  </div>
                  <div class="wf-save-preview-label">文件名模板</div>
                  <el-input v-model="node.params.file_template" size="small" placeholder="%filename%_%stem%_%model%" />
                  <button class="wf-save-run" @click.stop="emit('run')">
                    <el-icon><MagicStick /></el-icon>生成并自动保存
                  </button>
                </div>
              </template>

              <!-- 输出端口行 -->
              <div v-for="port in nodeOutputs(node)" :key="'out-' + port" class="wf-row wf-row--out">
                <span class="wf-row-label">
                  {{ translateUiText(portLabel(port)) }}
                  <span v-if="isPrimaryPort(node, port)" class="wf-port-flag">主</span>
                </span>
                <button
                  class="wf-save-link"
                  :class="{ on: connectsToSave(node.id, port) }"
                  :title="connectsToSave(node.id, port) ? '点击断开与保存节点的连线' : '快捷连接到保存节点'"
                  @pointerdown.stop
                  @click.stop="toggleSaveLink(node, port)"
                >{{ connectsToSave(node.id, port) ? '已连接保存' : '保存音轨' }}</button>
                <span
                  class="wf-dot wf-dot--out"
                  :data-node="node.id"
                  :data-port="port"
                  data-port-side="out"
                  :data-port-key="portKey(node.id, 'out', port)"
                  @pointerdown.stop="onOutputPortDown(node, port, $event)"
                ></span>
              </div>
            </div>
          </div>
        </div>

        <div class="wf-zoom">
          <button class="wf-zoom-btn" @click="setZoom(zoom + 0.15)">+</button>
          <span>{{ Math.round(zoom * 100) }}%</span>
          <button class="wf-zoom-btn" @click="setZoom(zoom - 0.15)">−</button>
          <button class="wf-zoom-btn" title="适应画布" @click="fitView()">⤢</button>
        </div>

        <div v-if="runLabel" class="wf-run-chip" :class="runStatus">
          <span class="wf-run-dot"></span>
          <span>{{ runLabel }}</span>
          <span class="wf-run-bar"><i :style="{ width: `${Math.max(0, Math.min(100, runProgress))}%` }"></i></span>
        </div>

        <aside v-if="inspectorOpen && selectedNode" class="wf-inspector">
          <template v-if="selectedNode">
            <div class="wf-inspector-title">
              <span class="wf-inspector-badge" :style="{ background: NODE_META[selectedNode.type].color }"></span>
              {{ NODE_META[selectedNode.type].label }}
              <span class="wf-inspector-hint">设置</span>
              <button class="wf-x" title="关闭设置" @click="inspectorOpen = false"><el-icon><Close /></el-icon></button>
            </div>

            <template v-if="selectedNode.type === 'separate'">
              <div class="wf-stack">
                <div class="wf-stack-label">引擎</div>
                <div class="wf-engine-toggle wf-engine-toggle--wide">
                  <button
                    :class="{ active: selectedNode.params.engine !== 'pymss' }"
                    @click="selectedNode.params.engine = 'uvr'; onSeparateEngineChange(selectedNode)"
                  >UVR</button>
                  <button
                    :class="{ active: selectedNode.params.engine === 'pymss' }"
                    @click="selectedNode.params.engine = 'pymss'; onSeparateEngineChange(selectedNode)"
                  >PyMSS</button>
                </div>
              </div>
              <div class="wf-stack">
                <div class="wf-stack-label">模型</div>
                <PymssModelPicker
                  v-if="selectedNode.params.engine === 'pymss'"
                  :model-value="selectedNode.params.model"
                  :models="props.pymssAllModels"
                  default-filter="vocal"
                  @update:model-value="onSeparateModelChange(selectedNode, $event)"
                  @download="emit('download-pymss', $event)"
                />
                <el-select v-else v-model="selectedNode.params.model" size="small" class="wf-full" filterable allow-create>
                  <el-option v-for="m in props.uvrModels" :key="m" :label="m" :value="m" />
                </el-select>
                <button
                  v-if="selectedNode.params.engine === 'pymss' && findPymssModel(selectedNode.params.model)?.downloaded === false"
                  class="wf-file-btn wf-model-download"
                  @click="emit('download-pymss', selectedNode.params.model)"
                >下载该模型</button>
              </div>
              <div class="wf-stack">
                <div class="wf-stack-label">输入来源</div>
                <div class="wf-source-box">{{ inputSourceLabel(selectedNode) }}</div>
              </div>
              <div class="wf-stack">
                <div class="wf-stack-label">
                  输出音轨
                  <span class="wf-stack-hint">{{ separateOutputHint(selectedNode) }}</span>
                </div>
                <div v-if="declaredStems(selectedNode).length" class="wf-stack-sub">
                  该模型声明 {{ declaredStems(selectedNode).length }} 路音轨（读取模型配置）
                </div>
                <div v-else-if="separateStemsUnknown(selectedNode)" class="wf-stack-sub">
                  未读取到模型配置（可能尚未下载），暂按用途推断输出音轨
                </div>
                <div v-if="declaredStems(selectedNode).length > 1" class="wf-stack">
                  <div class="wf-stack-sublabel">主音轨</div>
                  <el-select
                    :model-value="primaryStemOf(selectedNode)"
                    size="small"
                    class="wf-full"
                    @update:model-value="setPrimaryStem(selectedNode, $event)"
                  >
                    <el-option v-for="stem in declaredStems(selectedNode)" :key="stem" :label="stem" :value="stem" />
                  </el-select>
                </div>
                <div class="wf-port-chips">
                  <button
                    v-for="port in separateOutputChoices(selectedNode)"
                    :key="port"
                    class="wf-port-chip"
                    :class="{ on: isSeparateOutputOn(selectedNode, port) }"
                    @click="toggleSeparateOutput(selectedNode, port)"
                  >
                    {{ translateUiText(portLabel(port)) }}
                    <i v-if="isPrimaryPort(selectedNode, port)">主</i>
                  </button>
                </div>
                <p class="wf-hint-line">
                  端口按所选 PyMSS 模型声明的音轨生成（每个模型输出的音轨不同）；取消勾选会同步移除失效连线。
                </p>
                <button
                  v-if="Array.isArray(selectedNode.params.outputs)"
                  class="wf-link-btn"
                  @click="resetSeparateOutputs(selectedNode)"
                >恢复按模型自动适配</button>
              </div>
              <div class="wf-stack">
                <div class="wf-stack-label">设备</div>
                <el-select v-model="selectedNode.params.device" size="small" class="wf-full"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
              </div>
            </template>

            <template v-else-if="selectedNode.type === 'dereverb'">
              <div class="wf-stack">
                <div class="wf-stack-label">引擎</div>
                <div class="wf-engine-toggle wf-engine-toggle--wide">
                  <button
                    :class="{ active: selectedNode.params.engine !== 'pymss' }"
                    @click="selectedNode.params.engine = 'uvr'; onDereverbEngineChange(selectedNode)"
                  >UVR</button>
                  <button
                    :class="{ active: selectedNode.params.engine === 'pymss' }"
                    @click="selectedNode.params.engine = 'pymss'; onDereverbEngineChange(selectedNode)"
                  >PyMSS</button>
                </div>
              </div>
              <div class="wf-stack">
                <div class="wf-stack-label">模型</div>
                <PymssModelPicker
                  v-if="selectedNode.params.engine === 'pymss'"
                  v-model="selectedNode.params.model"
                  :models="props.pymssAllModels"
                  default-filter="dereverb"
                  @download="emit('download-pymss', $event)"
                />
                <el-select v-else v-model="selectedNode.params.model" size="small" class="wf-full" filterable allow-create>
                  <el-option label="UVR-DeEcho-DeReverb.pth" value="UVR-DeEcho-DeReverb.pth" />
                </el-select>
                <button
                  v-if="selectedNode.params.engine === 'pymss' && findPymssModel(selectedNode.params.model)?.downloaded === false"
                  class="wf-file-btn wf-model-download"
                  @click="emit('download-pymss', selectedNode.params.model)"
                >下载该模型</button>
              </div>
              <div class="wf-stack">
                <div class="wf-stack-label">设备</div>
                <el-select v-model="selectedNode.params.device" size="small" class="wf-full"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
              </div>
              <p class="wf-note">去混响节点固定输出一路「音频」（净化后的干声）。</p>
            </template>

            <template v-else-if="selectedNode.type === 'repair'">
              <label class="wf-field"><span>设备</span>
                <el-select v-model="selectedNode.params.device" size="small"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
              </label>
              <p class="wf-note">使用 DeepFilterNet3 修复分离 / 转换伪影，失败时自动沿用输入。</p>
            </template>

            <template v-else-if="selectedNode.type === 'convert'">
              <p class="wf-note">模型与推理参数在节点内调整：会按模型框架只显示对应的参数（So-VITS / RVC / SeedVC / DDSP）。</p>
            </template>

            <template v-else-if="selectedNode.type === 'blend'">
              <p class="wf-note">将多路转换人声叠加为合唱。多个上游节点可同时连接到本节点的「音频」输入圆点。</p>
            </template>

            <template v-else-if="selectedNode.type === 'enhance'">
              <label class="wf-field"><span>设备</span>
                <el-select v-model="selectedNode.params.device" size="small"><el-option v-for="d in DEVICE_OPTIONS" :key="d.value" :label="d.label" :value="d.value" /></el-select>
              </label>
              <label class="wf-field" v-for="c in ENHANCE_CONTROLS" :key="c.key">
                <span>{{ c.label }}</span>
                <el-slider v-model="selectedNode.params[c.key]" :min="0" :max="1" :step="0.05" :show-tooltip="false" />
              </label>
            </template>

            <template v-else-if="selectedNode.type === 'mix'">
              <p class="wf-note">人声与伴奏重新混音；无伴奏时仅输出人声。</p>
            </template>

            <template v-else-if="selectedNode.type === 'input'">
              <p class="wf-note">使用工作台已上传的歌曲作为源音频。</p>
            </template>

            <template v-else-if="selectedNode.type === 'output'">
              <p class="wf-note">最终翻唱成品输出。</p>
            </template>
          </template>
        </aside>

        <!-- 选中连线时只显示轻量删除条，不弹设置面板 -->
        <div v-if="selectedEdge" class="wf-edge-chip">
          <span class="wf-edge-chip-text">{{ translateUiText(portLabel(selectedEdge.from.port)) }} → {{ translateUiText(portLabel(selectedEdge.to.port)) }}</span>
          <button class="wf-file-btn" @click="deleteSelectedEdge">
            <el-icon><Delete /></el-icon>删除连线
          </button>
        </div>

        <div v-if="!selectedNode && !selectedEdge" class="wf-tip">
          <el-icon><MagicStick /></el-icon>
          点击节点右上角 ⚙ 打开设置 · 点击连线可删除
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wf {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid var(--xb-border);
  border-radius: 12px;
  background: var(--xb-panel);
  overflow: hidden;
}
/* 最大化：铺满导航栏以下的整个内容区，避免顶部工具栏被固定导航栏遮挡。
   .layout-main 自带 position:relative;z-index:1 的层叠上下文，
   内部的 fixed 覆盖层无法盖过 z-index:50 的 sticky 导航栏，因此改用 top:64px 让开。 */
.wf.wf--max {
  position: fixed;
  top: 64px;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  border-radius: 0;
  border: none;
  background: rgb(var(--xb-bg-rgb, 15 17 21));
}
.wf.wf--max .wf-body { flex: 1; height: auto; min-height: 0; }
.wf-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-bottom: 1px solid var(--xb-border);
  background: color-mix(in srgb, var(--xb-panel) 92%, var(--xb-primary) 2%);
}
.wf-name { width: 190px; }
.wf-load { width: 200px; }
.wf-hint { margin-left: auto; color: var(--xb-muted); font-size: 12px; }

.wf-body { display: flex; height: calc(100vh - 250px); min-height: 640px; }

/* 左侧节点面板 */
.wf-palette {
  width: 158px;
  border-right: 1px solid var(--xb-border);
  padding: 10px 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex-shrink: 0;
}
.wf-palette-title { font-size: 12px; color: var(--xb-muted); font-weight: 700; margin: 2px 4px 4px; }
.wf-palette-item {
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--xb-text);
  cursor: grab;
}
.wf-palette-item:hover { border-color: var(--acc); background: color-mix(in srgb, var(--acc) 10%, transparent); }
.wf-palette-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--acc); flex-shrink: 0; }
.wf-palette-copy { display: flex; flex-direction: column; min-width: 0; }
.wf-palette-copy b { font-size: 12.5px; }
.wf-palette-copy small { font-size: 10.5px; color: var(--xb-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 画布 */
.wf-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
  cursor: grab;
  background-color: color-mix(in srgb, var(--xb-panel) 90%, #000);
  background-image:
    linear-gradient(color-mix(in srgb, var(--xb-border) 45%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--xb-border) 45%, transparent) 1px, transparent 1px);
  background-size: 26px 26px;
}
.wf-canvas:active { cursor: grabbing; }
.wf-world { position: absolute; left: 0; top: 0; }
.wf-bg { position: absolute; left: -6000px; top: -6000px; width: 12000px; height: 12000px; }
.wf-svg { position: absolute; left: 0; top: 0; width: 1px; height: 1px; overflow: visible; pointer-events: none; }
.wf-edge { fill: none; stroke: color-mix(in srgb, var(--xb-muted) 65%, var(--xb-border)); stroke-width: 2; }
.wf-edge-hit { fill: none; stroke: transparent; stroke-width: 16; pointer-events: stroke; cursor: pointer; }
.wf-edge.active, .wf-edge-hit.active { stroke: var(--xb-primary); }
.wf-edge--temp { stroke: var(--xb-primary); stroke-dasharray: 6 4; stroke-width: 2; }
.wf-edge-dot { fill: var(--xb-primary); opacity: 0.85; }

/* 节点卡片 */
.wf-node {
  position: absolute;
  border: 1px solid var(--xb-border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--xb-panel) 92%, #000);
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.32);
  transition: box-shadow 0.15s, border-color 0.15s;
}
.wf-node.selected { border-color: var(--acc); box-shadow: 0 0 0 1.5px var(--acc), 0 10px 26px rgba(0, 0, 0, 0.4); }
.wf-node--running { border-color: var(--xb-primary) !important; animation: wf-pulse 1.2s ease-in-out infinite; }
.wf-node--done { border-color: #35d07f; }
.wf-node--failed { border-color: #f43f5e; }
@keyframes wf-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--xb-primary) 55%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--xb-primary) 22%, transparent); }
}
.wf-step-badge {
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: 5px;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}
.wf-step-badge.running { background: color-mix(in srgb, var(--xb-primary) 30%, transparent); color: var(--xb-text); }
.wf-step-badge.done { background: rgba(53, 208, 127, 0.22); color: #35d07f; }
.wf-step-badge.failed { background: rgba(244, 63, 94, 0.22); color: #f43f5e; }

.wf-run-chip {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: color-mix(in srgb, var(--xb-panel) 94%, #000);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  font-size: 12px;
  color: var(--xb-text);
  z-index: 15;
  max-width: 72%;
}
.wf-run-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--xb-muted); flex-shrink: 0; }
.wf-run-chip.running .wf-run-dot, .wf-run-chip.queue .wf-run-dot { background: var(--xb-primary); animation: wf-blink 1s infinite; }
.wf-run-chip.done .wf-run-dot { background: #35d07f; }
.wf-run-chip.failed .wf-run-dot { background: #f43f5e; }
.wf-run-bar { width: 90px; height: 4px; border-radius: 2px; background: color-mix(in srgb, var(--xb-border) 80%, transparent); overflow: hidden; }
.wf-run-bar i { display: block; height: 100%; background: var(--xb-primary); transition: width 0.4s ease; }
@keyframes wf-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.wf-node-head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 42px;
  padding: 0 10px 0 12px;
  border-radius: 9px 9px 0 0;
  background: color-mix(in srgb, var(--acc) 16%, var(--xb-panel));
  border-bottom: 1px solid color-mix(in srgb, var(--acc) 26%, var(--xb-border));
  cursor: move;
}
.wf-node-badge { width: 10px; height: 10px; border-radius: 3px; background: var(--acc); flex-shrink: 0; }
.wf-node-title { font-size: 13px; font-weight: 700; color: var(--xb-text); }
.wf-node-count {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: color-mix(in srgb, var(--acc) 65%, #000);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.wf-node-actions { margin-left: auto; display: flex; gap: 2px; }
.wf-node-subtitle {
  padding: 7px 12px 8px;
  font-size: 15px;
  font-weight: 800;
  color: var(--xb-text);
  border-bottom: 1px solid color-mix(in srgb, var(--xb-border) 65%, transparent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wf-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 13px;
}
.wf-ico:hover { background: color-mix(in srgb, var(--acc) 22%, transparent); color: var(--xb-text); }
.wf-node-body { padding: 10px 12px 12px; }

/* 端口行 */
.wf-row { position: relative; display: flex; align-items: center; gap: 8px; height: 26px; font-size: 12px; color: var(--xb-text); }
.wf-row--in { padding-left: 10px; }
.wf-row--out { padding-right: 10px; }
.wf-row-label { font-weight: 600; }
.wf-row-status { font-size: 11px; color: var(--xb-muted); }
.wf-row--out .wf-row-status { margin-left: auto; }
.wf-row--in .wf-row-status { margin-left: auto; }
.wf-row-status.on { color: var(--acc); }
.wf-save-link {
  margin-left: auto;
  border: 1px dashed color-mix(in srgb, var(--xb-border) 95%, transparent);
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 10.5px;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
}
.wf-save-link:hover { border-color: var(--acc); color: var(--xb-text); }
.wf-save-link.on {
  border-style: solid;
  border-color: color-mix(in srgb, var(--xb-primary) 60%, var(--xb-border));
  background: color-mix(in srgb, var(--xb-primary) 16%, transparent);
  color: var(--xb-primary);
}
.wf-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--acc);
  border: 2px solid var(--xb-panel);
  box-shadow: 0 0 0 1px var(--acc);
  flex-shrink: 0;
  cursor: crosshair;
}
.wf-dot--in { position: absolute; left: -6px; top: 50%; transform: translateY(-50%); }
.wf-dot--out { position: absolute; right: -6px; top: 50%; transform: translateY(-50%); }
.wf-row--out .wf-dot { cursor: crosshair; }

/* 内联字段 */
.wf-field { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; font-size: 12px; color: var(--xb-muted); }
.wf-field > span { flex-shrink: 0; }
.wf-field--flat { color: var(--xb-text); }
.wf-mini { width: 150px; }
.wf-stack { margin-top: 8px; }
.wf-stack-label { font-size: 11px; color: var(--xb-muted); margin-bottom: 4px; }
.wf-full { width: 100%; }
.wf-source-box {
  width: 100%;
  padding: 5px 10px;
  border: 1px solid var(--xb-border);
  border-radius: 6px;
  background: color-mix(in srgb, var(--xb-panel) 85%, transparent);
  color: var(--xb-text);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wf-num { width: 120px; }
.wf-badge-pitch { font-size: 11px; color: var(--xb-muted); }
.wf-auto-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--xb-text);
  padding: 1px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--acc) 14%, transparent);
}
.wf-source { color: var(--xb-text); font-size: 11.5px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-slider { margin-top: 8px; }
.wf-slider-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--xb-muted);
}
.wf-slider-head b {
  padding: 1px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--acc) 15%, transparent);
  color: var(--xb-text);
  font-weight: 700;
  font-size: 11px;
}
.wf-hint-line { margin: 4px 0 0; font-size: 10.5px; color: var(--xb-muted); line-height: 1.45; }
.wf-engine-toggle {
  display: inline-flex;
  margin: 8px 0 4px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  overflow: hidden;
}
.wf-engine-toggle button {
  border: none;
  background: transparent;
  color: var(--xb-muted);
  font-size: 11px;
  padding: 4px 12px;
  cursor: pointer;
}
.wf-engine-toggle button.active {
  background: color-mix(in srgb, var(--acc) 24%, transparent);
  color: var(--xb-text);
  font-weight: 700;
}
/* 设置面板里的引擎切换：铺满整行，两个按钮各占一半 */
.wf-engine-toggle--wide {
  display: flex;
  width: 100%;
  margin: 0;
}
.wf-engine-toggle--wide button {
  flex: 1;
  padding: 6px 12px;
  font-size: 12px;
}
.wf-stack-hint {
  margin-left: 6px;
  color: var(--xb-primary);
  font-weight: 600;
}
.wf-stack-sub {
  margin: 2px 0 6px;
  font-size: 10.5px;
  color: var(--xb-muted);
}
.wf-stack-sublabel {
  font-size: 11px;
  color: var(--xb-muted);
  margin: 6px 0 4px;
}
.wf-port-flag {
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--xb-primary) 22%, transparent);
  color: var(--xb-primary);
  font-size: 9px;
  font-weight: 700;
  vertical-align: middle;
}
.wf-port-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.wf-port-chip {
  padding: 3px 10px;
  border: 1px solid var(--xb-border);
  border-radius: 999px;
  background: transparent;
  color: var(--xb-muted);
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.16s ease;
}
.wf-port-chip:hover {
  border-color: var(--xb-primary);
  color: var(--xb-text);
}
.wf-port-chip.on {
  border-color: var(--xb-primary);
  background: color-mix(in srgb, var(--xb-primary) 18%, transparent);
  color: var(--xb-text);
  font-weight: 600;
}
.wf-port-chip.on::before {
  content: '✓ ';
  font-size: 10px;
}
.wf-port-chip i {
  margin-left: 4px;
  font-style: normal;
  font-size: 9px;
  opacity: 0.8;
}
.wf-link-btn {
  margin-top: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--xb-primary);
  font-size: 11px;
  text-decoration: underline;
  cursor: pointer;
}
.wf-file-box {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px dashed color-mix(in srgb, var(--acc) 50%, var(--xb-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--acc) 7%, transparent);
}
.wf-file-name { flex: 1; min-width: 0; font-size: 12px; color: var(--xb-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-file-btn {
  flex-shrink: 0;
  border: 1px solid var(--acc);
  border-radius: 6px;
  background: transparent;
  color: var(--xb-text);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
}
.wf-file-btn:hover { background: color-mix(in srgb, var(--acc) 18%, transparent); }
.wf-model-download { display: block; width: 100%; margin-top: 6px; }

/* 保存节点 */
.wf-save { margin-top: 8px; }
.wf-save-head { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 700; color: var(--xb-text); margin-bottom: 6px; }
.wf-save-drop {
  width: 100%;
  padding: 9px;
  margin-bottom: 8px;
  border: 1px dashed color-mix(in srgb, var(--acc) 65%, var(--xb-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--acc) 6%, transparent);
  color: var(--xb-text);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.wf-save-drop:hover { background: color-mix(in srgb, var(--acc) 14%, transparent); }
.wf-save-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--acc);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}
.wf-save-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 8px 10px;
  border: 1px dashed color-mix(in srgb, var(--acc) 55%, var(--xb-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--acc) 6%, transparent);
  font-size: 11px;
  color: var(--xb-muted);
}
.wf-save-item {
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--acc) 30%, var(--xb-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--acc) 5%, transparent);
}
.wf-save-row { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.wf-save-tag {
  padding: 1px 6px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--acc) 22%, transparent);
  color: var(--xb-text);
  font-size: 10.5px;
}
.wf-save-tag.primary { background: var(--acc); color: #fff; font-weight: 700; }
.wf-save-src { color: var(--xb-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-save-del {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--xb-muted);
  cursor: pointer;
  font-size: 12px;
}
.wf-save-del:hover { background: rgba(244, 63, 94, 0.18); color: #f43f5e; }
.wf-save-preview-label { margin-top: 7px; font-size: 10.5px; color: var(--xb-muted); }
.wf-save-preview {
  margin-top: 2px;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
  font-size: 11.5px;
  color: var(--xb-text);
  word-break: break-all;
}
.wf-save-auto { margin-top: 8px; width: 100%; }
.wf-save-run {
  margin-top: 10px;
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px 10px;
  border: 1px solid var(--acc);
  border-radius: 8px;
  background: color-mix(in srgb, var(--acc) 16%, transparent);
  color: var(--xb-text);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.wf-save-run:hover { background: color-mix(in srgb, var(--acc) 28%, transparent); }

/* 缩放控件 */
.wf-zoom {
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--xb-panel) 92%, #000);
  color: var(--xb-muted);
  font-size: 12px;
}
.wf-zoom-btn { border: none; background: transparent; color: var(--xb-text); cursor: pointer; font-size: 14px; line-height: 1; }

/* 浮动检查器 */
.wf-inspector {
  position: absolute;
  right: 12px;
  top: 12px;
  width: 320px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
  padding: 14px;
  border: 1px solid var(--xb-border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--xb-panel) 96%, #000);
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.45);
  z-index: 20;
}
.wf-inspector-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 700; margin-bottom: 12px; }
.wf-inspector-badge { width: 10px; height: 10px; border-radius: 3px; }
.wf-inspector-hint { margin-left: auto; font-size: 11px; font-weight: 500; color: var(--xb-muted); }
.wf-x { border: none; background: transparent; color: var(--xb-muted); cursor: pointer; }
.wf-x:hover { color: #f43f5e; }
.wf-check { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px; }
.wf-note { font-size: 12px; color: var(--xb-muted); line-height: 1.6; margin: 8px 0 0; }
/* ---- 节点内控件美化 ---- */
.wf-adv { margin-top: 10px; border: none; }
.wf-adv :deep(.el-collapse) { border: none; background: transparent; }
.wf-adv :deep(.el-collapse-item__header) {
  height: 34px;
  padding: 0 12px;
  border: 1px solid color-mix(in srgb, var(--acc) 32%, var(--xb-border));
  border-radius: 9px;
  background: color-mix(in srgb, var(--acc) 8%, var(--xb-panel));
  font-size: 12px;
  font-weight: 700;
  color: var(--xb-text);
  transition: background 0.15s, border-color 0.15s;
}
.wf-adv :deep(.el-collapse-item__header:hover) {
  border-color: color-mix(in srgb, var(--acc) 55%, var(--xb-border));
  background: color-mix(in srgb, var(--acc) 14%, var(--xb-panel));
}
.wf-adv :deep(.el-collapse-item__arrow) { color: var(--xb-muted); }
.wf-adv :deep(.el-collapse-item__wrap) {
  border: 1px solid color-mix(in srgb, var(--acc) 24%, var(--xb-border));
  border-top: none;
  border-radius: 0 0 9px 9px;
  background: color-mix(in srgb, var(--xb-panel) 78%, transparent);
  overflow: hidden;
}
.wf-adv :deep(.el-collapse-item__content) { padding: 12px; }

.wf-node :deep(.el-select__wrapper),
.wf-node :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: color-mix(in srgb, var(--xb-panel) 80%, transparent);
  box-shadow: 0 0 0 1px var(--xb-border) inset;
}
.wf-node :deep(.el-select__wrapper:hover),
.wf-node :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--acc) 45%, var(--xb-border)) inset;
}
.wf-node :deep(.el-select__wrapper.is-focused),
.wf-node :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--acc) inset;
}

.wf-node :deep(.el-slider) { --el-slider-runway-height: 6px; }
.wf-node :deep(.el-slider__runway) {
  background: color-mix(in srgb, var(--xb-border) 55%, transparent);
  border-radius: 999px;
}
.wf-node :deep(.el-slider__bar) {
  background: linear-gradient(90deg, color-mix(in srgb, var(--acc) 55%, #fff), var(--acc));
  border-radius: 999px;
}
.wf-node :deep(.el-slider__button) {
  border: 2px solid var(--acc);
  background: var(--xb-panel);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
}
.wf-node :deep(.el-checkbox__inner) { border-radius: 5px; }
.wf-node :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--acc);
  border-color: var(--acc);
}
.wf-node :deep(.el-checkbox__input.is-checked + .el-checkbox__label) { color: var(--xb-text); }

.wf-tip {
  position: absolute;
  left: 12px;
  top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--xb-panel) 88%, #000);
  border: 1px solid var(--xb-border);
  color: var(--xb-muted);
  font-size: 12px;
}
.wf-edge-chip {
  position: absolute;
  left: 12px;
  top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: color-mix(in srgb, var(--xb-panel) 94%, #000);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  font-size: 12px;
  color: var(--xb-text);
  z-index: 16;
}
.wf-edge-chip-text { color: var(--xb-muted); }
</style>
