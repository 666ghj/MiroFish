<template>
  <div class="reports-view">
    <header class="view-head">
      <div class="head-text">
        <h1 class="view-title">{{ $t('reportsList.title') }}</h1>
        <p class="view-subtitle">{{ $t('reportsList.subtitle') }}</p>
      </div>

      <span class="row-count">{{ $t('reportsList.count', { count: reports.length }) }}</span>

      <button type="button" class="refresh-btn" :disabled="loading" @click="load(true)">
        {{ $t('simulations.refresh') }}
      </button>
    </header>

    <p v-if="loadError" class="load-error">
      {{ $t('reportsList.loadFailed', { error: loadError }) }}
      <button type="button" class="inline-retry" @click="load(true)">{{ $t('common.retry') }}</button>
    </p>

    <div class="table-card">
      <div v-if="loading && !reports.length" class="table-state">
        <span class="spinner" />
        {{ $t('reportsList.loading') }}
      </div>

      <div v-else-if="!reports.length" class="table-state is-empty">
        <strong>{{ $t('reportsList.empty') }}</strong>
        <span>{{ $t('reportsList.emptyDesc') }}</span>
        <router-link class="state-action" to="/simulations">
          {{ $t('reportsList.emptyAction') }}
        </router-link>
      </div>

      <div v-else class="table-scroll">
        <table class="report-table">
          <thead>
            <tr>
              <th scope="col">{{ $t('reportsList.columnReport') }}</th>
              <th scope="col">{{ $t('reportsList.columnSimulation') }}</th>
              <th scope="col">{{ $t('reportsList.columnSections') }}</th>
              <th scope="col">{{ $t('reportsList.columnCreated') }}</th>
              <th scope="col" class="col-actions">{{ $t('reportsList.columnActions') }}</th>
            </tr>
          </thead>

          <tbody>
            <tr v-for="report in reports" :key="report.report_id">
              <td class="cell-report">
                <div class="stack">
                  <span class="report-title">{{ titleOf(report) }}</span>
                  <span class="report-status" :class="statusTone(report.status)">
                    {{ statusLabel(report.status) }}
                  </span>
                </div>
              </td>

              <td class="cell-sim">
                <router-link
                  class="sim-link"
                  :to="{ name: 'Simulation', params: { simulationId: report.simulation_id } }"
                  :title="report.simulation_id"
                >
                  {{ formatSimulationId(report.simulation_id) }}
                </router-link>
              </td>

              <td class="cell-sections">
                {{ $t('reportsList.sectionCount', { count: sectionCount(report) }) }}
              </td>

              <td class="cell-created">{{ formatTimestamp(report.created_at) }}</td>

              <td class="cell-actions">
                <div class="action-row">
                  <router-link
                    class="primary-btn"
                    :to="{ name: 'Report', params: { reportId: report.report_id } }"
                  >
                    {{ $t('reportsList.open') }}
                  </router-link>
                  <button type="button" class="danger-btn" @click="pending = report">
                    {{ $t('reportsList.delete') }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <ConfirmDialog
      :open="Boolean(pending)"
      :title="$t('reportsList.deleteTitle')"
      :body="pending ? $t('reportsList.deleteBody', { name: titleOf(pending) }) : ''"
      :confirm-label="$t('reportsList.deleteConfirm')"
      :busy="actionBusy"
      @confirm="confirmDelete"
      @cancel="pending = null"
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
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '../components/simulations/ConfirmDialog.vue'
import { deleteReport, listReports } from '../api/report'
import { formatSimulationId, formatTimestamp } from '../utils/simulationFormat'

const { t } = useI18n()

const REPORT_LIMIT = 100
const TOAST_TIMEOUT_MS = 6000

const reports = ref([])
const loading = ref(false)
const loadError = ref('')
const pending = ref(null)
const actionBusy = ref(false)
const toasts = ref([])

let toastSeq = 0

const dismiss = (id) => {
  toasts.value = toasts.value.filter((toast) => toast.id !== id)
}

const notify = (text, tone = 'info') => {
  const id = ++toastSeq
  toasts.value.push({ id, text, tone })
  setTimeout(() => dismiss(id), TOAST_TIMEOUT_MS)
}

const titleOf = (report) => report?.outline?.title || t('reportsList.untitled')

const sectionCount = (report) => report?.outline?.sections?.length || 0

// The report lifecycle reuses the shared status vocabulary, so the labels come
// from the shared keys rather than a second set of near-identical ones.
const statusLabel = (status) => {
  switch (status) {
    case 'completed':
      return t('common.completed')
    case 'failed':
      return t('common.failed')
    case 'pending':
      return t('common.pending')
    case 'planning':
    case 'generating':
      return t('common.processing')
    default:
      return t('common.unknown')
  }
}

const statusTone = (status) => {
  if (status === 'completed') return 'is-complete'
  if (status === 'failed') return 'is-failed'
  return 'is-pending'
}

const load = async (showSpinner = false) => {
  if (showSpinner) loading.value = true

  try {
    const res = await listReports({ limit: REPORT_LIMIT })
    reports.value = Array.isArray(res.data) ? res.data : []
    loadError.value = ''
  } catch (err) {
    loadError.value = err.message || t('common.unknownError')
  } finally {
    loading.value = false
  }
}

const confirmDelete = async () => {
  if (!pending.value || actionBusy.value) return

  const report = pending.value
  const name = titleOf(report)
  actionBusy.value = true

  try {
    await deleteReport(report.report_id)
    reports.value = reports.value.filter((row) => row.report_id !== report.report_id)
    notify(t('reportsList.deleted', { name }), 'success')
  } catch (err) {
    notify(
      t('reportsList.deleteFailed', { name, error: err.message || t('common.unknownError') }),
      'error'
    )
  } finally {
    actionBusy.value = false
    pending.value = null
  }
}

onMounted(() => load(true))
</script>

<style scoped>
.reports-view {
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

.table-scroll {
  overflow-x: auto;
}

.report-table {
  width: 100%;
  min-width: 820px;
  border-collapse: collapse;
}

.report-table th {
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

.report-table th:first-child {
  border-top-left-radius: var(--radius-xl);
}

.report-table th:last-child {
  border-top-right-radius: var(--radius-xl);
}

.report-table td {
  padding: 16px 18px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
  color: var(--text-secondary);
  vertical-align: top;
}

.report-table tbody tr:last-child td {
  border-bottom: none;
}

.report-table tbody tr:hover td {
  background: var(--bg-hover);
}

.stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.cell-report {
  max-width: 420px;
}

.report-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.report-status {
  padding: 3px 9px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
}

.report-status.is-complete {
  border-color: var(--success-border);
  background: var(--success-soft);
  color: var(--success);
}

.report-status.is-failed {
  border-color: var(--danger-border);
  background: var(--danger-soft);
  color: var(--danger);
}

.report-status.is-pending {
  border-color: var(--warning-border);
  background: var(--warning-soft);
  color: var(--warning);
}

.sim-link {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-link);
}

.cell-sections,
.cell-created {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.col-actions,
.cell-actions {
  text-align: right;
  white-space: nowrap;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.primary-btn {
  display: inline-flex;
  align-items: center;
  padding: 7px 16px;
  background: var(--accent);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--text-on-accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.primary-btn:hover {
  background: var(--accent-hover);
  color: var(--text-on-accent);
}

.danger-btn {
  padding: 7px 14px;
  background: transparent;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
}

.danger-btn:hover {
  background: var(--danger);
  color: var(--text-inverse);
}

/* Toasts live in #app-modals, a fixed full-viewport layer, and keep this
   component's scope id through the teleport. */
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

.toast.is-info { border-left-color: var(--info); }
.toast.is-success { border-left-color: var(--success); }

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

@media (max-width: 640px) {
  .reports-view {
    padding: 20px 12px 40px;
  }
}
</style>
