<template>
  <div class="page">
    <div class="page-head">
      <div>
        <p class="eyebrow">// PLUGIN PAGE</p>
        <h1>{{ pageTitle }}</h1>
        <p class="page-sub">{{ pageDescription }}</p>
      </div>
      <el-button class="back-btn" type="primary" plain @click="router.push('/plugins')"><el-icon><ArrowLeft /></el-icon><span>返回插件中心</span></el-button>
    </div>

    <section v-if="plugin && plugin.enabled && enabled && hasFrontendEntry" class="plugin-frame glass">
      <div v-if="frontendLoading" class="empty">正在载入插件页面…</div>
      <div v-else-if="frontendError" class="empty error">{{ frontendError }}</div>
      <iframe
        v-else
        ref="iframeRef"
        title="插件沙箱页面"
        sandbox="allow-scripts"
        :srcdoc="iframeSrcdoc"
      />
    </section>

    <section v-else-if="plugin && page && plugin.enabled && enabled" class="plugin-form glass">
      <el-form label-position="top">
        <el-form-item v-for="field in page.fields" :key="field.id" :label="field.label || field.id">
          <el-switch v-if="field.type === 'switch'" v-model="values[field.id]" />
          <el-select v-else-if="field.type === 'select'" v-model="values[field.id]" style="width: 100%">
            <el-option
              v-for="option in field.options || []"
              :key="String(option.value)"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-input
            v-else-if="field.type === 'textarea'"
            :model-value="textValue(field.id)"
            type="textarea"
            :rows="4"
            :placeholder="field.placeholder"
            @update:model-value="setTextValue(field.id, $event)"
          />
          <el-input
            v-else
            :model-value="textValue(field.id)"
            :type="field.type === 'number' ? 'number' : 'text'"
            :placeholder="field.placeholder"
            @update:model-value="setTextValue(field.id, $event)"
          />
          <small v-if="field.help">{{ field.help }}</small>
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button v-for="action in actions" :key="action.id" type="primary" @click="run(action.id)">
          {{ action.label }}
        </el-button>
      </div>
    </section>

    <section v-else class="empty glass">此插件已关闭，或全局插件功能未开启。</section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRaw } from 'vue'
import 'element-plus/es/components/notification/style/css'
import { ElNotification } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { api, type PluginInfo } from '@/api'

defineOptions({ name: 'PluginDynamicPage' })

const route = useRoute()
const router = useRouter()
const plugin = ref<PluginInfo>()
const enabled = ref(false)
const values = ref<Record<string, string | number | boolean>>({})
const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeSrcdoc = ref('')
const frontendLoading = ref(false)
const frontendError = ref('')
const token = ref('')

const page = computed(() => plugin.value?.pages.find((item) => item.id === route.params.pageId))
const actions = computed(() => plugin.value?.actions.filter((action) => !page.value?.actions?.length || page.value.actions.includes(action.id)) || [])
const hasFrontendEntry = computed(() => Boolean(plugin.value?.frontend?.entry))
const pageTitle = computed(() => page.value?.title || plugin.value?.name || '插件页面')
const pageDescription = computed(() => page.value?.description || plugin.value?.description || '')

function textValue(id: string): string | number | undefined {
  const value = values.value[id]
  return typeof value === 'boolean' ? String(value) : value
}

function setTextValue(id: string, value: string | number | undefined) {
  values.value[id] = value ?? ''
}

const bridgeScript = `
(function () {
  var config = window.__XB_SVCB_PLUGIN__ || {};
  var seq = 0;
  var pending = {};
  window.addEventListener('message', function (event) {
    var data = event.data;
    if (!data || data.channel !== 'xb-svcb-plugin' || data.type !== 'response' || data.token !== config.token) return;
    var waiter = pending[data.id];
    if (!waiter) return;
    delete pending[data.id];
    if (data.ok) waiter.resolve(data.result);
    else waiter.reject(new Error(data.error || '插件宿主调用失败'));
  });
  function request(method, payload) {
    if (!config.token) return Promise.reject(new Error('当前页面不在 XB-SVCB 插件宿主中运行'));
    var id = 'req_' + Date.now() + '_' + (++seq);
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      parent.postMessage({ channel: 'xb-svcb-plugin', type: 'request', token: config.token, id: id, method: method, payload: payload || {} }, '*');
    });
  }
  window.XBSVCB = {
    getContext: function () { return request('getContext'); },
    runAction: function (actionId, values) { return request('runAction', { actionId: actionId, values: values || {} }); },
    createWork: function (payload) { return request('createWork', { payload: payload || {} }); },
    assetData: function (path) { return request('assetData', { path: path }); },
    assetUrl: function (path) { return request('assetData', { path: path }).then(function (result) { return result.data; }); },
    notify: function (message, type) { return request('notify', { message: message, type: type || 'success' }); }
  };
  window.dispatchEvent(new CustomEvent('xb-svcb-ready', { detail: window.XBSVCB }));
})();`

function makeToken() {
  return `xb_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

function injectBridge(html: string) {
  const config = `<script>window.__XB_SVCB_PLUGIN__=${JSON.stringify({ token: token.value })};<\/script>`
  const bridge = `<script>${bridgeScript}<\/script>`
  const injection = `${config}${bridge}`
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head([^>]*)>/i, `<head$1>${injection}`)
  return `<!doctype html><html><head>${injection}</head><body>${html}</body></html>`
}

async function load() {
  const [status, plugins] = await Promise.all([api.getPluginStatus(), api.listPlugins()])
  enabled.value = status.enabled
  plugin.value = plugins.find((item) => item.id === route.params.pluginId)
  values.value = {}
  if (hasFrontendEntry.value) {
    await loadFrontend()
    return
  }
  for (const field of page.value?.fields || []) {
    values.value[field.id] = field.default ?? (field.type === 'switch' ? false : '')
  }
}

async function loadFrontend() {
  if (!plugin.value) return
  frontendLoading.value = true
  frontendError.value = ''
  token.value = makeToken()
  const result = await api.getPluginFrontendDocument(plugin.value.id)
  frontendLoading.value = false
  if (!result.ok || !result.html) {
    frontendError.value = result.error || '插件页面加载失败。'
    iframeSrcdoc.value = ''
    return
  }
  iframeSrcdoc.value = injectBridge(result.html)
}

async function run(actionId: string) {
  if (!plugin.value) return
  const result = await api.runPluginAction(plugin.value.id, actionId, values.value)
  if (!result.ok) {
    notify('error', result.error || '插件操作失败')
    return
  }
  if (result.type === 'create_work' && result.payload) {
    const work = await api.createWork(result.payload)
    notify('success', `已创建翻唱任务：${work.title}`)
    router.push('/works')
  } else {
    notify('success', result.message || '插件操作已完成')
  }
}

function notify(type: unknown, message: unknown) {
  const next = type === 'error' || type === 'warning' || type === 'info' ? type : 'success'
  const titles = { success: '操作完成', warning: '需要注意', info: '提示', error: '操作失败' }
  const text = String(message || '插件操作已完成')
  ElNotification({
    type: next,
    title: titles[next],
    message: text,
    position: 'top-right',
    customClass: 'xb-notification-center',
    duration: next === 'error' ? 4200 : 2600,
    showClose: true,
  })
}

async function handlePluginRequest(event: MessageEvent) {
  if (!iframeRef.value || event.source !== iframeRef.value.contentWindow) return
  const message = event.data
  if (!message || message.channel !== 'xb-svcb-plugin' || message.type !== 'request' || message.token !== token.value) return
  try {
    const result = await dispatchPluginRequest(String(message.method || ''), message.payload || {})
    postPluginResponse(message.id, true, result)
  } catch (error) {
    postPluginResponse(message.id, false, undefined, error instanceof Error ? error.message : String(error))
  }
}

function cloneForPostMessage(value: unknown) {
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(toRaw(value)))
}

async function dispatchPluginRequest(method: string, payload: Record<string, unknown>) {
  if (!plugin.value) throw new Error('插件未加载')
  if (method === 'getContext') return {
    plugin: cloneForPostMessage(plugin.value),
    page: cloneForPostMessage(page.value),
    theme: localStorage.getItem('xb-theme') || '',
  }
  if (method === 'runAction') {
    const actionId = String(payload.actionId || '')
    const result = await api.runPluginAction(plugin.value.id, actionId, (payload.values as Record<string, unknown>) || {})
    if (!result.ok) throw new Error(result.error || '插件动作执行失败')
    if (result.type === 'create_work' && result.payload) {
      const work = await api.createWork(result.payload)
      notify('success', `已创建翻唱任务：${work.title}`)
      return { ...result, work }
    }
    if (result.message) notify('success', result.message)
    return result
  }
  if (method === 'createWork') {
    const work = await api.createWork((payload.payload as Record<string, unknown>) || {})
    notify('success', `已创建翻唱任务：${work.title}`)
    return work
  }
  if (method === 'assetData') {
    const result = await api.getPluginFrontendAssetData(plugin.value.id, String(payload.path || ''))
    if (!result.ok) throw new Error(result.error || '插件资源读取失败')
    return result
  }
  if (method === 'notify') {
    notify(payload.type, payload.message)
    return true
  }
  throw new Error(`不支持的插件宿主方法：${method}`)
}

function postPluginResponse(id: string, ok: boolean, result?: unknown, error?: string) {
  iframeRef.value?.contentWindow?.postMessage({
    channel: 'xb-svcb-plugin',
    type: 'response',
    token: token.value,
    id,
    ok,
    result: cloneForPostMessage(result),
    error,
  }, '*')
}

onMounted(() => {
  window.addEventListener('message', handlePluginRequest)
  void load()
})
onBeforeUnmount(() => window.removeEventListener('message', handlePluginRequest))
</script>

<style scoped>
.page { width: min(1680px, calc(100% - 56px)); max-width: none; margin: 0 auto; padding: 30px 0 64px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
.eyebrow { color: var(--xb-primary); margin: 0 0 6px; font-size: 12px; }
.page-head h1 { margin: 0 0 6px; }
.page-sub, small { color: var(--xb-muted); }
.glass { background: var(--xb-panel); border: 1px solid var(--xb-border); border-radius: 8px; }
.plugin-form { padding: 24px; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; }
.empty { padding: 42px; text-align: center; color: var(--xb-muted); }
.empty.error { color: var(--xb-danger); }
.back-btn { min-height: 40px; border-color: rgba(var(--xb-primary-rgb), .36); color: var(--xb-primary); background: rgba(var(--xb-primary-rgb), .08); font-weight: 700; }
.back-btn:hover { border-color: rgba(var(--xb-primary-rgb), .62); color: var(--xb-on-primary); background: var(--xb-brand-gradient); }
.back-btn :deep(.el-icon) { margin-right: 6px; }
.plugin-frame { min-height: min(980px, calc(100dvh - 245px)); overflow: hidden; }
.plugin-frame iframe { display: block; width: 100%; height: min(980px, calc(100dvh - 245px)); min-height: 720px; border: 0; background: transparent; }
small { display: block; padding-top: 5px; }
@media (max-width: 720px) {
  .page { width: calc(100% - 28px); padding: 22px 0 48px; }
  .page-head { align-items: stretch; flex-direction: column; }
  .plugin-frame, .plugin-frame iframe { height: calc(100dvh - 220px); min-height: 560px; }
}
</style>
