<template>
  <div v-if="lines.length" class="run-status" role="status" aria-live="polite">
    <div v-for="line in lines" :key="line.key" class="status-row">
      <span class="status-dot" :class="[`tone-${line.tone}`, { pulsing: line.pulsing }]"></span>
      <span v-if="line.platform" class="status-platform">{{ line.platform }}</span>
      <span class="status-text mono">{{ line.text }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

// What the run is doing right now, in words: "Round 12: 6 agents awake, 2 failed so far", or the progress of the
// end-of-run questions. `activity` and `poll` come from the run status (see SimulationRunState on the backend).
const props = defineProps({
  activity: { type: Object, default: () => ({}) },
  poll: { type: Object, default: null },
  // The run is in progress (so "nothing yet" means "waiting", not "never started")
  active: { type: Boolean, default: false }
})

const { t } = useI18n()

const PLATFORMS = ['twitter', 'reddit']

const roundText = (a) => {
  const known = typeof a.woken === 'number'
  const failed = a.failed || 0
  if (a.state === 'done') {
    if (known && a.woken === 0) return t('runHealth.status.nobody', { round: a.round })
    return known
      ? t('runHealth.status.done', { round: a.round, woken: a.woken, acted: a.acted ?? 0, failed })
      : t('runHealth.status.doneUnknown', { round: a.round, acted: a.acted ?? 0, failed })
  }
  return known
    ? t('runHealth.status.running', { round: a.round, woken: a.woken, failed })
    : t('runHealth.status.runningUnknown', { round: a.round, failed })
}

const roundTone = (a) => {
  const failed = a.failed || 0
  if (!failed) return 'ok'
  return typeof a.woken === 'number' && failed >= a.woken ? 'bad' : 'warn'
}

const pollText = (p) => {
  const base = t('runHealth.status.poll', { answered: p.answered || 0, total: p.total || 0 })
  if (!p.attempt) return base
  const note = p.state === 'waiting' && p.retry_in
    ? t('runHealth.status.pollRetry', { attempt: p.attempt, max: p.max_attempts, seconds: Math.round(p.retry_in) })
    : t('runHealth.status.pollTry', { attempt: p.attempt, max: p.max_attempts })
  return `${base}, ${note}`
}

const lines = computed(() => {
  const p = props.poll
  if (p && p.state && p.state !== 'done') {
    return [{ key: 'poll', platform: '', text: pollText(p), tone: p.error_kind ? 'bad' : 'ok', pulsing: true }]
  }
  if (p && p.state === 'done' && props.active) {
    return [{
      key: 'poll', platform: '', pulsing: false,
      text: t('runHealth.status.pollDone', { answered: p.answered || 0, total: p.total || 0 }),
      tone: p.error_kind ? 'bad' : 'ok'
    }]
  }
  const rows = []
  for (const platform of PLATFORMS) {
    const a = props.activity && props.activity[platform]
    if (!a || !a.round) continue
    rows.push({
      key: platform,
      platform: t(`runHealth.platforms.${platform}`),
      text: roundText(a),
      tone: roundTone(a),
      pulsing: a.state !== 'done'
    })
  }
  if (!rows.length && props.active) {
    rows.push({ key: 'waiting', platform: '', text: t('runHealth.status.waiting'), tone: 'ok', pulsing: true })
  }
  return rows
})
</script>

<style scoped>
.run-status {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--c-555555);
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.status-dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c-4caf50);
}

.status-dot.tone-warn {
  background: var(--c-ff9800);
}

.status-dot.tone-bad {
  background: var(--c-c62828);
}

.status-dot.pulsing {
  animation: status-pulse 1.4s ease-in-out infinite;
}

@keyframes status-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.status-platform {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--c-333333);
}

.status-text {
  min-width: 0;
  overflow-wrap: anywhere;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
</style>
