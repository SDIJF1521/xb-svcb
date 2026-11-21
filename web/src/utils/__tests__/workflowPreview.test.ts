import { beforeEach, describe, expect, it } from 'vitest'

import { setLocale } from '@/i18n'
import {
  PREVIEW_NODE_HEIGHT,
  PREVIEW_NODE_WIDTH,
  PREVIEW_PADDING,
  PREVIEW_RANK_GAP,
  PREVIEW_ROW_GAP,
  buildCompactWorkflowPreviewLayout,
  buildWorkflowPreviewLayout,
  fitSingleLine,
  previewNodeColor,
  previewNodeLabel,
  summarizeNodeParams,
  wrapText,
} from '@/utils/workflowPreview'

beforeEach(() => setLocale('zh-CN'))

function nodes() {
  return [
    { id: 'i', type: 'input', x: 40, y: 190 },
    {
      id: 's',
      type: 'separate',
      x: 250,
      y: 140,
      params: { engine: 'pymss', model: 'bs_roformer_voc_hyperacev2.ckpt' },
    },
    { id: 'c', type: 'convert', x: 650, y: 60, params: {} },
    { id: 'e', type: 'enhance', x: 650, y: 320, params: { level: 'basic' } },
    { id: 'm', type: 'mix', x: 920, y: 190, params: { enhanced: true } },
    { id: 'o', type: 'output', x: 1160, y: 190, params: { file_template: '%filename%_%stem%' } },
  ]
}

function edges() {
  return [
    { id: 'e1', from: { node: 'i', port: 'audio' }, to: { node: 's', port: 'audio' } },
    { id: 'e2', from: { node: 's', port: 'vocals' }, to: { node: 'c', port: 'audio' } },
    { id: 'e3', from: { node: 's', port: 'vocals' }, to: { node: 'e', port: 'audio' } },
    { id: 'e4', from: { node: 's', port: 'instrumental' }, to: { node: 'm', port: 'instrumental' } },
    { id: 'e5', from: { node: 'c', port: 'audio' }, to: { node: 'm', port: 'vocals' } },
    { id: 'e6', from: { node: 'e', port: 'audio' }, to: { node: 'm', port: 'vocals' } },
    { id: 'e7', from: { node: 'm', port: 'audio' }, to: { node: 'o', port: 'audio' } },
  ]
}

describe('workflow preview layout', () => {
  it('ranks nodes left to right and centers branches vertically', () => {
    const layout = buildWorkflowPreviewLayout(nodes(), edges())
    const byId = new Map(layout.nodes.map((node) => [node.id, node]))
    expect(byId.get('i')!.rank).toBe(0)
    expect(byId.get('s')!.rank).toBe(1)
    expect(byId.get('c')!.rank).toBe(2)
    expect(byId.get('e')!.rank).toBe(2)
    expect(byId.get('m')!.rank).toBe(3)
    expect(byId.get('o')!.rank).toBe(4)

    const rankX = PREVIEW_PADDING + PREVIEW_RANK_GAP + PREVIEW_NODE_WIDTH
    const singleRowY =
      PREVIEW_PADDING +
      (PREVIEW_PADDING * 2 + 2 * PREVIEW_NODE_HEIGHT + PREVIEW_ROW_GAP - PREVIEW_PADDING * 2 - PREVIEW_NODE_HEIGHT) / 2
    expect(byId.get('s')!.x).toBe(rankX)
    expect(byId.get('s')!.y).toBe(singleRowY)
    expect(byId.get('c')!.y).toBeLessThan(byId.get('e')!.y)
    expect(byId.get('m')!.y).toBeGreaterThan(byId.get('c')!.y)
    expect(byId.get('m')!.y).toBeLessThan(byId.get('e')!.y)

    const expectedWidth =
      PREVIEW_PADDING * 2 + 5 * PREVIEW_NODE_WIDTH + 4 * PREVIEW_RANK_GAP
    expect(layout.width).toBe(expectedWidth)
    expect(layout.height).toBe(PREVIEW_PADDING * 2 + 2 * PREVIEW_NODE_HEIGHT + PREVIEW_ROW_GAP)
    expect(layout.edges).toHaveLength(7)
    expect(layout.edges[0]!.path.startsWith('M ')).toBe(true)
  })

  it('returns a stable empty canvas and ignores dangling edges', () => {
    expect(buildWorkflowPreviewLayout([], [])).toEqual({
      width: 520,
      height: 220,
      nodes: [],
      edges: [],
    })
    const layout = buildWorkflowPreviewLayout(
      [{ id: 'a', type: 'input', x: 0, y: 0 }],
      [{ id: 'bad', from: { node: 'a' }, to: { node: 'missing' } }],
    )
    expect(layout.edges).toEqual([])
  })

  it('handles cycles without hanging', () => {
    const layout = buildWorkflowPreviewLayout(
      [
        { id: 'a', type: 'convert', x: 0, y: 0 },
        { id: 'b', type: 'enhance', x: 300, y: 0 },
      ],
      [
        { id: 'ab', from: { node: 'a' }, to: { node: 'b' } },
        { id: 'ba', from: { node: 'b' }, to: { node: 'a' } },
      ],
    )
    expect(layout.nodes).toHaveLength(2)
    expect(layout.edges).toHaveLength(2)
  })

  it('summarizes params and keeps card text inside the node width', () => {
    const layout = buildWorkflowPreviewLayout(nodes(), edges())
    const separate = layout.nodes.find((node) => node.id === 's')!
    expect(separate.summaryLines[0]).toContain('PyMSS')
    expect(separate.label).toBe('人声分离')
    for (const line of separate.summaryLines) {
      expect(fitSingleLine(line, PREVIEW_NODE_WIDTH - 34, 17)).toBe(line)
    }
    expect(
      summarizeNodeParams({ id: 'c', type: 'convert', x: 0, y: 0, params: {} }),
    ).toBe('选择声音模型')
    expect(previewNodeColor('convert')).toBe('#e11d6f')
    expect(previewNodeLabel('output')).toBe('输出成品')
  })

  it('builds a larger-node compact layout for list cards', () => {
    const layout = buildCompactWorkflowPreviewLayout(nodes(), edges())
    expect(layout.nodes.length).toBe(6)
    expect(layout.nodes.every((node) => node.width < PREVIEW_NODE_WIDTH)).toBe(true)
    expect(layout.nodes.every((node) => node.label === '')).toBe(true)
    expect(layout.edges.length).toBe(7)
    expect(layout.width).toBeGreaterThan(300)
  })

  it('wraps long text into at most two lines with an ellipsis', () => {
    const lines = wrapText(
      'UVR · this_is_a_very_long_model_name_that_should_not_overflow_the_card',
      140,
      14,
      2,
    )
    expect(lines.length).toBeLessThanOrEqual(2)
    expect(lines[0]!.length).toBeGreaterThan(0)
    expect(lines[1]!.endsWith('…')).toBe(true)
  })
})
