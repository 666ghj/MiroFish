import service from './index'

/**
 * OrcaRouter provider API.
 *
 * The OrcaRouter API key is held server-side in the project's own secret
 * location (.env); the browser only ever sees a redacted preview. Model
 * discovery is server-side too, so the key never reaches the browser.
 */

export const getOrcaStatus = () => service.get('/api/orcarouter/status')

export const saveOrcaKey = (key) => service.post('/api/orcarouter/key', { key })

export const clearOrcaKey = () => service.delete('/api/orcarouter/key')

export const startOrcaConnect = () => service.post('/api/orcarouter/connect/start')

export const exchangeOrcaCode = (attempt_id, code) =>
  service.post('/api/orcarouter/connect/exchange', { attempt_id, code })

export const cancelOrcaConnect = (attempt_id) =>
  service.post('/api/orcarouter/connect/cancel', { attempt_id })

export const getOrcaModels = (capability = 'chat') =>
  service.get('/api/orcarouter/models', { params: { capability } })

export const setOrcaModel = (model) => service.post('/api/orcarouter/model', { model })

export const setOrcaProvider = (provider) =>
  service.post('/api/orcarouter/provider', { provider })

export const markOrcaReauth = () => service.post('/api/orcarouter/reauth')
