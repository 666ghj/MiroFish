import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { reactive, ref, computed, watch, nextTick, effectScope } from 'vue'

const source = readFileSync(new URL('../src/components/GraphPanel.vue', import.meta.url), 'utf8')
const watcherStart = source.indexOf('watch(() => props.graphData, () => {')
const helperStart = source.indexOf('const refreshSelectedItem = () => {')
const code = source.slice(helperStart < 0 ? watcherStart : helperStart, source.indexOf('// 监听边标签', watcherStart))
async function refresh(selection, graph) {
  const props = reactive({ graphData: { nodes: [], edges: [] } })
  const selectedItem = ref(selection), expandedSelfLoops = ref(new Set(['old']))
  const entityTypes = computed(() => [{ name: 'Person', color: '#123456' }])
  const renderGraph = () => {}
  const closeDetailPanel = () => { selectedItem.value = null; expandedSelfLoops.value = new Set() }
  const scope = effectScope()
  scope.run(() => eval(code))
  props.graphData = graph
  await nextTick()
  scope.stop()
  return { selection: selectedItem.value, expanded: expandedSelfLoops.value }
}
const node = { uuid: 'a', name: 'Alpha', labels: ['Entity', 'Person'], summary: 'new evidence' }
const other = { uuid: 'b', name: 'Beta' }
const edge = { uuid: 'ab', source_node_uuid: 'a', target_node_uuid: 'b', fact: 'new fact' }

test('selected node details use the latest graph evidence and type', async () => {
  const result = await refresh({ type: 'node', data: { uuid: 'a', summary: 'old evidence' }, entityType: 'Old' }, { nodes: [node] })
  assert.equal(result.selection.data.summary, 'new evidence')
  assert.equal(result.selection.entityType, 'Person')
  assert.equal(result.selection.color, '#123456')
})
test('removed node closes its obsolete detail panel', async () => {
  const result = await refresh({ type: 'node', data: node }, { nodes: [other] })
  assert.equal(result.selection, null)
  assert.equal(result.expanded.size, 0)
})
test('selected edge details use the refreshed fact and endpoint names', async () => {
  const result = await refresh({ type: 'edge', data: { ...edge, fact: 'old fact' } }, { nodes: [node, other], edges: [edge] })
  assert.equal(result.selection.data.fact, 'new fact')
  assert.equal(result.selection.data.source_name, 'Alpha')
  assert.equal(result.selection.data.target_name, 'Beta')
})
test('removed or no-longer-renderable edge closes its obsolete detail panel', async () => {
  for (const graph of [{ nodes: [node, other], edges: [] }, { nodes: [node], edges: [edge] }]) {
    assert.equal((await refresh({ type: 'edge', data: edge }, graph)).selection, null)
  }
})
test('unchanged selected entity stays open after a refresh', async () => {
  const result = await refresh({ type: 'node', data: node }, { nodes: [node] })
  assert.equal(result.selection.data.uuid, 'a')
  assert.equal(result.selection.data.summary, node.summary)
})
test('obsolete merged self-loop details close rather than showing old facts', async () => {
  assert.equal((await refresh({ type: 'edge', data: { isSelfLoopGroup: true } }, { nodes: [node], edges: [] })).selection, null)
})
