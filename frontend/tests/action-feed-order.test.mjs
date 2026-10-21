import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { computed, ref } from 'vue'

const source = readFileSync(new URL('../src/components/Step3Simulation.vue', import.meta.url), 'utf8')
const start = source.indexOf('const fetchRunStatusDetail = async () => {')
const handler = source.slice(start, source.indexOf('\n}\n', start) + 2)
const computedStart = source.indexOf('const chronologicalActions = computed(() => {')
const order = source.slice(computedStart, source.indexOf('\n})', computedStart) + 3)
const action = (id, timestamp) => ({ id, timestamp, platform: 'reddit', agent_id: id, action_type: 'CREATE_POST' })
const event = id => action(id, `2026-10-21T10:00:0${id}Z`)
function client(batches) {
  const props = { simulationId: 'sim-test' }, allActions = ref([]), actionIds = ref(new Set())
  const getRunStatusDetail = async () => ({ success: true, data: { all_actions: batches.shift() } })
  return eval(`${handler}\n${order}; ({ fetch: fetchRunStatusDetail, ordered: chronologicalActions, stored: allActions })`)
}

test('newest-first API batches produce one oldest-first feed without changing stored arrival order', async () => {
  const h = client([[event(3), event(2), event(1)], [event(5), event(4), event(3), event(2), event(1)], [event(5), event(4)]])
  await h.fetch()
  assert.deepEqual(h.ordered.value.map(a => a.id), [1, 2, 3])
  await h.fetch()
  assert.deepEqual(h.ordered.value.map(a => a.id), [1, 2, 3, 4, 5])
  assert.deepEqual(h.stored.value.map(a => a.id), [3, 2, 1, 5, 4])
  await h.fetch()
  assert.equal(h.ordered.value.length, 5)
})
test('simultaneous actions retain stable arrival order', async () => {
  const timestamp = '2026-10-21T10:00:00Z'
  const h = client([[action('first', timestamp), action('second', timestamp)]])
  await h.fetch()
  assert.deepEqual(h.ordered.value.map(a => a.id), ['first', 'second'])
})
test('ordering compares actual times for timestamps with timezone offsets', async () => {
  const h = client([[action('later', '2026-10-21T10:00:00Z'), action('earlier', '2026-10-21T11:00:00+03:00')]])
  await h.fetch()
  assert.deepEqual(h.ordered.value.map(a => a.id), ['earlier', 'later'])
})
