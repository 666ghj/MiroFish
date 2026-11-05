// MiniMax OpenAI-compatible endpoint/model: https://platform.minimax.io/docs/api-reference/text-openai-api
export const aiProviders = [
  { id: 'custom', label: null },
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { id: 'minimax', label: 'MiniMax', baseUrl: 'https://api.minimax.io/v1', model: 'MiniMax-M3.1-Flash' }
]

export function detectProvider(baseUrl) {
  const normalized = baseUrl.replace(/\/+$/, '')
  return aiProviders.find(provider => provider.baseUrl === normalized)?.id || 'custom'
}
