<template>
  <div class="main-view">
    <teleport to="#nav-context">
      <div class="view-switcher">
        <button
          v-for="mode in ['graph', 'split', 'workbench']"
          :key="mode"
          class="switch-btn"
          :class="{ active: viewMode === mode }"
          @click="viewMode = mode"
        >
          {{ { graph: $t('main.layoutGraph'), split: $t('main.layoutSplit'), workbench: $t('main.layoutWorkbench') }[mode] }}
        </button>
      </div>
      <span class="nav-step">Step {{ currentStep }}/5</span>
      <span class="nav-step-name">{{ $tm('main.stepNames')[currentStep - 1] }}</span>
      <span class="nav-status" :class="statusClass"><i class="dot" />{{ statusText }}</span>
    </teleport>

    <!-- Main Content Area -->
    <main class="content-area">
      <!-- Left Panel: Graph -->
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <GraphPanel
          :graphData="graphData"
          :loading="graphLoading"
          :currentPhase="currentPhase"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <!-- Right Panel: Step Components -->
      <div class="panel-wrapper right" :style="rightPanelStyle">
        <!-- Step 1: graph build -->
        <Step1GraphBuild
          v-if="currentStep === 1"
          :currentPhase="currentPhase"
          :projectData="projectData"
          :ontologyProgress="ontologyProgress"
          :buildProgress="buildProgress"
          :graphData="graphData"
          :systemLogs="systemLogs"
          :buildFailed="buildFailed"
          :buildError="buildErrorMessage"
          :rebuildRequired="rebuildRequired"
          :retryingBuild="retryingBuild"
          @retry-build="handleRetryBuild"
          @next-step="handleNextStep"
        />
        <!-- Step 2: environment setup -->
        <Step2EnvSetup
          v-else-if="currentStep === 2"
          :projectData="projectData"
          :graphData="graphData"
          :systemLogs="systemLogs"
          @go-back="handleGoBack"
          @next-step="handleNextStep"
          @add-log="addLog"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import GraphPanel from '../components/GraphPanel.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import Step2EnvSetup from '../components/Step2EnvSetup.vue'
import { generateOntology, getProject, buildGraph, getTaskStatus, getGraphData } from '../api/graph'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'

const route = useRoute()
const router = useRouter()
const { t, tm } = useI18n()

// Layout State
const viewMode = ref('split') // graph | split | workbench

// Step State
// 1: graph build, 2: environment setup, 3: run simulation, 4: report
// generation, 5: deep interaction
const currentStep = ref(1)
const stepNames = computed(() => tm('main.stepNames'))

// Data State
const currentProjectId = ref(route.params.projectId)
const loading = ref(false)
const graphLoading = ref(false)
const error = ref('')
const projectData = ref(null)
const graphData = ref(null)
const currentPhase = ref(-1) // -1: Upload, 0: Ontology, 1: Build, 2: Complete
const ontologyProgress = ref(null)
const buildProgress = ref(null)
const systemLogs = ref([])
// The phase says which step the project stands on; it cannot also say the
// build there is dead. Reusing phase 1 for a failed build rendered the build
// card as 'processing, 0%' for good, because nothing polls a project that has
// already failed, so the failure carries its own flag.
const buildFailed = ref(false)
// The failed build's own message. It is deliberately not the page-level error
// ref: that one is written by the project load and by the new-project flow, so
// sharing it rendered an unrelated failure inside the build's failure panel and
// let starting a build wipe an unrelated error off the page.
const buildErrorMessage = ref('')
// Set when the build endpoint answers 409 'recoverable': the interrupted batch
// can no longer be resumed, and only a rebuild clears the project.
const rebuildRequired = ref(false)
const retryingBuild = ref(false)

// Polling timers
let pollTimer = null
let graphPollTimer = null

// --- Computed Layout Styles ---
const leftPanelStyle = computed(() => {
  if (viewMode.value === 'graph') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'workbench') return { width: '0%', opacity: 0, transform: 'translateX(-20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'workbench') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'graph') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

// --- Status Computed ---
const statusClass = computed(() => {
  if (error.value || buildFailed.value) return 'error'
  if (currentPhase.value >= 2) return 'completed'
  return 'processing'
})

const statusText = computed(() => {
  if (error.value || buildFailed.value) return 'Error'
  if (currentPhase.value >= 2) return 'Ready'
  if (currentPhase.value === 1) return 'Building graph'
  if (currentPhase.value === 0) return 'Generating ontology'
  return 'Initializing'
})

// --- Helpers ---
const addLog = (msg) => {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + new Date().getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg })
  // Keep last 100 logs
  if (systemLogs.value.length > 100) {
    systemLogs.value.shift()
  }
}

// --- Layout Methods ---
const toggleMaximize = (target) => {
  if (viewMode.value === target) {
    viewMode.value = 'split'
  } else {
    viewMode.value = target
  }
}

const handleNextStep = (params = {}) => {
  if (currentStep.value < 5) {
    currentStep.value++
    addLog(t('log.enterStep', { step: currentStep.value, name: stepNames.value[currentStep.value - 1] }))

    // Step 2 hands the round count forward when the user overrode the default.
    if (currentStep.value === 3 && params.maxRounds) {
      addLog(t('log.customSimRounds', { rounds: params.maxRounds }))
    }
  }
}

const handleGoBack = () => {
  if (currentStep.value > 1) {
    currentStep.value--
    addLog(t('log.returnToStep', { step: currentStep.value, name: stepNames.value[currentStep.value - 1] }))
  }
}

// --- Data Logic ---

const initProject = async () => {
  addLog('Project view initialized')
  if (currentProjectId.value === 'new') {
    await handleNewProject()
  } else {
    await loadProject()
  }
}

// The backend reads project_name off this form and falls back to the literal
// 'Unnamed Project' when it is missing, which is what every project on the
// instance was called: the upload console never sent one. It has no name field,
// so the closest thing to a title it captures is the first line of the
// requirement, with the first filename standing in when the requirement is
// blank. An over-long line is cut rather than dropped - a truncated name still
// tells two projects apart in the Projects list.
const PROJECT_NAME_MAX = 60
const NAME_ELLIPSIS = '...'

const deriveProjectName = ({ simulationRequirement, files }) => {
  const firstLine = (simulationRequirement || '').trim().split('\n')[0].trim()
  const source = firstLine || (files[0]?.name || '').replace(/\.[^.]+$/, '')
  if (source.length <= PROJECT_NAME_MAX) return source
  // The ellipsis comes out of the budget rather than being added to it:
  // appending it to a full-length slice sent a 63-character name.
  return `${source.slice(0, PROJECT_NAME_MAX - NAME_ELLIPSIS.length).trimEnd()}${NAME_ELLIPSIS}`
}

const handleNewProject = async () => {
  const pending = getPendingUpload()
  if (!pending.isPending || pending.files.length === 0) {
    error.value = 'No pending files found'
    addLog('Failed to start a new project: no pending files found')
    return
  }

  try {
    loading.value = true
    currentPhase.value = 0
    ontologyProgress.value = { message: 'Uploading and analyzing documents' }
    addLog('Uploading files and generating the ontology')

    const formData = new FormData()
    pending.files.forEach(f => formData.append('files', f))
    formData.append('simulation_requirement', pending.simulationRequirement)
    formData.append('project_name', deriveProjectName(pending))

    const res = await generateOntology(formData)
    if (res.success) {
      clearPendingUpload()
      currentProjectId.value = res.data.project_id
      projectData.value = res.data

      router.replace({ name: 'Process', params: { projectId: res.data.project_id } })
      ontologyProgress.value = null
      addLog(`Generated the ontology for project ${res.data.project_id}`)
      await startBuildGraph()
    } else {
      error.value = res.error || 'Ontology generation failed'
      addLog(`Failed to generate the ontology: ${error.value}`)
    }
  } catch (err) {
    error.value = err.message
    addLog(`Failed to create the project: ${err.message}`)
  } finally {
    loading.value = false
  }
}

const loadProject = async () => {
  try {
    loading.value = true
    addLog(`Loading project ${currentProjectId.value}`)
    const res = await getProject(currentProjectId.value)
    if (res.success) {
      projectData.value = res.data
      updatePhaseByStatus(res.data)
      addLog(`Project loaded, status: ${res.data.status}`)

      if (res.data.status === 'ontology_generated' && !res.data.graph_id) {
        await startBuildGraph()
      } else if (res.data.status === 'graph_building' && res.data.graph_build_task_id) {
        startPollingTask(res.data.graph_build_task_id)
      } else if (res.data.graph_id) {
        // Any status with a graph_id, not just 'graph_completed'. A build that
        // failed on its last episode still left every earlier one committed in
        // FalkorDB, so the graph is there to be drawn and refreshGraph would
        // have loaded it on demand anyway.
        await loadGraph(res.data.graph_id)
      }
    } else {
      error.value = res.error
      addLog(`Failed to load the project: ${res.error}`)
    }
  } catch (err) {
    error.value = err.message
    addLog(`Failed to load the project: ${err.message}`)
  } finally {
    loading.value = false
  }
}

// The build's failure is state of its own, not a phase. Step1GraphBuild reads
// it to render the failed build - the message the backend recorded, and the
// two ways out of it - instead of a progress badge no poll will ever move.
const recordBuildFailure = (message, { rebuildOnly = false } = {}) => {
  buildErrorMessage.value = message || 'Graph build failed'
  buildFailed.value = true
  rebuildRequired.value = rebuildOnly
  buildProgress.value = null
}

const clearBuildFailure = () => {
  buildErrorMessage.value = ''
  buildFailed.value = false
  rebuildRequired.value = false
}

// 'failed' used to set the error and leave currentPhase at its initial -1,
// which rendered every step card inactive and left the page with nothing on it
// the user could act on. A failed project is not an empty one: a build that
// timed out on one episode is recorded as failed with its graph_id already on
// disk, so it resumes at the same phase a completed build does and only a
// failure that produced no graph falls back to the build step.
const updatePhaseByStatus = (project) => {
  switch (project.status) {
    case 'created':
    case 'ontology_generated': currentPhase.value = 0; clearBuildFailure(); break;
    case 'graph_building': currentPhase.value = 1; clearBuildFailure(); break;
    case 'graph_completed': currentPhase.value = 2; clearBuildFailure(); break;
    case 'failed':
      // project.error is the one-line str(e) the build recorded, not the
      // traceback the task carries; it is what the failed card renders.
      recordBuildFailure(project.error || 'Project failed')
      currentPhase.value = project.graph_id ? 2 : 1
      break;
  }
}

// A read that only refreshes the cached project. It must not take the page
// down with it: every caller has already published the state it cares about.
const refreshProjectData = async () => {
  try {
    const res = await getProject(currentProjectId.value)
    if (res.success) projectData.value = res.data
  } catch (err) {
    console.warn('Failed to refresh the project:', err)
  }
}

// force is the destructive rebuild: /api/graph/build deletes the graph the run
// left behind and re-ingests every document. The plain call is the safe one -
// on a failed project whose Zep batch is still readable the backend resumes
// that batch, so the episodes already committed are kept.
const startBuildGraph = async ({ force = false } = {}) => {
  try {
    clearBuildFailure()
    currentPhase.value = 1
    buildProgress.value = {
      progress: 0,
      message: force ? 'Rebuilding the graph from scratch' : 'Preparing the graph build'
    }
    addLog(force ? 'Rebuilding the knowledge graph from scratch' : 'Building the knowledge graph')

    const payload = { project_id: currentProjectId.value }
    if (force) payload.force = true

    const res = await buildGraph(payload)
    if (res.success) {
      if (res.data.reused) {
        // 'reused' covers two different situations - a graph that is already
        // complete, and a build still running under an earlier task - and only
        // the project says which. Taking a running build for a finished one is
        // what opens the environment-setup button over a graph that has an id
        // but nothing in it yet.
        buildProgress.value = null

        // This read is the app finding out WHICH of the two it is; it is a read
        // about the build, not the build. It used to sit bare inside the outer
        // try, so a network blip or a backend restart between the POST above
        // and this GET fell into the catch below and painted 'BUILD FAILED'
        // over a build the backend had just confirmed was alive. It answers for
        // itself now, and a failure here costs the page the status - never the
        // build it was following.
        let reusedProject = null
        let reusedReadError = ''
        try {
          const projectRes = await getProject(currentProjectId.value)
          if (projectRes.success) reusedProject = projectRes.data
        } catch (err) {
          reusedReadError = err.message
          addLog(`Could not read the project back after the build request: ${err.message}`)
        }

        if (!reusedProject) {
          // Nothing was learned about the build, and following res.data.task_id
          // here is a dead end rather than a fallback: the likeliest reason this
          // read failed is a backend that is down or restarting, and the task
          // registry is in-memory, so a restarted backend answers
          // GET /api/graph/task/<id> with 404 for the rest of that task's life
          // while the poll only logs it - no progress, no failure, no way out.
          // The page reports what it actually knows and leaves the failure
          // panel's controls to try again with.
          const detail = reusedReadError ? `: ${reusedReadError}` : ''
          recordBuildFailure(`Could not read the project back after the build request${detail}. The build may still be running - reload the page, or start the build again, to find out.`)
          addLog('Could not follow the reused graph build: the project could not be read back')
          return
        }

        projectData.value = reusedProject
        updatePhaseByStatus(reusedProject)

        if (reusedProject.status === 'graph_building') {
          // The project's own task id first; the reused reply names the same
          // build when the project was saved without one.
          const runningTaskId = reusedProject.graph_build_task_id || res.data.task_id
          if (runningTaskId) {
            addLog(`Attached to the graph build task already running: ${runningTaskId}`)
            startPollingTask(runningTaskId)
            return
          }
          // A build in progress that names no task cannot be followed, and
          // leaving the page on the build phase would sit at 0% for good.
          recordBuildFailure('The backend reports a graph build in progress but names no task to follow. Start the build again to take it over.')
          addLog('The reused graph build named no task to follow')
          return
        }

        if (res.data.graph_id) {
          await loadGraph(res.data.graph_id)
        }
        return
      }

      if (res.data.resumed) {
        addLog('Resuming the Zep batch the interrupted build left behind')
      }
      addLog(`Started graph build task ${res.data.task_id}`)
      // Read the project back before the first poll so the cached copy carries
      // the build that has just started. Step1GraphBuild's environment-setup
      // gate reads that status, and a project still remembered as 'failed'
      // would leave the button open over a graph this run is rewriting.
      await refreshProjectData()
      startPollingTask(res.data.task_id)
    } else {
      recordBuildFailure(res.error)
      addLog(`Failed to start the graph build: ${res.error}`)
    }
  } catch (err) {
    // 409 'recoverable' is the backend reporting that it has just marked the
    // stale build failed and that nothing of it is left to resume, so the card
    // stops offering a resume as the way forward.
    recordBuildFailure(err.message, { rebuildOnly: err.response?.data?.recoverable === true })
    addLog(`Failed to start the graph build: ${err.message}`)
  }
}

// The two ways out of a failed build. The plain retry is the resuming one;
// force is the deliberate rebuild, which Step1GraphBuild confirms before it
// emits it.
const handleRetryBuild = async ({ force = false } = {}) => {
  if (retryingBuild.value) return

  retryingBuild.value = true
  try {
    await startBuildGraph({ force })
  } finally {
    retryingBuild.value = false
  }
}

const startGraphPolling = () => {
  addLog('Polling for graph data')
  fetchGraphData()
  graphPollTimer = setInterval(fetchGraphData, 10000)
}

const fetchGraphData = async () => {
  try {
    // Refresh project info to check for graph_id
    const projRes = await getProject(currentProjectId.value)
    if (projRes.success && projRes.data.graph_id) {
      const gRes = await getGraphData(projRes.data.graph_id)
      if (gRes.success) {
        graphData.value = gRes.data
        const nodeCount = gRes.data.node_count || gRes.data.nodes?.length || 0
        const edgeCount = gRes.data.edge_count || gRes.data.edges?.length || 0
        addLog(`Refreshed graph data: ${nodeCount} nodes, ${edgeCount} edges`)
      }
    }
  } catch (err) {
    console.warn('Failed to fetch graph data:', err)
  }
}

const startPollingTask = (taskId) => {
  // A retry can be pressed while an earlier timer is still around; without
  // this each attempt would leave its own interval running.
  stopPolling()
  pollTaskStatus(taskId)
  pollTimer = setInterval(() => pollTaskStatus(taskId), 2000)
}

const pollTaskStatus = async (taskId) => {
  try {
    const res = await getTaskStatus(taskId)
    if (res.success) {
      const task = res.data

      // Log progress message if it changed
      if (task.message && task.message !== buildProgress.value?.message) {
        addLog(task.message)
      }

      buildProgress.value = { progress: task.progress || 0, message: task.message }

      if (task.status === 'completed') {
        addLog('Graph build task completed')
        stopPolling()
        stopGraphPolling() // Stop polling, do final load
        currentPhase.value = 2

        // Final load
        const projRes = await getProject(currentProjectId.value)
        if (projRes.success && projRes.data.graph_id) {
            projectData.value = projRes.data
            await loadGraph(projRes.data.graph_id)
        }
      } else if (task.status === 'failed') {
        stopPolling()
        stopGraphPolling()

        // Recorded before the request below, which can throw: the poll is
        // already stopped, so a follow-up that fails must not leave the card on
        // a progress badge nothing is left to move. task.error is the raw
        // traceback, so the message is the task's own summary line.
        recordBuildFailure(task.message || task.error)
        addLog(`Graph build task failed: ${task.message || task.error}`)

        // Then read the project back rather than trusting the phase the page
        // was on: the build records its failure with graph_id already saved
        // when it got as far as creating the graph, and that is what decides
        // whether the graph can still be drawn and a simulation created from
        // it.
        const projRes = await getProject(currentProjectId.value)
        if (projRes.success) {
          projectData.value = projRes.data
          // Only once the project has caught up with the task. The two are
          // saved one after the other, and a status still reading
          // 'graph_building' would recompute this as a build in progress.
          if (projRes.data.status === 'failed') {
            updatePhaseByStatus(projRes.data)
          }
          if (projRes.data.graph_id) {
            await loadGraph(projRes.data.graph_id)
          }
        }
      }
    }
  } catch (e) {
    console.error(e)
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  addLog(`Loading full graph data: ${graphId}`)
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog('Graph data loaded successfully')
    } else {
      addLog(`Failed to load graph data: ${res.error}`)
    }
  } catch (e) {
    addLog(`Failed to load graph data: ${e.message}`)
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) {
    addLog('Refreshing the graph')
    loadGraph(projectData.value.graph_id)
  }
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const stopGraphPolling = () => {
  if (graphPollTimer) {
    clearInterval(graphPollTimer)
    graphPollTimer = null
    addLog('Graph polling stopped')
  }
}

onMounted(() => {
  initProject()
})

onUnmounted(() => {
  stopPolling()
  stopGraphPolling()
})
</script>

<style scoped>
.main-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Nav context, teleported into the shell's #nav-context region. The block is
   deliberately identical in every routed view so the bar never shifts. */
.view-switcher {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--bg-inset);
  border-radius: var(--radius-md);
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  border-radius: var(--radius-sm);
  transition: color 0.2s, background-color 0.2s;
}

.switch-btn:hover {
  color: var(--text-primary);
}

.switch-btn.active {
  background: var(--bg-raised);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
}

.nav-step {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
}

.nav-step-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-left: -8px;
}

.nav-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.nav-status .dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-pill);
  background: var(--neutral-dot);
}

.nav-status.processing .dot { background: var(--accent); animation: pulse 1s infinite; }
.nav-status.completed .dot { background: var(--success); }
.nav-status.error .dot { background: var(--danger); }
.nav-status.ready .dot { background: var(--info); }

@keyframes pulse { 50% { opacity: 0.5; } }

/* Content */
.content-area {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
  overflow: hidden;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1), opacity 0.3s ease, transform 0.3s ease;
  will-change: width, opacity, transform;
}

.panel-wrapper.left {
  border-right: 1px solid var(--border-subtle);
}
</style>
