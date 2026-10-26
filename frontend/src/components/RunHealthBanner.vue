<template>
  <div v-if="visible" class="run-health-banner" :class="`level-${health.level}`" role="alert">
    <svg class="banner-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
    <div class="banner-body">
      <div class="banner-title">{{ health.level === 'error' ? $t('runHealth.titleError') : $t('runHealth.titleWarning') }}</div>
      <p class="banner-text">{{ advice }}</p>
      <p v-if="counts" class="banner-counts">{{ counts }}</p>
      <p v-if="health.message" class="banner-said">
        <span class="said-label">{{ $t('runHealth.providerSaid') }}</span>
        <span class="said-text mono">{{ health.message }}</span>
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

// Shown while the model is refusing or failing requests, so a run that does nothing explains itself.
// `health` is the verdict the backend computes from the run's recent rounds and its end-of-run poll:
// { level: 'ok' | 'warning' | 'error', kind, message, source: 'rounds' | 'poll', recent_woken, recent_failed }.
const props = defineProps({
  health: { type: Object, default: null }
})

const { t, te } = useI18n()

const visible = computed(() => !!props.health && (props.health.level === 'warning' || props.health.level === 'error'))

const advice = computed(() => {
  const kind = props.health && props.health.kind
  const text = t(te(`runHealth.kinds.${kind}`) ? `runHealth.kinds.${kind}` : 'runHealth.kinds.other')
  // When it is the end-of-run questions that cannot be answered, say so first
  return props.health && props.health.source === 'poll' ? `${t('runHealth.pollPrefix')}${text}` : text
})

const counts = computed(() => {
  const h = props.health
  if (!h || h.source === 'poll' || !h.recent_failed) return ''
  return h.recent_woken
    ? t('runHealth.counts', { failed: h.recent_failed, woken: h.recent_woken })
    : t('runHealth.countsFailedOnly', { failed: h.recent_failed })
})
</script>

<style scoped>
.run-health-banner {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin: 0 0 14px;
  padding: 12px 14px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.55;
}

.level-warning {
  color: var(--c-6b5b2e);
  background: var(--c-fffaeb);
  border: 1px solid var(--c-f1e3b5);
}

.level-error {
  color: var(--c-c62828);
  background: var(--c-fff5f5);
  border: 1px solid var(--c-f3cfcf);
}

.banner-icon {
  flex-shrink: 0;
  margin-top: 1px;
}

.banner-body {
  min-width: 0;
}

.banner-title {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 3px;
}

.banner-text,
.banner-counts,
.banner-said {
  margin: 0 0 3px;
}

.banner-counts {
  opacity: 0.85;
}

.banner-said {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  opacity: 0.85;
}

.said-text {
  font-size: 11px;
  word-break: break-word;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}
</style>
