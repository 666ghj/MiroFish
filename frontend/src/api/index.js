import axios from 'axios'

// The shared axios instance.
const service = axios.create({
  // UXE fork: default to same-origin. The previous default
  // ('http://localhost:5001') is resolved by the BROWSER, so opening the UI
  // from any machine other than the server hit that machine's own port 5001
  // and failed. Every request path already starts with '/api', which Vite's
  // dev proxy (vite.config.js), or any reverse proxy, forwards to the
  // backend. Consequence: only the frontend port needs to be exposed.
  // Set VITE_API_BASE_URL only to target a backend on a different origin.
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  // Ontology generation and graph building both run inline, and either can take
  // several minutes on a large document.
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// No Accept-Language header is sent. English is the only language SoSim ships,
// and the backend no longer reads the header: locale.py resolves every key
// against locales/en.json regardless of the request.

service.interceptors.response.use(
  response => {
    const res = response.data

    // A 2xx body can still report a failure. The stop endpoint answers 202
    // with success:false and pending:true while the previous monitor finishes
    // publishing its terminal state, so the response is attached to the error:
    // a caller that has to tell "pending" from "failed" reads
    // err.response.data.pending, exactly as it would for a non-2xx reply.
    if (res && res.success === false) {
      const error = new Error(res.error || res.message || 'Request failed')
      error.response = response
      console.error('API error:', error.message)
      return Promise.reject(error)
    }

    return res
  },
  error => {
    console.error('Response error:', error)
    const apiError = error.response?.data?.error || error.response?.data?.message

    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.error('Request timed out')
    }

    if (error.message === 'Network Error') {
      console.error('Network error - check the connection to the backend')
    }

    // Axios rejects non-2xx responses before the success interceptor can
    // surface the backend's safe, actionable error message.
    if (typeof apiError === 'string' && apiError) {
      error.message = apiError
    }

    return Promise.reject(error)
  }
)

export default service
