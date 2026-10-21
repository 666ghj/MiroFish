import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/GraphPanel.vue', import.meta.url), 'utf8')
const lifecycle = source.slice(source.indexOf('const handleResize = () => {'), source.indexOf('</script>'))

test('observe panel size changes and disconnect on unmount', () => {
  let mounted, unmounted, resizeObserver, observer, renders = 0
  const container = {}, graphContainer = { value: container }
  const currentSimulation = null
  const listeners = new Map()
  const window = {
    addEventListener: (event, callback) => listeners.set(event, callback),
    removeEventListener: (event, callback) => { if (listeners.get(event) === callback) listeners.delete(event) }
  }
  const onMounted = callback => { mounted = callback }
  const onUnmounted = callback => { unmounted = callback }
  const renderGraph = () => { renders++ }
  const nextTick = callback => callback()
  class ResizeObserver {
    constructor(callback) { this.callback = callback; observer = this }
    observe(target) { this.target = target }
    disconnect() { this.disconnected = true }
  }
  eval(lifecycle)
  mounted()
  assert.equal(observer?.target, container)
  observer.callback()
  assert.equal(renders, 1)
  listeners.get('resize')()
  assert.equal(renders, 2)
  unmounted()
  assert.equal(observer.disconnected, true)
  assert.equal(listeners.size, 0)
})
