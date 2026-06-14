<template>
  <div class="layout">
    <!-- 全局背景装饰 -->
    <div class="bg-decor">
      <div class="grid-floor"></div>
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
      <!-- 二次元主题专属：漂浮花瓣/气泡 -->
      <div class="petals">
        <span v-for="n in 9" :key="n" class="petal" :style="petalStyle(n)"></span>
      </div>
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

function petalStyle(n: number) {
  const left = (n * 11 + 5) % 100
  const delay = (n * 1.7) % 9
  const duration = 9 + ((n * 1.3) % 7)
  const size = 8 + ((n * 3) % 10)
  return {
    left: `${left}%`,
    width: `${size}px`,
    height: `${size}px`,
    animationDelay: `-${delay}s`,
    animationDuration: `${duration}s`,
  }
}
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
    linear-gradient(rgba(var(--xb-grid-rgb), var(--xb-grid-opacity)) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--xb-grid-rgb), var(--xb-grid-opacity)) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: radial-gradient(ellipse 80% 55% at 50% 0%, #000 30%, transparent 100%);
}
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(110px);
  opacity: var(--xb-orb-opacity);
}
.orb-1 {
  width: 520px; height: 520px;
  background: var(--xb-deco-1);
  top: -180px; left: -120px;
}
.orb-2 {
  width: 440px; height: 440px;
  background: var(--xb-deco-2);
  top: 180px; right: -160px;
}
.orb-3 {
  width: 480px; height: 480px;
  background: var(--xb-deco-3);
  bottom: -220px; left: 40%;
  opacity: calc(var(--xb-orb-opacity) * 0.8);
}

/* —— 花瓣/气泡：仅二次元主题显示 —— */
.petals { position: absolute; inset: 0; }
.petal { display: none; }
html[data-theme='anime'] .petal {
  display: block;
  position: absolute;
  top: -40px;
  border-radius: 60% 40% 55% 45% / 55% 50% 50% 45%;
  background: linear-gradient(135deg, var(--xb-deco-2), var(--xb-deco-3));
  opacity: 0.55;
  animation-name: petal-fall;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}
/* 二次元主题：弱化科技网格，氛围更柔和 */
html[data-theme='anime'] .grid-floor {
  mask-image: radial-gradient(ellipse 90% 60% at 50% 0%, #000 10%, transparent 90%);
}
@keyframes petal-fall {
  0% { transform: translateY(0) translateX(0) rotate(0deg); opacity: 0; }
  10% { opacity: 0.6; }
  90% { opacity: 0.6; }
  100% { transform: translateY(105vh) translateX(40px) rotate(320deg); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  html[data-theme='anime'] .petal { animation: none; display: none; }
}
</style>
