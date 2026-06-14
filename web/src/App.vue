<template>
  <router-view />
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
/* ============================================================
   主题系统：所有颜色走语义化变量，由 <html data-theme> 切换。
   两套主题：cyber（赛博霓虹·暗）/ anime（二次元·蓝粉·亮）
   ============================================================ */

/* —— 赛博主题（默认，也作为根回退） —— */
:root,
html[data-theme='cyber'] {
  --xb-bg: #05060d;
  --xb-bg-2: #080b16;
  --xb-bg-rgb: 5, 6, 13;
  --xb-panel: rgba(10, 20, 40, 0.45);
  --xb-border: rgba(0, 240, 255, 0.16);
  --xb-text: #e6f5ff;
  --xb-muted: #7c93b8;
  --xb-primary: #00f0ff;
  --xb-primary-2: #2f6bff;
  --xb-accent: #ff2e88;

  /* 语义扩展（供各页面统一引用） */
  --xb-on-primary: #05060d;        /* 主色/渐变之上的文字色 */
  --xb-primary-rgb: 0, 240, 255;
  --xb-secondary-rgb: 47, 107, 255;
  --xb-accent-rgb: 255, 46, 136;
  --xb-fill-rgb: 255, 255, 255;    /* 表面叠加基色 */
  --xb-success: #19f59a;
  --xb-success-rgb: 25, 245, 154;
  --xb-warn: #ffae00;
  --xb-warn-rgb: 255, 174, 0;

  --xb-hero-gradient: linear-gradient(120deg, #00f0ff 0%, #2f6bff 45%, #ff2e88 100%);
  --xb-brand-gradient: linear-gradient(135deg, #00f0ff, #2f6bff);
  --xb-scroll-track: #05060d;
  --xb-scroll-thumb: #14203a;
  --xb-scroll-thumb-hover: #1d2c4d;

  /* 装饰层 */
  --xb-deco-1: #00f0ff;
  --xb-deco-2: #ff2e88;
  --xb-deco-3: #2f6bff;
  --xb-grid-rgb: 0, 240, 255;
  --xb-grid-opacity: 0.06;
  --xb-orb-opacity: 0.35;

  --xb-font: 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif;
}

/* —— 二次元主题（蓝粉·亮） —— */
html[data-theme='anime'] {
  --xb-bg: #fdf3fb;
  --xb-bg-2: #eef3ff;
  --xb-bg-rgb: 253, 243, 251;
  --xb-panel: rgba(255, 255, 255, 0.72);
  --xb-border: rgba(126, 142, 232, 0.22);
  --xb-text: #4a3a63;
  --xb-muted: #a193bb;
  --xb-primary: #5b9cff;
  --xb-primary-2: #8a7bff;
  --xb-accent: #ff84bd;

  --xb-on-primary: #ffffff;
  --xb-primary-rgb: 91, 156, 255;
  --xb-secondary-rgb: 138, 123, 255;
  --xb-accent-rgb: 255, 132, 189;
  --xb-fill-rgb: 150, 150, 220;
  --xb-success: #2bbf8f;
  --xb-success-rgb: 43, 191, 143;
  --xb-warn: #ff9f43;
  --xb-warn-rgb: 255, 159, 67;

  --xb-hero-gradient: linear-gradient(120deg, #5b9cff 0%, #a07bff 45%, #ff84bd 100%);
  --xb-brand-gradient: linear-gradient(135deg, #5b9cff, #ff84bd);
  --xb-scroll-track: #f1e6f7;
  --xb-scroll-thumb: #d9c8ee;
  --xb-scroll-thumb-hover: #c3aee4;

  --xb-deco-1: #8ab6ff;
  --xb-deco-2: #ffb0d8;
  --xb-deco-3: #c0a8ff;
  --xb-grid-rgb: 150, 150, 220;
  --xb-grid-opacity: 0.05;
  --xb-orb-opacity: 0.5;

  --xb-font: 'Yuanti SC', 'YouYuan', 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif;
}

* {
  box-sizing: border-box;
}
html,
body {
  margin: 0;
  padding: 0;
  background: var(--xb-bg);
  color: var(--xb-text);
  font-family: var(--xb-font);
  transition: background 0.4s ease, color 0.4s ease;
}
#app {
  min-height: 100vh;
}
html {
  scroll-behavior: smooth;
}
::selection {
  background: rgba(var(--xb-primary-rgb), 0.35);
  color: #fff;
}
::-webkit-scrollbar {
  width: 10px;
}
::-webkit-scrollbar-track {
  background: var(--xb-scroll-track);
}
::-webkit-scrollbar-thumb {
  background: var(--xb-scroll-thumb);
  border-radius: 5px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--xb-scroll-thumb-hover);
}
</style>
