/**
 * 工作流画布：端口偏移（连线端点）的纯计算。
 *
 * 端口位置由 DOM 实测得到「相对节点左上角的世界坐标偏移」，按 ``节点id:side:port``
 * 存放。节点的内容高度会随「高级参数」折叠、切换模型后的参数区变化而改变，此时只
 * 重测尺寸变化的节点；这里负责把增量结果合并回整张表，并判断是否需要更新。
 */

export interface PortOffset {
  x: number
  y: number
}

/** 端口键：节点 id + 方向 + 端口名（与画布模板里的 ``data-port-key`` 一致）。 */
export function portOffsetKey(nodeId: string, side: 'in' | 'out', port: string): string {
  return `${nodeId}:${side}:${port}`
}

/** 是否属于某个节点（节点 id 可能自带冒号，只认 ``<id>:in|out:`` 前缀）。 */
function belongsToNode(key: string, nodeId: string): boolean {
  const prefix = `${nodeId}:`
  return key.startsWith(prefix) && /^(in|out):/.test(key.slice(prefix.length))
}

/**
 * 合并一次（增量）测量结果：被重测节点的旧端口先删掉（端口数量可能变化），
 * 再写回新值；其它节点的偏移保持不变。
 */
export function mergePortOffsets(
  current: Record<string, PortOffset>,
  measured: Record<string, PortOffset>,
  measuredNodeIds: Iterable<string>,
): Record<string, PortOffset> {
  const merged: Record<string, PortOffset> = { ...current }
  for (const nodeId of measuredNodeIds) {
    for (const key of Object.keys(merged)) {
      if (belongsToNode(key, nodeId)) delete merged[key]
    }
  }
  Object.assign(merged, measured)
  return merged
}

/**
 * 两套端口偏移是否一致。默认 0.01px 以内视为没变，避免每次测量都触发整张图的
 * 连线重算（折叠动画期间一秒会测几十次）。
 */
export function portOffsetsEqual(
  left: Record<string, PortOffset>,
  right: Record<string, PortOffset>,
  tolerance = 0.01,
): boolean {
  const leftKeys = Object.keys(left)
  if (leftKeys.length !== Object.keys(right).length) return false
  for (const key of leftKeys) {
    const a = left[key]!
    const b = right[key]
    if (!b) return false
    if (Math.abs(a.x - b.x) > tolerance || Math.abs(a.y - b.y) > tolerance) return false
  }
  return true
}
