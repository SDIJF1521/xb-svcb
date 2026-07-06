import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { applyStoredThemeBeforeMount } from './stores/theme'

// 挂载前先应用持久化的主题，避免首屏闪烁
applyStoredThemeBeforeMount()

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
