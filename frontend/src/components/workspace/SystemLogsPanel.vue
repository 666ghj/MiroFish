<template>
  <div class="logs-panel" :class="{ expanded: isExpanded }">
    <!-- Header clicável para expandir/colapsar -->
    <button class="logs-header" @click="toggle" :aria-expanded="isExpanded">
      <div class="logs-header-left">
        <span class="logs-title">SYSTEM LOG</span>
        <span v-if="contextId" class="logs-ctx-id">{{ contextId }}</span>
      </div>
      <div class="logs-header-right">
        <span class="logs-count" v-if="logs.length">{{ logs.length }}</span>
        <span class="expand-icon" :class="{ rotated: isExpanded }">▾</span>
      </div>
    </button>

    <!-- Conteúdo expansível -->
    <Transition name="logs-slide">
      <div v-if="isExpanded" class="logs-body" ref="logsBody">
        <div
          v-for="(log, idx) in logs"
          :key="idx"
          class="log-line"
          :class="logClass(log.msg)"
        >
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
        <div v-if="!logs.length" class="log-empty">{{ $t('system.noLogs') }}</div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  /** Array de { time: string, msg: string } */
  logs: { type: Array, default: () => [] },
  /** ID de contexto a exibir no header (ex: simulation ID) */
  contextId: { type: String, default: '' },
  /** Expandido por padrão */
  defaultExpanded: { type: Boolean, default: false },
})

const isExpanded = ref(props.defaultExpanded)
const logsBody = ref(null)

const toggle = () => { isExpanded.value = !isExpanded.value }

/** Scroll automático para o final quando novos logs chegam */
watch(
  () => props.logs.length,
  () => {
    if (!isExpanded.value) return
    nextTick(() => {
      if (logsBody.value) logsBody.value.scrollTop = logsBody.value.scrollHeight
    })
  }
)

/** Coloração semântica dos logs */
const logClass = (msg) => {
  if (!msg) return ''
  const lower = msg.toLowerCase()
  if (lower.startsWith('error') || lower.includes('failed') || lower.includes('exception'))
    return 'log--error'
  if (lower.includes('complete') || lower.includes('success') || lower.includes('ready'))
    return 'log--success'
  if (lower.includes('warning') || lower.includes('warn'))
    return 'log--warn'
  return ''
}
</script>

<style scoped>
.logs-panel {
  border-top: 1px solid #EBEBEB;
  background: #FAFAFA;
  flex-shrink: 0;
}

/* Header */
.logs-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
}
.logs-header:hover { background: #F3F3F3; }

.logs-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logs-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #AAAAAA;
}

.logs-ctx-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: #C8C8C8;
}

.logs-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logs-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #BBBBBB;
}

.expand-icon {
  font-size: 12px;
  color: #BBBBBB;
  transition: transform 0.2s ease;
}
.expand-icon.rotated { transform: rotate(180deg); }

/* Body */
.logs-body {
  max-height: 180px;
  overflow-y: auto;
  padding: 0 16px 10px;
  scroll-behavior: smooth;
}
.logs-body::-webkit-scrollbar { width: 4px; }
.logs-body::-webkit-scrollbar-thumb { background: #DDD; border-radius: 2px; }

.log-line {
  display: flex;
  gap: 10px;
  padding: 2px 0;
  font-size: 11px;
  line-height: 1.5;
  font-family: 'JetBrains Mono', monospace;
  border-bottom: 1px solid #F0F0F0;
}
.log-line:last-child { border-bottom: none; }

.log-time {
  color: #C0C0C0;
  flex-shrink: 0;
  font-size: 10px;
}

.log-msg { color: #4A4A4A; word-break: break-word; }

/* Variantes semânticas */
.log--error .log-msg { color: #C62828; }
.log--success .log-msg { color: #2E7D32; }
.log--warn .log-msg { color: #E65100; }

.log-empty {
  font-size: 11px;
  color: #CCCCCC;
  font-style: italic;
  padding: 8px 0;
}

/* Transição slide */
.logs-slide-enter-active,
.logs-slide-leave-active {
  transition: max-height 0.25s ease, opacity 0.2s ease;
  overflow: hidden;
}
.logs-slide-enter-from,
.logs-slide-leave-to {
  max-height: 0;
  opacity: 0;
}
.logs-slide-enter-to,
.logs-slide-leave-from {
  max-height: 220px;
  opacity: 1;
}
</style>
