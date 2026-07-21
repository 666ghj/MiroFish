<template>
  <div class="main-view">
    <WorkspaceHeader
      v-model="viewMode"
      :step="3"
      :stepName="String($tm('main.stepNames')[2] || '')"
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
          :currentPhase="3"
          :isSimulating="isSimulating"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </template>

      <template #content>
        <Step3Simulation
          :simulationId="currentSimulationId"
          :maxRounds="maxRounds"
          :minutesPerRound="minutesPerRound"
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
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import WorkspaceHeader from '../components/workspace/WorkspaceHeader.vue'
import WorkspaceLayout from '../components/workspace/WorkspaceLayout.vue'
import GraphPanel       from '../components/GraphPanel.vue'
import Step3Simulation  from '../components/Step3Simulation.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'

import { useWorkspaceShell } from '../composables/useWorkspaceShell'

import { getProject, getGraphData } from '../api/graph'
import { getSimulation, getSimulationConfig, stopSimulation, closeSimulationEnv, getEnvStatus } from '../api/simulation'

const { t } = useI18n()
const route  = useRoute()
const router = useRouter()

// ── Shell compartilhado ────────────────────────────────────────────────────────
const { viewMode, systemLogs, addLog, toggleMaximize } = useWorkspaceShell('split')

// ── Data state ─────────────────────────────────────────────────────────────────
const currentSimulationId = ref(route.params.simulationId)
const maxRounds           = ref(route.query.maxRounds ? parseInt(route.query.maxRounds) : null)
const minutesPerRound     = ref(30)
const projectData         = ref(null)
const graphData           = ref(null)
const graphLoading        = ref(false)
const currentStatus       = ref('processing')

// ── Status ─────────────────────────────────────────────────────────────────────
const isSimulating = computed(() => currentStatus.value === 'processing')

const statusVariant = computed(() => currentStatus.value)

const statusLabel = computed(() => {
  if (currentStatus.value === 'error')     return 'Error'
  if (currentStatus.value === 'completed') return 'Completed'
  return 'Running'
})

const updateStatus = (status) => { currentStatus.value = status }

// ── Navigation ─────────────────────────────────────────────────────────────────
const handleGoBack = async () => {
  addLog(t('log.preparingGoBack'))
  stopGraphRefresh()

  try {
    const envStatusRes = await getEnvStatus({ simulation_id: currentSimulationId.value })
    if (envStatusRes.success && envStatusRes.data?.env_alive) {
      addLog(t('log.closingSimEnv'))
      try {
        await closeSimulationEnv({ simulation_id: currentSimulationId.value, timeout: 10 })
        addLog(t('log.simEnvClosed'))
      } catch (closeErr) {
        addLog(t('log.closeSimEnvFailed'))
        try {
          await stopSimulation({ simulation_id: currentSimulationId.value })
          addLog(t('log.simForceStopSuccess'))
        } catch (stopErr) {
          addLog(t('log.forceStopFailed', { error: stopErr.message }))
        }
      }
    } else {
      if (isSimulating.value) {
        addLog(t('log.stoppingSimProcess'))
        try {
          await stopSimulation({ simulation_id: currentSimulationId.value })
          addLog(t('log.simStopped'))
        } catch (err) {
          addLog(t('log.stopSimFailed', { error: err.message }))
        }
      }
    }
  } catch (err) {
    addLog(t('log.checkStatusFailed', { error: err.message }))
  }

  router.push({ name: 'Simulation', params: { simulationId: currentSimulationId.value } })
}

const handleNextStep = () => {
  addLog(t('log.enterStep4'))
}

// ── Graph auto-refresh durante simulação ──────────────────────────────────────
let graphRefreshTimer = null

const startGraphRefresh = () => {
  if (graphRefreshTimer) return
  addLog(t('log.graphRealtimeRefreshStart'))
  graphRefreshTimer = setInterval(refreshGraph, 30000)
}

const stopGraphRefresh = () => {
  if (graphRefreshTimer) {
    clearInterval(graphRefreshTimer)
    graphRefreshTimer = null
    addLog(t('log.graphRealtimeRefreshStop'))
  }
}

watch(isSimulating, (val) => {
  if (val) startGraphRefresh()
  else     stopGraphRefresh()
}, { immediate: true })

// ── Data loading ───────────────────────────────────────────────────────────────
const loadSimulationData = async () => {
  try {
    addLog(t('log.loadingSimData', { id: currentSimulationId.value }))

    const simRes = await getSimulation(currentSimulationId.value)
    if (simRes.success && simRes.data) {
      const simData = simRes.data

      try {
        const configRes = await getSimulationConfig(currentSimulationId.value)
        if (configRes.success && configRes.data?.time_config?.minutes_per_round) {
          minutesPerRound.value = configRes.data.time_config.minutes_per_round
          addLog(t('log.timeConfig', { minutes: minutesPerRound.value }))
        }
      } catch {
        addLog(t('log.timeConfigFetchFailed', { minutes: minutesPerRound.value }))
      }

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
  if (!isSimulating.value) graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      if (!isSimulating.value) addLog(t('log.graphDataLoadSuccess'))
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

onMounted(() => {
  addLog(t('log.simRunViewInit'))
  if (maxRounds.value) addLog(t('log.customRounds', { rounds: maxRounds.value }))
  loadSimulationData()
})

onUnmounted(() => { stopGraphRefresh() })
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
