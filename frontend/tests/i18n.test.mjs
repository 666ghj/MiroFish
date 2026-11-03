import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { baseCompile } from '@intlify/message-compiler'
import { resolveLocale } from '../src/i18n/locale.js'

const catalogs = ['en', 'zh', 'pt-BR']

test('saved language aliases resolve to available catalogs', () => {
  for (const value of ['pt', 'pt-br', 'PT_br', 'pt-BR', 'pt-PT']) {
    assert.equal(resolveLocale(value, catalogs), 'pt-BR')
  }
  assert.equal(resolveLocale('en-US', catalogs), 'en')
  assert.equal(resolveLocale('zh-CN', catalogs), 'zh')
  assert.equal(resolveLocale('fr', catalogs), undefined)
  assert.equal(resolveLocale(null, catalogs), undefined)
})

test('every Brazilian Portuguese message compiles with Vue I18n', () => {
  const messages = JSON.parse(readFileSync(new URL('../../locales/pt-BR.json', import.meta.url), 'utf8'))
  function visit(value, key = '') {
    if (typeof value === 'object') {
      for (const [name, child] of Object.entries(value)) visit(child, `${key}.${name}`)
    } else {
      baseCompile(value, { onError: error => assert.fail(`${key}: ${error.message}`) })
    }
  }
  visit(messages)
})
