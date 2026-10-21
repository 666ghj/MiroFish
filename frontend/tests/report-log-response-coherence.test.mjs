import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/Step4Report.vue', import.meta.url), 'utf8')
function harness(kind) {
  const name = kind === 'agent' ? 'fetchAgentLog' : 'fetchConsoleLog'
  const start = source.indexOf(`const ${name} = async () => {`)
  const handler = source.slice(start, source.indexOf('\n}\n', start) + 2)
  const props = { reportId: 'report-a' }
  const agentLogLine = { value: 0 }, consoleLogLine = { value: 0 }
  const agentLogs = { value: [] }, consoleLogs = { value: [] }
  const reportOutline = { value: null }, currentSectionIndex = { value: null }
  const generatedSections = { value: {} }, expandedContent = { value: new Set() }
  const isComplete = { value: false }, startTime = { value: null }
  const rightPanel = { value: null }, logContent = { value: null }
  const emissions = [], requests = []
  const emit = (...args) => emissions.push(args)
  const stopPolling = () => { emissions.push(['stopPolling']) }
  const nextTick = callback => callback()
  const getAgentLog = (reportId, fromLine) => new Promise(resolve => requests.push({ reportId, fromLine, resolve }))
  const getConsoleLog = getAgentLog
  const fetch = eval(`${handler}; ${name}`)
  return { fetch, props, requests, emissions, isComplete,
    logs: kind === 'agent' ? agentLogs : consoleLogs,
    cursor: kind === 'agent' ? agentLogLine : consoleLogLine }
}
for (const kind of ['agent', 'console']) {
  test(`${kind}: ignore a response for a report that is no longer displayed`, async () => {
    const h = harness(kind)
    const pending = h.fetch()
    h.props.reportId = 'report-b'
    const logs = kind === 'agent' ? [{ action: 'report_complete' }] : ['old report final log']
    h.requests[0].resolve({ success: true, data: { from_line: 0, logs } })
    await pending
    assert.deepEqual(h.logs.value, [])
    assert.equal(h.cursor.value, 0)
    assert.equal(h.isComplete.value, false)
    assert.deepEqual(h.emissions, [])
  })
  test(`${kind}: a slower overlapping poll cannot duplicate logs or rewind the cursor`, async () => {
    const h = harness(kind)
    const slower = h.fetch(), faster = h.fetch()
    const logs = kind === 'agent' ? [{ action: 'tool_call' }, { action: 'tool_result' }] : ['first', 'second']
    h.requests[1].resolve({ success: true, data: { from_line: 0, logs } })
    await faster
    h.requests[0].resolve({ success: true, data: { from_line: 0, logs: logs.slice(0, 1) } })
    await slower
    assert.deepEqual(h.logs.value, logs)
    assert.equal(h.cursor.value, 2)
    const next = h.fetch()
    assert.equal(h.requests[2].fromLine, 2)
    h.requests[2].resolve({ success: true, data: { from_line: 2, logs: [] } })
    await next
    assert.equal(h.cursor.value, 2)
  })
}
