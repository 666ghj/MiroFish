<template>
  <div class="main-view">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="router.push('/')">MIROFISH</div>
      </div>

      <div class="header-center">
        <div class="view-switcher">
          <button
            v-for="mode in ['graph', 'split', 'workbench']"
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{ { graph: $t('main.layoutGraph'), split: $t('main.layoutSplit'), workbench: $t('main.layoutWorkbench') }[mode] }}
          </button>
        </div>
      </div>

      <div class="header-right">
        <LanguageSwitcher />
        <div class="step-divider"></div>
        <div class="workflow-step">
          <span class="step-num">Step 4b/5</span>
          <span class="step-name">{{ $t('interview.title') }}</span>
        </div>
        <div class="step-divider"></div>
        <span class="status-indicator idle">
          <span class="dot"></span>
          {{ $t('common.ready') }}
        </span>
      </div>
    </header>

    <!-- Main Content Area -->
    <main class="content-area">
      <!-- Right Panel fills workbench mode -->
      <div class="panel-wrapper right" :style="rightPanelStyle">
        <Step4bInterviews :sim-id="currentSimId" />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import Step4bInterviews from '../components/Step4bInterviews.vue'

const route = useRoute()
const router = useRouter()

const currentSimId = ref(route.params.simulationId)
const viewMode = ref('workbench')

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'workbench') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'graph') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})
</script>

<style scoped>
.main-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  background: #000;
  color: #fff;
  flex-shrink: 0;
  z-index: 10;
}

.brand {
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: opacity 0.2s;
}

.brand:hover { opacity: 0.8; }

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.view-switcher {
  display: flex;
  gap: 2px;
  background: #1a1a1a;
  padding: 3px;
  border-radius: 4px;
}

.switch-btn {
  padding: 4px 12px;
  font-size: 0.75rem;
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  border-radius: 2px;
  transition: all 0.15s;
  font-family: inherit;
}

.switch-btn.active {
  background: #fff;
  color: #000;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-divider {
  width: 1px;
  height: 20px;
  background: #333;
}

.workflow-step {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.step-num {
  font-size: 0.65rem;
  color: #666;
  letter-spacing: 0.05em;
}

.step-name {
  font-size: 0.75rem;
  color: #fff;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #999;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #666;
}

.status-indicator.idle .dot { background: #666; }

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
}

.panel-wrapper {
  overflow: hidden;
  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.3s ease,
              transform 0.3s ease;
}

.panel-wrapper.right {
  overflow-y: auto;
}
</style>
