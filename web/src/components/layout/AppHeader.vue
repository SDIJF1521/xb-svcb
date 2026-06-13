<template>
  <header class="app-header">
    <div class="header-inner">
      <!-- 品牌 -->
      <router-link class="brand" to="/">
        <span class="logo"><el-icon><Headset /></el-icon></span>
        <span class="brand-text">XB-<b>SVCB</b></span>
      </router-link>

      <!-- 主导航 -->
      <nav class="nav-links">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          exact-active-class="active"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <!-- 右侧操作 -->
      <div class="header-actions">
        <div class="search">
          <el-icon><Search /></el-icon>
          <input type="text" placeholder="搜索作品、模型…" />
        </div>

        <div class="env-status" :class="{ degraded: !allReady }" :title="envTitle">
          <span class="env-dot"></span>
          <span>{{ allReady ? '环境就绪' : '降级模式' }}</span>
        </div>

        <button class="icon-btn" title="消息">
          <el-icon><Bell /></el-icon>
          <span class="dot"></span>
        </button>

        <div class="user">
          <div class="avatar">L</div>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { Headset, Search, Bell, HomeFilled, Microphone, FolderOpened, Files } from '@element-plus/icons-vue'
import { useSystemStore } from '@/stores/system'

defineOptions({ name: 'AppHeader' })

const navItems = [
  { label: '首页', to: '/', icon: HomeFilled },
  { label: 'AI 翻唱', to: '/create', icon: Microphone },
  { label: '我的模型', to: '/models', icon: FolderOpened },
  { label: '我的作品', to: '/works', icon: Files },
]

const systemStore = useSystemStore()
const { tools, loaded } = storeToRefs(systemStore)

const allReady = computed(() => loaded.value && tools.value.every((t) => t.ok))
const envTitle = computed(() =>
  tools.value.map((t) => `${t.name}: ${t.status}`).join('  |  ') || '正在检测集成工具…',
)

onMounted(() => {
  if (!loaded.value) systemStore.load()
})
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(5, 6, 13, 0.82);
  backdrop-filter: blur(18px);
  border-bottom: 1px solid var(--xb-border);
}
.header-inner {
  max-width: 1320px;
  margin: 0 auto;
  height: 64px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 28px;
}

/* 品牌 */
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--xb-text);
  flex-shrink: 0;
}
.logo {
  width: 36px; height: 36px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-primary-2));
  font-size: 19px;
  color: #05060d;
  box-shadow: 0 0 20px rgba(0, 240, 255, 0.5);
}
.brand-text {
  font-size: 19px;
  font-weight: 600;
  letter-spacing: 1px;
}
.brand-text b {
  background: linear-gradient(135deg, #00f0ff, #2f6bff);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

/* 主导航 */
.nav-links {
  display: flex;
  align-items: center;
  gap: 6px;
}
.nav-link {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 14px;
  border-radius: 9px;
  color: var(--xb-muted);
  text-decoration: none;
  font-size: 14.5px;
  font-weight: 500;
  transition: all 0.2s;
}
.nav-link:hover {
  color: var(--xb-text);
  background: rgba(0, 240, 255, 0.06);
}
.nav-link.active {
  color: var(--xb-primary);
  background: rgba(0, 240, 255, 0.1);
  box-shadow: inset 0 0 0 1px rgba(0, 240, 255, 0.3);
}

/* 右侧 */
.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--xb-border);
  color: var(--xb-muted);
  width: 220px;
}
.search input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--xb-text);
  font-size: 14px;
  width: 100%;
}
.search input::placeholder { color: var(--xb-muted); }
.search:focus-within { border-color: var(--xb-primary); }

.env-status {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  border-radius: 999px;
  background: rgba(25, 245, 154, 0.1);
  border: 1px solid rgba(25, 245, 154, 0.3);
  color: #19f59a;
  font-weight: 600;
  font-size: 13px;
}
.env-status.degraded {
  background: rgba(255, 174, 0, 0.1);
  border-color: rgba(255, 174, 0, 0.3);
  color: #ffae00;
}
.env-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #19f59a;
  box-shadow: 0 0 8px #19f59a;
  animation: env-pulse 1.8s infinite;
}
.env-status.degraded .env-dot {
  background: #ffae00;
  box-shadow: 0 0 8px #ffae00;
}
@keyframes env-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.icon-btn {
  position: relative;
  width: 38px; height: 38px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: rgba(255, 255, 255, 0.04);
  color: var(--xb-muted);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 18px;
  transition: all 0.2s;
}
.icon-btn:hover { color: var(--xb-primary); border-color: var(--xb-primary); }
.icon-btn .dot {
  position: absolute;
  top: 8px; right: 9px;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--xb-accent);
  box-shadow: 0 0 8px var(--xb-accent);
}

.avatar {
  width: 38px; height: 38px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-weight: 800;
  color: #05060d;
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent));
  cursor: pointer;
  box-shadow: 0 0 16px rgba(0, 240, 255, 0.4);
}

@media (max-width: 1080px) {
  .search { width: 150px; }
}
@media (max-width: 860px) {
  .nav-link span { display: none; }
  .search, .env-status { display: none; }
}
</style>
