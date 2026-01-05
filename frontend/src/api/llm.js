import service from './index'

export const getLlmConfig = () => service.get('/api/llm/config')

export const saveLlmConfig = (payload) => service.post('/api/llm/config', payload)

export const listLlmModels = () => service.get('/api/llm/models')

export const getLlmUsage = (limit = 5000) => service.get('/api/llm/usage', { params: { limit } })

// Stage definitions for model routing
export const getLlmStages = () => service.get('/api/llm/stages')

// Model routing presets
export const getLlmPresets = () => service.get('/api/llm/presets')

// Quick set model routing (with routing object or preset name)
export const setLlmRouting = (payload) => service.post('/api/llm/routing', payload)

