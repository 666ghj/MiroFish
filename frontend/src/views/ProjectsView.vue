<template>
  <div class="projects-view">
    <header class="view-head">
      <div class="head-text">
        <h1 class="view-title">{{ $t('projectsList.title') }}</h1>
        <p class="view-subtitle">{{ $t('projectsList.subtitle') }}</p>
      </div>

      <span class="row-count">{{ $t('projectsList.count', { count: projects.length }) }}</span>

      <!-- The nav's Projects entry points here now rather than at the upload
           console, so this list has to carry the way back to it. -->
      <router-link class="new-btn" to="/">{{ $t('projectsList.newProject') }}</router-link>

      <button type="button" class="refresh-btn" :disabled="loading" @click="load(true)">
        {{ $t('simulations.refresh') }}
      </button>
    </header>

    <p v-if="loadError" class="load-error">
      {{ $t('projectsList.loadFailed', { error: loadError }) }}
      <button type="button" class="inline-retry" @click="load(true)">{{ $t('common.retry') }}</button>
    </p>

    <div class="table-card">
      <div v-if="loading && !projects.length" class="table-state">
        <span class="spinner" />
        {{ $t('projectsList.loading') }}
      </div>

      <div v-else-if="!projects.length" class="table-state is-empty">
        <strong>{{ $t('projectsList.empty') }}</strong>
        <span>{{ $t('projectsList.emptyDesc') }}</span>
        <router-link class="state-action" to="/">
          {{ $t('projectsList.emptyAction') }}
        </router-link>
      </div>

      <div v-else class="table-scroll">
        <table class="project-table">
          <thead>
            <tr>
              <th scope="col">{{ $t('projectsList.columnProject') }}</th>
              <th scope="col">{{ $t('projectsList.columnStatus') }}</th>
              <th scope="col">{{ $t('projectsList.columnCreated') }}</th>
              <th scope="col" class="col-actions">{{ $t('projectsList.columnActions') }}</th>
            </tr>
          </thead>

          <tbody>
            <tr v-for="project in projects" :key="project.project_id">
              <td class="cell-project">
                <div class="stack">
                  <span class="project-name">{{ nameOf(project) }}</span>
                  <span class="project-id">{{ project.project_id }}</span>
                </div>
              </td>

              <td class="cell-status">
                <div class="stack">
                  <span class="project-status" :class="statusTone(project.status)">
                    {{ statusLabel(project.status) }}
                  </span>

                  <!-- The graph outlives the build that reported the failure:
                       every episode ingested before the one that timed out is
                       committed, so the row says the project is still usable
                       rather than leaving the status pill to imply it is not. -->
                  <span v-if="project.status === 'failed' && project.graph_id" class="status-note">
                    {{ $t('projectsList.graphAvailable') }}
                  </span>

                  <span v-if="errorNote(project)" class="status-error">{{ errorNote(project) }}</span>
                </div>
              </td>

              <td class="cell-created">{{ formatTimestamp(project.created_at) }}</td>

              <td class="cell-actions">
                <router-link
                  class="primary-btn"
                  :to="{ name: 'Process', params: { projectId: project.project_id } }"
                >
                  {{ $t('projectsList.open') }}
                </router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { listProjects } from '../api/graph'
import { formatTimestamp } from '../utils/simulationFormat'

const { t } = useI18n()

const PROJECT_LIMIT = 100

const projects = ref([])
const loading = ref(false)
const loadError = ref('')

const nameOf = (project) => (project?.name || '').trim() || t('projectsList.untitled')

// The project lifecycle has a vocabulary of its own - ontology, build, graph -
// so unlike the report list this cannot borrow the shared common.* labels.
const statusLabel = (status) => {
  const key = `projectsList.status.${status}`
  const label = t(key)
  return label === key ? t('projectsList.status.unknown') : label
}

// A project keeps whatever str(e) its build raised - endpoint URLs, upstream
// payloads, internal ids - and the build path stores it unscrubbed, unlike the
// ontology path's public_error. So the list shows it only on the row where it
// is the point of the row, and only as much of it as belongs on one line: the
// project's own page is where the whole message is read.
const ERROR_NOTE_MAX = 140
const ERROR_NOTE_ELLIPSIS = '...'

const errorNote = (project) => {
  if (project?.status !== 'failed') return ''
  const text = (project.error || '').replace(/\s+/g, ' ').trim()
  if (text.length <= ERROR_NOTE_MAX) return text
  return `${text.slice(0, ERROR_NOTE_MAX - ERROR_NOTE_ELLIPSIS.length).trimEnd()}${ERROR_NOTE_ELLIPSIS}`
}

const statusTone = (status) => {
  if (status === 'graph_completed') return 'is-complete'
  if (status === 'failed') return 'is-failed'
  return 'is-pending'
}

const load = async (showSpinner = false) => {
  if (showSpinner) loading.value = true

  try {
    const res = await listProjects(PROJECT_LIMIT)
    projects.value = Array.isArray(res.data) ? res.data : []
    loadError.value = ''
  } catch (err) {
    loadError.value = err.message || t('common.unknownError')
  } finally {
    loading.value = false
  }
}

onMounted(() => load(true))
</script>

<style scoped>
.projects-view {
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

.new-btn {
  padding: 8px 16px;
  background: var(--accent);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--text-on-accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.new-btn:hover {
  background: var(--accent-hover);
  color: var(--text-on-accent);
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

.project-table {
  width: 100%;
  min-width: 820px;
  border-collapse: collapse;
}

.project-table th {
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

.project-table th:first-child {
  border-top-left-radius: var(--radius-xl);
}

.project-table th:last-child {
  border-top-right-radius: var(--radius-xl);
}

.project-table td {
  padding: 16px 18px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
  color: var(--text-secondary);
  vertical-align: top;
}

.project-table tbody tr:last-child td {
  border-bottom: none;
}

.project-table tbody tr:hover td {
  background: var(--bg-hover);
}

.stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.cell-project {
  max-width: 420px;
}

.project-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.project-id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-faint);
}

.cell-status {
  max-width: 380px;
}

.project-status {
  padding: 3px 9px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.project-status.is-complete {
  border-color: var(--success-border);
  background: var(--success-soft);
  color: var(--success);
}

.project-status.is-failed {
  border-color: var(--danger-border);
  background: var(--danger-soft);
  color: var(--danger);
}

.project-status.is-pending {
  border-color: var(--warning-border);
  background: var(--warning-soft);
  color: var(--warning);
}

.status-note {
  font-size: 11px;
  font-weight: 600;
  color: var(--success);
}

.status-error {
  font-size: 11px;
  line-height: 1.45;
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
  white-space: nowrap;
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

@media (max-width: 640px) {
  .projects-view {
    padding: 20px 12px 40px;
  }
}
</style>
