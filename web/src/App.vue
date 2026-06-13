<template>
  <router-view />
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
:root {
  --xb-bg: #05060d;
  --xb-bg-2: #080b16;
  --xb-panel: rgba(10, 20, 40, 0.45);
  --xb-border: rgba(0, 240, 255, 0.16);
  --xb-text: #e6f5ff;
  --xb-muted: #7c93b8;
  --xb-primary: #00f0ff;
  --xb-primary-2: #2f6bff;
  --xb-accent: #ff2e88;
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
  font-family: 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif;
}
#app {
  min-height: 100vh;
}
html {
  scroll-behavior: smooth;
}
::selection {
  background: rgba(0, 240, 255, 0.35);
  color: #fff;
}
::-webkit-scrollbar {
  width: 10px;
}
::-webkit-scrollbar-track {
  background: var(--xb-bg);
}
::-webkit-scrollbar-thumb {
  background: #14203a;
  border-radius: 5px;
}
::-webkit-scrollbar-thumb:hover {
  background: #1d2c4d;
}
</style>
