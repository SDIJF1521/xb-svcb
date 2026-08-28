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
  --xb-custom-bg-image: none;
  --xb-custom-image-opacity: 0;
  --xb-image-overlay: 0.5;
  --xb-particle-opacity: 0;
  --xb-particle-size: 3.5px;

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
}

/* —— 自定义主题兜底；实际颜色由 theme store 写入内联 CSS 变量 —— */
html[data-theme='custom'] {
  --xb-bg: #fbfcff;
  --xb-bg-2: #eef7ff;
  --xb-bg-rgb: 251, 252, 255;
  --xb-panel: rgba(238, 247, 255, 0.72);
  --xb-border: rgba(79, 140, 255, 0.22);
  --xb-text: #223047;
  --xb-muted: #71809a;
  --xb-primary: #4f8cff;
  --xb-primary-2: #2fc7a1;
  --xb-accent: #ff7aa8;

  --xb-on-primary: #ffffff;
  --xb-primary-rgb: 79, 140, 255;
  --xb-secondary-rgb: 47, 199, 161;
  --xb-accent-rgb: 255, 122, 168;
  --xb-fill-rgb: 34, 48, 71;
  --xb-success: #21b981;
  --xb-success-rgb: 33, 185, 129;
  --xb-warn: #f3a13b;
  --xb-warn-rgb: 243, 161, 59;

  --xb-hero-gradient: linear-gradient(120deg, #4f8cff 0%, #2fc7a1 48%, #ff7aa8 100%);
  --xb-brand-gradient: linear-gradient(135deg, #4f8cff, #2fc7a1);
  --xb-scroll-track: #fbfcff;
  --xb-scroll-thumb: #eef7ff;
  --xb-scroll-thumb-hover: #71809a;

  --xb-deco-1: #4f8cff;
  --xb-deco-2: #ff7aa8;
  --xb-deco-3: #2fc7a1;
  --xb-grid-rgb: 79, 140, 255;
  --xb-grid-opacity: 0.045;
  --xb-orb-opacity: 0.42;
  --xb-custom-bg-image: none;
  --xb-custom-image-opacity: 0;
  --xb-image-overlay: 0.3;
  --xb-particle-opacity: 0.62;
  --xb-particle-size: 3.2px;
}

/* Element Plus 默认变量定义在 :root；使用更高优先级覆盖，避免控件回到白底默认主题。 */
html:root,
html[data-theme] {
  --el-color-primary: var(--xb-primary);
  --el-color-primary-rgb: var(--xb-primary-rgb);
  --el-color-primary-light-3: color-mix(in srgb, var(--xb-primary) 70%, #fff);
  --el-color-primary-light-5: color-mix(in srgb, var(--xb-primary) 55%, #fff);
  --el-color-primary-light-7: color-mix(in srgb, var(--xb-primary) 35%, #fff);
  --el-color-primary-light-8: color-mix(in srgb, var(--xb-primary) 22%, #fff);
  --el-color-primary-light-9: color-mix(in srgb, var(--xb-primary) 12%, var(--xb-bg-2));
  --el-color-primary-dark-2: color-mix(in srgb, var(--xb-primary) 78%, #000);
  --el-color-success: var(--xb-success);
  --el-color-success-rgb: var(--xb-success-rgb);
  --el-color-warning: var(--xb-warn);
  --el-color-warning-rgb: var(--xb-warn-rgb);
  --el-color-danger: var(--xb-accent);
  --el-color-danger-rgb: var(--xb-accent-rgb);
  --el-color-error: var(--xb-accent);
  --el-color-error-rgb: var(--xb-accent-rgb);
  --el-color-info: var(--xb-muted);
  --el-color-info-rgb: var(--xb-fill-rgb);
  --el-bg-color: var(--xb-bg);
  --el-bg-color-page: var(--xb-bg);
  --el-bg-color-overlay: var(--xb-bg-2);
  --el-text-color-primary: var(--xb-text);
  --el-text-color-regular: var(--xb-text);
  --el-text-color-secondary: var(--xb-muted);
  --el-text-color-placeholder: var(--xb-muted);
  --el-text-color-disabled: var(--xb-muted);
  --el-border-color: var(--xb-border);
  --el-border-color-light: var(--xb-border);
  --el-border-color-lighter: var(--xb-border);
  --el-border-color-extra-light: var(--xb-border);
  --el-border-color-hover: var(--xb-primary);
  --el-fill-color: rgba(var(--xb-fill-rgb), 0.06);
  --el-fill-color-light: rgba(var(--xb-fill-rgb), 0.09);
  --el-fill-color-lighter: rgba(var(--xb-fill-rgb), 0.05);
  --el-fill-color-extra-light: rgba(var(--xb-fill-rgb), 0.035);
  --el-fill-color-dark: rgba(var(--xb-fill-rgb), 0.13);
  --el-fill-color-darker: rgba(var(--xb-fill-rgb), 0.18);
  --el-fill-color-blank: var(--xb-bg-2);
  --el-disabled-bg-color: rgba(var(--xb-fill-rgb), 0.08);
  --el-disabled-text-color: var(--xb-muted);
  --el-disabled-border-color: var(--xb-border);
  --el-box-shadow: 0 12px 32px rgba(var(--xb-bg-rgb), 0.28);
  --el-box-shadow-light: 0 12px 28px rgba(var(--xb-bg-rgb), 0.32);
  --el-box-shadow-lighter: 0 6px 16px rgba(var(--xb-bg-rgb), 0.24);
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

/* Element Plus 弹层会 teleport 到 body，必须在全局统一主题。 */
.el-popper.is-light,
.el-select__popper.el-popper,
.el-dropdown__popper.el-popper {
  --el-bg-color: var(--xb-bg-2);
  --el-bg-color-overlay: var(--xb-bg-2);
  --el-text-color-primary: var(--xb-text);
  --el-text-color-regular: var(--xb-muted);
  --el-text-color-secondary: var(--xb-muted);
  --el-border-color-light: var(--xb-border);
  --el-border-color-lighter: var(--xb-border);
  --el-fill-color-light: rgba(var(--xb-primary-rgb), 0.1);
  --el-fill-color-lighter: rgba(var(--xb-primary-rgb), 0.06);
  background: var(--xb-bg-2) !important;
  border-color: var(--xb-border) !important;
  color: var(--xb-text);
  box-shadow: 0 16px 40px rgba(var(--xb-bg-rgb), 0.35), 0 0 0 1px rgba(var(--xb-primary-rgb), 0.08);
}
.el-select-dropdown,
.el-dropdown-menu {
  background: transparent !important;
  border: 0;
}
.el-select-dropdown__item,
.el-dropdown-menu__item {
  color: var(--xb-text) !important;
  background: transparent !important;
}
.el-select-dropdown__item.hover,
.el-select-dropdown__item:hover,
.el-dropdown-menu__item:not(.is-disabled):hover,
.el-dropdown-menu__item:focus {
  color: var(--xb-primary) !important;
  background: rgba(var(--xb-primary-rgb), 0.12) !important;
}
.el-select-dropdown__item.is-selected {
  color: var(--xb-primary) !important;
  background: rgba(var(--xb-primary-rgb), 0.16) !important;
  font-weight: 700;
}
.el-select-dropdown__item.is-disabled,
.el-select-dropdown__empty,
.el-select-group__title {
  color: var(--xb-muted) !important;
}
.el-dropdown-menu__item.is-disabled {
  color: var(--xb-muted) !important;
  opacity: 0.55;
}
.el-dropdown-menu__item--divided::before,
.el-dropdown-menu__item--divided {
  border-top-color: var(--xb-border) !important;
}
.el-popper__arrow::before {
  background: var(--xb-bg-2) !important;
  border-color: var(--xb-border) !important;
}

/* Element Plus 2.x 选择器关闭态使用 __wrapper，而不是旧版 __input。 */
.el-select__wrapper,
.el-input__wrapper,
.el-textarea__inner {
  background-color: var(--xb-bg-2) !important;
  color: var(--xb-text) !important;
  box-shadow: 0 0 0 1px var(--xb-border) inset !important;
}
.el-select__wrapper:hover,
.el-input__wrapper:hover {
  box-shadow: 0 0 0 1px var(--xb-primary) inset !important;
}
.el-select__wrapper.is-focused,
.el-input__wrapper.is-focus,
.el-input__wrapper:focus-within {
  box-shadow: 0 0 0 1px var(--xb-primary) inset, 0 0 0 3px rgba(var(--xb-primary-rgb), 0.12) !important;
}
.el-select__placeholder,
.el-input__inner::placeholder,
.el-textarea__inner::placeholder {
  color: var(--xb-muted) !important;
}
.el-select__selected-item,
.el-input__inner,
.el-textarea__inner {
  color: var(--xb-text) !important;
}
.el-select__caret,
.el-select__suffix,
.el-input__icon {
  color: var(--xb-muted) !important;
}
.el-select__wrapper.is-disabled,
.el-input.is-disabled .el-input__wrapper,
.el-textarea.is-disabled .el-textarea__inner {
  background-color: rgba(var(--xb-fill-rgb), 0.08) !important;
  color: var(--xb-muted) !important;
  box-shadow: 0 0 0 1px var(--xb-border) inset !important;
}

/* 开关默认关闭态是 Element Plus 灰色，改为主题表面；启用态沿用主色。 */
.el-switch {
  --el-switch-off-color: rgba(var(--xb-fill-rgb), 0.24);
  --el-switch-on-color: var(--xb-primary);
  --el-switch-border-color: var(--xb-border);
}
.el-switch__core {
  border-color: var(--el-switch-border-color) !important;
  background: var(--el-switch-off-color) !important;
}
.el-switch.is-checked .el-switch__core {
  border-color: var(--xb-primary) !important;
  background: var(--xb-primary) !important;
}
.el-switch.is-disabled .el-switch__core {
  border-color: var(--xb-border) !important;
  background: rgba(var(--xb-fill-rgb), 0.12) !important;
}

/* 原生下拉框的关闭态与可见选项也使用当前主题；系统 popup 是否支持 hover 由浏览器决定。 */
select {
  background-color: var(--xb-bg-2);
  color: var(--xb-text);
}
select option {
  background-color: var(--xb-bg-2);
  color: var(--xb-text);
}
select option:checked {
  background: var(--xb-primary);
  color: var(--xb-on-primary);
}

.xb-notification-center.el-notification {
  --el-color-success: var(--xb-success);
  --el-color-warning: var(--xb-warn);
  --el-color-info: var(--xb-primary);
  --el-color-danger: var(--xb-accent);
  --el-color-error: var(--xb-accent);
  --el-notification-title-color: var(--xb-text);
  --el-notification-content-color: var(--xb-muted);
  --el-notification-close-color: var(--xb-muted);
  --el-notification-close-hover-color: var(--xb-primary);
  left: 50% !important;
  right: auto !important;
  width: min(420px, calc(100vw - 32px));
  max-width: calc(100vw - 32px);
  overflow: hidden;
  transform: translateX(-50%);
  border: 1px solid var(--xb-border);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(var(--xb-fill-rgb), 0.08), rgba(var(--xb-primary-rgb), 0.04)),
    var(--xb-panel);
  color: var(--xb-text);
  font-family: var(--xb-font);
  box-shadow: 0 16px 36px rgba(var(--xb-bg-rgb), 0.22), 0 0 24px rgba(var(--xb-primary-rgb), 0.1);
  backdrop-filter: blur(18px);
}
.xb-notification-center.el-notification::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: var(--xb-brand-gradient);
  opacity: 0.72;
}
.xb-notification-center .el-notification__title {
  color: var(--xb-text);
  font-weight: 700;
}
.xb-notification-center .el-notification__content,
.xb-notification-center .el-notification__content p {
  color: var(--xb-muted);
  line-height: 1.55;
}
.xb-notification-center .el-notification__closeBtn {
  color: var(--xb-muted);
}
.xb-notification-center .el-notification__closeBtn:hover {
  color: var(--xb-primary);
}
.xb-notification-center .el-notification--success {
  color: var(--xb-success);
}
.xb-notification-center .el-notification--warning {
  color: var(--xb-warn);
}
.xb-notification-center .el-notification--info {
  color: var(--xb-primary);
}
.xb-notification-center .el-notification--error {
  color: var(--xb-accent);
}
::view-transition {
  background: var(--theme-transition-from-bg, transparent);
}
::view-transition-group(root) {
  animation: none;
}
::view-transition-image-pair(root) {
  isolation: isolate;
}
::view-transition-old(root),
::view-transition-new(root) {
  animation: none;
  mix-blend-mode: normal;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
html.theme-transition-expand::view-transition-old(root) {
  z-index: 1;
  opacity: 1;
  clip-path: inset(0);
}
html.theme-transition-expand::view-transition-new(root) {
  z-index: 999;
  opacity: 1;
  clip-path: circle(0px at var(--theme-transition-x) var(--theme-transition-y));
}
html.theme-transition-contract::view-transition-old(root) {
  z-index: 999;
  opacity: 1;
  clip-path: circle(var(--theme-transition-radius) at var(--theme-transition-x) var(--theme-transition-y));
}
html.theme-transition-contract::view-transition-new(root) {
  z-index: 1;
  opacity: 1;
  clip-path: inset(0);
}
html.theme-transitioning *,
html.theme-transitioning *::before,
html.theme-transitioning *::after {
  transition-duration: 0s !important;
}
html.theme-transitioning {
  overflow-anchor: none;
}
.theme-snapshot-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483647;
  pointer-events: none;
  overflow: hidden;
  background: var(--xb-bg);
  contain: layout style paint;
}
.theme-snapshot-overlay *,
.theme-snapshot-overlay *::before,
.theme-snapshot-overlay *::after {
  transition-duration: 0s !important;
  animation-play-state: paused !important;
}
.theme-snapshot-overlay > #app {
  min-height: 100vh;
}
@media (prefers-reduced-motion: reduce) {
  ::view-transition-old(root),
  ::view-transition-new(root) {
    animation: none;
  }
}
</style>
