<template>
  <div class="layout">
    <ThemeBackground />
    <AppHeader />
    <FirstUseGuide />

    <main class="layout-main">
      <router-view v-slot="{ Component, route }">
        <Transition name="page-slide" mode="out-in">
          <component :is="Component" :key="route.fullPath" />
        </Transition>
      </router-view>
    </main>

    <GlobalPlayer />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import FirstUseGuide from '@/components/onboarding/FirstUseGuide.vue'
import GlobalPlayer from '@/components/player/GlobalPlayer.vue'
import ThemeBackground from '@/components/theme/ThemeBackground.vue'
import { useNotificationsStore } from '@/stores/notifications'
import { usePlayerStore } from '@/stores/player'

defineOptions({ name: 'DefaultLayout' })

const notifications = useNotificationsStore()
const player = usePlayerStore()
onMounted(() => {
  notifications.start()
  // 恢复的持久化队列里可能残留应用关闭期间被删除的作品 / 下载素材。
  void player.reconcileLibrary()
})
onUnmounted(() => notifications.stop())
</script>

<style scoped>
.layout {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
}
.layout-main {
  position: relative;
  z-index: 1;
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.layout-main::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}
.page-slide-enter-active,
.page-slide-leave-active { transition: opacity .22s ease, transform .22s ease; }
.page-slide-enter-from { opacity: 0; transform: translateY(12px); }
.page-slide-leave-to { opacity: 0; transform: translateY(-8px); }
@media (prefers-reduced-motion: reduce) {
  .page-slide-enter-active,
  .page-slide-leave-active { transition: none; }
}
</style>
