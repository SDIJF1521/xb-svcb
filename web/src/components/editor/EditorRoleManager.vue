<template>
  <section class="role-manager">
    <div class="section-head">
      <span>角色管理</span>
      <button type="button" title="添加角色" @click="emit('add')">
        <el-icon><Plus /></el-icon>
      </button>
    </div>

    <div v-if="roles.length" class="role-list">
      <article
        v-for="role in roles"
        :key="role.id"
        class="role-card"
        :class="{ selected: role.id === selectedRoleId }"
        :style="{ '--role-color': role.color }"
      >
        <div class="role-top">
          <input
            class="role-color"
            type="color"
            :value="role.color"
            title="角色颜色"
            @change="updateRole(role.id, { color: inputValue($event) })"
          />
          <input
            class="role-name"
            :value="role.name"
            maxlength="18"
            placeholder="角色名"
            @change="updateRole(role.id, { name: inputValue($event) })"
          />
          <button
            type="button"
            class="role-delete"
            title="删除角色"
            :disabled="roles.length <= 1"
            @click="emit('remove', role.id)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </div>

        <select
          class="role-model"
          :value="role.model_id || ''"
          @change="updateRole(role.id, { model_id: inputValue($event) || undefined })"
        >
          <option value="">未关联模型</option>
          <option v-for="model in models" :key="model.id" :value="model.id">
            {{ model.name }}
          </option>
        </select>

        <div class="role-pitch">
          <span>变调</span>
          <input
            type="number"
            min="-24"
            max="24"
            step="1"
            :value="role.pitch ?? 0"
            @change="updateRole(role.id, { pitch: numberValue($event) })"
          />
        </div>

        <input
          class="role-note"
          :value="role.notes || ''"
          maxlength="40"
          placeholder="备注，如：主歌 / 副歌 / 和声"
          @change="updateRole(role.id, { notes: inputValue($event) })"
        />

        <button
          type="button"
          class="assign-btn"
          :disabled="!hasSelectedClip"
          @click="emit('assign', role.id)"
        >
          <el-icon><Select /></el-icon>
          <span>{{ role.id === selectedRoleId ? '已分配到片段' : '分配给选中片段' }}</span>
        </button>
      </article>
    </div>

    <div v-else class="empty-role">
      <el-icon><UserFilled /></el-icon>
      <span>还没有角色</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Delete, Plus, Select, UserFilled } from '@element-plus/icons-vue'
import type { EditorRole } from '@/api'

interface RoleModelOption {
  id: string
  name: string
}

defineOptions({ name: 'EditorRoleManager' })

defineProps<{
  roles: EditorRole[]
  models: RoleModelOption[]
  selectedRoleId: string
  hasSelectedClip: boolean
}>()

const emit = defineEmits<{
  add: []
  update: [id: string, patch: Partial<EditorRole>]
  remove: [id: string]
  assign: [id: string]
}>()

function inputValue(e: Event) {
  return (e.target as HTMLInputElement | HTMLSelectElement).value.trim()
}

function numberValue(e: Event) {
  const value = Number((e.target as HTMLInputElement).value)
  return Number.isFinite(value) ? Math.max(-24, Math.min(24, Math.round(value))) : 0
}

function updateRole(id: string, patch: Partial<EditorRole>) {
  emit('update', id, patch)
}
</script>

<style scoped>
.role-manager {
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
.section-head button,
.role-delete {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  cursor: pointer;
}
.section-head button:hover,
.role-delete:hover:not(:disabled) {
  color: var(--xb-primary);
  border-color: var(--xb-primary);
}
.role-delete:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
.role-list {
  display: grid;
  gap: 10px;
}
.role-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--role-color) 34%, var(--xb-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--role-color) 8%, transparent);
}
.role-card.selected {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--role-color) 72%, transparent);
}
.role-top {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 28px;
  gap: 8px;
  align-items: center;
}
.role-color {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: transparent;
  cursor: pointer;
}
.role-name,
.role-model,
.role-note,
.role-pitch input {
  width: 100%;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.045);
  color: var(--xb-text);
  outline: none;
  padding: 0 9px;
  font: inherit;
  font-size: 12px;
}
.role-name:focus,
.role-model:focus,
.role-note:focus,
.role-pitch input:focus {
  border-color: var(--xb-primary);
}
.role-pitch {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  color: var(--xb-muted);
  font-size: 12px;
  font-weight: 700;
}
.assign-btn {
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid color-mix(in srgb, var(--role-color) 44%, var(--xb-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--role-color) 12%, transparent);
  color: var(--xb-text);
  font: inherit;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}
.assign-btn:hover:not(:disabled) {
  color: var(--role-color);
  border-color: var(--role-color);
}
.assign-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.empty-role {
  min-height: 92px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 7px;
  border: 1px dashed var(--xb-border);
  border-radius: 8px;
  color: var(--xb-muted);
  font-size: 12px;
}
.empty-role .el-icon {
  font-size: 24px;
  color: var(--xb-primary);
}
</style>
