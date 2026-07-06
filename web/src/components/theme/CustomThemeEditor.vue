<template>
  <div class="theme-editor">
    <input
      class="theme-name-input"
      maxlength="16"
      placeholder="主题名"
      :value="modelValue.name"
      @input="updateStringField('name', $event)"
    />

    <div class="theme-color-grid">
      <label v-for="field in customThemeFields" :key="field.key" class="theme-color-field">
        <span>{{ field.label }}</span>
        <input
          type="color"
          :value="modelValue[field.key]"
          @input="updateStringField(field.key, $event)"
        />
      </label>
    </div>

    <div class="theme-media">
      <div class="theme-section-title">背景与粒子</div>
      <div class="theme-image-row">
        <div
          class="theme-image-thumb"
          :class="{ empty: !modelValue.bgImage }"
          :style="themeImageThumbStyle"
        >
          <el-icon v-if="!modelValue.bgImage"><Picture /></el-icon>
        </div>
        <div class="theme-image-actions">
          <button class="pf-btn" type="button" @click="pickThemeImage">
            <el-icon><Picture /></el-icon><span>{{ modelValue.bgImage ? '更换图片' : '添加图片' }}</span>
          </button>
          <button v-if="modelValue.bgImage" class="pf-btn" type="button" @click="removeThemeImage">
            <el-icon><Close /></el-icon><span>移除</span>
          </button>
        </div>
        <input
          ref="themeImageInput"
          type="file"
          accept="image/*"
          hidden
          @change="onThemeImageFile"
        />
      </div>

      <label class="theme-slider-field">
        <span>图片遮罩 <b>{{ Math.round(modelValue.imageOverlay) }}%</b></span>
        <input
          type="range"
          min="0"
          max="90"
          :value="modelValue.imageOverlay"
          @input="updateNumberField('imageOverlay', $event)"
        />
      </label>
      <label class="theme-check-field">
        <span>动态粒子</span>
        <input
          type="checkbox"
          :checked="modelValue.particles"
          @change="updateParticles"
        />
      </label>
      <label class="theme-slider-field">
        <span>粒子数量 <b>{{ Math.round(modelValue.particleDensity) }}</b></span>
        <input
          type="range"
          min="0"
          max="64"
          :value="modelValue.particleDensity"
          @input="updateNumberField('particleDensity', $event)"
        />
      </label>
      <label class="theme-slider-field">
        <span>粒子大小 <b>{{ modelValue.particleSize.toFixed(1) }}</b></span>
        <input
          type="range"
          min="1.5"
          max="8"
          step="0.5"
          :value="modelValue.particleSize"
          @input="updateNumberField('particleSize', $event)"
        />
      </label>
    </div>

    <div class="theme-preview" :style="draftPreviewStyle">
      <span></span>
      <b></b>
      <i></i>
      <em v-for="n in 6" :key="n"></em>
    </div>

    <div class="theme-actions">
      <button class="pf-btn" type="button" @click="emit('preview', $event)">
        <el-icon><MagicStick /></el-icon><span>预览</span>
      </button>
      <button class="pf-btn primary" type="button" @click="emit('save', $event)">
        <el-icon><Check /></el-icon><span>保存</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Close, MagicStick, Picture } from '@element-plus/icons-vue'
import { CUSTOM_THEME_FIELDS } from '@/stores/theme'
import type { CustomTheme, CustomThemeField } from '@/stores/theme'

defineOptions({ name: 'CustomThemeEditor' })

type StringThemeKey = 'name' | CustomThemeField['key']
type NumberThemeKey = 'imageOverlay' | 'particleDensity' | 'particleSize'

const props = defineProps<{
  modelValue: CustomTheme
}>()

const emit = defineEmits<{
  'update:modelValue': [value: CustomTheme]
  preview: [event: MouseEvent]
  save: [event: MouseEvent]
}>()

const customThemeFields = CUSTOM_THEME_FIELDS
const themeImageInput = ref<HTMLInputElement>()

const draftPreviewStyle = computed<Record<string, string>>(() => ({
  '--draft-bg': props.modelValue.bg,
  '--draft-bg2': props.modelValue.bg2,
  '--draft-text': props.modelValue.text,
  '--draft-primary': props.modelValue.primary,
  '--draft-primary-2': props.modelValue.primary2,
  '--draft-accent': props.modelValue.accent,
  '--draft-bg-image': cssUrl(props.modelValue.bgImage),
  '--draft-image-opacity': props.modelValue.bgImage ? '1' : '0',
  '--draft-overlay': String(props.modelValue.imageOverlay / 100),
  '--draft-particle-opacity': props.modelValue.particles ? '0.78' : '0',
}))

const themeImageThumbStyle = computed<Record<string, string>>(() => ({
  '--theme-image-preview': cssUrl(props.modelValue.bgImage),
}))

function patchCustomTheme(patch: Partial<CustomTheme>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function updateStringField(key: StringThemeKey, e: Event) {
  const input = e.target as HTMLInputElement
  patchCustomTheme({ [key]: input.value } as Partial<CustomTheme>)
}

function updateNumberField(key: NumberThemeKey, e: Event) {
  const input = e.target as HTMLInputElement
  patchCustomTheme({ [key]: Number(input.value) } as Partial<CustomTheme>)
}

function updateParticles(e: Event) {
  const input = e.target as HTMLInputElement
  patchCustomTheme({ particles: input.checked })
}

function cssUrl(value: string) {
  return value ? `url("${value.replace(/"/g, '\\"')}")` : 'none'
}

function pickThemeImage() {
  themeImageInput.value?.click()
}

function removeThemeImage() {
  patchCustomTheme({ bgImage: '' })
}

function resizeThemeImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      const maxSide = 1600
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height))
      const width = Math.max(1, Math.round(img.width * scale))
      const height = Math.max(1, Math.round(img.height * scale))
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        reject(new Error('Canvas unavailable'))
        return
      }
      ctx.drawImage(img, 0, 0, width, height)
      resolve(canvas.toDataURL('image/jpeg', 0.82))
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Image load failed'))
    }
    img.src = url
  })
}

function onThemeImageFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  resizeThemeImage(file)
    .then((dataUrl) => {
      patchCustomTheme({ bgImage: dataUrl })
    })
    .catch(() => {})
}
</script>

<style scoped>
.theme-editor {
  padding: 12px;
}
.theme-name-input {
  width: 100%;
  height: 36px;
  padding: 0 11px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.05);
  color: var(--xb-text);
  outline: none;
  font: inherit;
  font-size: 13.5px;
  font-weight: 700;
}
.theme-name-input:focus {
  border-color: var(--xb-primary);
}
.theme-color-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}
.theme-color-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  height: 34px;
  padding: 0 9px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-muted);
  font-size: 12px;
  font-weight: 600;
}
.theme-color-field input {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
}
.theme-color-field input::-webkit-color-swatch-wrapper { padding: 0; }
.theme-color-field input::-webkit-color-swatch {
  border: 1px solid rgba(var(--xb-fill-rgb), 0.22);
  border-radius: 50%;
}
.theme-media {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--xb-border);
}
.theme-section-title {
  margin-bottom: 8px;
  color: var(--xb-text);
  font-size: 12.5px;
  font-weight: 800;
}
.theme-image-row {
  display: grid;
  grid-template-columns: 74px 1fr;
  gap: 10px;
  align-items: stretch;
}
.theme-image-thumb {
  min-height: 64px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  border: 1px solid var(--xb-border);
  background:
    linear-gradient(rgba(var(--xb-bg-rgb), 0.16), rgba(var(--xb-bg-rgb), 0.16)),
    var(--theme-image-preview);
  background-size: cover;
  background-position: center;
  color: var(--xb-muted);
  overflow: hidden;
}
.theme-image-thumb.empty {
  background: rgba(var(--xb-fill-rgb), 0.045);
}
.theme-image-thumb .el-icon {
  font-size: 20px;
  opacity: 0.7;
}
.theme-image-actions {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.theme-image-actions .pf-btn {
  width: 100%;
  flex: none;
  min-height: 28px;
  padding: 7px 8px;
}
.theme-slider-field,
.theme-check-field {
  display: grid;
  gap: 7px;
  margin-top: 10px;
  color: var(--xb-muted);
  font-size: 12px;
  font-weight: 700;
}
.theme-slider-field span,
.theme-check-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.theme-slider-field b {
  color: var(--xb-primary);
  font-size: 12px;
}
.theme-slider-field input[type='range'] {
  width: 100%;
  accent-color: var(--xb-primary);
}
.theme-check-field {
  grid-template-columns: 1fr auto;
  padding: 7px 9px;
  border-radius: 9px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
}
.theme-check-field input {
  width: 16px;
  height: 16px;
  accent-color: var(--xb-primary);
}
.theme-preview {
  position: relative;
  height: 54px;
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1fr 0.7fr 34px;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--draft-primary) 32%, transparent);
  background: linear-gradient(135deg, var(--draft-bg), var(--draft-bg2));
  overflow: hidden;
}
.theme-preview::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: var(--draft-image-opacity);
  background-image:
    linear-gradient(rgba(0, 0, 0, var(--draft-overlay)), rgba(0, 0, 0, var(--draft-overlay))),
    var(--draft-bg-image);
  background-size: cover;
  background-position: center;
}
.theme-preview span,
.theme-preview b,
.theme-preview i {
  position: relative;
  z-index: 1;
  display: block;
  height: 12px;
  border-radius: 999px;
}
.theme-preview span { background: var(--draft-text); opacity: 0.9; }
.theme-preview b { background: linear-gradient(135deg, var(--draft-primary), var(--draft-primary-2)); }
.theme-preview i {
  width: 24px;
  height: 24px;
  justify-self: end;
  background: var(--draft-accent);
  box-shadow: 0 0 14px color-mix(in srgb, var(--draft-accent) 55%, transparent);
}
.theme-preview em {
  position: absolute;
  z-index: 1;
  width: 4px;
  height: 4px;
  border-radius: 999px;
  opacity: var(--draft-particle-opacity);
  background: var(--draft-primary);
  box-shadow: 0 0 10px var(--draft-primary);
}
.theme-preview em:nth-of-type(1) { left: 16%; top: 24%; background: var(--draft-primary); }
.theme-preview em:nth-of-type(2) { left: 31%; top: 72%; background: var(--draft-accent); }
.theme-preview em:nth-of-type(3) { left: 49%; top: 18%; background: var(--draft-primary-2); }
.theme-preview em:nth-of-type(4) { left: 65%; top: 66%; background: var(--draft-primary); }
.theme-preview em:nth-of-type(5) { left: 77%; top: 28%; background: var(--draft-accent); }
.theme-preview em:nth-of-type(6) { left: 90%; top: 58%; background: var(--draft-primary-2); }
.theme-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}
.pf-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s;
}
.pf-btn:hover:not(:disabled) { border-color: var(--xb-primary); color: var(--xb-primary); }
.pf-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.pf-btn.primary {
  border: none;
  color: var(--xb-on-primary);
  background: var(--xb-brand-gradient);
}
.pf-btn.primary:hover { box-shadow: 0 0 16px rgba(var(--xb-primary-rgb), 0.4); color: var(--xb-on-primary); }
</style>
