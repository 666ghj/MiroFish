import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../src/components/Step3Simulation.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: 'reconnect-test' }).content
  .replace(/^import[\s\S]*?from ['"][^'"]+['"];?\s*$/gm, '')
  .replace('export default', 'globalThis.component =')

async function openScreen(status, failure = false) {
  let mounted
  const starts = []
  const reports = []
  const intervals = []
  const context = vm.createContext({
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }),
    watch() {}, onMounted(fn) { mounted = fn }, onUnmounted() {}, nextTick: fn => fn(),
    useRouter: () => ({}), useI18n: () => ({ t: key => key }),
    setInterval: fn => intervals.push(fn), clearInterval() {}, console,
    getRunStatus: async () => {
      if (failure) throw new Error('Network Error')
      return { success: true, data: { runner_status: status, process_pid: 12345 } }
    },
    getRunStatusDetail: async () => ({ success: true, data: { all_actions: [] } }),
    startSimulation: async params => {
      starts.push(params)
      return { success: true, data: { runner_status: 'running', process_pid: 12345 } }
    },
    stopSimulation() { throw new Error('Unexpected stop') },
    generateReport: async params => { reports.push(params); return { success: false } },
  })
  vm.runInContext(compiled, context)
  const state = context.component.setup({ simulationId: 'saved-simulation', maxRounds: 40 }, { expose() {}, emit() {} })
  await mounted()
  return { starts, reports, state, intervals }
}

for (const status of ['starting', 'running', 'paused', 'stopping', 'completed', 'stopped', 'failed']) {
  test(`opening a ${status} simulation preserves it without a start request`, async () => {
    const { starts, state } = await openScreen(status)
    assert.equal(starts.length, 0)
    assert.equal(state.runStatus.value.runner_status, status)
    assert.equal(state.runStatus.value.process_pid, 12345)
  })
}

test('a new simulation starts once without force', async () => {
  const { starts } = await openScreen('idle')
  assert.equal(starts.length, 1)
  assert.equal(starts[0].force, undefined)
  assert.equal(starts[0].max_rounds, 40)
})

test('unavailable or malformed status cannot trigger a paid rerun', async () => {
  for (const [status, failure] of [['running', true], [undefined, false]]) {
    const { starts, state } = await openScreen(status, failure)
    assert.equal(starts.length, 0)
    assert.ok(state.startError.value)
  }
})

for (const status of ['running', 'stopping', 'failed']) {
  test(`report generation is blocked while the run is ${status}`, async () => {
    const { state, reports } = await openScreen(status)
    await state.handleNextStep()
    assert.equal(reports.length, 0)
  })
}

test('report generation is enabled after successful finalization', async () => {
  const { state, reports } = await openScreen('completed')
  await state.handleNextStep()
  assert.equal(reports.length, 1)
})
