<template>
  <main class="ws-layout">
    <!-- Painel Esquerdo: Graph -->
    <div class="ws-panel ws-panel--left" :style="leftStyle">
      <slot name="graph" />
    </div>

    <!-- Painel Direito: Conteúdo do Step -->
    <div class="ws-panel ws-panel--right" :style="rightStyle">
      <slot name="content" />
    </div>
  </main>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** Modo de layout: 'graph' | 'split' | 'workbench' */
  viewMode: { type: String, default: 'split' },
})

const leftStyle = computed(() => {
  if (props.viewMode === 'graph')
    return { width: '100%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
  if (props.viewMode === 'workbench')
    return { width: '0%', opacity: 0, transform: 'translateX(-16px)', pointerEvents: 'none' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
})

const rightStyle = computed(() => {
  if (props.viewMode === 'workbench')
    return { width: '100%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
  if (props.viewMode === 'graph')
    return { width: '0%', opacity: 0, transform: 'translateX(16px)', pointerEvents: 'none' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
})
</script>

<style scoped>
.ws-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.ws-panel {
  height: 100%;
  overflow: hidden;
  transition:
    width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    opacity 0.28s ease,
    transform 0.28s ease;
  will-change: width, opacity, transform;
}

.ws-panel--left {
  border-right: 1px solid #EAEAEA;
}
</style>
