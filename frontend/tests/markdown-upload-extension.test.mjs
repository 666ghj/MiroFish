import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/views/Home.vue', import.meta.url), 'utf8')
const start = source.indexOf('const addFiles = (newFiles) => {')
const handler = source.slice(start, source.indexOf('// 移除文件', start))

test('accept Markdown long extensions alongside existing document formats', () => {
  const files = { value: [] }
  const addFiles = new Function('files', `${handler}; return addFiles`)(files)
  const supported = ['notes.markdown', 'NOTES.MARKDOWN', 'notes.md', 'paper.pdf', 'notes.txt']
  addFiles([...supported, 'archive.zip'].map(name => new File(['text'], name)))
  assert.deepEqual(files.value.map(file => file.name), supported)
})

test('native file picker allows the backend-supported long Markdown extension', () => {
  const accept = source.match(/accept="([^"]+)"/)[1].split(',')
  for (const extension of ['.pdf', '.md', '.markdown', '.txt']) {
    assert.ok(accept.includes(extension), `missing picker extension ${extension}`)
  }
})
