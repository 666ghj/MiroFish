<template>
  <div class="simulations-view">
    <header class="view-head">
      <div class="head-text">
        <h1 class="view-title">{{ $t('simulations.title') }}</h1>
        <p class="view-subtitle">{{ $t('simulations.subtitle') }}</p>
      </div>

      <span class="row-count">{{ $t('simulations.count', { count: visible.length }) }}</span>

      <button
        type="button"
        class="refresh-btn"
        :disabled="loading"
        @click="load({ showSpinner: true })"
      >
        {{ $t('simulations.refresh') }}
      </button>
    </header>

    <div class="view-controls">
      <input
        v-model="query"
        type="search"
        class="search-input"
        :placeholder="$t('simulations.searchPlaceholder')"
        :aria-label="$t('simulations.searchPlaceholder')"
      />

      <div class="filter-tabs">
        <button
          v-for="option in filterOptions"
          :key="option.id"
          type="button"
          class="filter-tab"
          :class="{ 'is-active': filter === option.id }"
          :aria-pressed="filter === option.id"
          @click="filter = option.id"
        >
          {{ $t(option.labelKey) }}
        </button>
      </div>
    </div>

    <p v-if="loadError" class="load-error">
      {{ $t('simulations.loadFailed', { error: loadError }) }}
      <button type="button" class="inline-retry" @click="load({ showSpinner: true })">
        {{ $t('common.retry') }}
      </button>
    </p>

    <SimulationTable
      :simulations="visible"
      :total="simulations.length"
      :loading="loading && !simulations.length"
      @restart="ask('restart', $event)"
      @stop="ask('stop', $event)"
      @view-logs="openLogs"
      @delete="ask('delete', $event)"
      @clear-filter="clearFilter"
    />

    <ConfirmDialog
      :open="Boolean(pending)"
      :title="confirmCopy.title"
      :body="confirmCopy.body"
      :confirm-label="confirmCopy.confirmLabel"
      :tone="pending?.kind === 'stop' ? 'accent' : 'danger'"
      :busy="actionBusy"
      @confirm="runPending"
      @cancel="pending = null"
    />

    <LogViewerModal
      v-if="logTarget"
      :simulation-id="logTarget.simulation_id"
      :name="nameOf(logTarget)"
      @close="logTarget = null"
    />

    <teleport to="#app-modals">
      <div v-if="toasts.length" class="toast-stack" role="status" aria-live="polite">
        <div v-for="toast in toasts" :key="toast.id" class="toast" :class="`is-${toast.tone}`">
          <span class="toast-text">{{ toast.text }}</span>
          <button
            type="button"
            class="toast-close"
            :aria-label="$t('common.close')"
            @click="dismiss(toast.id)"
          >
            <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path d="M3.5 3.5 L12.5 12.5 M12.5 3.5 L3.5 12.5" fill="none"
                stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          </button>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SimulationTable from '../components/simulations/SimulationTable.vue'
import ConfirmDialog from '../components/simulations/ConfirmDialog.vue'
import LogViewerModal from '../components/simulations/LogViewerModal.vue'
import {
  deleteSimulation,
  getSimulationHistory,
  pendingPreparation,
  restartSimulation,
  stopSimulation
} from '../api/simulation'
import {
  deleteNeedsForce,
  isLive,
  matchesFilter,
  matchesQuery,
  resolveStatus,
  restartParams,
  simulationName
} from '../utils/simulationFormat'

const { t } = useI18n()

// The whole history, not a page of it. The endpoint enriches every row from
// disk, so this is the one request the menu makes; everything else on this
// page is derived from it.
const HISTORY_LIMIT = 100

// Fast enough that a stop or a restart looks immediate, slow enough that a
// hundred enriched rows are not re-read off disk continuously.
const REFRESH_INTERVAL_MS = 5000

// A stop or a restart settles a moment after the request returns, so the list
// is read once more rather than showing the state the run was in mid-request.
const SETTLE_DELAY_MS = 1500

const TOAST_TIMEOUT_MS = 6000

const filterOptions = [
  { id: 'all', labelKey: 'simulations.filterAll' },
  { id: 'live', labelKey: 'simulations.filterLive' },
  { id: 'finished', labelKey: 'simulations.filterFinished' }
]

const simulations = ref([])
const loading = ref(false)
const loadError = ref('')
const query = ref('')
const filter = ref('all')

const pending = ref(null)
const actionBusy = ref(false)
const logTarget = ref(null)
const toasts = ref([])

let refreshTimer = null
let settleTimer = null
let toastSeq = 0
// A request in flight when the view unmounts still runs its finally block, and
// without this it would schedule a refresh nothing is left to cancel.
let disposed = false

const visible = computed(() =>
  simulations.value.filter(
    (sim) => matchesFilter(sim, filter.value) && matchesQuery(sim, query.value)
  )
)

const anyLive = computed(() =>
  simulations.value.some((sim) => isLive(sim) || resolveStatus(sim) === 'preparing')
)

const nameOf = (sim) => simulationName(sim) || t('simulations.untitled')

// --- Toasts ---

const dismiss = (id) => {
  toasts.value = toasts.value.filter((toast) => toast.id !== id)
}

const notify = (text, tone = 'info') => {
  const id = ++toastSeq
  toasts.value.push({ id, text, tone })
  setTimeout(() => dismiss(id), TOAST_TIMEOUT_MS)
}

// --- Loading ---

const load = async ({ showSpinner = false } = {}) => {
  if (showSpinner) loading.value = true

  try {
    const res = await getSimulationHistory(HISTORY_LIMIT)
    simulations.value = Array.isArray(res.data) ? res.data : []
    loadError.value = ''
  } catch (err) {
    loadError.value = err.message || t('common.unknownError')
  } finally {
    loading.value = false
    scheduleRefresh()
  }
}

// Polling runs only while something can still change and only while the tab is
// being looked at.
const scheduleRefresh = () => {
  clearTimeout(refreshTimer)
  refreshTimer = null
  if (disposed || !anyLive.value || document.visibilityState !== 'visible') return
  refreshTimer = setTimeout(() => load(), REFRESH_INTERVAL_MS)
}

const settle = () => {
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => load(), SETTLE_DELAY_MS)
}

const onVisibilityChange = () => {
  if (document.visibilityState === 'visible') {
    load()
  } else {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

const clearFilter = () => {
  query.value = ''
  filter.value = 'all'
}

const openLogs = (sim) => {
  logTarget.value = sim
}

// --- Destructive actions ---

// Restart discards everything the previous run produced and Delete is
// permanent, so both name what is lost before they run. Stop keeps its output
// and says so, which is the difference the user actually needs to see.
const ask = (kind, sim) => {
  pending.value = { kind, sim }
}

const confirmCopy = computed(() => {
  if (!pending.value) return { title: '', body: '', confirmLabel: '' }

  const { kind, sim } = pending.value
  const name = nameOf(sim)

  return {
    title: t(`simulations.confirm.${kind}Title`),
    body: t(`simulations.confirm.${kind}Body`, { name }),
    confirmLabel: t(`simulations.confirm.${kind}Confirm`)
  }
})

const runRestart = async (sim, name) => {
  notify(t('simulations.toast.restarting', { name }), 'info')
  // POST /restart always quiesces the previous run and clears its logs, action
  // databases and run state before it relaunches - the cleanup is the reason
  // this route exists rather than reusing /start.
  //
  // The parameters matter as much as the route. /restart defaults graph memory
  // off and leaves max_rounds unset, so posting only a simulation_id would
  // relaunch the run with less than it had: no graph memory update, and the
  // backend's own auto-planned round count instead of the one this simulation
  // was running to. restartParams restates what a normal start sends.
  try {
    await restartSimulation(restartParams(sim))
    notify(t('simulations.toast.restarted', { name }), 'success')
  } catch (err) {
    // 409 preparation_live:true means a preparation is running right now and
    // owns the files this restart would clear, so the backend refused it. The
    // refusal is narrow: a claim whose thread has died is dropped and the
    // restart goes through, so this only ever fires on a genuinely running
    // preparation. Reported as the generic 'Failed to restart' it read as the
    // app arguing with itself - the menu offering a restart and the backend
    // answering that the simulation is still being prepared. It is a state to
    // explain, and the place to watch it is the setup view, which follows the
    // running preparation rather than starting another.
    if (pendingPreparation(err)) {
      notify(t('simulations.toast.restartPreparing', { name }), 'info')
      return
    }
    throw err
  }
}

const runStop = async (sim, name) => {
  notify(t('simulations.toast.stopping', { name }), 'info')
  try {
    await stopSimulation({ simulation_id: sim.simulation_id })
    notify(t('simulations.toast.stopped', { name }), 'success')
  } catch (err) {
    // A stop answers 202 with pending:true while the monitor finishes
    // publishing the run's terminal state. The axios wrapper rejects any body
    // that says success:false, so this arrives as an error and is not one.
    if (err.response?.data?.pending) {
      notify(t('simulations.toast.stopPending', { name }), 'info')
      return
    }
    throw err
  }
}

const runDelete = async (sim, name) => {
  // force is only for a stale row - one whose saved state claims a run that no
  // longer has a process behind it. It is the flag that makes the backend skip
  // its busy guard, reap the child and remove the directory, so a genuinely
  // live row is sent without it: the delete is refused with 409 busy and the
  // refusal reaches the user as a toast, which is the whole point of the
  // guard. See deleteNeedsForce.
  await deleteSimulation(sim.simulation_id, { force: deleteNeedsForce(sim) })
  simulations.value = simulations.value.filter(
    (row) => row.simulation_id !== sim.simulation_id
  )
  notify(t('simulations.toast.deleted', { name }), 'success')
}

const runPending = async () => {
  if (!pending.value || actionBusy.value) return

  const { kind, sim } = pending.value
  const name = nameOf(sim)
  actionBusy.value = true

  try {
    if (kind === 'restart') await runRestart(sim, name)
    else if (kind === 'stop') await runStop(sim, name)
    else if (kind === 'delete') await runDelete(sim, name)
  } catch (err) {
    notify(
      t(`simulations.toast.${kind}Failed`, {
        name,
        error: err.message || t('common.unknownError')
      }),
      'error'
    )
  } finally {
    actionBusy.value = false
    pending.value = null
    await load()
    settle()
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  load({ showSpinner: true })
})

onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('visibilitychange', onVisibilityChange)
  clearTimeout(refreshTimer)
  clearTimeout(settleTimer)
})
</script>

<style scoped>
.simulations-view {
  max-width: 1360px;
  min-height: 100%;
  margin: 0 auto;
  padding: 32px 24px 56px;
}

.view-head {
  display: flex;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}

.head-text {
  margin-right: auto;
}

.view-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.view-subtitle {
  margin-top: 5px;
  font-size: 13px;
  color: var(--text-muted);
}

.row-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-faint);
}

.refresh-btn {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.refresh-btn:not(:disabled):hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.refresh-btn:disabled {
  opacity: 0.55;
}

.view-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.search-input {
  flex: 1;
  min-width: 240px;
  max-width: 420px;
  padding: 9px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 13px;
}

.search-input::placeholder {
  color: var(--text-faint);
}

.search-input:focus {
  outline: none;
  border-color: var(--border-accent);
  box-shadow: var(--focus-shadow);
}

.filter-tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--bg-inset);
  border-radius: var(--radius-md);
}

.filter-tab {
  padding: 6px 16px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}

.filter-tab:hover {
  color: var(--text-primary);
}

.filter-tab.is-active {
  background: var(--bg-raised);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
}

.load-error {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--danger-soft);
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--danger);
}

.inline-retry {
  padding: 4px 12px;
  background: transparent;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-sm);
  color: var(--danger);
  font-size: 12px;
  font-weight: 600;
}

.inline-retry:hover {
  background: var(--danger);
  color: var(--text-inverse);
}

@media (max-width: 640px) {
  .simulations-view {
    padding: 20px 12px 40px;
  }
}

/* Toasts live in #app-modals, which is a fixed full-viewport layer, so they
   are positioned against it rather than against this view. Teleported nodes
   keep this component's scope id, so these rules still reach them. */
.toast-stack {
  position: absolute;
  right: 24px;
  bottom: 24px;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(380px, calc(100vw - 32px));
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-left-width: 3px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  font-size: 13px;
  color: var(--text-primary);
}

.toast.is-info {
  border-left-color: var(--info);
}

.toast.is-success {
  border-left-color: var(--success);
}

.toast.is-error {
  border-left-color: var(--danger);
  color: var(--danger);
}

.toast-text {
  flex: 1;
  line-height: 1.45;
}

.toast-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  padding: 0;
  background: transparent;
  border: none;
  color: var(--text-muted);
}

.toast-close .icon {
  width: 11px;
  height: 11px;
}

.toast-close:hover {
  color: var(--text-primary);
}
</style>
