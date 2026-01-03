<template>
  <div class="history-view">
    <header class="header">
      <div class="brand" @click="router.push('/')">MIROFISH</div>
      <div class="actions">
        <button class="btn" @click="refresh" :disabled="loading">{{ loading ? 'Loading…' : 'Refresh' }}</button>
      </div>
    </header>

    <main class="content">
      <div v-if="error" class="error">
        {{ error }}
      </div>

      <div class="grid">
        <section class="panel">
          <div class="panel-title">Projects</div>
          <div class="panel-sub">
            {{ projects.length }} items
            <span v-if="selectedProject" class="selected-pill">Selected: {{ selectedProject.name }}</span>
          </div>

          <div class="table">
            <div class="row head">
              <div>ID</div>
              <div>Name</div>
              <div>Status</div>
              <div class="right">Actions</div>
            </div>
            <div
              v-for="p in projects"
              :key="p.project_id"
              class="row selectable"
              :class="{ selected: p.project_id === selectedProjectId }"
              @click="selectProject(p.project_id)"
            >
              <div class="mono">{{ p.project_id }}</div>
              <div class="truncate">{{ p.name }}</div>
              <div class="status" :class="`s-${p.status}`">{{ p.status }}</div>
              <div class="right">
                <button class="link" @click.stop="openProject(p.project_id)">Open</button>
                <button
                  v-if="canResumeProject(p)"
                  class="link"
                  @click.stop="resumeProject(p.project_id)"
                >
                  Resume
                </button>
              </div>
            </div>
            <div v-if="projects.length === 0 && !loading" class="empty">
              No projects found. Go back to Home to create one.
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-title">Simulations</div>
          <div class="panel-sub">
            <span v-if="!selectedProjectId">Select a project to view simulations.</span>
            <span v-else>{{ simulations.length }} items</span>
            <span v-if="selectedSimulation" class="selected-pill">Selected: {{ selectedSimulation.simulation_id }}</span>
          </div>

          <div class="table">
            <div class="row head">
              <div>ID</div>
              <div>Status</div>
              <div>Agents</div>
              <div class="right">Actions</div>
            </div>
            <div
              v-for="s in simulations"
              :key="s.simulation_id"
              class="row selectable"
              :class="{ selected: s.simulation_id === selectedSimulationId }"
              @click="selectSimulation(s.simulation_id)"
            >
              <div class="mono">{{ s.simulation_id }}</div>
              <div class="status" :class="`s-${s.status}`">{{ s.status }}</div>
              <div class="mono">{{ formatAgentsCount(s) }}</div>
              <div class="right">
                <button class="link" @click.stop="openSimulation(s.simulation_id)">Step 2</button>
                <button class="link" @click.stop="openSimulationRun(s.simulation_id)">Step 3</button>
                <button class="link" @click.stop="branchFromSimulation(s.simulation_id)" :disabled="loading">
                  Branch
                </button>
              </div>
            </div>
            <div v-if="selectedProjectId && simulations.length === 0 && !loading" class="empty">
              No simulations found for this project.
            </div>
            <div v-if="!selectedProjectId && !loading" class="empty">Select a project first.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-title">Reports</div>
          <div class="panel-sub">
            <span v-if="!selectedSimulationId">Select a simulation to view reports.</span>
            <span v-else>{{ reports.length }} items</span>
          </div>

          <div class="table">
            <div class="row head">
              <div>ID</div>
              <div>Simulation</div>
              <div>Status</div>
              <div class="right">Actions</div>
            </div>
            <div v-for="r in reports" :key="r.report_id" class="row">
              <div class="mono">{{ r.report_id }}</div>
              <div class="mono">{{ r.simulation_id }}</div>
              <div class="status" :class="`s-${r.status}`">{{ r.status }}</div>
              <div class="right">
                <button class="link" @click="openReport(r.report_id)">
                  {{ r.status === 'completed' ? 'View' : 'Continue' }}
                </button>
                <button class="link" @click="openInteraction(r.report_id)">Chat</button>
                <button class="link" @click="regenerateReportForSimulation(r.simulation_id)" :disabled="loading">
                  Regenerate
                </button>
              </div>
            </div>
            <div v-if="selectedSimulationId && reports.length === 0 && !loading" class="empty">
              No reports found for this simulation.
            </div>
            <div v-if="!selectedSimulationId && !loading" class="empty">Select a simulation first.</div>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { listProjects, resumeBuildGraph } from '../api/graph'
import { branchSimulation, listSimulations } from '../api/simulation'
import { generateReport, listReports } from '../api/report'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const error = ref('')
const projects = ref([])
const simulations = ref([])
const reports = ref([])

const selectedProjectId = ref(typeof route.query.project_id === 'string' ? route.query.project_id : '')
const selectedSimulationId = ref(typeof route.query.simulation_id === 'string' ? route.query.simulation_id : '')

const selectedProject = computed(
  () => projects.value.find((p) => p.project_id === selectedProjectId.value) || null
)
const selectedSimulation = computed(
  () => simulations.value.find((s) => s.simulation_id === selectedSimulationId.value) || null
)

watch(
  [selectedProjectId, selectedSimulationId],
  ([projectId, simulationId]) => {
    const nextQuery = { ...route.query }
    if (projectId) nextQuery.project_id = projectId
    else delete nextQuery.project_id
    if (simulationId) nextQuery.simulation_id = simulationId
    else delete nextQuery.simulation_id
    router.replace({ query: nextQuery })
  }
)

const formatAgentsCount = (s) => {
  if (!s) return '-'
  const profiles = Number(s.profiles_count || 0)
  const entities = Number(s.entities_count || 0)
  if (profiles > 0) return `${profiles} profiles`
  if (entities > 0) return `${entities} entities`
  return '-'
}

const canResumeProject = (p) => {
  if (!p) return false
  return (
    (p.status === 'graph_building' || p.status === 'failed') &&
    (p.graph_build_task_id || p.graph_id)
  )
}

const resumeProject = async (projectId) => {
  loading.value = true
  error.value = ''
  try {
    await resumeBuildGraph({ project_id: projectId })
    router.push({ name: 'Process', params: { projectId } })
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const loadSimulations = async (projectId) => {
  if (!projectId) {
    simulations.value = []
    selectedSimulationId.value = ''
    reports.value = []
    return
  }

  const sRes = await listSimulations(projectId)
  simulations.value = sRes.data || []

  if (selectedSimulationId.value && simulations.value.some((s) => s.simulation_id === selectedSimulationId.value)) {
    // keep
  } else {
    selectedSimulationId.value = simulations.value[0]?.simulation_id || ''
  }

  await loadReports(selectedSimulationId.value)
}

const loadReports = async (simulationId) => {
  if (!simulationId) {
    reports.value = []
    return
  }
  const rRes = await listReports(simulationId, 100)
  reports.value = rRes.data || []
}

const regenerateReportForSimulation = async (simulationId) => {
  if (!simulationId || loading.value) return
  const confirmed = window.confirm('将基于该模拟重新生成一份全新报告（会生成新的 Report ID，旧报告会保留在历史记录中）。继续？')
  if (!confirmed) return
  loading.value = true
  error.value = ''
  try {
    const res = await generateReport({ simulation_id: simulationId, force_regenerate: true })
    const newReportId = res?.data?.report_id
    if (newReportId) {
      router.push({ name: 'Report', params: { reportId: newReportId } })
    } else {
      error.value = '重新生成失败：未返回 report_id'
    }
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const branchFromSimulation = async (simulationId) => {
  if (!simulationId || loading.value) return
  const confirmed = window.confirm('将基于该模拟创建一个新的“安全分支”（新 Simulation ID，保留原模拟所有数据）。继续？')
  if (!confirmed) return
  loading.value = true
  error.value = ''
  try {
    const res = await branchSimulation({ source_simulation_id: simulationId })
    const newSimulationId = res?.data?.simulation_id
    if (!newSimulationId) {
      error.value = '创建分支失败：未返回 simulation_id'
      return
    }
    await loadSimulations(selectedProjectId.value)
    selectedSimulationId.value = newSimulationId
    await loadReports(newSimulationId)
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const selectProject = async (projectId) => {
  if (selectedProjectId.value === projectId) return
  selectedProjectId.value = projectId
  selectedSimulationId.value = ''
  reports.value = []
  loading.value = true
  error.value = ''
  try {
    await loadSimulations(projectId)
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const selectSimulation = async (simulationId) => {
  if (selectedSimulationId.value === simulationId) return
  selectedSimulationId.value = simulationId
  loading.value = true
  error.value = ''
  try {
    await loadReports(simulationId)
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const refresh = async () => {
  loading.value = true
  error.value = ''
  try {
    const pRes = await listProjects(100)
    projects.value = pRes.data || []
    if (selectedProjectId.value && projects.value.some((p) => p.project_id === selectedProjectId.value)) {
      // keep selected project
    } else {
      selectedProjectId.value = projects.value[0]?.project_id || ''
    }

    await loadSimulations(selectedProjectId.value)
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const openProject = (projectId) => router.push({ name: 'Process', params: { projectId } })
const openSimulation = (simulationId) => router.push({ name: 'Simulation', params: { simulationId } })
const openSimulationRun = (simulationId) =>
  router.push({ name: 'SimulationRun', params: { simulationId }, query: { autoStart: '0' } })
const openReport = (reportId) => router.push({ name: 'Report', params: { reportId } })
const openInteraction = (reportId) => router.push({ name: 'Interaction', params: { reportId } })

onMounted(refresh)
</script>

<style scoped>
.history-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.header {
  height: 60px;
  border-bottom: 1px solid #eaeaea;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}

.btn {
  border: 1px solid #e5e7eb;
  background: #ffffff;
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.content {
  padding: 16px 24px 24px 24px;
  overflow: auto;
}

.error {
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #991b1b;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}

@media (min-width: 1100px) {
  .grid {
    grid-template-columns: 1fr 1fr 1fr;
  }
}

.panel {
  border: 1px solid #eaeaea;
  border-radius: 12px;
  padding: 12px;
  background: #ffffff;
  min-height: 260px;
}

.panel-title {
  font-weight: 800;
  letter-spacing: 0.5px;
}

.panel-sub {
  margin-top: 4px;
  color: #6b7280;
  font-size: 12px;
}

.table {
  margin-top: 10px;
  border-top: 1px solid #f3f4f6;
}

.row {
  display: grid;
  grid-template-columns: 1.2fr 1.2fr 0.8fr 0.8fr;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid #f3f4f6;
  align-items: center;
  font-size: 12px;
}

.row.selectable {
  cursor: pointer;
}

.row.selectable:hover {
  background: #f9fafb;
}

.row.selected {
  background: #eff6ff;
}

.row.head {
  font-weight: 800;
  color: #111827;
  position: sticky;
  top: 0;
  background: #ffffff;
  z-index: 2;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.truncate {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.right {
  text-align: right;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.link {
  border: none;
  background: transparent;
  color: #2563eb;
  font-weight: 700;
  cursor: pointer;
  padding: 4px 6px;
}

.link:hover {
  text-decoration: underline;
}

.status {
  font-weight: 700;
  text-transform: lowercase;
  color: #374151;
}

.selected-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 10px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  font-size: 11px;
  color: #374151;
}

.s-completed,
.s-ready,
.s-graph_completed {
  color: #065f46;
}

.s-failed,
.s-error {
  color: #b91c1c;
}

.empty {
  padding: 16px 0;
  color: #9ca3af;
  font-size: 12px;
}
</style>
