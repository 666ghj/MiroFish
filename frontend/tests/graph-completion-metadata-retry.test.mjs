import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/views/MainView.vue', import.meta.url), 'utf8')
const start = source.indexOf('const pollTaskStatus = async (taskId) => {')
const handler = source.slice(start, source.indexOf('\n}\n', start) + 2)
function harness(metadata, status = 'completed') {
  const currentProjectId = { value: 'project-test' }, projectData = { value: { graph_id: null } }
  const currentPhase = { value: 1 }, buildProgress = { value: {} }, error = { value: '' }
  let taskStopped = false, graphStopped = false, projectCalls = 0
  const loaded = [], addLog = () => {}
  const stopPolling = () => { taskStopped = true }, stopGraphPolling = () => { graphStopped = true }
  const getTaskStatus = async () => ({ success: true, data: { status, progress: 100, error: 'build failed' } })
  const getProject = async () => { projectCalls++; const result = metadata.shift(); if (result instanceof Error) throw result; return await result }
  const loadGraph = async id => loaded.push(id)
  return { poll: eval(`${handler}; pollTaskStatus`), currentPhase, projectData, error, loaded,
    taskStopped: () => taskStopped, graphStopped: () => graphStopped, projectCalls: () => projectCalls }
}
const ready = { success: true, data: { project_id: 'project-test', graph_id: 'graph-test' } }
for (const [label, first] of [['connection failure', new Error('connection reset')], ['missing graph ID', { success: true, data: {} }], ['unusable response', { success: false }]]) {
  test(`completed task remains recoverable after ${label}`, async () => {
    const h = harness([first, ready])
    const original = console.error; console.error = () => {}
    try { await h.poll('task-test') } finally { console.error = original }
    assert.equal(h.currentPhase.value, 1)
    assert.equal(h.taskStopped(), false)
    assert.equal(h.graphStopped(), false)
    await h.poll('task-test')
    assert.equal(h.projectData.value.graph_id, 'graph-test')
    assert.equal(h.currentPhase.value, 2)
    assert.equal(h.taskStopped(), true)
    assert.equal(h.graphStopped(), true)
    assert.deepEqual(h.loaded, ['graph-test'])
  })
}
test('pending final metadata does not advertise a ready project', async () => {
  let release
  const h = harness([new Promise(resolve => { release = resolve })])
  const pending = h.poll('task-test')
  await Promise.resolve(); await Promise.resolve()
  assert.equal(h.currentPhase.value, 1)
  assert.equal(h.taskStopped(), false)
  release(ready); await pending
  assert.equal(h.currentPhase.value, 2)
})
test('healthy completion still loads the graph and stops polling', async () => {
  const h = harness([ready])
  await h.poll('task-test')
  assert.equal(h.currentPhase.value, 2)
  assert.deepEqual(h.loaded, ['graph-test'])
  assert.equal(h.taskStopped(), true)
})
test('terminal task failure keeps existing error handling without fetching metadata', async () => {
  const h = harness([], 'failed')
  await h.poll('task-test')
  assert.equal(h.error.value, 'build failed')
  assert.equal(h.taskStopped(), true)
  assert.equal(h.projectCalls(), 0)
})
