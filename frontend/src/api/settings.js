import service from './index'

export function getAISettings() {
  return service({ url: '/api/settings/ai', method: 'get' })
}

export function saveAISettings(data, setupToken) {
  return service({ url: '/api/settings/ai', method: 'post', data, headers: { 'X-MiroFish-Setup': setupToken } })
}
