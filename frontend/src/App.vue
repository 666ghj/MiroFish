<template>
  <router-view />
</template>

<script setup>
// 使用 Vue Router 来管理页面
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--c-000000);
  background-color: var(--c-ffffff);
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--c-f1f1f1);
}

::-webkit-scrollbar-thumb {
  background: var(--c-000000);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--c-333333);
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}
</style>
