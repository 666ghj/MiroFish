import service from './index'

export const getProviderStatus = () => service.get('/api/provider/status')
export const activateCodex = () => service.post('/api/provider/codex/activate')
export const deactivateCodex = () => service.post('/api/provider/codex/deactivate')
export const startChatGPT = (accountKey = null) => service.post('/api/provider/chatgpt/start', { account_key: accountKey })
export const getChatGPTModels = () => service.get('/api/provider/chatgpt/models')
export const activateChatGPT = (model) => service.post('/api/provider/chatgpt/activate', { model })
export const deactivateChatGPT = () => service.post('/api/provider/chatgpt/deactivate')
