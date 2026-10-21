import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/Step4Report.vue', import.meta.url), 'utf8')
const start = source.indexOf('const fetchAgentLog = async () => {')
const handler = source.slice(start, source.indexOf('\n}\n', start) + 2)
function client(responses) {
  const props = { reportId: 'report-test' }, agentLogLine = { value: 0 }
  const agentLogs = { value: [] }, reportOutline = { value: null }
  const currentSectionIndex = { value: null }, generatedSections = { value: {} }
  const expandedContent = { value: new Set() }, isComplete = { value: false }
  const startTime = { value: null }, rightPanel = { value: null }
  const emit = () => {}, stopPolling = () => {}, nextTick = callback => callback()
  const requested = []
  const getAgentLog = async (reportId, fromLine) => {
    requested.push(fromLine)
    return { success: true, data: responses.shift() }
  }
  return { fetch: eval(`${handler}; fetchAgentLog`), agentLogs, agentLogLine, requested }
}
test('uses server physical cursor rather than replaying records after malformed lines', async () => {
  const logs = [{ action: 'tool_call' }, { action: 'tool_result' }]
  const h = client([{ logs, from_line: 0, next_line: 3 }, { logs: [], from_line: 3, next_line: 3 }])
  await h.fetch(); await h.fetch()
  assert.deepEqual(h.requested, [0, 3])
  assert.deepEqual(h.agentLogs.value, logs)
})
test('advances when a batch contains only malformed lines', async () => {
  const h = client([{ logs: [], from_line: 0, next_line: 2 }])
  await h.fetch()
  assert.equal(h.agentLogLine.value, 2)
})
test('remains compatible with servers that omit next_line', async () => {
  const h = client([{ logs: [{ action: 'tool_call' }], from_line: 0 }])
  await h.fetch()
  assert.equal(h.agentLogLine.value, 1)
})
