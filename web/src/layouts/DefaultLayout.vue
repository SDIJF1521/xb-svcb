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
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import FirstUseGuide from '@/components/onboarding/FirstUseGuide.vue'
import ThemeBackground from '@/components/theme/ThemeBackground.vue'
import { useNotificationsStore } from '@/stores/notifications'

defineOptions({ name: 'DefaultLayout' })

const notifications = useNotificationsStore()
onMounted(() => notifications.start())
onUnmounted(() => notifications.stop())
</script>

<style scoped>
.layout {
  position: relative;
  min-height: 100vh;
  overflow-x: hidden;
}
.layout-main {
  position: relative;
  z-index: 1;
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
