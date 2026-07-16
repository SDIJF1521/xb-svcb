<template>
  <div class="layout">
    <ThemeBackground />
    <AppHeader />

    <main class="layout-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import AppHeader from '@/components/layout/AppHeader.vue'
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
</style>
