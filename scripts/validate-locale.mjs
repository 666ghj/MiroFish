import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(new URL('..', import.meta.url).pathname)
const localePath = (name) => resolve(root, 'locales', `${name}.json`)
const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'))

const languages = readJson(resolve(root, 'locales', 'languages.json'))
const en = readJson(localePath('en'))
const ptPath = localePath('pt-BR')

const errors = []

if (!languages['pt-BR']) {
  errors.push('languages.json must register pt-BR')
}

if (!existsSync(ptPath)) {
  errors.push('locales/pt-BR.json must exist')
}

const flattenKeys = (value, prefix = '') => {
  if (Array.isArray(value)) {
    return [prefix]
  }
  if (value && typeof value === 'object') {
    return Object.keys(value).flatMap((key) => flattenKeys(value[key], prefix ? `${prefix}.${key}` : key))
  }
  return [prefix]
}

if (existsSync(ptPath)) {
  const pt = readJson(ptPath)
  const enKeys = flattenKeys(en).sort()
  const ptKeys = flattenKeys(pt).sort()
  const missing = enKeys.filter((key) => !ptKeys.includes(key))
  const extra = ptKeys.filter((key) => !enKeys.includes(key))

  if (missing.length) {
    errors.push(`pt-BR is missing keys: ${missing.slice(0, 20).join(', ')}`)
  }
  if (extra.length) {
    errors.push(`pt-BR has extra keys: ${extra.slice(0, 20).join(', ')}`)
  }

  const firstScreenKeys = [
    'home.dragToUpload',
    'home.startEngine',
    'home.tagline',
    'home.promptPlaceholder',
    'home.workflowSequence',
    'main.layoutWorkbench'
  ]

  const getValue = (obj, path) => path.split('.').reduce((current, key) => current?.[key], obj)
  for (const key of firstScreenKeys) {
    const value = getValue(pt, key)
    if (typeof value !== 'string') {
      errors.push(`pt-BR key ${key} must be a string`)
      continue
    }
    if (typeof value === 'string' && /\b(Upload|Start|Workflow|Workbench|Describe)\b/.test(value)) {
      errors.push(`pt-BR key ${key} still appears to be English: ${value}`)
    }
  }
}

if (errors.length) {
  console.error(errors.join('\n'))
  process.exit(1)
}

console.log('pt-BR locale validation passed')
