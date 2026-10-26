<template>
  <section class="ensemble-summary">
    <header class="summary-head">
      <h3 class="summary-title">{{ $t('ensemble.summaryTitle') }}</h3>
      <span class="summary-meta mono">
        {{ $t('ensemble.summaryRuns', { ok: summary.n_replicates_ok, requested: summary.n_replicates_requested }) }}
        <template v-if="parseRate !== null"> · {{ $t('ensemble.parseRate', { rate: pct(parseRate) }) }}</template>
      </span>
    </header>

    <p class="caveat">{{ $t('ensemble.caveat', { n: summary.n_replicates_ok }) }}</p>

    <div class="table-wrap">
      <table class="stats-table">
        <thead>
          <tr>
            <th class="col-label">{{ $t('ensemble.colQuestion') }}</th>
            <th>{{ $t('ensemble.colMedian') }}</th>
            <th>{{ $t('ensemble.colRange') }}</th>
            <th>{{ $t('ensemble.colMinMax') }}</th>
            <th>{{ $t('ensemble.colRuns') }}</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in rows" :key="row.key">
            <tr v-if="row.type === 'group'" class="group-row">
              <td colspan="5">{{ row.label }}</td>
            </tr>
            <tr v-else-if="row.type === 'empty'">
              <td class="col-label">{{ row.label }}</td>
              <td colspan="4" class="muted">{{ $t('ensemble.noAnswer') }}</td>
            </tr>
            <tr v-else-if="row.type === 'note'" class="note-row">
              <td colspan="5">{{ row.label }}: <span class="mono">{{ row.value }}</span></td>
            </tr>
            <tr v-else :class="{ option: row.option }">
              <td class="col-label">{{ row.label }}</td>
              <td class="mono strong">{{ show(row, row.stats.median) }}</td>
              <td class="mono">{{ range(row, row.stats.p10, row.stats.p90) }}</td>
              <td class="mono">{{ range(row, row.stats.min, row.stats.max) }}</td>
              <td class="mono">{{ row.stats.n }}</td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  // The ensemble's summary.json as returned by GET /api/simulation/ensemble/<id>/summary
  summary: { type: Object, required: true }
})

const { t } = useI18n()

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value)

const plain = (value, digits = 1) => {
  if (!isNumber(value)) return '–'
  return Math.abs(value - Math.round(value)) < 1e-9 ? String(Math.round(value)) : value.toFixed(digits)
}

const pct = (value) => (isNumber(value) ? `${Math.round(value * 100)}%` : '–')

// How a value is written depends on what the row measures.
const show = (row, value) => {
  if (!isNumber(value)) return '–'
  if (row.kind === 'share') return pct(value)
  if (row.kind === 'probability') return `${plain(value)}%`
  if (row.kind === 'number') return row.unit ? `${plain(value, 2)} ${row.unit}` : plain(value, 2)
  return plain(value, 0)
}

// "29.5–73.6%": the suffix is written once, which keeps the table narrow
const range = (row, low, high) => {
  if (!isNumber(low) || !isNumber(high)) return '–'
  if (row.kind === 'share') return `${Math.round(low * 100)}–${pct(high)}`
  if (row.kind === 'probability') return `${plain(low)}–${plain(high)}%`
  if (row.kind === 'number') return `${plain(low, 2)}–${plain(high, 2)}${row.unit ? ` ${row.unit}` : ''}`
  return `${plain(low, 0)}–${plain(high, 0)}`
}

const parseRate = computed(() => {
  const stats = props.summary.parse_rate
  return stats && stats.n ? stats.mean : null
})

const statRow = (key, label, stats, kind, extra = {}) => ({ type: 'stat', key, label, stats, kind, ...extra })

const rows = computed(() => {
  const summary = props.summary
  const result = []

  for (const question of summary.questions || []) {
    const poll = (summary.polls || {})[question.id]
    if (!poll || !poll.replicates_with_data) {
      result.push({ type: 'empty', key: question.id, label: question.text })
      continue
    }
    if (poll.type === 'probability') {
      result.push(statRow(question.id, question.text, poll.agent_mean, 'probability'))
      result.push({
        type: 'note',
        key: `${question.id}:above50`,
        label: t('ensemble.meanAbove50'),
        value: pct(poll.share_of_replicates_mean_above_50)
      })
    } else if (poll.type === 'choice') {
      result.push({ type: 'group', key: question.id, label: question.text })
      for (const [option, stats] of Object.entries(poll.options || {})) {
        result.push(statRow(`${question.id}:${option}`, option, stats, 'share', { option: true }))
      }
    } else {
      result.push(statRow(question.id, question.text, poll.median, 'number', { unit: poll.unit }))
    }
  }

  const drift = summary.stance_drift
  const behavior = summary.behavior || {}
  const behaviorRows = []
  if (drift && drift.applicable && drift.switched_share) {
    behaviorRows.push(statRow('drift', t('ensemble.stanceDrift'), drift.switched_share, 'share'))
  }
  for (const [key, label] of [['total_actions', 'totalActions'], ['posts', 'posts'], ['comments', 'comments']]) {
    if (behavior[key]) behaviorRows.push(statRow(key, t(`ensemble.${label}`), behavior[key], 'count'))
  }
  if (behaviorRows.length) {
    result.push({ type: 'group', key: 'behavior', label: t('ensemble.behaviorTitle') })
    result.push(...behaviorRows)
  }
  return result
})
</script>

<style scoped>
.ensemble-summary {
  border: 1px solid var(--c-eaeaea);
  border-radius: 6px;
  background: var(--c-ffffff);
  padding: 14px 16px;
}

.summary-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.summary-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c-111111);
}

.summary-meta {
  font-size: 11px;
  color: var(--c-777777);
}

.caveat {
  margin: 8px 0 12px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--c-6b5b2e);
  background: var(--c-fffaeb);
  border: 1px solid var(--c-f1e3b5);
  border-radius: 4px;
}

.table-wrap {
  overflow-x: auto;
}

.stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.stats-table th {
  padding: 6px;
  text-align: right;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--c-999999);
  border-bottom: 1px solid var(--c-eaeaea);
  white-space: nowrap;
}

.stats-table td {
  padding: 7px 6px;
  text-align: right;
  border-bottom: 1px solid var(--c-f3f3f3);
  white-space: nowrap;
}

.stats-table .col-label {
  text-align: left;
  white-space: normal;
  min-width: 120px;
  color: var(--c-222222);
}

.group-row td {
  text-align: left;
  white-space: normal;
  padding-top: 12px;
  font-weight: 600;
  color: var(--c-222222);
  border-bottom: 1px solid var(--c-eaeaea);
}

.option .col-label {
  padding-left: 20px;
  color: var(--c-555555);
}

.note-row td {
  text-align: left;
  padding-top: 0;
  font-size: 11px;
  color: var(--c-888888);
}

.muted { color: var(--c-999999); text-align: left; }
.strong { font-weight: 700; color: var(--c-000000); }
.mono { font-family: 'JetBrains Mono', monospace; }
</style>
