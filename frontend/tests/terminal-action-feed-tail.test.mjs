import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/Step3Simulation.vue', import.meta.url), 'utf8')
const extract = name => { const start = source.indexOf(`const ${name} =`); return source.slice(start, source.indexOf('\n}\n', start) + 2) }
function harness(status, mode = 'success') {
  const props = { simulationId: 'sim-test' }, runStatus = { value: {} }, phase = { value: 1 }
  const prevTwitterRound = { value: 0 }, prevRedditRound = { value: 0 }, isStopping = { value: false }
  const allActions = { value: [] }, actionIds = { value: new Set() }, emissions = []
  const addLog = () => {}, t = key => key, emit = (...args) => emissions.push(args)
  let stopped = false, calls = 0, release
  const stopPolling = () => { stopped = true }
  const getRunStatus = async () => ({ success: true, data: { runner_status: status, total_actions_count: 5 } })
  const stopSimulation = getRunStatus
  const events = [1, 2, 3, 4, 5].map(id => ({ id, timestamp: `2026-10-21T10:00:0${id}Z`, platform: 'reddit', agent_id: id, action_type: 'CREATE_POST' }))
  const getRunStatusDetail = async () => {
    calls++
    if (calls > 1 && mode === 'failure') throw new Error('detail endpoint unavailable')
    if (calls > 1 && mode === 'deferred') await new Promise(resolve => { release = resolve })
    return { success: true, data: { all_actions: events.slice(0, calls === 1 ? 3 : 5) } }
  }
  const handlers = eval(`${['fetchRunStatusDetail', 'fetchRunStatus', 'handleStopSimulation'].map(extract).join('\n')}; ({fetchRunStatusDetail,fetchRunStatus,handleStopSimulation})`)
  return { ...handlers, allActions, phase, emissions, stopped: () => stopped, calls: () => calls, release: () => release() }
}
for (const status of ['completed', 'stopped', 'failed']) {
  test(`${status} polling captures the action tail after the previous detail poll`, async () => {
    const h = harness(status)
    await h.fetchRunStatusDetail()
    assert.equal(h.allActions.value.length, 3)
    await h.fetchRunStatus()
    assert.equal(h.allActions.value.length, 5)
    assert.equal(h.calls(), 2)
    assert.equal(h.stopped(), true)
    assert.deepEqual(h.emissions.at(-1), ['update-status', status === 'failed' ? 'error' : 'completed'])
  })
}
test('active simulation status does not add an extra detail request', async () => {
  const h = harness('running')
  await h.fetchRunStatusDetail(); await h.fetchRunStatus()
  assert.equal(h.calls(), 1)
  assert.equal(h.stopped(), false)
})
test('pending final details do not delay the terminal UI', async () => {
  const h = harness('completed', 'deferred')
  await h.fetchRunStatusDetail(); await h.fetchRunStatus()
  assert.equal(h.calls(), 2)
  assert.equal(h.phase.value, 2)
  assert.equal(h.stopped(), true)
  assert.deepEqual(h.emissions.at(-1), ['update-status', 'completed'])
  h.release(); await Promise.resolve(); await Promise.resolve()
  assert.equal(h.allActions.value.length, 5)
})
test('failed final details preserve terminal status and stop periodic polling', async () => {
  const h = harness('completed', 'failure')
  const warn = console.warn
  console.warn = () => {}
  try {
    await h.fetchRunStatusDetail(); await h.fetchRunStatus()
    assert.equal(h.calls(), 2)
    assert.equal(h.phase.value, 2)
    assert.equal(h.stopped(), true)
  } finally { console.warn = warn }
})
test('a confirmed stopped response captures remaining actions', async () => {
  const h = harness('stopped')
  await h.fetchRunStatusDetail(); await h.handleStopSimulation()
  assert.equal(h.allActions.value.length, 5)
})
test('a nonterminal stop response does not flush a purported final tail', async () => {
  const h = harness('stopping')
  await h.fetchRunStatusDetail(); await h.handleStopSimulation()
  assert.equal(h.calls(), 1)
})
