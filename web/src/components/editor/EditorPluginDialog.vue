<template>
  <el-dialog
    v-model="open"
    title="插件窗口"
    width="760px"
    class="plugin-dialog"
    append-to-body
    draggable
    overflow
    :modal="false"
    modal-penetrable
    :lock-scroll="false"
    :close-on-click-modal="false"
    @close="emit('closed')"
  >
    <div class="plugin-dialog-body">
      <div class="plugin-host-bar">
        <div>
          <b>{{ effect?.name || 'VST3 插件' }}</b>
          <span>{{ hostStatus?.message || '等待 JUCE Host' }}</span>
        </div>
        <el-button circle class="ghost-btn mini-inline" :loading="loading" title="刷新 Host 状态" @click="emit('refresh')">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
      <div class="plugin-host-stage">
        <div class="plugin-host-placeholder">
          <b>{{ sessionId ? (hostStatus?.realtime_ready ? '块级实时播放已连接' : (hostStatus?.monitor_ready ? '实时监听已连接' : 'JUCE Host 会话已打开')) : 'JUCE VST3 Host' }}</b>
          <span>{{ activePath || hostStatus?.host_path || '未选择插件' }}</span>
          <span v-if="hostStatus?.monitor?.audio_output_ready" class="realtime-device">
            {{ hostStatus.monitor.device_name || '系统音频输出' }} · {{ hostStatus.monitor.block_size || 128 }} samples · {{ Number(hostStatus.monitor.latency_ms || 0).toFixed(1) }} ms
          </span>
          <span v-if="hostStatus?.realtime_reason" class="compatibility-note">
            {{ hostStatus.realtime_reason }}
          </span>
          <span v-else-if="hostStatus?.monitor?.safety_bypassed" class="compatibility-note">
            插件持续输出静音或非法采样，已自动旁通为干声保护。
          </span>
        </div>
      </div>
      <div v-if="effect" class="plugin-dialog-fields">
        <div class="plugin-path-row wide">
          <input
            :value="activePath"
            :disabled="!editable"
            placeholder="VST3 插件路径"
            @change="emit('setPath', $event)"
          />
          <button :disabled="!editable" title="选择插件" @click="emit('pickPlugin')">
            <el-icon><FolderAdd /></el-icon>
          </button>
        </div>
        <input
          :value="pluginParamJson(effect)"
          :disabled="!editable"
          placeholder='{"parameterId":0.5}'
          @change="emit('setParams', $event)"
        />
      </div>
    </div>
    <template #footer>
      <el-button round class="ghost-btn" :disabled="!activePath" @click="emit('inspect')">
        检查插件
      </el-button>
      <el-button round class="ghost-btn" :disabled="!sessionId" @click="emit('closeNative')">
        关闭窗口
      </el-button>
      <el-button
        round
        class="cta-btn"
        :loading="loading"
        :disabled="!effect || !activePath || !!sessionId"
        @click="emit('openNative')"
      >
        <el-icon class="el-icon--left"><Monitor /></el-icon>
        {{ sessionId ? '插件 GUI 已打开' : '打开插件 GUI' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { FolderAdd, Monitor, Refresh } from '@element-plus/icons-vue'
import type { EditorClipEffect, EditorPluginHostStatus } from '@/api'

const props = defineProps<{
  modelValue: boolean
  effect: EditorClipEffect | null
  activePath: string
  hostStatus: EditorPluginHostStatus | null
  loading: boolean
  sessionId: string
  editable: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  closed: []
  refresh: []
  inspect: []
  closeNative: []
  openNative: []
  pickPlugin: []
  setPath: [event: Event]
  setParams: [event: Event]
}>()

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

function pluginParamJson(effect: EditorClipEffect) {
  const params = effect.params?.parameters
  try {
    return JSON.stringify(params && typeof params === 'object' ? params : {}, null, 0)
  } catch {
    return '{}'
  }
}
</script>

<style scoped>
.ghost-btn {
  background: rgba(var(--xb-fill-rgb), 0.04) !important;
  border: 1px solid var(--xb-border) !important;
  color: var(--xb-text) !important;
  font-weight: 600;
}
.cta-btn {
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2)) !important;
  border: none !important;
  color: var(--xb-on-primary) !important;
  font-weight: 700;
}
.plugin-dialog-body {
  display: grid;
  gap: 12px;
}
.plugin-host-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
}
.plugin-host-bar div {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.plugin-host-bar b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.plugin-host-bar span,
.plugin-host-placeholder span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xb-muted);
  font-size: 12px;
}
.plugin-host-placeholder .compatibility-note {
  color: var(--el-color-warning);
  white-space: normal;
}
.mini-inline {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
}
.plugin-host-stage {
  min-height: 280px;
  border: 1px dashed rgba(var(--xb-primary-rgb), 0.42);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.035);
  display: grid;
  place-items: center;
  padding: 16px;
}
.plugin-host-placeholder {
  display: grid;
  gap: 6px;
  min-width: 0;
  width: 100%;
  text-align: center;
}
.plugin-host-placeholder b {
  color: var(--xb-primary);
  font-size: 14px;
}
.plugin-dialog-fields {
  display: grid;
  gap: 8px;
}
.plugin-dialog-fields input {
  width: 100%;
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.05);
  color: var(--xb-text);
  padding: 0 10px;
  outline: none;
}
.plugin-path-row {
  display: grid;
  gap: 6px;
  align-items: center;
}
.plugin-path-row.wide {
  grid-template-columns: minmax(0, 1fr) 34px;
}
.plugin-path-row button {
  height: 34px;
  width: 34px;
  padding: 0;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  cursor: pointer;
}
.plugin-path-row button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
