<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import type { PymssModel } from '@/api'
import { translateUiText } from '@/i18n'
import { pymssPurposeKey } from '@/utils/pymssPurpose'

// PyMSS 模型选择器：分类快捷筛选 + 关键词搜索 + 下载状态标记，
// 供自定义工作流的人声分离 / 去混响节点使用（模型数量多，纯下拉很难找）。
const props = withDefaults(
  defineProps<{
    modelValue?: string
    models?: PymssModel[]
    /** 打开面板时默认选中的筛选项：all / vocal / dereverb / harmony / downloaded */
    defaultFilter?: string
    placeholder?: string
  }>(),
  {
    modelValue: '',
    models: () => [],
    defaultFilter: 'all',
    placeholder: '选择模型',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'download', name: string): void
}>()

const open = ref(false)
const keyword = ref('')
const filter = ref(props.defaultFilter || 'all')

const MATCHERS: Record<string, (model: PymssModel) => boolean> = {
  all: () => true,
  vocal: (model) => pymssPurposeKey(model) === 'vocal_separation',
  dereverb: (model) => pymssPurposeKey(model) === 'dereverb',
  harmony: (model) => pymssPurposeKey(model) === 'harmony_removal',
  downloaded: (model) => model.downloaded !== false,
}

const buckets = computed(() => {
  const list = props.models || []
  const count = (key: string) => list.filter(MATCHERS[key]!).length
  return [
    { key: 'all', label: translateUiText('全部'), total: list.length },
    { key: 'vocal', label: translateUiText('人声分离'), total: count('vocal') },
    { key: 'dereverb', label: translateUiText('去混响'), total: count('dereverb') },
    { key: 'harmony', label: translateUiText('和声分离'), total: count('harmony') },
    { key: 'downloaded', label: translateUiText('已下载'), total: count('downloaded') },
  ]
})

function haystack(model: PymssModel): string {
  return [
    model.name,
    model.purpose_label,
    model.category_label,
    model.primary_category_label,
    model.secondary_category_label,
    model.architecture,
    model.target_stem,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

const filtered = computed(() => {
  const matcher = MATCHERS[filter.value] || MATCHERS.all!
  const kw = keyword.value.trim().toLowerCase()
  const list = (props.models || []).filter((model) => matcher(model))
  const searched = kw ? list.filter((model) => haystack(model).includes(kw)) : list
  // 已下载的排前面，方便直接挑能跑的
  return [...searched].sort((a, b) => {
    const da = a.downloaded === false ? 1 : 0
    const db = b.downloaded === false ? 1 : 0
    if (da !== db) return da - db
    return a.name.localeCompare(b.name)
  })
})

const selectedModel = computed(() => (props.models || []).find((model) => model.name === props.modelValue) || null)
const triggerLabel = computed(() => props.modelValue || translateUiText(props.placeholder))

function purposeText(model: PymssModel): string {
  return String(model.purpose_label || model.category_label || '').trim()
}

function sizeText(bytes?: number): string {
  if (!bytes || bytes <= 0) return ''
  const mb = bytes / (1024 * 1024)
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`
}

function subText(model: PymssModel): string {
  return [purposeText(model), sizeText(model.size_bytes)].filter(Boolean).join(' · ')
}

function pick(model: PymssModel) {
  emit('update:modelValue', model.name)
  open.value = false
}

function download(model: PymssModel) {
  emit('download', model.name)
}

// 每次打开都回到该节点的推荐分类，并清空上次的关键词；
// 若当前选中的模型不属于推荐分类，退回「全部」以免看不到自己选的模型。
watch(open, (value) => {
  if (!value) return
  keyword.value = ''
  const preset = props.defaultFilter || 'all'
  const matcher = MATCHERS[preset] || MATCHERS.all!
  const current = (props.models || []).find((model) => model.name === props.modelValue)
  filter.value = current && !matcher(current) ? 'all' : preset
})
</script>

<template>
  <el-popover
    v-model:visible="open"
    placement="bottom-start"
    trigger="click"
    :width="344"
    :show-arrow="false"
    popper-class="pmp-popper"
    :teleported="true"
  >
    <template #reference>
      <button type="button" class="pmp-trigger" :class="{ open }" :title="triggerLabel" @pointerdown.stop>
        <span class="pmp-trigger-text" :class="{ empty: !modelValue }">{{ triggerLabel }}</span>
        <span v-if="selectedModel && selectedModel.downloaded === false" class="pmp-trigger-tag">未下载</span>
        <span class="pmp-caret" aria-hidden="true"></span>
      </button>
    </template>

    <div class="pmp-panel" @pointerdown.stop @keydown.stop>
      <div class="pmp-search">
        <el-icon class="pmp-search-icon"><Search /></el-icon>
        <input v-model="keyword" class="pmp-search-input" type="text" placeholder="搜索模型名或分类" />
      </div>

      <div class="pmp-chips">
        <button
          v-for="bucket in buckets"
          :key="bucket.key"
          type="button"
          class="pmp-chip"
          :class="{ active: filter === bucket.key }"
          :disabled="!bucket.total && bucket.key !== 'all'"
          @click="filter = bucket.key"
        >
          {{ bucket.label }}<i>{{ bucket.total }}</i>
        </button>
      </div>

      <div class="pmp-list">
        <div v-for="model in filtered" :key="model.name" class="pmp-row">
          <button
            type="button"
            class="pmp-item"
            :class="{ active: model.name === modelValue }"
            :title="model.name"
            @click="pick(model)"
          >
            <span class="pmp-item-main">
              <b>{{ model.name }}</b>
              <small v-if="subText(model)">{{ subText(model) }}</small>
            </span>
            <span class="pmp-tags">
              <span v-if="model.downloaded === false" class="pmp-tag pmp-tag--muted">未下载</span>
              <span v-else class="pmp-tag pmp-tag--ok">已下载</span>
              <span v-if="model.supported === false" class="pmp-tag pmp-tag--warn">不支持</span>
            </span>
          </button>
          <button
            v-if="model.downloaded === false"
            type="button"
            class="pmp-dl"
            title="下载该模型"
            @click.stop="download(model)"
          >
            下载
          </button>
        </div>
        <div v-if="!filtered.length" class="pmp-empty">
          {{
            !models.length
              ? '尚未读取到 PyMSS 模型目录'
              : keyword
                ? '没有匹配的模型，换个关键词试试'
                : '该分类下暂无模型，可切换到「全部」查看'
          }}
        </div>
      </div>

      <div class="pmp-foot">
        <span>{{ filtered.length }} 个模型 · 点击即可切换</span>
        <button type="button" class="pmp-clear" @click="emit('update:modelValue', '')">清空</button>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.pmp-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 30px;
  padding: 4px 8px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--xb-panel) 82%, #000);
  color: var(--xb-text);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.pmp-trigger:hover,
.pmp-trigger.open {
  border-color: var(--xb-primary);
  background: color-mix(in srgb, var(--xb-primary) 10%, transparent);
}
.pmp-trigger-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}
.pmp-trigger-text.empty {
  color: var(--xb-muted);
}
.pmp-trigger-tag {
  flex-shrink: 0;
  padding: 1px 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--xb-warn) 20%, transparent);
  color: var(--xb-warn);
  font-size: 10px;
}
.pmp-caret {
  flex-shrink: 0;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid var(--xb-muted);
}

.pmp-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pmp-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  height: 30px;
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--xb-panel) 70%, #000);
}
.pmp-search:focus-within {
  border-color: var(--xb-primary);
}
.pmp-search-icon {
  color: var(--xb-muted);
  font-size: 13px;
}
.pmp-search-input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--xb-text);
  font-size: 12px;
  outline: none;
}
.pmp-search-input::placeholder {
  color: var(--xb-muted);
}

.pmp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pmp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid var(--xb-border);
  border-radius: 999px;
  background: transparent;
  color: var(--xb-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.16s ease;
}
.pmp-chip i {
  font-style: normal;
  font-size: 10px;
  opacity: 0.75;
}
.pmp-chip:hover {
  border-color: var(--xb-primary);
  color: var(--xb-text);
}
.pmp-chip.active {
  border-color: var(--xb-primary);
  background: color-mix(in srgb, var(--xb-primary) 16%, transparent);
  color: var(--xb-text);
}
.pmp-chip:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pmp-list {
  max-height: 248px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 2px;
}
.pmp-list::-webkit-scrollbar {
  width: 6px;
}
.pmp-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--xb-scroll-thumb);
}
.pmp-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pmp-item {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: color-mix(in srgb, var(--xb-panel) 55%, transparent);
  color: var(--xb-text);
  text-align: left;
  cursor: pointer;
  transition: all 0.16s ease;
}
.pmp-item:hover {
  border-color: var(--xb-border);
  background: color-mix(in srgb, var(--xb-primary) 10%, transparent);
}
.pmp-item.active {
  border-color: var(--xb-primary);
  background: color-mix(in srgb, var(--xb-primary) 16%, transparent);
}
.pmp-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.pmp-item-main b {
  font-size: 11.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pmp-item-main small {
  font-size: 10px;
  color: var(--xb-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pmp-tags {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.pmp-tag {
  padding: 0 5px;
  border-radius: 999px;
  font-size: 9.5px;
  line-height: 14px;
}
.pmp-tag--ok {
  background: color-mix(in srgb, var(--xb-success) 18%, transparent);
  color: var(--xb-success);
}
.pmp-tag--muted {
  background: color-mix(in srgb, var(--xb-muted) 20%, transparent);
  color: var(--xb-muted);
}
.pmp-tag--warn {
  background: color-mix(in srgb, var(--xb-warn) 18%, transparent);
  color: var(--xb-warn);
}
.pmp-dl {
  flex-shrink: 0;
  padding: 3px 7px;
  border: 1px solid var(--xb-border);
  border-radius: 7px;
  background: transparent;
  color: var(--xb-primary);
  font-size: 10.5px;
  cursor: pointer;
}
.pmp-dl:hover {
  border-color: var(--xb-primary);
  background: color-mix(in srgb, var(--xb-primary) 14%, transparent);
}
.pmp-empty {
  padding: 14px 6px;
  text-align: center;
  font-size: 11.5px;
  color: var(--xb-muted);
}
.pmp-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 6px;
  border-top: 1px solid var(--xb-border);
  font-size: 10.5px;
  color: var(--xb-muted);
}
.pmp-clear {
  border: 0;
  background: transparent;
  color: var(--xb-primary);
  font-size: 10.5px;
  cursor: pointer;
}
</style>

<style>
/* 弹层挂在 body 上，需要非 scoped 才能收紧内边距 */
.pmp-popper.el-popover.el-popper {
  padding: 10px;
  border-radius: 12px;
  border: 1px solid var(--xb-border);
  background: color-mix(in srgb, var(--xb-panel) 96%, #05060d);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
}
</style>
