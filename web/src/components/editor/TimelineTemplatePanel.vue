<template>
  <section class="template-panel">
    <div class="section-head">
      <span>时间轴模板</span>
      <small>{{ templates.length }} 个</small>
    </div>

    <div class="template-list">
      <button
        v-for="template in templates"
        :key="template.id"
        type="button"
        class="template-card"
        :class="{ active: template.id === activeTemplateId }"
        :disabled="disabled"
        @click="emit('apply', template.id)"
      >
        <span class="template-icon">
          <el-icon><CollectionTag /></el-icon>
        </span>
        <span class="template-copy">
          <b>{{ template.name }}</b>
          <small>{{ template.description }}</small>
        </span>
        <span class="template-meta">{{ template.tracks.length }} 轨</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { CollectionTag } from '@element-plus/icons-vue'
import type { EditorTimelineTemplate } from '@/api'

defineOptions({ name: 'TimelineTemplatePanel' })

defineProps<{
  templates: EditorTimelineTemplate[]
  activeTemplateId: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  apply: [id: string]
}>()
</script>

<style scoped>
.template-panel {
  display: grid;
  gap: 10px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 800;
}
.section-head small {
  color: var(--xb-muted);
  font-size: 11px;
  font-weight: 700;
}
.template-list {
  display: grid;
  gap: 8px;
}
.template-card {
  width: 100%;
  min-height: 58px;
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.035);
  color: var(--xb-text);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.template-card:hover:not(:disabled),
.template-card.active {
  border-color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.08);
}
.template-card:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}
.template-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.12);
}
.template-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.template-copy b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
}
.template-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-muted);
  font-size: 11.5px;
}
.template-meta {
  padding: 3px 7px;
  border-radius: 999px;
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  font-size: 11px;
  font-weight: 800;
}
</style>
