import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { api } from './api'
import { applyStoredLocaleBeforeMount, startDomLocalization, useI18n } from './i18n'
import { applyStoredThemeBeforeMount } from './stores/theme'

// 挂载前先应用持久化的主题，避免首屏闪烁
applyStoredThemeBeforeMount()
applyStoredLocaleBeforeMount()

/**
 * 原生打开 / 保存对话框由 Python 端弹出，它只知道界面语言才能本地化
 * 文件类型筛选与默认文件名，所以切换语言时同步一次。
 */
function syncDialogLocale(value: string) {
  void api.setUiLocale(value).catch(() => {})
}
syncDialogLocale(useI18n().locale.value)
watch(useI18n().locale, syncDialogLocale)

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
startDomLocalization()
