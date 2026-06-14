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

        <!-- 主题切换 -->
        <button
          class="theme-toggle"
          :class="theme"
          :title="`当前：${themeLabel}（点击切换主题）`"
          @click="themeStore.toggle()"
        >
          <span class="theme-knob">
            <el-icon><component :is="theme === 'anime' ? Sunny : Moon" /></el-icon>
          </span>
          <span class="theme-name">{{ themeLabel }}</span>
        </button>

        <!-- 消息通知 -->
        <div ref="notifWrap" class="menu-wrap">
          <button
            class="icon-btn"
            :class="{ active: openMenu === 'notif' }"
            title="消息"
            @click="toggleMenu('notif')"
          >
            <el-icon><Bell /></el-icon>
            <span v-if="hasUnread" class="dot"></span>
          </button>
          <transition name="pop">
            <div v-if="openMenu === 'notif'" class="popover notif-pop">
              <div class="pop-head">
                <span>消息通知</span>
                <button v-if="notifications.length" class="pop-link" @click="markAllRead">
                  全部已读
                </button>
              </div>
              <div v-if="notifications.length" class="notif-list">
                <button
                  v-for="n in notifications"
                  :key="n.id"
                  class="notif-item"
                  @click="onNotifClick(n)"
                >
                  <span class="notif-dot" :class="n.tone"></span>
                  <span class="notif-body">
                    <span class="notif-title">{{ n.title }}</span>
                    <span class="notif-text">{{ n.text }}</span>
                  </span>
                  <span class="notif-time">{{ n.time }}</span>
                </button>
              </div>
              <div v-else class="pop-empty">
                <el-icon><Bell /></el-icon>
                <span>暂无消息</span>
              </div>
            </div>
          </transition>
        </div>

        <!-- 用户头像 / 资料 -->
        <div ref="profileWrap" class="menu-wrap">
          <button class="avatar" :title="profile.nickname" @click="toggleMenu('profile')">
            <img v-if="profile.avatar" :src="profile.avatar" alt="头像" />
            <span v-else>{{ profile.initial }}</span>
          </button>
          <transition name="pop">
            <div v-if="openMenu === 'profile'" class="popover profile-pop">
              <div class="profile-head">
                <div class="avatar lg">
                  <img v-if="profile.avatar" :src="profile.avatar" alt="头像" />
                  <span v-else>{{ profile.initial }}</span>
                </div>
                <input
                  v-model="nameDraft"
                  class="name-input"
                  maxlength="16"
                  placeholder="昵称"
                  @change="saveName"
                  @keyup.enter="saveName"
                />
              </div>
              <div class="profile-actions">
                <button class="pf-btn primary" @click="pickAvatar">
                  <el-icon><Picture /></el-icon><span>更换头像</span>
                </button>
                <button class="pf-btn" :disabled="!profile.avatar" @click="profile.clearAvatar()">
                  恢复默认
                </button>
              </div>
              <input
                ref="fileInput"
                type="file"
                accept="image/*"
                hidden
                @change="onAvatarFile"
              />
            </div>
          </transition>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { Headset, Search, Bell, HomeFilled, Microphone, FolderOpened, Files, Sunny, Moon, Picture } from '@element-plus/icons-vue'
import { useSystemStore } from '@/stores/system'
import { useWorksStore } from '@/stores/works'
import { useProfileStore } from '@/stores/profile'
import { useThemeStore, THEMES } from '@/stores/theme'

defineOptions({ name: 'AppHeader' })

const router = useRouter()

const themeStore = useThemeStore()
const { theme } = storeToRefs(themeStore)
const themeLabel = computed(() => THEMES.find((t) => t.value === theme.value)?.label ?? '主题')

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

/* ----- 弹出菜单（消息 / 资料）----- */
type MenuName = 'none' | 'notif' | 'profile'
const openMenu = ref<MenuName>('none')
const notifWrap = ref<HTMLElement>()
const profileWrap = ref<HTMLElement>()

function toggleMenu(which: Exclude<MenuName, 'none'>) {
  openMenu.value = openMenu.value === which ? 'none' : which
  if (openMenu.value === 'notif') markAllRead()
  if (openMenu.value === 'profile') nameDraft.value = profile.nickname
}

function onDocClick(e: MouseEvent) {
  const t = e.target as Node
  if (notifWrap.value?.contains(t) || profileWrap.value?.contains(t)) return
  openMenu.value = 'none'
}

/* ----- 消息通知（由作品与环境状态派生）----- */
interface Notif {
  id: string
  title: string
  text: string
  time: string
  tone: 'done' | 'failed' | 'running' | 'queue' | 'warn'
  to: string
}

const worksStore = useWorksStore()
const { works } = storeToRefs(worksStore)

const notifications = computed<Notif[]>(() => {
  const items: Notif[] = []
  if (loaded.value && !allReady.value) {
    items.push({
      id: 'env',
      title: '运行环境降级',
      text: '部分集成工具不可用，点击查看',
      time: '',
      tone: 'warn',
      to: '/',
    })
  }
  for (const w of works.value.slice(0, 8)) {
    let text = '排队中'
    let tone: Notif['tone'] = 'queue'
    if (w.status === 'done') {
      text = '翻唱完成，可试听 / 导出'
      tone = 'done'
    } else if (w.status === 'failed') {
      text = w.error ? `任务失败：${w.error}` : '任务失败，点击查看日志'
      tone = 'failed'
    } else if (w.status === 'running') {
      text = `处理中 ${w.progress || 0}%`
      tone = 'running'
    }
    items.push({ id: w.id, title: w.title, text, time: w.time || '', tone, to: '/works' })
  }
  return items
})

const NOTIF_KEY = 'xb-notif-seen'
const seenSig = ref<string>(localStorage.getItem(NOTIF_KEY) || '')
const currentSig = computed(() => notifications.value.map((n) => `${n.id}:${n.tone}`).join('|'))
const hasUnread = computed(() => currentSig.value !== '' && currentSig.value !== seenSig.value)

function markAllRead() {
  seenSig.value = currentSig.value
  try {
    localStorage.setItem(NOTIF_KEY, seenSig.value)
  } catch {
    /* ignore */
  }
}

function onNotifClick(n: Notif) {
  openMenu.value = 'none'
  router.push(n.to)
}

/* ----- 用户资料 / 头像 ----- */
const profile = useProfileStore()
const fileInput = ref<HTMLInputElement>()
const nameDraft = ref(profile.nickname)

function saveName() {
  profile.setNickname(nameDraft.value.trim() || '创作者')
  nameDraft.value = profile.nickname
}

function pickAvatar() {
  fileInput.value?.click()
}

function onAvatarFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const img = new Image()
    img.onload = () => {
      const size = 160
      const canvas = document.createElement('canvas')
      canvas.width = size
      canvas.height = size
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      const scale = Math.max(size / img.width, size / img.height)
      const w = img.width * scale
      const h = img.height * scale
      ctx.drawImage(img, (size - w) / 2, (size - h) / 2, w, h)
      profile.setAvatar(canvas.toDataURL('image/png'))
    }
    img.src = reader.result as string
  }
  reader.readAsDataURL(file)
}

onMounted(() => {
  if (!loaded.value) systemStore.load()
  worksStore.ensureLoaded()
  document.addEventListener('click', onDocClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(var(--xb-bg-rgb), 0.82);
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
  color: var(--xb-on-primary);
  box-shadow: 0 0 20px rgba(var(--xb-primary-rgb), 0.5);
}
.brand-text {
  font-size: 19px;
  font-weight: 600;
  letter-spacing: 1px;
}
.brand-text b {
  background: var(--xb-brand-gradient);
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
  background: rgba(var(--xb-primary-rgb), 0.06);
}
.nav-link.active {
  color: var(--xb-primary);
  background: rgba(var(--xb-primary-rgb), 0.1);
  box-shadow: inset 0 0 0 1px rgba(var(--xb-primary-rgb), 0.3);
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
  background: rgba(var(--xb-fill-rgb), 0.04);
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
  background: rgba(var(--xb-success-rgb), 0.1);
  border: 1px solid rgba(var(--xb-success-rgb), 0.3);
  color: var(--xb-success);
  font-weight: 600;
  font-size: 13px;
}
.env-status.degraded {
  background: rgba(var(--xb-warn-rgb), 0.1);
  border-color: rgba(var(--xb-warn-rgb), 0.3);
  color: var(--xb-warn);
}
.env-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--xb-success);
  box-shadow: 0 0 8px var(--xb-success);
  animation: env-pulse 1.8s infinite;
}
.env-status.degraded .env-dot {
  background: var(--xb-warn);
  box-shadow: 0 0 8px var(--xb-warn);
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
  background: rgba(var(--xb-fill-rgb), 0.04);
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

.icon-btn.active { color: var(--xb-primary); border-color: var(--xb-primary); }

.avatar {
  width: 38px; height: 38px;
  border: none;
  padding: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 15px;
  color: var(--xb-on-primary);
  background: linear-gradient(135deg, var(--xb-primary), var(--xb-accent));
  cursor: pointer;
  overflow: hidden;
  box-shadow: 0 0 16px rgba(var(--xb-primary-rgb), 0.4);
  transition: transform 0.2s;
}
.avatar:hover { transform: scale(1.06); }
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.avatar.lg {
  width: 56px; height: 56px;
  font-size: 22px;
  cursor: default;
}
.avatar.lg:hover { transform: none; }

/* ----- 弹出菜单容器与气泡 ----- */
.menu-wrap { position: relative; }
.popover {
  position: absolute;
  top: calc(100% + 12px);
  right: 0;
  width: 320px;
  background: var(--xb-bg-2);
  border: 1px solid var(--xb-border);
  border-radius: 16px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(var(--xb-primary-rgb), 0.05);
  backdrop-filter: blur(20px);
  overflow: hidden;
  z-index: 80;
}
.pop-enter-active, .pop-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-6px); }

.pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  font-weight: 700;
  font-size: 14px;
  border-bottom: 1px solid var(--xb-border);
}
.pop-link {
  border: none;
  background: none;
  color: var(--xb-primary);
  font-size: 12.5px;
  cursor: pointer;
}
.pop-link:hover { text-decoration: underline; }
.pop-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 34px 16px;
  color: var(--xb-muted);
  font-size: 13px;
}
.pop-empty .el-icon { font-size: 26px; opacity: 0.5; }

/* ----- 通知列表 ----- */
.notif-list { max-height: 380px; overflow-y: auto; padding: 6px; }
.notif-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  background: none;
  border-radius: 10px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}
.notif-item:hover { background: rgba(var(--xb-fill-rgb), 0.06); }
.notif-dot {
  width: 8px; height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.notif-dot.done { background: var(--xb-success); box-shadow: 0 0 8px var(--xb-success); }
.notif-dot.failed { background: var(--xb-accent); box-shadow: 0 0 8px var(--xb-accent); }
.notif-dot.running { background: var(--xb-primary); box-shadow: 0 0 8px var(--xb-primary); }
.notif-dot.queue { background: var(--xb-muted); }
.notif-dot.warn { background: var(--xb-warn); box-shadow: 0 0 8px var(--xb-warn); }
.notif-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.notif-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--xb-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.notif-text {
  font-size: 12px;
  color: var(--xb-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.notif-time { font-size: 11px; color: var(--xb-muted); flex-shrink: 0; }

/* ----- 资料卡 ----- */
.profile-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 16px;
  border-bottom: 1px solid var(--xb-border);
}
.name-input {
  flex: 1;
  min-width: 0;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.05);
  color: var(--xb-text);
  font-size: 14px;
  font-weight: 600;
  outline: none;
}
.name-input:focus { border-color: var(--xb-primary); }
.profile-actions { display: flex; gap: 10px; padding: 14px 16px; }
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

/* 主题切换按钮 */
.theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 14px 0 6px;
  border-radius: 999px;
  border: 1px solid var(--xb-border);
  background: rgba(var(--xb-fill-rgb), 0.04);
  color: var(--xb-text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.25s;
}
.theme-toggle:hover {
  border-color: var(--xb-primary);
  box-shadow: 0 0 16px rgba(var(--xb-primary-rgb), 0.25);
}
.theme-knob {
  width: 28px; height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 15px;
  color: var(--xb-on-primary);
  background: var(--xb-brand-gradient);
  box-shadow: 0 0 12px rgba(var(--xb-primary-rgb), 0.45);
  transition: transform 0.4s ease;
}
.theme-toggle.anime .theme-knob { transform: rotate(360deg); }
.theme-name { letter-spacing: 0.5px; }

@media (max-width: 1080px) {
  .search { width: 150px; }
}
@media (max-width: 860px) {
  .nav-link span { display: none; }
  .search, .env-status, .theme-name { display: none; }
  .theme-toggle { padding: 0 5px; }
}
</style>
