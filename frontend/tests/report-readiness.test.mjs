import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse } from 'vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'

const source = readFileSync(new URL('../src/components/Step3Simulation.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const template = baseParse(descriptor.template.content)
const findReportButton = node => {
  if (node.tag === 'button' && node.props.some(prop => prop.name === 'on' && prop.exp?.content === 'handleNextStep')) return node
  for (const child of node.children || []) {
    const found = findReportButton(child)
    if (found) return found
  }
}
const disabledExpression = findReportButton(template).props.find(prop => prop.name === 'bind' && prop.arg?.content === 'disabled').exp.content
const extract = name => {
  const start = source.indexOf(`const ${name} =`)
  assert.notEqual(start, -1, name)
  return source.slice(start, source.indexOf('\n}\n', start) + 2)
}

function harness(status, currentPhase = 2) {
  const phase = { value: currentPhase }, runStatus = { value: {
    runner_status: status, current_round: 120, total_rounds: 120,
    twitter_completed: true, reddit_completed: true,
  } }
  const isGeneratingReport = { value: false }, props = { simulationId: 'sim-test' }
  const requests = [], routes = [], logs = [], emissions = []
  const isStopping = { value: false }
  const stopSimulation = async () => ({ success: true, data: { runner_status: status } })
  const stopPolling = () => {}, emit = (...args) => emissions.push(args)
  const generateReport = async params => { requests.push(params); return { success: true, data: { report_id: 'report-test' } } }
  const router = { push: route => routes.push(route) }
  const addLog = message => logs.push(message), t = key => key
  const computed = getter => ({ get value() { return getter() } })
  // Exercise the production predicate and handler, plus the actual template binding.
  const predicateStart = source.indexOf('const canGenerateReport =')
  const predicate = predicateStart < 0 ? '' : source.slice(predicateStart, source.indexOf('\n\n', predicateStart))
  const handlers = eval(`${predicate}\n${extract('handleNextStep')}\n${extract('handleStopSimulation')}; ({handleNextStep, handleStopSimulation, canGenerateReport: typeof canGenerateReport === 'undefined' ? undefined : canGenerateReport})`)
  const disabled = () => new Function('phase', 'runStatus', 'isGeneratingReport', 'canGenerateReport', `return (${disabledExpression})`)(
    phase.value, runStatus.value, isGeneratingReport.value, handlers.canGenerateReport?.value,
  )
  return { ...handlers, disabled, requests, routes, runStatus, phase, isGeneratingReport }
}

for (const status of ['failed', 'stopping', 'starting', 'running', 'paused', 'idle', undefined]) {
  test(`${status}: finished platform counters do not unlock reports`, async () => {
    const h = harness(status)
    assert.equal(h.disabled(), true)
    await h.handleNextStep()
    assert.equal(h.requests.length, 0)
    assert.equal(h.routes.length, 0)
  })
}

for (const status of ['completed', 'stopped']) {
  test(`${status}: a successful terminal state can generate one report`, async () => {
    const h = harness(status)
    assert.equal(h.disabled(), false)
    await h.handleNextStep()
    assert.deepEqual(h.requests, [{ simulation_id: 'sim-test', force_regenerate: true }])
    assert.deepEqual(h.routes, [{ name: 'Report', params: { reportId: 'report-test' } }])
    assert.equal(h.disabled(), true)
    await h.handleNextStep()
    assert.equal(h.requests.length, 1)
  })
}

test('the click handler rechecks readiness after the last rendered successful state', async () => {
  const h = harness('completed')
  assert.equal(h.disabled(), false)
  h.runStatus.value.runner_status = 'failed'
  await h.handleNextStep()
  assert.equal(h.requests.length, 0)
})

test('a successful snapshot alone does not bypass an active UI phase', async () => {
  const h = harness('completed', 1)
  assert.equal(h.disabled(), true)
  await h.handleNextStep()
  assert.equal(h.requests.length, 0)
})

for (const status of ['stopped', 'stopping', 'failed']) {
  test(`the stop response is authoritative for report readiness: ${status}`, async () => {
    const h = harness(status, 1)
    h.runStatus.value.runner_status = 'running'
    await h.handleStopSimulation()
    assert.equal(h.runStatus.value.runner_status, status)
    assert.equal(h.disabled(), status !== 'stopped')
    await h.handleNextStep()
    assert.equal(h.requests.length, status === 'stopped' ? 1 : 0)
  })
}
