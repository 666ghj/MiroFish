import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

function downloadComponent(downloadReportPdf, disabled = false) {
  const setup = readFileSync(new URL('../src/components/ReportDownload.vue', import.meta.url), 'utf8')
    .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import.*$/gm, '')
  const saved = []
  const context = vm.createContext({
    ref: value => ({ value }), watch() {}, defineProps: () => ({ reportId: 'report_abc', disabled }),
    useI18n: () => ({ t: key => key }), downloadReportPdf,
    savePdfBlob: (blob, name) => saved.push({ blob, name }),
  })
  vm.runInContext(setup+'\nglobalThis.subject = { download, downloading, downloadError, downloaded }', context)
  return { ...context.subject, saved }
}

test('PDF download exports the current saved report without starting generation', async () => {
  const ids = []; const pdf = { type: 'application/pdf' }
  const c = downloadComponent(async id => { ids.push(id); return pdf })
  await c.download()
  assert.deepEqual(ids, ['report_abc'])
  assert.equal(c.saved[0].blob, pdf)
  assert.equal(c.saved[0].name, 'report_abc.pdf')
  assert.equal(c.downloaded.value, true)
})

test('download failure remains visible and another attempt can succeed', async () => {
  let fail = true
  const c = downloadComponent(async () => { if (fail) throw new Error('Export unavailable'); return {} })
  await c.download()
  assert.equal(c.downloadError.value, 'Export unavailable')
  assert.equal(c.downloading.value, false)
  assert.equal(c.saved.length, 0)
  fail = false
  await c.download()
  assert.equal(c.downloadError.value, '')
  assert.equal(c.saved.length, 1)
})

test('incomplete reports and repeated clicks do not start duplicate exports', async () => {
  let calls = 0; let finish
  const api = () => { calls++; return new Promise(resolve => { finish = resolve }) }
  await downloadComponent(api, true).download()
  assert.equal(calls, 0)
  const c = downloadComponent(api)
  const pending = c.download()
  await c.download()
  assert.equal(calls, 1)
  finish({})
  await pending
})
