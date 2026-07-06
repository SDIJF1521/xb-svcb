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
import AppHeader from '@/components/layout/AppHeader.vue'
import ThemeBackground from '@/components/theme/ThemeBackground.vue'

defineOptions({ name: 'DefaultLayout' })
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
