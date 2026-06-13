<template>
  <div class="layout">
    <!-- 全局背景装饰 -->
    <div class="bg-decor">
      <div class="grid-floor"></div>
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>

    <AppHeader />

    <main class="layout-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import AppHeader from '@/components/layout/AppHeader.vue'

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
.bg-decor {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}
.grid-floor {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 240, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 240, 255, 0.06) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: radial-gradient(ellipse 80% 55% at 50% 0%, #000 30%, transparent 100%);
}
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(110px);
  opacity: 0.35;
}
.orb-1 {
  width: 520px; height: 520px;
  background: #00f0ff;
  top: -180px; left: -120px;
}
.orb-2 {
  width: 440px; height: 440px;
  background: #ff2e88;
  top: 180px; right: -160px;
}
.orb-3 {
  width: 480px; height: 480px;
  background: #2f6bff;
  bottom: -220px; left: 40%;
  opacity: 0.28;
}
</style>
