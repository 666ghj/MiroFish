<template>
  <header class="ws-header">
    <!-- Brand -->
    <div class="ws-brand" @click="$emit('brand-click')" role="button" tabindex="0">
      <span class="brand-text">MIROFISH</span>
    </div>

    <!-- Layout switcher — centro absoluto -->
    <div class="ws-center">
      <div class="layout-switcher" role="group" aria-label="Layout mode">
        <button
          v-for="mode in layoutModes"
          :key="mode.key"
          class="layout-btn"
          :class="{ active: modelValue === mode.key }"
          @click="$emit('update:modelValue', mode.key)"
        >
          {{ mode.label }}
        </button>
      </div>
    </div>

    <!-- Direita: slot + step + status -->
    <div class="ws-right">
      <slot name="right" />

      <template v-if="step !== null">
        <div class="ws-sep" />
        <div class="step-context">
          <span class="step-counter">{{ String(step).padStart(2, '0') }}</span>
          <span class="step-slash">/</span>
          <span class="step-total">05</span>
          <span class="step-name-text">{{ stepName }}</span>
        </div>
      </template>

      <div class="ws-sep" />
      <div class="status-pill" :class="statusVariant">
        <span class="status-pulse" />
        <span class="status-label">{{ statusLabel }}</span>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  /** v-model para viewMode: 'graph' | 'split' | 'workbench' */
  modelValue: { type: String, default: 'split' },
  /** Número do step atual (1–5). null = não exibir */
  step: { type: Number, default: null },
  /** Nome do step atual */
  stepName: { type: String, default: '' },
  /** Variante visual: 'processing' | 'completed' | 'error' | 'idle' */
  statusVariant: { type: String, default: 'idle' },
  /** Texto do status */
  statusLabel: { type: String, default: '' },
})

defineEmits(['update:modelValue', 'brand-click'])

const layoutModes = computed(() => [
  { key: 'graph',     label: t('main.layoutGraph') },
  { key: 'split',     label: t('main.layoutSplit') },
  { key: 'workbench', label: t('main.layoutWorkbench') },
])
</script>

<style scoped>
/* ── Container ── */
.ws-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  background: #fff;
  border-bottom: 1px solid #E8E8E8;
  position: relative;
  z-index: 100;
  flex-shrink: 0;
}

/* ── Brand ── */
.ws-brand {
  display: flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
  outline: none;
}
.brand-text {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 2px;
  color: #0A0A0A;
  transition: opacity 0.15s;
}
.ws-brand:hover .brand-text { opacity: 0.65; }

/* ── Centro — switcher absoluto ── */
.ws-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.layout-switcher {
  display: flex;
  background: #F4F4F4;
  border-radius: 7px;
  padding: 3px;
  gap: 2px;
}

.layout-btn {
  border: none;
  background: transparent;
  padding: 5px 18px;
  font-size: 11.5px;
  font-weight: 600;
  color: #888;
  border-radius: 5px;
  cursor: pointer;
  letter-spacing: 0.3px;
  transition: background 0.18s, color 0.18s, box-shadow 0.18s;
  white-space: nowrap;
}
.layout-btn.active {
  background: #fff;
  color: #111;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.layout-btn:not(.active):hover { color: #333; }

/* ── Direita ── */
.ws-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* Separador vertical */
.ws-sep {
  width: 1px;
  height: 16px;
  background: #E0E0E0;
  flex-shrink: 0;
}

/* Step context */
.step-context {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.step-counter {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  font-size: 13px;
  color: #C0C0C0;
  line-height: 1;
}
.step-slash {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #D0D0D0;
}
.step-total {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
  font-size: 11px;
  color: #C0C0C0;
  margin-right: 8px;
}
.step-name-text {
  font-size: 12.5px;
  font-weight: 700;
  color: #1A1A1A;
  letter-spacing: 0.1px;
}

/* Status pill */
.status-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 11.5px;
  font-weight: 600;
  background: #F5F5F5;
  color: #666;
  transition: background 0.2s, color 0.2s;
}

.status-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #CCCCCC;
  flex-shrink: 0;
}

/* Variantes */
.status-pill.processing { background: #FFF3EE; color: #D44B00; }
.status-pill.processing .status-pulse {
  background: #FF5722;
  animation: pulse-dot 1s ease-in-out infinite;
}
.status-pill.completed { background: #F0FBF2; color: #2A7D3A; }
.status-pill.completed .status-pulse { background: #4CAF50; }
.status-pill.error { background: #FFF0F0; color: #C62828; }
.status-pill.error .status-pulse { background: #EF5350; }
.status-pill.idle { background: #F5F5F5; color: #888; }
.status-pill.idle .status-pulse { background: #C0C0C0; }

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.8); }
}
</style>
