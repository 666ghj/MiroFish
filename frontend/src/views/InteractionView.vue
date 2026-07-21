<template>
  <div class="main-view">
    <WorkspaceHeader
      v-model="viewMode"
      :step="5"
      :stepName="String($tm('main.stepNames')[4] || '')"
      :statusVariant="statusVariant"
      :statusLabel="statusLabel"
      @brand-click="router.push('/')"
    >
      <template #right>
        <LanguageSwitcher />
      </template>
    </WorkspaceHeader>

    <WorkspaceLayout :viewMode="viewMode">
      <template #graph>
        <GraphPanel
          :graphData="graphData"
          :projectData="projectData"
          :loading="graphLoading"
          :currentPhase="5"
          :isSimulating="false"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </template>

      <template #content>
        <Step5Interaction
          :reportId="currentReportId"
          :simulationId="simulationId"
          :systemLogs="systemLogs"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </template>
    </WorkspaceLayout>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import WorkspaceHeader   from '../components/workspace/WorkspaceHeader.vue'
import WorkspaceLayout   from '../components/workspace/WorkspaceLayout.vue'
import GraphPanel        from '../components/GraphPanel.vue'
import Step5Interaction  from '../components/Step5Interaction.vue'
import LanguageSwitcher  from '../components/LanguageSwitcher.vue'

import { useWorkspaceShell } from '../composables/useWorkspaceShell'

import { getProject, getGraphData } from '../api/graph'
import { getSimulation } from '../api/simulation'
import { getReport } from '../api/report'

const { t } = useI18n()
const route  = useRoute()
const router = useRouter()

// ── Shell compartilhado — default 'workbench' (view de interação profunda) ───
const { viewMode, systemLogs, addLog, toggleMaximize } = useWorkspaceShell('workbench')

// ── Data state ─────────────────────────────────────────────────────────────────
const currentReportId = ref(route.params.reportId)
const simulationId    = ref(null)
const projectData     = ref(null)
const graphData       = ref(null)
const graphLoading    = ref(false)
// 'ready': aguardando interação; 'processing': respondendo; 'completed'; 'error'
const currentStatus   = ref('ready')

// ── Status ─────────────────────────────────────────────────────────────────────
// 'ready' → 'idle' (dot cinza): aguardando input
const statusVariant = computed(() => {
  if (currentStatus.value === 'ready') return 'idle'
  return currentStatus.value
})

const statusLabel = computed(() => {
  if (currentStatus.value === 'error')      return 'Error'
  if (currentStatus.value === 'completed')  return 'Completed'
  if (currentStatus.value === 'processing') return 'Processing'
  return 'Ready'
})

const updateStatus = (status) => { currentStatus.value = status }

// ── Data loading ───────────────────────────────────────────────────────────────
const loadReportData = async () => {
  try {
    addLog(t('log.loadReportData', { id: currentReportId.value }))

    const reportRes = await getReport(currentReportId.value)
    if (reportRes.success && reportRes.data) {
      simulationId.value = reportRes.data.simulation_id

      if (simulationId.value) {
        const simRes = await getSimulation(simulationId.value)
        if (simRes.success && simRes.data?.project_id) {
          const projRes = await getProject(simRes.data.project_id)
          if (projRes.success && projRes.data) {
            projectData.value = projRes.data
            addLog(t('log.projectLoadSuccess', { id: projRes.data.project_id }))
            if (projRes.data.graph_id) await loadGraph(projRes.data.graph_id)
          }
        }
      }
    } else {
      addLog(t('log.getReportInfoFailed', { error: reportRes.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('log.loadException', { error: err.message }))
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog(t('log.graphDataLoadSuccess'))
    }
  } catch (err) {
    addLog(t('log.graphLoadFailed', { error: err.message }))
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) loadGraph(projectData.value.graph_id)
}

watch(() => route.params.reportId, (newId) => {
  if (newId && newId !== currentReportId.value) {
    currentReportId.value = newId
    loadReportData()
  }
})

onMounted(() => {
  addLog(t('log.interactionViewInit'))
  loadReportData()
})
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FFF;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}
</style>
