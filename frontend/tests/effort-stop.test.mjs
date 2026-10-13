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

test('idle simulation waits for an explicit start', async () => {
  let starts = 0
  const c = component('Step3Simulation', ['restoreSimulation', 'phase'], {
    getRunStatus: async () => ok({ runner_status: 'idle' }),
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
    startSimulation: async () => { starts++; return ok({ runner_status: 'running' }) },
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  assert.equal(starts, 0)
  assert.equal(c.phase.value, 0)
})

test('explicit start uses Full and does not let a legacy round prop override it', async () => {
  let request
  const c = component('Step3Simulation', ['doStartSimulation'], {
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
    startSimulation: async data => { request = data; return ok({ runner_status: 'running', total_rounds: 4 }) },
  }, { simulationId: 'sim', maxRounds: 40 })
  await c.doStartSimulation()
  assert.equal(request.simulation_effort, 'full')
  assert.equal(request.max_rounds, undefined)
})

test('stopping waits for authoritative stopped status before report generation', async () => {
  let reports = 0
  const c = component('Step3Simulation', ['handleStopSimulation', 'handleNextStep', 'phase', 'runStatus', 'fetchRunStatus'], {
    stopSimulation: async () => ok({ runner_status: 'stopping', stop_pending: true }),
    getRunStatus: async () => ok({ runner_status: 'stopped', total_rounds: 4, twitter_current_round: 1 }),
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    generateReport: async () => { reports++; return ok({ report_id: 'partial' }) },
  }, { simulationId: 'sim' })
  c.runStatus.value = { runner_status: 'running' }
  c.phase.value = 1
  await c.handleStopSimulation()
  assert.equal(c.phase.value, 1)
  await c.handleNextStep()
  assert.equal(reports, 0)
  await c.fetchRunStatus()
  assert.equal(c.phase.value, 2)
  await c.handleNextStep()
  assert.equal(reports, 1)
})

for (const [hours, minutes, expected] of [[2, 30, [1, 2, 4]], [1, 20, [1, 2, 3]], [0.1, 30, [1, 1, 1]], [25, 30, [13, 25, 50]]]) {
  test(`effort counts follow the actual ${hours}h plan without inflating short runs`, () => {
    const full = plannedSimulationRounds({ time_config: { total_simulation_hours: hours, minutes_per_round: minutes } })
    assert.deepEqual(simulationEfforts.map(effort => roundsForEffort(full, effort)), expected)
  })
}

test('invalid plan is visible and cannot start with an invented round budget', async () => {
  let starts = 0
  const c = component('Step3Simulation', ['doStartSimulation', 'configError'], {
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 0, minutes_per_round: 30 } }),
    startSimulation: async () => { starts++; return ok({}) },
  }, { simulationId: 'sim' })
  await c.doStartSimulation()
  assert.equal(starts, 0)
  assert.equal(c.configError.value, 'step3.invalidPlan')
})

test('selected effort survives refresh and is sent when retrying a failed run', async () => {
  const stored = new Map()
  let request
  const mocks = {
    localStorage: { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value) },
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
    startSimulation: async data => { request = data; return ok({ runner_status: 'running', total_rounds: 2 }) },
  }
  const first = component('Step3Simulation', ['selectEffort'], mocks, { simulationId: 'sim' })
  first.selectEffort('moderate')
  const refreshed = component('Step3Simulation', ['recoverSimulation'], mocks, { simulationId: 'sim' })
  await refreshed.recoverSimulation()
  assert.equal(request.simulation_effort, 'moderate')
  assert.equal(request.force, true)
})

test('cancel never stops; duplicate confirmation sends one stop request and keeps polling', async () => {
  let stops = 0
  const c = component('Step3Simulation', ['requestStop', 'cancelStop', 'confirmStop', 'runStatus', 'showStopConfirmation', 'canGenerateReport'], {
    stopSimulation: async data => { assert.equal(data.wait, false); stops++; return ok({ runner_status: 'stopping' }) },
  }, { simulationId: 'sim' })
  c.runStatus.value = { runner_status: 'paused' }
  c.requestStop()
  assert.equal(c.showStopConfirmation.value, true)
  c.cancelStop()
  await c.confirmStop()
  assert.equal(stops, 0)
  c.requestStop()
  await Promise.all([c.confirmStop(), c.confirmStop()])
  assert.equal(stops, 1)
  assert.equal(c.canGenerateReport.value, false)
  assert.equal(c.timers.size, 2)
})

test('stop finalization failure retries stop, preserving activity without restarting', async () => {
  let stops = 0
  let starts = 0
  const c = component('Step3Simulation', ['restoreSimulation', 'recoverSimulation', 'stopError', 'runStatus', 'allActions'], {
    getRunStatus: async () => ok({ runner_status: 'failed', stop_requested: true, error: 'Flush failed', twitter_actions_count: 3 }),
    getRunStatusDetail: async () => ok({ all_actions: [{ id: 'saved' }] }),
    stopSimulation: async () => { stops++; return ok({ runner_status: 'stopping' }) },
    startSimulation: async () => { starts++; return ok({}) },
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  assert.equal(c.stopError.value, 'Flush failed')
  await c.recoverSimulation()
  assert.equal(starts, 0)
  assert.equal(stops, 1)
  assert.equal(c.allActions.value[0].id, 'saved')
})

test('stop confirmed during start waits for its response before stopping', async () => {
  const calls = []
  let finishStart
  const c = component('Step3Simulation', ['doStartSimulation', 'requestStop', 'confirmStop', 'stopRequested'], {
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
    startSimulation: () => { calls.push('start'); return new Promise(resolve => { finishStart = resolve }) },
    stopSimulation: async () => { calls.push('stop'); return ok({ runner_status: 'stopping' }) },
  }, { simulationId: 'sim' })
  const starting = c.doStartSimulation()
  await new Promise(resolve => setImmediate(resolve))
  c.requestStop()
  await c.confirmStop()
  assert.equal(c.stopRequested.value, true)
  assert.deepEqual(calls, ['start'])
  finishStart(ok({ runner_status: 'running' }))
  await starting
  assert.deepEqual(calls, ['start', 'stop'])
})

test('refresh resumes a locally confirmed stop that had not reached the backend', async () => {
  let stops = 0
  const c = component('Step3Simulation', ['restoreSimulation'], {
    localStorage: { getItem: key => key.endsWith('stop-requested') ? 'true' : 'full', setItem() {} },
    getRunStatus: async () => ok({ runner_status: 'running' }),
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    stopSimulation: async () => { stops++; return ok({ runner_status: 'stopping' }) },
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  assert.equal(stops, 1)
})

test('detail connection failure during stopping retries finalization, never run start', async () => {
  const c = component('Step3Simulation', ['restoreSimulation', 'stopError', 'startError'], {
    getRunStatus: async () => ok({ runner_status: 'stopping', stop_requested: true }),
    getRunStatusDetail: async () => { throw new Error('Detail offline') },
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  assert.equal(c.stopError.value, 'Detail offline')
  assert.equal(c.startError.value, null)
})

test('idle backend default effort cannot overwrite an unstarted saved choice on refresh', async () => {
  const c = component('Step3Simulation', ['restoreSimulation', 'selectedEffort'], {
    localStorage: { getItem: key => key.endsWith(':effort') ? 'quick' : null, setItem() {} },
    getRunStatus: async () => ok({ runner_status: 'idle', simulation_effort: 'full' }),
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  assert.equal(c.selectedEffort.value, 'quick')
})

test('an old in-flight failed status cannot restart or overwrite a confirmed stop', async () => {
  let finishRead
  const c = component('Step3Simulation', ['requestStop', 'confirmStop', 'fetchRunStatus', 'runStatus', 'startError'], {
    getRunStatus: () => new Promise(resolve => { finishRead = resolve }),
    stopSimulation: async () => ok({ runner_status: 'stopping' }),
  }, { simulationId: 'sim' })
  c.runStatus.value = { runner_status: 'running' }
  const stale = c.fetchRunStatus()
  c.requestStop()
  await c.confirmStop()
  finishRead(ok({ runner_status: 'failed', error: 'Old failure' }))
  await stale
  assert.equal(c.runStatus.value.runner_status, 'stopping')
  assert.equal(c.startError.value, null)
})

test('connection recovery retries an explicitly requested start only after confirming idle', async () => {
  const requests = []
  const c = component('Step3Simulation', ['doStartSimulation', 'recoverSimulation', 'selectEffort', 'runStatus'], {
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
    getRunStatus: async () => ok({ runner_status: 'idle', simulation_effort: 'full' }),
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    startSimulation: async data => { requests.push(data); if (requests.length === 1) throw new Error('Offline'); return ok({ runner_status: 'running', simulation_effort: 'quick' }) },
  }, { simulationId: 'sim' })
  c.selectEffort('quick')
  await c.doStartSimulation()
  await c.recoverSimulation()
  assert.equal(requests.length, 2)
  assert.equal(requests[1].simulation_effort, 'quick')
  assert.equal(requests[1].force, false)
  assert.equal(c.runStatus.value.runner_status, 'running')
})

test('recovery of an idle status read failure does not initiate a new simulation', async () => {
  let reads = 0
  let starts = 0
  const c = component('Step3Simulation', ['restoreSimulation', 'recoverSimulation'], {
    getSimulationConfig: async () => ok({ time_config: { total_simulation_hours: 2, minutes_per_round: 30 } }),
    getRunStatus: async () => { if (++reads === 1) throw new Error('Offline'); return ok({ runner_status: 'idle' }) },
    getRunStatusDetail: async () => ok({ all_actions: [] }),
    startSimulation: async () => { starts++; return ok({ runner_status: 'running' }) },
  }, { simulationId: 'sim' })
  await c.restoreSimulation()
  await c.recoverSimulation()
  assert.equal(starts, 0)
})

test('simulation view configuration failure remains visible until all data loads successfully', async () => {
  let configFails = true
  const c = component('../views/SimulationRunView', ['loadSimulationData', 'recoverData', 'loadError', 'dataLoaded', 'minutesPerRound'], {
    useRoute: () => ({ params: { simulationId: 'sim' } }),
    getSimulation: async () => ok({ project_id: 'project' }),
    getSimulationConfig: async () => { if (configFails) throw new Error('Config offline'); return ok({ time_config: { minutes_per_round: 15 } }) },
    getProject: async () => ok({ project_id: 'project', graph_id: 'graph' }),
    getGraphData: async () => ok({ nodes: [] }),
  }, { simulationId: 'sim' })
  await c.loadSimulationData()
  assert.equal(c.loadError.value, 'Config offline')
  assert.equal(c.dataLoaded.value, false)
  configFails = false
  await c.recoverData()
  assert.equal(c.loadError.value, '')
  assert.equal(c.dataLoaded.value, true)
  assert.equal(c.minutesPerRound.value, 15)
})

test('terminal status fetches the final saved activity before enabling a partial report', async () => {
  let finishFinalDetail
  const c = component('Step3Simulation', ['handleStopSimulation', 'fetchRunStatus', 'allActions', 'canGenerateReport'], {
    stopSimulation: async () => ok({ runner_status: 'stopping' }),
    getRunStatus: async () => ok({ runner_status: 'stopped', stop_requested: true, twitter_actions_count: 1 }),
    getRunStatusDetail: () => new Promise(resolve => { finishFinalDetail = resolve }),
  }, { simulationId: 'sim' })
  await c.handleStopSimulation()
  const terminalPoll = c.fetchRunStatus()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(c.canGenerateReport.value, false)
  assert.equal(typeof finishFinalDetail, 'function')
  finishFinalDetail(ok({ all_actions: [{ id: 'last-saved-action', platform: 'twitter' }] }))
  await terminalPoll
  assert.equal(c.allActions.value[0].id, 'last-saved-action')
  assert.equal(c.canGenerateReport.value, true)
  assert.equal(c.timers.size, 0)
})

test('failed final activity fetch after stopped is visible and retries detail without restarting', async () => {
  let detailFails = true
  let starts = 0
  let stops = 0
  const c = component('Step3Simulation', ['fetchRunStatus', 'recoverSimulation', 'stopError', 'allActions', 'canGenerateReport'], {
    getRunStatus: async () => ok({ runner_status: 'stopped', stop_requested: true }),
    getRunStatusDetail: async () => { if (detailFails) throw new Error('Final activity offline'); return ok({ all_actions: [{ id: 'final' }] }) },
    startSimulation: async () => { starts++; return ok({}) },
    stopSimulation: async () => { stops++; return ok({}) },
  }, { simulationId: 'sim' })
  await c.fetchRunStatus()
  assert.equal(c.stopError.value, 'Final activity offline')
  assert.equal(c.canGenerateReport.value, false)
  detailFails = false
  await c.recoverSimulation()
  assert.equal(c.allActions.value[0].id, 'final')
  assert.equal(c.canGenerateReport.value, true)
  assert.equal(starts, 0)
  assert.equal(stops, 0)
})
