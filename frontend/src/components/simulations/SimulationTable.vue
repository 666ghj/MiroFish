<template>
  <div class="table-card">
    <div v-if="loading" class="table-state">
      <span class="spinner" />
      {{ $t('simulations.loading') }}
    </div>

    <div v-else-if="!total" class="table-state is-empty">
      <strong>{{ $t('simulations.empty') }}</strong>
      <span>{{ $t('simulations.emptyDesc') }}</span>
      <router-link class="state-action" to="/">{{ $t('simulations.emptyAction') }}</router-link>
    </div>

    <div v-else-if="!simulations.length" class="table-state is-empty">
      <strong>{{ $t('simulations.noMatches') }}</strong>
      <button type="button" class="state-action" @click="$emit('clear-filter')">
        {{ $t('simulations.clearFilter') }}
      </button>
    </div>

    <div v-else class="table-scroll">
      <table class="sim-table">
        <thead>
          <tr>
            <th scope="col">{{ $t('simulations.columnSimulation') }}</th>
            <th scope="col">{{ $t('simulations.columnProject') }}</th>
            <th scope="col">{{ $t('simulations.columnStatus') }}</th>
            <th scope="col">{{ $t('simulations.columnProgress') }}</th>
            <th scope="col">{{ $t('simulations.columnCreated') }}</th>
            <th scope="col" class="col-actions">{{ $t('simulations.columnActions') }}</th>
          </tr>
        </thead>

        <tbody>
          <tr v-for="sim in simulations" :key="sim.simulation_id">
            <td class="cell-sim">
              <div class="stack">
                <span class="sim-id" :title="sim.simulation_id">
                  {{ formatSimulationId(sim.simulation_id) }}
                </span>
                <span class="sim-requirement">
                  {{ sim.simulation_requirement || $t('simulations.noRequirement') }}
                </span>
                <span class="sim-agents">{{ agentCountLabel(sim) }}</span>
              </div>
            </td>

            <td class="cell-project">
              <span v-if="sim.project_name">{{ sim.project_name }}</span>
              <span v-else class="is-absent">{{ $t('simulations.noProject') }}</span>
            </td>

            <td class="cell-status">
              <div class="stack is-tight">
                <span class="status-pill" :class="statusTone(sim)">
                  <i class="dot" />{{ statusLabel(sim) }}
                </span>
                <span v-if="sim.stale" class="stale-flag" :title="$t('simulations.staleHint')">
                  {{ $t('simulations.staleLabel') }}
                </span>
                <span v-if="sim.report_id" class="report-flag">{{ $t('simulations.reportReady') }}</span>
              </div>
            </td>

            <td class="cell-progress">
              <div class="progress-track" :aria-hidden="true">
                <div class="progress-fill" :style="{ width: `${progressOf(sim).percent}%` }" />
              </div>
              <span class="progress-label">{{ progressLabel(sim) }}</span>
            </td>

            <td class="cell-created">{{ formatTimestamp(sim.created_at) }}</td>

            <td class="cell-actions">
              <SimulationRowActions
                :simulation="sim"
                :name="rowName(sim)"
                @restart="$emit('restart', sim)"
                @stop="$emit('stop', sim)"
                @view-logs="$emit('view-logs', sim)"
                @delete="$emit('delete', sim)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import SimulationRowActions from './SimulationRowActions.vue'
import {
  formatSimulationId,
  formatTimestamp,
  agentCount,
  progressOf,
  resolveStatus,
  simulationName,
  statusTone
} from '../../utils/simulationFormat'

defineProps({
  // Already filtered and sorted by the view.
  simulations: { type: Array, default: () => [] },
  // How many rows exist before filtering, so an empty result can tell "nothing
  // here yet" from "nothing matches".
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false }
})

defineEmits(['restart', 'stop', 'view-logs', 'delete', 'clear-filter'])

const { t } = useI18n()

// Pending an i18n key of its own; this group does not own locales/en.json.
const agentCountLabel = (sim) => `${agentCount(sim)} agents`

const rowName = (sim) => simulationName(sim) || t('simulations.untitled')

const statusLabel = (sim) => {
  const status = resolveStatus(sim)
  const key = `simulations.status.${status}`
  const label = t(key)
  return label === key ? t('simulations.status.unknown') : label
}

const progressLabel = (sim) => {
  const progress = progressOf(sim)
  if (!progress.started) return t('simulations.notStarted')
  if (!progress.hasTotal) return t('simulations.roundsCurrent', { current: progress.current })
  return t('simulations.roundsProgress', { current: progress.current, total: progress.total })
}
</script>

<style scoped>
.table-card {
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  box-shadow: var(--edge-highlight);
}

.table-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 72px 24px;
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
}

.table-state strong {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.state-action {
  margin-top: 6px;
  padding: 8px 18px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  color: var(--accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.state-action:hover {
  background: var(--accent);
  color: var(--text-on-accent);
}

.spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: var(--radius-pill);
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* The action column must never be pushed off-screen silently, so the table
   scrolls inside its own card rather than widening the page. */
.table-scroll {
  overflow-x: auto;
}

.sim-table {
  width: 100%;
  min-width: 940px;
  border-collapse: collapse;
}

.sim-table th {
  padding: 12px 18px;
  background: var(--bg-sunken);
  border-bottom: 1px solid var(--border-default);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-align: left;
  text-transform: uppercase;
  white-space: nowrap;
}

.sim-table th:first-child {
  border-top-left-radius: var(--radius-xl);
}

.sim-table th:last-child {
  border-top-right-radius: var(--radius-xl);
}

.sim-table td {
  padding: 16px 18px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
  color: var(--text-secondary);
  vertical-align: top;
}

.sim-table tbody tr:last-child td {
  border-bottom: none;
}

.sim-table tbody tr:hover td {
  background: var(--bg-hover);
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stack.is-tight {
  align-items: flex-start;
  gap: 6px;
}

.cell-sim {
  max-width: 340px;
}

.sim-id {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.sim-requirement {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  color: var(--text-muted);
  line-height: 1.45;
}

.sim-agents {
  font-size: 11px;
  color: var(--text-faint);
}

.cell-project {
  max-width: 200px;
  color: var(--text-primary);
}

.cell-project .is-absent {
  color: var(--text-faint);
}

.cell-status {
  white-space: nowrap;
}

/* The pill carries its own opaque ground instead of a same-hue wash over the
   row. A 14% wash of the status colour lightens the surface under 12px text of
   that same colour, and on a hovered row that took the accent and info pills to
   4.30:1 and the danger pill to 4.43:1 - all under AA. Sinking the pill instead
   puts every status between 7.98:1 and 12.84:1, and holds there when the row
   lightens on hover, because the pill no longer composites with it. Hue still
   reads from the border, the dot and the text. */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  background: var(--bg-sunken);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.status-pill .dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-pill);
  background: var(--neutral-dot);
}

.status-pill.is-running {
  border-color: var(--accent-border);
  color: var(--accent);
}

.status-pill.is-running .dot {
  background: var(--accent);
  animation: pill-pulse 1.2s infinite;
}

@keyframes pill-pulse {
  50% { opacity: 0.35; }
}

.status-pill.is-pending {
  border-color: var(--warning-border);
  color: var(--warning);
}

.status-pill.is-pending .dot { background: var(--warning); }

.status-pill.is-ready {
  border-color: var(--info-border);
  color: var(--info);
}

.status-pill.is-ready .dot { background: var(--info); }

.status-pill.is-complete {
  border-color: var(--success-border);
  color: var(--success);
}

.status-pill.is-complete .dot { background: var(--success); }

.status-pill.is-failed,
.status-pill.is-stale {
  border-color: var(--danger-border);
  color: var(--danger);
}

.status-pill.is-failed .dot,
.status-pill.is-stale .dot { background: var(--danger); }

/* Same ground as the pill it sits under: it is 11px text in the status colour,
   so a same-hue wash costs it the most contrast of anything in this table
   (5.54:1 on a hovered row). Sunken puts it at 11.23:1 and keeps the two
   badges looking like one control. */
.stale-flag {
  padding: 2px 8px;
  background: var(--bg-sunken);
  border: 1px solid var(--warning-border);
  border-radius: var(--radius-sm);
  color: var(--warning);
  font-size: 11px;
  font-weight: 700;
  cursor: help;
}

.report-flag {
  font-size: 11px;
  color: var(--text-link);
}

.cell-progress {
  min-width: 150px;
}

.progress-track {
  height: 5px;
  margin-bottom: 7px;
  overflow: hidden;
  background: var(--bg-inset);
  border-radius: var(--radius-pill);
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: var(--radius-pill);
  transition: width 0.4s ease;
}

.progress-label {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.cell-created {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.col-actions,
.cell-actions {
  text-align: right;
}
</style>
