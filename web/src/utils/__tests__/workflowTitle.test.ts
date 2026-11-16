import { describe, expect, it } from 'vitest'
import type { WorkflowGraph } from '@/api'
import {
  edgeContext,
  expandTemplate,
  saveNodeOf,
  trackPreview,
  workflowOutputPreview,
  workflowOutputTitle,
} from '@/utils/workflowTitle'

const models = [{ id: 'mdl_a', name: 'MyModel' }]

function makeGraph(overrides: Partial<WorkflowGraph> = {}): WorkflowGraph {
  return {
    id: '',
    name: '测试工作流',
    updated_at: '',
    nodes: [
      { id: 'i', type: 'input', x: 0, y: 0, params: {} },
      { id: 's', type: 'separate', x: 0, y: 0, params: { model: 'bs_roformer' } },
      { id: 'c', type: 'convert', x: 0, y: 0, params: { model_id: 'mdl_a' } },
      { id: 'o', type: 'output', x: 0, y: 0, params: { file_template: '%filename%_%stem%_%model%' } },
    ],
    edges: [
      { id: 'e1', from: { node: 'i', port: 'audio' }, to: { node: 's', port: 'audio' } },
      { id: 'e2', from: { node: 's', port: 'vocals' }, to: { node: 'c', port: 'audio' } },
      { id: 'e3', from: { node: 'c', port: 'audio' }, to: { node: 'o', port: 'audio' } },
    ],
    ...overrides,
  }
}

describe('workflowTitle', () => {
  it('finds the connected save node', () => {
    const graph = makeGraph()
    expect(saveNodeOf(graph)?.id).toBe('o')
  })

  it('prefers a connected save node over an earlier disconnected one', () => {
    const graph = makeGraph()
    graph.nodes.unshift({ id: 'o0', type: 'output', x: 0, y: 0, params: {} })
    expect(saveNodeOf(graph)?.id).toBe('o')
  })

  it('builds per-track context from the edge', () => {
    const graph = makeGraph()
    const edge = graph.edges.find((e) => e.id === 'e3')!
    const ctx = edgeContext(graph, edge, '晴天.mp3', models)
    expect(ctx.filename).toBe('歌声转换')
    expect(ctx.stem).toBe('音频')
    expect(ctx.model).toBe('MyModel')
    expect(ctx.song).toBe('晴天')
  })

  it('uses input label for the source track', () => {
    const graph = makeGraph()
    const edge = graph.edges.find((e) => e.id === 'e1')!
    const ctx = edgeContext(graph, edge, 'song.wav', models)
    expect(ctx.filename).toBe('input')
    expect(ctx.stem).toBe('音频')
  })

  it('expands %song% / %stem% / %model%', () => {
    const graph = makeGraph()
    const edge = graph.edges.find((e) => e.id === 'e3')!
    const ctx = edgeContext(graph, edge, '晴天.mp3', models)
    expect(expandTemplate('%song%_%stem%_%model%', ctx)).toBe('晴天_音频_MyModel')
  })

  it('derives the work title from the primary track template', () => {
    const graph = makeGraph()
    expect(workflowOutputTitle(graph, '晴天.mp3', models)).toBe('歌声转换_音频_MyModel')
  })

  it('supports the %song%_%model% template', () => {
    const graph = makeGraph()
    graph.nodes = graph.nodes.map((n) =>
      n.id === 'o' ? { ...n, params: { file_template: '%song%_%model%' } } : n,
    )
    expect(workflowOutputTitle(graph, '晴天.flac', models)).toBe('晴天_MyModel')
  })

  it('produces a .wav filename preview', () => {
    const graph = makeGraph()
    const edge = graph.edges.find((e) => e.id === 'e3')!
    expect(trackPreview(graph, edge, '晴天.mp3', models)).toBe('歌声转换_音频_MyModel.wav')
    expect(workflowOutputPreview(graph, '晴天.mp3', models)).toBe('歌声转换_音频_MyModel.wav')
  })

  it('sanitizes illegal filename characters', () => {
    const graph = makeGraph()
    graph.nodes = graph.nodes.map((n) =>
      n.id === 'o' ? { ...n, params: { file_template: '%song%/%model%' } } : n,
    )
    expect(workflowOutputTitle(graph, 'a/b/c.mp3', models)).toBe('a_b_c_MyModel')
  })
})
