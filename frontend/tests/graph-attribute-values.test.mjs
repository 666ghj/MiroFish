import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compile, createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

// Compile the actual property's template rather than duplicating its fallback.
const source = readFileSync(new URL('../src/components/GraphPanel.vue', import.meta.url), 'utf8')
const template = source.match(/<span class="property-value">[\s\S]*?<\/span>/)[0]
for (const [label, value, expected] of [
  ['zero', 0, '0'], ['false', false, 'false'], ['null', null, 'None'],
  ['undefined', undefined, 'None'], ['positive number', 7, '7'], ['empty string', '', '']
]) {
  test(`graph property preserves ${label}`, async () => {
    const app = createSSRApp({ data: () => ({ value }), render: compile(template) })
    assert.equal(await renderToString(app), `<span class="property-value">${expected}</span>`)
  })
}
