<template>
  <router-view />
  <!-- 桌面版：在任何页面都能快速进入配置页 -->
  <router-link v-if="showDesktopBar" to="/settings" class="desktop-settings-fab" title="配置 API Key">
    <span class="dot" :class="{ ready: configured }"></span>
    {{ configured ? '配置' : '未配置 Key' }}
  </router-link>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import service from './api'

const desktop = ref(false)
const configured = ref(true)
const route = useRoute()
const router = useRouter()
const showDesktopBar = ref(false)

onMounted(async () => {
  try {
    const res = await service.get('/api/desktop/status')
    const data = res.data || {}
    desktop.value = !!data.desktop
    configured.value = !!data.configured
    showDesktopBar.value = desktop.value && route.path !== '/settings'
    // 首次使用且尚未配置：直接引导到配置页
    if (desktop.value && !configured.value && route.path !== '/settings') {
      router.push('/settings')
      return
    }
  } catch (err) {
    // 非桌面版（例如源码部署）时该接口不存在，忽略
    desktop.value = false
  }
})
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
  color: #000000;
  background-color: #ffffff;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #000000;
}

::-webkit-scrollbar-thumb:hover {
  background: #333333;
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}

/* 桌面版右下角配置入口 */
.desktop-settings-fab {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 9999;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 15px;
  border-radius: 999px;
  background: rgba(10, 20, 38, 0.92);
  border: 1px solid rgba(34, 211, 238, 0.35);
  color: #d7ecff;
  font-size: 12px;
  text-decoration: none;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  transition: all 0.18s ease;
}

.desktop-settings-fab:hover {
  border-color: #22d3ee;
  color: #ffffff;
}

.desktop-settings-fab .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f87171;
}

.desktop-settings-fab .dot.ready {
  background: #34d399;
}
</style>
