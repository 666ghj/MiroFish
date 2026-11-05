import assert from 'node:assert/strict'
import { test } from 'node:test'
import { aiProviders, detectProvider } from '../src/config/aiProviders.js'

test('MiniMax preset supplies the documented OpenAI-compatible API and a model', () => {
  const provider = aiProviders.find(item => item.id === 'minimax')
  assert.equal(provider.baseUrl, 'https://api.minimax.io/v1')
  assert.equal(provider.model, 'MiniMax-M3.1-Flash')
  assert.equal(detectProvider(`${provider.baseUrl}/`), 'minimax')
})

test('reopening settings recognizes the provider without rewriting custom URLs', () => {
  assert.equal(detectProvider('https://api.openai.com/v1'), 'openai')
  assert.equal(detectProvider('https://my-model.example.org/v1'), 'custom')
  assert.equal(detectProvider('https://api.minimax.io.evil.example/v1'), 'custom')
})
