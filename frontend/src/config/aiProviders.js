// MiniMax OpenAI-compatible endpoint/model: https://platform.minimax.io/docs/api-reference/text-openai-api
export const aiProviders = [
  { id: 'custom', label: null },
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { id: 'minimax', labelKey: 'aiSettings.minimaxApi', keyType: 'api', baseUrl: 'https://api.minimax.io/v1', model: 'MiniMax-M3.1-Flash' },
  { id: 'minimax_m_plan', labelKey: 'aiSettings.minimaxPlan', keyType: 'm_plan', baseUrl: 'https://api.minimax.io/v1', model: 'MiniMax-M3.1-Flash' }
]

export function detectProvider(baseUrl, keyType = null) {
  const normalized = baseUrl.replace(/\/+$/, '')
  if (normalized === 'https://api.minimax.io/v1' && keyType === 'm_plan') return 'minimax_m_plan'
  return aiProviders.find(provider => provider.baseUrl === normalized)?.id || 'custom'
}
