import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { simulationEfforts, normalizeSimulationEffort, plannedSimulationRounds, roundsForEffort } from '../src/utils/simulationEffort.js'

// Run the real setup functions with deterministic API, lifecycle and timer boundaries.
// This avoids a DOM dependency while checking the requests and state transitions.
function component(name, names, mocks = {}, props = {}) {
  const source = readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
  const setup = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
    .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
  const timers = new Map()
  const mounted = []
  let timerId = 0
  const context = vm.createContext({
    simulationEfforts, normalizeSimulationEffort, plannedSimulationRounds, roundsForEffort,
    console, Set, Date, JSON, localStorage: { getItem: () => null, setItem() {} },
    ref: value => ({ value }), reactive: value => value,
    computed: getter => ({ get value() { return getter() } }), watch() {},
    nextTick: fn => fn?.(), onMounted: fn => mounted.push(fn), onUnmounted() {},
    defineProps: () => props, defineEmits: () => () => {},
    useRouter: () => ({ push() {} }), useI18n: () => ({ t: key => key }),
    setInterval: fn => { timers.set(++timerId, fn); return timerId },
    clearInterval: id => timers.delete(id), ...mocks,
  })
  vm.runInContext(`${setup}\nglobalThis.subject = { ${names.join(', ')} };`, context)
  return { ...context.subject, timers, mounted }
}

const ok = data => ({ success: true, data })

test('preparation reload shows saved profiles and error without restarting; resume omits force', async () => {
  const requests = []
  const c = component('Step2EnvSetup', ['restorePreparation', 'recoverPreparation', 'prepareError', 'profiles', 'taskId'], {
    getPrepareStatus: async () => ok({ status: 'failed', error: 'Provider quota', task_id: 'old' }),
    getSimulationProfilesRealtime: async () => ok({ profiles: [{ name: 'Saved' }], total_expected: 2 }),
    prepareSimulation: async data => { requests.push(data); return ok({ task_id: 'resumed' }) },
  }, { simulationId: 'sim' })
  await c.restorePreparation()
  assert.equal(c.prepareError.value, 'Provider quota')
  assert.equal(c.profiles.value.length, 1)
  assert.equal(requests.length, 0)
  await c.recoverPreparation()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].force_regenerate, undefined)
  assert.equal(c.taskId.value, 'resumed')
  assert.equal(c.profiles.value.length, 1)
})

for (const status of ['completed', 'running', 'failed']) {
  test(`simulation refresh restores ${status} without POST start`, async () => {
    let starts = 0
    const c = component('Step3Simulation', ['restoreSimulation', 'startError', 'phase'], {
      getRunStatus: async () => ok({ runner_status: status, error: status === 'failed' ? 'Model failed' : null }),
      getRunStatusDetail: async () => ok({ all_actions: [] }),
      startSimulation: async () => { starts++; return ok({}) },
    }, { simulationId: 'sim' })
    await c.restoreSimulation()
    assert.equal(starts, 0)
    if (status === 'failed') assert.equal(c.startError.value, 'Model failed')
    if (status === 'completed') assert.equal(c.phase.value, 2)
  })
}

test('simulation connection recovery reads state, never force restarts a live run', async () => {
  let reads = 0
  let starts = 0
  const c = component('Step3Simulation', ['restoreSimulation', 'recoverSimulation', 'connectionError'], {
    getRunStatus: async () => { if (++reads === 1) throw new Error('Disconnected'); return ok({ runner_status: 'running' }) },
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    startSimulation: async () => { starts++; return ok({}) },
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  assert.equal(c.connectionError.value, true)
  await c.recoverSimulation()
  assert.equal(reads, 2)
  assert.equal(starts, 0)
})

test('failed report stops polling and resumes the same report preserving sections', async () => {
  let failed = true
  const requests = []
  const c = component('Step4Report', ['startPolling', 'fetchReportStatus', 'recoverReport', 'reportError', 'generatedSections'], {
    getReport: async () => ok({ status: failed ? 'failed' : 'generating', simulation_id: 'sim', error: 'Tool failed' }),
    getAgentLog: async () => ok({ logs: [], from_line: 0 }),
    getConsoleLog: async () => ok({ logs: [], from_line: 0 }),
    generateReport: async data => { requests.push(data); failed = false; return ok({ report_id: 'report' }) },
  }, { reportId: 'report', simulationId: 'sim' })
  c.generatedSections.value[1] = 'Saved section'
  c.startPolling()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(c.reportError.value, 'Tool failed')
  assert.equal(c.timers.size, 0)
  await c.recoverReport()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].resume, true)
  assert.equal(requests[0].report_id, 'report')
  assert.equal(c.generatedSections.value[1], 'Saved section')
})

test('chat retry retains the user message and excludes errors from conversation context', async () => {
  const requests = []
  const c = component('Step5Interaction', ['sendMessage', 'retryMessage', 'chatInput', 'chatHistory'], {
    chatWithReport: async data => { requests.push(data); if (requests.length === 1) throw new Error('Offline'); return ok({ response: 'Reply' }) },
  }, { reportId: 'report', simulationId: 'sim' })
  c.chatInput.value = 'Question'
  await c.sendMessage()
  assert.equal(c.chatHistory.value.length, 1)
  assert.equal(c.chatHistory.value[0].error, 'Offline')
  await c.retryMessage(c.chatHistory.value[0])
  assert.equal(c.chatHistory.value.length, 2)
  assert.equal(c.chatHistory.value.filter(msg => msg.role === 'user').length, 1)
  assert.equal(requests[1].chat_history.length, 0)
  await c.retryMessage(c.chatHistory.value[0])
  assert.equal(requests.length, 2, 'successful messages cannot be retried')
})

test('survey retry sends only unanswered agents and retains successful answers', async () => {
  const requests = []
  const c = component('Step5Interaction', ['submitSurvey', 'retrySurvey', 'selectedAgents', 'surveyQuestion', 'surveyResults'], {
    interviewAgents: async data => { requests.push(data); return ok({ results: requests.length === 1
      ? { reddit_0: { response: 'First' }, reddit_1: { error: 'Timed out' } }
      : { reddit_1: { response: 'Second' } } }) },
  }, { simulationId: 'sim' })
  c.selectedAgents.value = new Set([0, 1])
  c.surveyQuestion.value = 'Why?'
  await c.submitSurvey()
  assert.equal(c.surveyResults.value.length, 1)
  await c.retrySurvey()
  assert.equal(requests[1].interviews.length, 1)
  assert.equal(requests[1].interviews[0].agent_id, 1)
  assert.equal(c.surveyResults.value.length, 2)
})

test('graph recovery resumes without force and retains the displayed graph', async () => {
  const requests = []
  const c = component('../views/MainView', ['recoverProject', 'projectData', 'graphData', 'currentProjectId'], {
    useRoute: () => ({ params: { projectId: 'project' } }),
    buildGraph: async data => { requests.push(data); return ok({ task_id: 'task' }) },
    getTaskStatus: async () => ok({ status: 'processing', progress: 50 }),
  })
  c.projectData.value = { project_id: 'project', status: 'failed', graph_id: 'graph', ontology: { entity_types: [] } }
  c.graphData.value = { nodes: [{ id: 'saved' }] }
  await c.recoverProject()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].project_id, 'project')
  assert.equal(requests[0].force, undefined)
  assert.equal(c.graphData.value.nodes.length, 1)
})

test('returning to preparation reuses the saved simulation', async () => {
  let creates = 0
  let destination
  const c = component('Step1GraphBuild', ['handleEnterEnvSetup'], {
    useRouter: () => ({ push: value => { destination = value } }),
    listSimulations: async () => ok([{ graph_id: 'graph', simulation_id: 'saved-sim' }]),
    createSimulation: async () => { creates++; return ok({ simulation_id: 'new' }) },
  }, { projectData: { project_id: 'project', graph_id: 'graph' } })
  await c.handleEnterEnvSetup()
  assert.equal(creates, 0)
  assert.equal(destination.params.simulationId, 'saved-sim')
})

test('entering report generation does not force regeneration', async () => {
  let request
  const c = component('Step3Simulation', ['handleNextStep', 'runStatus'], {
    generateReport: async data => { request = data; return ok({ report_id: 'existing' }) },
  }, { simulationId: 'sim' })
  c.runStatus.value = { runner_status: 'completed' }
  await c.handleNextStep()
  assert.equal(request.simulation_id, 'sim')
  assert.equal(request.force_regenerate, undefined)
})

test('ontology failure adopts saved project and resumes its documents without uploading again', async () => {
  let uploads = 0
  let resumes = 0
  let resumed = false
  const failure = new Error('Provider unavailable')
  failure.response = { data: { data: { project_id: 'saved-project' } } }
  const c = component('../views/MainView', ['handleNewProject', 'recoverProject', 'currentProjectId', 'error'], {
    useRoute: () => ({ params: { projectId: 'new' } }),
    useRouter: () => ({ replace() {}, push() {} }),
    FormData: class { append() {} },
    getPendingUpload: () => ({ isPending: true, files: ['document'], simulationRequirement: 'Research' }),
    generateOntology: async () => { uploads++; throw failure },
    getProject: async () => ok({ project_id: 'saved-project', ontology: resumed ? { entity_types: [] } : null }),
    resumeOntology: async id => { assert.equal(id, 'saved-project'); resumes++; resumed = true; return ok({}) },
    buildGraph: async () => ok({ task_id: 'task' }),
    getTaskStatus: async () => ok({ status: 'processing' }),
  })
  await c.handleNewProject()
  assert.equal(c.currentProjectId.value, 'saved-project')
  assert.equal(c.error.value, 'Provider unavailable')
  await c.recoverProject()
  assert.equal(uploads, 1)
  assert.equal(resumes, 1)
})

test('refresh before upload persistence directs missing browser files back to selection', async () => {
  let destination
  const c = component('../views/MainView', ['handleNewProject', 'recoverProject', 'needsFiles'], {
    useRoute: () => ({ params: { projectId: 'new' } }),
    useRouter: () => ({ push: path => { destination = path } }),
    getPendingUpload: () => ({ isPending: false, files: [] }),
  })
  await c.handleNewProject()
  assert.equal(c.needsFiles.value, true)
  await c.recoverProject()
  assert.equal(destination, '/')
})

test('prepared refresh profile failure shows reconnect and retains saved data without completing', async () => {
  let configReads = 0
  let starts = 0
  const c = component('Step2EnvSetup', ['restorePreparation', 'prepareError', 'connectionError', 'profiles', 'simulationConfig', 'phase'], {
    getPrepareStatus: async () => ok({ status: 'ready', already_prepared: true }),
    getSimulationProfilesRealtime: async () => { throw new Error('Profiles connection lost') },
    getSimulationConfigRealtime: async () => { configReads++; return ok({ config_generated: true, config: {} }) },
    prepareSimulation: async () => { starts++; return ok({ task_id: 'new' }) },
  }, { simulationId: 'sim' })
  c.profiles.value = [{ name: 'Saved persona' }]
  c.simulationConfig.value = { saved: true }
  await c.restorePreparation()
  assert.equal(c.prepareError.value, 'Profiles connection lost')
  assert.equal(c.connectionError.value, true)
  assert.equal(c.profiles.value[0].name, 'Saved persona')
  assert.equal(c.simulationConfig.value.saved, true)
  assert.notEqual(c.phase.value, 4)
  assert.equal(configReads, 0)
  assert.equal(starts, 0)
  assert.equal(c.timers.size, 0)
})

test('already-prepared start cannot mark setup complete after profile load fails', async () => {
  let configReads = 0
  const c = component('Step2EnvSetup', ['startPrepareSimulation', 'prepareError', 'phase'], {
    prepareSimulation: async () => ok({ already_prepared: true }),
    getSimulationProfilesRealtime: async () => { throw new Error('Profile service down') },
    getSimulationConfigRealtime: async () => { configReads++; return ok({ config_generated: true, config: {} }) },
  }, { simulationId: 'sim' })
  await c.startPrepareSimulation()
  assert.equal(c.prepareError.value, 'Profile service down')
  assert.notEqual(c.phase.value, 4)
  assert.equal(configReads, 0)
  assert.equal(c.timers.size, 0)
})

test('a stale completed poll cannot override a recovered preparation attempt', async () => {
  let resolveOldStatus
  let profileReads = 0
  const c = component('Step2EnvSetup', ['pollPrepareStatus', 'handlePrepareFailure', 'recoverPreparation', 'phase', 'taskId'], {
    getPrepareStatus: () => new Promise(resolve => { resolveOldStatus = resolve }),
    prepareSimulation: async () => ok({ task_id: 'recovered' }),
    getSimulationProfilesRealtime: async () => { profileReads++; return ok({ profiles: [] }) },
  }, { simulationId: 'sim' })
  const oldPoll = c.pollPrepareStatus()
  c.handlePrepareFailure('Task failed')
  await c.recoverPreparation()
  resolveOldStatus(ok({ status: 'completed', already_prepared: true }))
  await oldPoll
  assert.equal(c.taskId.value, 'recovered')
  assert.equal(c.phase.value, 1)
  assert.equal(profileReads, 0)
  assert.equal(c.timers.size, 2)
})

test('preparation status reconnect failure remains visible', async () => {
  const c = component('Step2EnvSetup', ['restorePreparation', 'prepareError', 'connectionError'], {
    getPrepareStatus: async () => { throw new Error('Status disconnected') },
  }, { simulationId: 'sim' })
  await c.restorePreparation()
  assert.equal(c.prepareError.value, 'Status disconnected')
  assert.equal(c.connectionError.value, true)
})
