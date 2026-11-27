<template>
  <div class="hifi-panel">
    <div class="hifi-head">
      <div>
        <p class="eyebrow">HIFI OUTPUT</p>
        <h3>高保真输出</h3>
      </div>
      <span class="quality-badge" :class="{ lossless: player.isLossless }">
        {{ player.currentQuality || '等待音源' }}
      </span>
    </div>

    <div class="hifi-info">
      <div class="hifi-line">
        <span>当前音源</span>
        <b>{{ player.currentDetail || '暂无技术信息' }}</b>
      </div>
      <div class="hifi-line">
        <span>输出方式</span>
        <b>{{ player.eqEnabled ? 'Web Audio · 均衡器' : '母带直通 · 未处理' }}</b>
      </div>
    </div>

    <p class="hifi-note">
      直通时音频按源文件采样直接送往系统输出，不做转码、增益或音效处理；开启均衡器会改变声音，关闭后立即恢复直通。
    </p>

    <div class="hifi-switch">
      <div>
        <strong>10 段均衡器</strong>
        <small>31 Hz – 16 kHz · ±12 dB</small>
      </div>
      <el-switch
        :model-value="player.eqEnabled"
        :disabled="!player.eqSupported"
        @update:model-value="onToggle"
      />
    </div>

    <p v-if="!player.eqSupported" class="hifi-warn">
      当前音源不支持跨域读取，只能直通播放；如需要调音，请播放本地作品或已下载歌曲。
    </p>

    <template v-if="player.eqEnabled">
      <div class="eq-presets">
        <button
          v-for="preset in EQ_PRESETS"
          :key="preset.id"
          class="eq-preset"
          @click="player.applyEqPreset(preset.id)"
        >
          {{ preset.label }}
        </button>
        <button class="eq-preset reset" @click="player.resetEq()">重置</button>
      </div>
      <div class="eq-bands">
        <div v-for="(frequency, index) in EQ_FREQUENCIES" :key="frequency" class="eq-band">
          <span class="eq-value">{{ signedGain(index) }}</span>
          <input
            type="range"
            min="-12"
            max="12"
            step="1"
            :value="gainAt(index)"
            :aria-label="`${frequency} Hz`"
            @input="onGain(index, $event)"
          />
          <span class="eq-freq">{{ frequency >= 1000 ? `${frequency / 1000}k` : frequency }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { EQ_FREQUENCIES, EQ_PRESETS, usePlayerStore } from '@/stores/player'

defineOptions({ name: 'HiFiPanel' })

const player = usePlayerStore()

function gainAt(index: number): number {
  return player.eqGains[index] ?? 0
}

function signedGain(index: number): string {
  const gain = gainAt(index)
  return `${gain > 0 ? '+' : ''}${gain}`
}

function onToggle(value: string | number | boolean) {
  player.setEqEnabled(Boolean(value))
}

function onGain(index: number, event: Event) {
  const target = event.target as HTMLInputElement
  player.setEqGain(index, Number(target.value))
}
</script>

<style scoped>
.hifi-panel {
  width: 100%;
  padding: 4px 2px 2px;
  color: var(--xb-text);
}
.hifi-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.eyebrow {
  margin: 0 0 5px;
  color: var(--xb-primary);
  font: 700 10px/1 ui-monospace, monospace;
  letter-spacing: 1.4px;
}
.hifi-head h3 {
  margin: 0;
  font-size: 18px;
}
.quality-badge {
  flex: 0 0 auto;
  padding: 4px 9px;
  border: 1px solid var(--xb-border);
  border-radius: 999px;
  color: var(--xb-muted);
  font-size: 11px;
  font-weight: 700;
}
.quality-badge.lossless {
  color: var(--xb-success);
  border-color: rgba(var(--xb-success-rgb), 0.4);
  background: rgba(var(--xb-success-rgb), 0.1);
}
.hifi-info {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 14px 0 10px;
  padding: 10px 12px;
  border: 1px solid var(--xb-border);
  border-radius: 9px;
  background: rgba(var(--xb-fill-rgb), 0.03);
}
.hifi-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
}
.hifi-line span {
  color: var(--xb-muted);
}
.hifi-line b {
  text-align: right;
  font-weight: 600;
}
.hifi-note {
  margin: 0 0 12px;
  color: var(--xb-muted);
  font-size: 11px;
  line-height: 1.6;
}
.hifi-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-top: 1px solid var(--xb-border);
}
.hifi-switch strong {
  display: block;
  font-size: 13px;
}
.hifi-switch small {
  color: var(--xb-muted);
  font-size: 10px;
}
.hifi-warn {
  margin: 8px 0 0;
  color: var(--xb-warn);
  font-size: 11px;
  line-height: 1.5;
}
.eq-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 12px 0 10px;
}
.eq-preset {
  padding: 5px 10px;
  border: 1px solid var(--xb-border);
  border-radius: 999px;
  background: transparent;
  color: var(--xb-muted);
  font-size: 11px;
  cursor: pointer;
}
.eq-preset:hover {
  color: var(--xb-primary);
  border-color: rgba(var(--xb-primary-rgb), 0.45);
}
.eq-preset.reset {
  margin-left: auto;
}
.eq-bands {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 2px;
  padding: 6px 2px 0;
}
.eq-band {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
}
.eq-band input {
  writing-mode: vertical-lr;
  direction: rtl;
  width: 18px;
  height: 108px;
  accent-color: var(--xb-primary);
  cursor: pointer;
}
.eq-value {
  color: var(--xb-primary);
  font: 10px ui-monospace, monospace;
  min-height: 12px;
}
.eq-freq {
  color: var(--xb-muted);
  font: 9px ui-monospace, monospace;
}
</style>
