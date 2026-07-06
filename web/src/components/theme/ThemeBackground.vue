<template>
  <div class="bg-decor">
    <div class="custom-bg-image"></div>
    <div class="grid-floor"></div>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>
    <div class="custom-particles">
      <span
        v-for="n in customParticleCount"
        :key="`custom-${n}`"
        class="custom-particle"
        :style="customParticleStyle(n)"
      ></span>
    </div>
    <div class="petals">
      <span v-for="n in 9" :key="n" class="petal" :style="petalStyle(n)"></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useThemeStore } from '@/stores/theme'

defineOptions({ name: 'ThemeBackground' })

const themeStore = useThemeStore()
const { customTheme } = storeToRefs(themeStore)

const customParticleCount = computed(() =>
  customTheme.value.particles ? Math.round(customTheme.value.particleDensity) : 0,
)

function customParticleStyle(n: number) {
  const left = (n * 17 + 9) % 100
  const top = (n * 29 + 13) % 100
  const delay = (n * 0.73) % 8
  const duration = 8 + ((n * 1.9) % 9)
  const scale = 0.72 + ((n * 11) % 60) / 100
  const tone = n % 3 === 0 ? 'var(--xb-accent)' : n % 3 === 1 ? 'var(--xb-primary)' : 'var(--xb-primary-2)'
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `calc(var(--xb-particle-size) * ${scale})`,
    height: `calc(var(--xb-particle-size) * ${scale})`,
    animationDelay: `-${delay}s`,
    animationDuration: `${duration}s`,
    '--particle-color': tone,
  }
}

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
.bg-decor {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}
.custom-bg-image {
  position: absolute;
  inset: 0;
  opacity: 0;
  background-image:
    linear-gradient(rgba(var(--xb-bg-rgb), var(--xb-image-overlay)), rgba(var(--xb-bg-rgb), var(--xb-image-overlay))),
    var(--xb-custom-bg-image);
  background-size: cover;
  background-position: center;
  transform: scale(1.02);
  transition: opacity 0.25s ease;
}
html[data-theme='custom'] .custom-bg-image {
  opacity: var(--xb-custom-image-opacity);
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
.custom-particles {
  position: absolute;
  inset: 0;
}
.custom-particle {
  display: none;
}
html[data-theme='custom'] .custom-particle {
  display: block;
  position: absolute;
  border-radius: 999px;
  background:
    radial-gradient(circle, color-mix(in srgb, var(--particle-color) 95%, #fff 5%) 0%, var(--particle-color) 42%, transparent 72%);
  opacity: var(--xb-particle-opacity);
  box-shadow: 0 0 14px color-mix(in srgb, var(--particle-color) 70%, transparent);
  animation-name: custom-particle-drift;
  animation-timing-function: ease-in-out;
  animation-iteration-count: infinite;
}
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
html[data-theme='anime'] .grid-floor {
  mask-image: radial-gradient(ellipse 90% 60% at 50% 0%, #000 10%, transparent 90%);
}
@keyframes petal-fall {
  0% { transform: translateY(0) translateX(0) rotate(0deg); opacity: 0; }
  10% { opacity: 0.6; }
  90% { opacity: 0.6; }
  100% { transform: translateY(105vh) translateX(40px) rotate(320deg); opacity: 0; }
}
@keyframes custom-particle-drift {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); opacity: calc(var(--xb-particle-opacity) * 0.35); }
  35% { transform: translate3d(18px, -28px, 0) scale(1.3); opacity: var(--xb-particle-opacity); }
  70% { transform: translate3d(-16px, 22px, 0) scale(0.82); opacity: calc(var(--xb-particle-opacity) * 0.72); }
}
@media (prefers-reduced-motion: reduce) {
  html[data-theme='anime'] .petal { animation: none; display: none; }
  html[data-theme='custom'] .custom-particle { animation: none; }
}
</style>
