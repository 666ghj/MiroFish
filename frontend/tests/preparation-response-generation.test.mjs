import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/Step2EnvSetup.vue', import.meta.url), 'utf8')
const names = ['handlePrepareFailure', 'startPrepareSimulation', 'pollPrepareStatus', 'fetchProfilesRealtime', 'fetchConfigRealtime', 'loadPreparedData']
const methods = names.map(name => {
  const start = source.indexOf(`const ${name} =`)
  return source.slice(start, source.indexOf('\n}\n', start) + 2)
}).join('\n')
function harness(deferredKinds) {
  let preparationGeneration = 0, preparationFailed = false
  const props = { simulationId: 'sim-test' }, phase = { value: 2 }, taskId = { value: 'old-task' }
  const prepareProgress = { value: 0 }, progressMessage = { value: '' }, currentStage = { value: '' }
  const profiles = { value: [] }, entityTypes = { value: [] }, expectedTotal = { value: null }, simulationConfig = { value: null }
  let lastLoggedMessage = '', lastLoggedProfileCount = 0, lastLoggedConfigStage = '', configTimer = null
  const emissions = [], requests = { config: [], profile: [], task: [], prepare: [] }, started = []
  const emit = (...args) => emissions.push(args), addLog = () => {}, t = key => key
  const stopPolling = () => {}, stopProfilesPolling = () => {}, stopConfigPolling = () => {}
  const startPolling = () => started.push('task'), startProfilesPolling = () => started.push('profile')
  const startConfigPolling = () => started.push('config')
  const api = kind => {
    if (deferredKinds.includes(kind)) return new Promise(resolve => requests[kind].push({ resolve }))
    requests[kind].push({})
    return Promise.resolve({ success: true, data: { profiles: [], config_generated: true, config: {} } })
  }
  const getSimulationConfigRealtime = () => api('config'), getSimulationProfilesRealtime = () => api('profile')
  const getPrepareStatus = () => api('task'), prepareSimulation = () => api('prepare')
  const handlers = eval(`${methods}; ({${names.join(',')}})`)
  let dispose, stageChange
  const onUnmounted = callback => { dispose = callback }
  const watch = (state, callback) => { stageChange = callback }
  const unmountStart = source.indexOf('onUnmounted(() => {')
  eval(source.slice(unmountStart, source.indexOf('\n})', unmountStart) + 3))
  const stageStart = source.indexOf('watch(currentStage, (newStage) => {')
  eval(source.slice(stageStart, source.indexOf('\n})', stageStart) + 3))
  const completed = () => emissions.some(([event, status]) => event === 'update-status' && status === 'completed')
  return { ...handlers, phase, profiles, requests, emissions, started, completed, dispose, stageChange }
}
const readyConfig = { success: true, data: { config_generated: true, config: {} } }

test('late configuration cannot complete a failed preparation', async () => {
  const h = harness(['config']), pending = h.fetchConfigRealtime()
  h.handlePrepareFailure('failed')
  h.requests.config[0].resolve(readyConfig)
  await pending
  assert.equal(h.completed(), false)
  assert.notEqual(h.phase.value, 4)
})
test('late profiles do not repopulate failed preparation state', async () => {
  const h = harness(['profile']), pending = h.fetchProfilesRealtime()
  h.handlePrepareFailure('failed')
  h.requests.profile[0].resolve({ success: true, data: { profiles: [{ username: 'late profile' }] } })
  await pending
  assert.deepEqual(h.profiles.value, [])
})
test('late task completion cannot trigger prepared-data recovery after failure', async () => {
  const h = harness(['task']), pending = h.pollPrepareStatus()
  h.handlePrepareFailure('failed')
  h.requests.task[0].resolve({ success: true, data: { status: 'completed' } })
  await pending
  assert.equal(h.requests.profile.length, 0)
  assert.equal(h.completed(), false)
})
test('late prepared-data configuration cannot override terminal failure', async () => {
  const h = harness(['config']), pending = h.loadPreparedData()
  await Promise.resolve(); await Promise.resolve()
  h.handlePrepareFailure('failed')
  h.requests.config[0].resolve(readyConfig)
  await pending
  assert.equal(h.completed(), false)
})
test('retry starts a fresh attempt while old replies remain invalid', async () => {
  const h = harness(['config', 'prepare']), old = h.fetchConfigRealtime()
  h.handlePrepareFailure('failed')
  const retry = h.startPrepareSimulation()
  h.requests.config[0].resolve(readyConfig)
  await old
  assert.equal(h.completed(), false)
  h.requests.prepare[0].resolve({ success: true, data: { task_id: 'new-task' } })
  await retry
  const fresh = h.fetchConfigRealtime()
  h.requests.config[1].resolve(readyConfig)
  await fresh
  assert.equal(h.completed(), true)
  assert.equal(h.phase.value, 4)
})
test('late initial preparation response cannot restart polling after failure', async () => {
  const h = harness(['prepare']), pending = h.startPrepareSimulation()
  h.handlePrepareFailure('failed')
  h.requests.prepare[0].resolve({ success: true, data: { task_id: 'late-task' } })
  await pending
  assert.deepEqual(h.started, [])
})

test('queued stage updates cannot restart configuration polling after failure', () => {
  const h = harness([])
  h.handlePrepareFailure('failed')
  h.stageChange('generating_config')
  assert.deepEqual(h.started, [])
})
test('leaving the component invalidates pending configuration replies', async () => {
  const h = harness(['config']), pending = h.fetchConfigRealtime()
  h.dispose()
  h.requests.config[0].resolve(readyConfig)
  await pending
  assert.equal(h.completed(), false)
})

test('a failed preparation request leaves later polling unable to report completion', async () => {
  const h = harness(['prepare']), pending = h.startPrepareSimulation()
  h.requests.prepare[0].resolve({ success: false, error: 'prepare failed' })
  await pending
  await h.fetchConfigRealtime()
  assert.equal(h.requests.config.length, 0)
  assert.equal(h.completed(), false)
})
