import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Exercise the component's production handler without adding a Vue test runtime.
const source = readFileSync(new URL('../src/components/Step5Interaction.vue', import.meta.url), 'utf8')
const start = source.indexOf('const submitSurvey = async () => {')
const handler = source.slice(start, source.indexOf('// Load Report Data', start))

for (const responseShape of ['dictionary', 'array']) {
  test(`survey preserves the submitted question across edits (${responseShape})`, async () => {
    let resolveInterview
    const pendingResponse = new Promise(resolve => { resolveInterview = resolve })
    const selectedAgents = { value: new Set([0]) }
    const surveyQuestion = { value: '  Original question?  ' }
    const isSurveying = { value: false }
    const profiles = { value: [{ username: 'Agent A', profession: 'Engineer' }] }
    const surveyResults = { value: [] }
    const props = { simulationId: 'sim-test' }
    const addLog = () => {}
    const t = key => key
    let request
    const interviewAgents = async payload => {
      request = payload
      return pendingResponse
    }
    const submitSurvey = eval(`${handler}; submitSurvey`)
    const pending = submitSurvey()
    assert.equal(isSurveying.value, true)
    assert.equal(request.interviews[0].prompt, 'Original question?')
    surveyQuestion.value = 'An unrelated question?'
    selectedAgents.value = new Set()
    const answer = { agent_id: 0, response: 'Answer to original question' }
    const results = responseShape === 'array' ? [answer] : { reddit_0: answer }
    resolveInterview({ success: true, data: { result: { results } } })
    await pending
    assert.equal(surveyResults.value.length, 1)
    assert.equal(surveyResults.value[0].question, request.interviews[0].prompt)
    assert.equal(surveyResults.value[0].answer, answer.response)
    assert.equal(surveyQuestion.value, 'An unrelated question?')
    assert.equal(isSurveying.value, false)
  })
}
