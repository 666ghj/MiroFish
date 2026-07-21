<template>
  <div class="main-view">
    <WorkspaceHeader
      v-model="viewMode"
      :step="2"
      :stepName="String($tm('main.stepNames')[1] || '')"
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
          :currentPhase="2"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </template>

      <template #content>
        <Step2EnvSetup
          :simulationId="currentSimulationId"
          :projectData="projectData"
          :graphData="graphData"
          :systemLogs="systemLogs"
          @go-back="handleGoBack"
          @next-step="handleNextStep"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </template>
    </WorkspaceLayout>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import WorkspaceHeader from '../components/workspace/WorkspaceHeader.vue'
import WorkspaceLayout from '../components/workspace/WorkspaceLayout.vue'
import GraphPanel      from '../components/GraphPanel.vue'
import Step2EnvSetup   from '../components/Step2EnvSetup.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'

import { useWorkspaceShell } from '../composables/useWorkspaceShell'

import { getProject, getGraphData } from '../api/graph'
import { getSimulation, stopSimulation, getEnvStatus, closeSimulationEnv } from '../api/simulation'

const { t } = useI18n()
const route  = useRoute()
const router = useRouter()

// ── Shell compartilhado ────────────────────────────────────────────────────────
const { viewMode, systemLogs, addLog, toggleMaximize } = useWorkspaceShell('split')

// ── Data state ─────────────────────────────────────────────────────────────────
const currentSimulationId = ref(route.params.simulationId)
const projectData         = ref(null)
const graphData           = ref(null)
const graphLoading        = ref(false)
const currentStatus       = ref('processing')

// ── Status computed ────────────────────────────────────────────────────────────
const statusVariant = computed(() => currentStatus.value)

const statusLabel = computed(() => {
  if (currentStatus.value === 'error')     return 'Error'
  if (currentStatus.value === 'completed') return 'Ready'
  return 'Preparing'
})

const updateStatus = (status) => { currentStatus.value = status }

// ── Navigation ─────────────────────────────────────────────────────────────────
const handleGoBack = () => {
  if (projectData.value?.project_id) {
    router.push({ name: 'Process', params: { projectId: projectData.value.project_id } })
  } else {
    router.push('/')
  }
}

const handleNextStep = (params = {}) => {
  addLog(t('log.enterStep3'))
  if (params.maxRounds) {
    addLog(t('log.customRoundsConfig', { rounds: params.maxRounds }))
  } else {
    addLog(t('log.useAutoRounds'))
  }

  const routeParams = { name: 'SimulationRun', params: { simulationId: currentSimulationId.value } }
  if (params.maxRounds) routeParams.query = { maxRounds: params.maxRounds }
  router.push(routeParams)
}

// ── Simulation cleanup (quando volta do Step 3) ───────────────────────────────
const checkAndStopRunningSimulation = async () => {
  if (!currentSimulationId.value) return
  try {
    const envStatusRes = await getEnvStatus({ simulation_id: currentSimulationId.value })
    if (envStatusRes.success && envStatusRes.data?.env_alive) {
      addLog(t('log.detectedSimEnvRunning'))
      try {
        const closeRes = await closeSimulationEnv({ simulation_id: currentSimulationId.value, timeout: 10 })
        if (closeRes.success) {
          addLog(t('log.simEnvClosed'))
        } else {
          addLog(t('log.closeSimEnvFailedWithError', { error: closeRes.error || t('common.unknownError') }))
          await forceStopSimulation()
        }
      } catch (closeErr) {
        addLog(t('log.closeSimEnvException', { error: closeErr.message }))
        await forceStopSimulation()
      }
    } else {
      const simRes = await getSimulation(currentSimulationId.value)
      if (simRes.success && simRes.data?.status === 'running') {
        addLog(t('log.detectedSimRunning'))
        await forceStopSimulation()
      }
    }
  } catch (err) {
    console.warn('Erro ao verificar status da simulação:', err)
  }
}

const forceStopSimulation = async () => {
  try {
    const stopRes = await stopSimulation({ simulation_id: currentSimulationId.value })
    if (stopRes.success) {
      addLog(t('log.simForceStopSuccess'))
    } else {
      addLog(t('log.forceStopSimFailed', { error: stopRes.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('log.forceStopSimException', { error: err.message }))
  }
}

// ── Data loading ───────────────────────────────────────────────────────────────
const loadSimulationData = async () => {
  try {
    addLog(t('log.loadingSimData', { id: currentSimulationId.value }))
    const simRes = await getSimulation(currentSimulationId.value)
    if (simRes.success && simRes.data) {
      const simData = simRes.data
      if (simData.project_id) {
        const projRes = await getProject(simData.project_id)
        if (projRes.success && projRes.data) {
          projectData.value = projRes.data
          addLog(t('log.projectLoadSuccess', { id: projRes.data.project_id }))
          if (projRes.data.graph_id) await loadGraph(projRes.data.graph_id)
        }
      }
    } else {
      addLog(t('log.loadSimDataFailed', { error: simRes.error || t('common.unknownError') }))
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

onMounted(async () => {
  addLog(t('log.simViewInit'))
  await checkAndStopRunningSimulation()
  loadSimulationData()
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
