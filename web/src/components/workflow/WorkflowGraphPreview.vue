<template>
  <div class="wfp" :class="{ compact }" :style="containerStyle">
    <svg
      v-if="layout.nodes.length"
      class="wfp-svg"
      :viewBox="`0 0 ${layout.width} ${layout.height}`"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      :aria-label="label"
    >
      <defs>
        <marker
          :id="markerId"
          markerWidth="10"
          markerHeight="8"
          refX="9"
          refY="4"
          orient="auto"
          markerUnits="userSpaceOnUse"
        >
          <path class="wfp-arrow" d="M 0 0 L 10 4 L 0 8 z" />
        </marker>
      </defs>
      <g class="wfp-edges">
        <path
          v-for="edge in layout.edges"
          :key="edge.id"
          :d="edge.path"
          :marker-end="`url(#${markerId})`"
        />
      </g>
      <g
        v-for="node in layout.nodes"
        :key="node.id"
        :transform="`translate(${node.x} ${node.y})`"
      >
        <rect
          class="wfp-card"
          :width="node.width"
          :height="node.height"
          rx="13"
          :stroke="node.color"
        />
        <rect :width="5" :height="node.height" rx="2.5" :fill="node.color" />
        <template v-if="!compact">
          <text x="19" y="33" class="wfp-title">{{ node.label }}</text>
          <text
            v-for="(line, index) in node.summaryLines"
            :key="`${node.id}-${index}`"
            x="19"
            :y="59 + index * 20"
            class="wfp-sub"
          >{{ line }}</text>
        </template>
      </g>
    </svg>
    <div v-else class="wfp-empty">
      <span>{{ emptyText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'
import { translateUiText } from '@/i18n'
import {
  buildCompactWorkflowPreviewLayout,
  buildWorkflowPreviewLayout,
  type PreviewEdgeLike,
  type PreviewNodeLike,
} from '@/utils/workflowPreview'

defineOptions({ name: 'WorkflowGraphPreview' })

const props = withDefaults(
  defineProps<{
    graph?: { nodes?: PreviewNodeLike[] | null; edges?: PreviewEdgeLike[] | null } | null
    /** 缩略图模式高度（详情模式按节点图比例自适应）。 */
    height?: number
    compact?: boolean
    maxHeight?: number
    label?: string
  }>(),
  {
    graph: null,
    height: 130,
    compact: false,
    maxHeight: 520,
    label: '',
  },
)

const layout = computed(() =>
  props.compact
    ? buildCompactWorkflowPreviewLayout(props.graph?.nodes || [], props.graph?.edges || [])
    : buildWorkflowPreviewLayout(props.graph?.nodes || [], props.graph?.edges || []),
)
const emptyText = computed(() => translateUiText('暂无可预览的节点'))
const markerId = `wfp-arrow-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`

const containerStyle = computed(() => {
  if (props.compact) return { height: `${props.height}px` }
  return {
    aspectRatio: `${layout.value.width} / ${layout.value.height}`,
    maxHeight: `${props.maxHeight}px`,
    minHeight: '160px',
  }
})
</script>

<style scoped>
.wfp {
  position: relative;
  width: 100%;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--xb-border);
  background-color: var(--xb-bg-2, var(--xb-bg, #05060d));
  background-image:
    linear-gradient(rgba(var(--xb-primary-rgb), 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--xb-primary-rgb), 0.055) 1px, transparent 1px);
  background-size: 28px 28px;
}
.wfp.compact {
  border-radius: 0;
  border: none;
  border-bottom: 1px solid var(--xb-border);
  background-size: 22px 22px;
}
.wfp-svg {
  display: block;
  width: 100%;
  height: 100%;
}
.wfp-edges path {
  fill: none;
  stroke: rgba(var(--xb-primary-rgb), 0.5);
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.wfp-arrow {
  fill: rgba(var(--xb-primary-rgb), 0.68);
}
.wfp-card {
  fill: var(--xb-panel);
  fill-opacity: 0.94;
  stroke-width: 1.5;
  stroke-opacity: 0.62;
}
.wfp-title {
  font-size: 22px;
  font-weight: 700;
  fill: var(--xb-text);
}
.wfp-sub {
  font-size: 17px;
  fill: var(--xb-muted);
}
.wfp-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 180px;
  color: var(--xb-muted);
  font-size: 13px;
}
</style>
