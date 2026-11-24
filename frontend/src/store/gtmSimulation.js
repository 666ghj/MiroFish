/**
 * GTM simulation session state.
 * Reactive singleton - same pattern as store/pendingUpload.js.
 * Holds the brief, quick preview, and full persona set between views.
 */
import { reactive } from 'vue'

const state = reactive({
  /** @type {object|null} Raw normalized form data */
  brief: null,
  /** @type {string|null} brief_id returned from POST /api/gtm/brief */
  briefId: null,
  /** @type {'idle'|'submitting'|'preview'|'error'} */
  status: 'idle',
  /** @type {object|null} Quick 3-persona preview from GET /api/gtm/brief/<id>/preview */
  preview: null,
  /**
   * Full 12-persona array from POST/GET /api/gtm/personas/<id>.
   * @type {Array<{
   *   id: string, name: string, title: string, company_type: string,
   *   company_stage: string, persona_type: string, primary_goal: string,
   *   pain_points: string[], buying_triggers: string[], objections: string[],
   *   communication_style: string, budget_sensitivity: 'low'|'medium'|'high',
   *   risk_tolerance: 'low'|'medium'|'high', preferred_channels: string[],
   *   likely_message_angle: string, summary: string,
   *   reaction: 'interested'|'neutral'|'objection', skepticism_level: number,
   *   likely_response: string, objection_category: string|null
   * }>|null}
   */
  personas: null,
  /** @type {Array<{id, angle, subject_line, body, target_persona_reasoning}>|null} */
  messages: null,
  /**
   * Full reaction result from POST/GET /api/gtm/reactions/<id>.
   * @type {{
   *   reactions: Array<{id, persona_id, message_id, interest_score, clarity_score,
   *     trust_score, urgency_score, objection, buying_trigger, preferred_cta,
   *     risk_signal, simulated_reply, verdict}>|null,
   *   summaries: Array<{message_id, angle, average_interest_score, positive_count, ...}>|null,
   *   winner: {winner_message_id, winner_angle, close_test, note}|null
   * }|null}
   */
  reactionResult: null,
  /** @type {object|null} Full GTMReport from POST/GET /api/gtm/report/<id> */
  report: null,
  /** @type {string|null} */
  error: null,
})

export function setGTMBrief(briefData) {
  state.brief = briefData
  state.status = 'submitting'
  state.error = null
}

export function setSimulationPreview(briefId, previewData) {
  state.briefId = briefId
  state.preview = previewData
  state.status = 'preview'
}

export function setPersonas(personasArray) {
  state.personas = personasArray
}

export function getPersonas() {
  return state.personas
}

export function setMessageResults(data) {
  state.messages = data.messages ?? data
  if (data.reactions !== undefined) {
    state.reactionResult = {
      reactions: data.reactions,
      summaries: data.summaries ?? null,
      winner: data.winner ?? null,
    }
  }
}

export function getMessageResults() {
  return {
    messages: state.messages,
    reactionResult: state.reactionResult,
  }
}

export function setReport(reportData) {
  state.report = reportData
}

export function getReport() {
  return state.report
}

export function setGTMError(message) {
  state.error = message
  state.status = 'error'
}

export function getGTMState() {
  return {
    brief: state.brief,
    briefId: state.briefId,
    status: state.status,
    preview: state.preview,
    personas: state.personas,
    error: state.error,
  }
}

export function resetGTMState() {
  state.brief = null
  state.briefId = null
  state.status = 'idle'
  state.preview = null
  state.personas = null
  state.messages = null
  state.reactionResult = null
  state.report = null
  state.error = null
}

export default state
