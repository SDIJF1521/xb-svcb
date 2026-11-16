import type { WorkflowEdge, WorkflowGraph } from '@/api'

interface NamedModel {
  id: string
  name: string
}

type GraphNode = WorkflowGraph['nodes'][number]

const DEFAULT_TEMPLATE = '%filename%_%stem%_%model%'

const TYPE_LABELS: Record<string, string> = {
  input: 'input',
  separate: '人声分离',
  dereverb: '去混响',
  repair: '人声修复',
  convert: '歌声转换',
  blend: '合唱叠加',
  enhance: '歌声增强',
  mix: '混音合成',
  output: '保存',
}

const PORT_LABELS: Record<string, string> = {
  audio: '音频',
  vocals: '人声',
  instrumental: '伴奏',
  other: '其他音轨',
}

/** 端口可读名；动态 stem 端口回落为音轨名。 */
export function portLabelText(port: string): string {
  const key = String(port || '')
  if (PORT_LABELS[key]) return PORT_LABELS[key]
  if (key.startsWith('stem:')) return key.slice(5)
  return key
}

/** 文件名模板可用的占位符上下文。 */
export interface TemplateContext {
  filename: string
  stem: string
  model: string
  song: string
  workflow: string
  date: string
}

/** 去除文件名非法字符。 */
function sanitizeName(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, ' ').trim()
}

function baseName(value: string): string {
  return (value || '').split(/[/\\]/).pop() || ''
}

function nodeById(graph: WorkflowGraph, id: string): GraphNode | undefined {
  return (graph.nodes || []).find((n) => n.id === id)
}

/** 找到工作流中的「保存」节点：优先返回已接入音轨的那个。 */
export function saveNodeOf(graph: WorkflowGraph) {
  const outputs = (graph.nodes || []).filter((n) => n.type === 'output')
  const edges = graph.edges || []
  const connected = outputs.find((n) => edges.some((e) => e.to.node === n.id))
  return connected || outputs[0] || null
}

/** 某条连线所代表音轨的模板上下文。 */
export function edgeContext(
  graph: WorkflowGraph,
  edge: WorkflowEdge | undefined,
  songName: string,
  models: NamedModel[] = [],
): TemplateContext {
  const song = baseName(songName).replace(/\.[^.]+$/, '') || '歌曲'
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const from = edge ? nodeById(graph, edge.from.node) : undefined
  const filename = from ? TYPE_LABELS[from.type] || from.type : 'input'
  const stem = edge ? portLabelText(edge.from.port) : '音频'
  let model = '音频'
  if (from?.type === 'convert' || from?.type === 'separate') {
    const modelId = String((from.params as { model_id?: string })?.model_id || '')
    const matched = models.find((m) => m.id === modelId)
    if (matched?.name) model = matched.name
    else if (from.type === 'separate' && (from.params as { model?: string })?.model) {
      model = String((from.params as { model?: string }).model)
    }
  }
  return { filename, stem, model, song, workflow: graph.name || '工作流', date }
}

/** 展开文件名模板。 */
export function expandTemplate(template: string, ctx: TemplateContext): string {
  return String(template || DEFAULT_TEMPLATE)
    .split('%filename%').join(ctx.filename)
    .split('%stem%').join(ctx.stem)
    .split('%model%').join(ctx.model)
    .split('%song%').join(ctx.song)
    .split('%workflow%').join(ctx.workflow)
    .split('%date%').join(ctx.date)
}

/** 保存节点中某条音轨的文件名预览（带扩展名）。 */
export function trackPreview(
  graph: WorkflowGraph,
  edge: WorkflowEdge,
  songName: string,
  models: NamedModel[] = [],
): string {
  const saveNode = saveNodeOf(graph)
  const template = String(
    (saveNode?.params as { file_template?: string })?.file_template || DEFAULT_TEMPLATE,
  )
  const expanded = expandTemplate(template, edgeContext(graph, edge, songName, models))
  return /\.[a-z0-9]{2,4}$/i.test(expanded) ? expanded : `${expanded}.wav`
}

/** 作品标题（由保存节点的主音轨模板生成，不含扩展名）。 */
export function workflowOutputTitle(
  graph: WorkflowGraph,
  songName: string,
  models: NamedModel[] = [],
): string {
  const saveNode = saveNodeOf(graph)
  const template = String(
    (saveNode?.params as { file_template?: string })?.file_template || DEFAULT_TEMPLATE,
  )
  const primaryEdge = saveNode
    ? (graph.edges || []).find((e) => e.to.node === saveNode.id)
    : undefined
  const expanded = expandTemplate(template, edgeContext(graph, primaryEdge, songName, models))
  const base = sanitizeName(expanded).replace(/\.[a-z0-9]{2,4}$/i, '')
  return base || baseName(songName).replace(/\.[^.]+$/, '') || '歌曲'
}

/** 保存节点「文件名称预览」（带扩展名，仅用于界面展示）。 */
export function workflowOutputPreview(
  graph: WorkflowGraph,
  songName: string,
  models: NamedModel[] = [],
): string {
  const saveNode = saveNodeOf(graph)
  const primaryEdge = saveNode
    ? (graph.edges || []).find((e) => e.to.node === saveNode.id)
    : undefined
  if (primaryEdge) return trackPreview(graph, primaryEdge, songName, models)
  return `${workflowOutputTitle(graph, songName, models)}.wav`
}
