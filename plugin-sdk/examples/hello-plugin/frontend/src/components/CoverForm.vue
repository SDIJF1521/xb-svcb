<script setup lang="ts">
import { reactive, ref } from 'vue'

import { usePluginHost } from '@xb-svcb/plugin-sdk/vue'

const form = reactive({
  source_path: 'D:/Music/song.wav',
  model_id: 'model_xxx',
  title: '我的第一首翻唱',
  pitch: 0,
})
const output = ref('')
const { hosted, loading, error, runAction } = usePluginHost()

async function createCover() {
  if (!hosted.value) {
    output.value = '当前是浏览器开发预览；安装插件后可创建真实翻唱任务。'
    return
  }
  try {
    const result = await runAction('create', { ...form })
    output.value = JSON.stringify(result, null, 2)
  } catch {
    output.value = error.value?.message || '创建翻唱失败'
  }
}
</script>

<template>
  <section class="cover-form">
    <div class="form-grid">
      <label>源音频路径 <input v-model="form.source_path"></label>
      <label>模型 ID <input v-model="form.model_id"></label>
      <label>作品标题 <input v-model="form.title"></label>
      <label>升降调 <input v-model.number="form.pitch" type="number"></label>
    </div>
    <button type="button" :disabled="loading" @click="createCover">
      {{ loading ? '正在创建…' : '开始翻唱' }}
    </button>
    <pre v-if="output" aria-live="polite">{{ output }}</pre>
  </section>
</template>
