import service from './index'

/**
 * Idea Studio API.
 * Sessions are stored server-side as JSON; replies stream as Server-Sent Events.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'

export const createIdeaSession = (title) =>
  service.post('/api/idea/sessions', title ? { title } : {})

export const getIdeaSession = (sessionId) =>
  service.get(`/api/idea/sessions/${sessionId}`)

export const listIdeaSessions = (limit = 20) =>
  service.get('/api/idea/sessions', { params: { limit } })

/**
 * Send a message and stream the co-founder's reply.
 *
 * Axios cannot read a response while it streams, so this uses fetch + a stream reader.
 *
 * @param {string} sessionId
 * @param {string} content
 * @param {{ onDelta?: (text: string) => void, signal?: AbortSignal }} [opts]
 * @returns {Promise<object>} the final saved assistant message
 * @throws {Error} on HTTP errors, model errors, or a stream that ends without a reply
 */
export async function streamIdeaMessage(sessionId, content, { onDelta, signal } = {}) {
  const res = await fetch(`${BASE_URL}/api/idea/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try { msg = (await res.json()).error || msg } catch (_) {}
    throw new Error(msg)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final = null

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE events are separated by a blank line
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = raw.split('\n').find(l => l.startsWith('data: '))
      if (!line) continue
      const event = JSON.parse(line.slice(6))
      if (event.type === 'delta') onDelta?.(event.text)
      else if (event.type === 'done') final = event.message
      else if (event.type === 'error') throw new Error(event.error)
    }
  }
  if (!final) throw new Error('The reply ended unexpectedly.')
  return final
}
