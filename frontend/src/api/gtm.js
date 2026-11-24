import service from './index'

// Retry helper kept local to the GTM API (upstream MiroFish removed its shared copy).
const requestWithRetry = async (requestFn, maxRetries = 3, delay = 1000) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await requestFn()
    } catch (error) {
      if (i === maxRetries - 1) throw error
      console.warn(`Request failed, retrying (${i + 1}/${maxRetries})...`)
      await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, i)))
    }
  }
}

/**
 * Submit a new GTM brief.
 * @param {object} data - normalized payload from formatGTMBrief()
 * @returns {Promise<{success: boolean, data: {brief_id: string, brief: object}}>}
 */
export const submitGTMBrief = (data) =>
  requestWithRetry(() => service.post('/api/gtm/brief', data), 3, 1000)

/**
 * Retrieve a stored GTM brief by ID.
 * @param {string} briefId
 */
export const getGTMBrief = (briefId) =>
  service.get(`/api/gtm/brief/${briefId}`)

/**
 * Get mock simulation preview data for a brief.
 * Returns 3 buyer persona previews + 2 message angle teasers.
 * @param {string} briefId
 */
export const getGTMPreview = (briefId) =>
  service.get(`/api/gtm/brief/${briefId}/preview`)

/**
 * List recent GTM briefs.
 * @param {number} limit
 */
export const listGTMBriefs = (limit = 20) =>
  service.get('/api/gtm/briefs', { params: { limit } })

/**
 * Generate 10–12 buyer personas for a brief (LLM + fallback to mock).
 * Idempotent - returns cached personas if already generated.
 * @param {string} briefId
 * @param {number} [count=12]
 * @returns {Promise<{success: boolean, data: object[], cached: boolean}>}
 */
export const generatePersonas = (briefId, count = 12) =>
  requestWithRetry(
    () => service.post(`/api/gtm/personas/${briefId}`, { count }),
    3, 1500
  )

/**
 * Retrieve cached personas for a brief (generates if not yet cached).
 * @param {string} briefId
 */
export const getPersonas = (briefId) =>
  service.get(`/api/gtm/personas/${briefId}`)

/**
 * Generate 3 outreach message variants for a brief (LLM + fallback to mock).
 * Idempotent - returns cached messages if already generated.
 * @param {string} briefId
 * @returns {Promise<{success: boolean, data: object[], cached: boolean}>}
 */
export const generateMessages = (briefId) =>
  requestWithRetry(() => service.post(`/api/gtm/messages/${briefId}`), 3, 1500)

/**
 * Retrieve cached messages for a brief (generates if not yet cached).
 * @param {string} briefId
 */
export const getMessages = (briefId) =>
  service.get(`/api/gtm/messages/${briefId}`)

/**
 * Simulate all persona × message reactions for a brief (LLM + fallback to mock).
 * Idempotent - returns cached reactions if already simulated.
 * @param {string} briefId
 * @returns {Promise<{success: boolean, data: {reactions, summaries, winner}, cached: boolean}>}
 */
export const generateReactions = (briefId) =>
  requestWithRetry(() => service.post(`/api/gtm/reactions/${briefId}`), 3, 2000)

/**
 * Retrieve cached reaction results for a brief (auto-simulates if missing).
 * @param {string} briefId
 */
export const getReactions = (briefId) =>
  service.get(`/api/gtm/reactions/${briefId}`)

/**
 * Generate a structured GTM report for a brief (LLM + deterministic + mock fallback).
 * Idempotent - returns cached report if already generated.
 * @param {string} briefId
 * @returns {Promise<{success: boolean, data: object, cached: boolean}>}
 */
export const generateReport = (briefId) =>
  requestWithRetry(() => service.post(`/api/gtm/report/${briefId}`), 3, 2000)

/**
 * Retrieve cached GTM report for a brief (auto-generates if missing).
 * @param {string} briefId
 */
export const getReport = (briefId) =>
  service.get(`/api/gtm/report/${briefId}`)
