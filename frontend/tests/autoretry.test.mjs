import test from 'node:test'
import assert from 'node:assert/strict'
import { createRetryController, RETRY_DELAYS } from '../src/utils/autoRetry.js'

function fixture(storage = new Map(), retry = () => {}) {
  let id = 0
  const timers = new Map()
  const calls = []
  const controller = createRetryController({
    storage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    setTimer: (fn, delay) => { timers.set(++id, { fn, delay }); return id },
    clearTimer: id => timers.delete(id),
    retry: metadata => { calls.push(metadata); retry(metadata) },
  })
  let props = { retryKey: 'operation-a', error: 'Failure', busy: false, autoRetry: true, completed: false }
  return { controller, calls, timers, storage,
    update(next = {}) { props = { ...props, ...next }; controller.update(props) },
    tick(expectedDelay) {
      assert.equal(timers.size, 1)
      const [id, { fn, delay }] = timers.entries().next().value
      assert.equal(delay, expectedDelay)
      timers.delete(id)
      fn()
    },
  }
}

function failAgain(f) {
  f.update({ busy: true, error: '' })
  f.update({ busy: false }) // Request accepted; background job still running.
  assert.equal(f.timers.size, 0)
  f.update({ error: 'Failure' })
}

test('exactly three retries after initial failure use 2/5/10s, then show manual resume', () => {
  const f = fixture()
  f.update()
  for (const [index, delay] of RETRY_DELAYS.entries()) {
    assert.equal(f.controller.getState().manual, false)
    assert.equal(f.controller.getState().attempt, index + 1)
    f.tick(delay)
    failAgain(f)
  }
  assert.equal(f.calls.length, 3)
  assert.deepEqual(f.calls, [{ automatic: true }, { automatic: true }, { automatic: true }])
  assert.equal(f.timers.size, 0)
  assert.equal(f.controller.getState().manual, true)
  f.update({ busy: true }); f.update({ busy: false })
  assert.equal(f.timers.size, 0)
})

test('clearing the error and accepting a resumed job retains its budget until explicit completion', () => {
  const f = fixture()
  f.update(); f.tick(2000)
  f.update({ error: '', busy: true }); f.update({ busy: false })
  assert.equal(f.controller.getState().attempts, 1)
  assert.equal(f.controller.getState().inFlight, true)
  f.update({ completed: true })
  assert.equal(f.controller.getState().attempts, 0)
  assert.equal(f.controller.getState().inFlight, false)
  assert.equal(f.storage.size, 0)
  f.update({ completed: false, error: 'New failure' })
  f.tick(2000)
})

test('busy and a persistent error cannot create overlapping attempts', () => {
  const f = fixture()
  f.update({ busy: true }); assert.equal(f.timers.size, 0)
  f.update({ busy: false }); f.tick(2000)
  assert.equal(f.controller.manualRetry(), false)
  f.update({ busy: true }); f.update({ busy: false })
  assert.equal(f.timers.size, 0, 'same error is not a new failure')
  assert.equal(f.calls.length, 1)
  failAgain(f)
  assert.equal(f.timers.size, 1)
})

test('refresh retains consumed retries, and manual resume begins a fresh cycle', () => {
  const f = fixture()
  f.update(); f.tick(2000); f.controller.dispose()
  const g = fixture(f.storage)
  g.update(); g.tick(5000); failAgain(g); g.tick(10000); failAgain(g)
  assert.equal(g.controller.getState().manual, true)
  g.controller.dispose()
  const h = fixture(f.storage)
  h.update()
  assert.equal(h.timers.size, 0)
  assert.equal(h.controller.manualRetry(), true)
  assert.deepEqual(h.calls, [{ automatic: false }])
  failAgain(h); h.tick(2000)
  assert.equal(h.controller.getState().attempts, 1)
})

test('unmount cancels timers, and navigation isolates operation identities', () => {
  const f = fixture()
  f.update(); f.tick(2000); failAgain(f)
  f.update({ retryKey: 'operation-b' })
  f.tick(2000)
  assert.equal(f.controller.getState().attempts, 1)
  f.update({ retryKey: 'operation-a' })
  assert.equal(f.controller.getState().attempts, 1)
  f.tick(5000); failAgain(f)
  f.controller.dispose()
  assert.equal(f.timers.size, 0)
  f.update({ retryKey: 'operation-c' })
  assert.equal(f.timers.size, 0)
})

test('intentional stop or invalid inputs can disable automatic recovery', () => {
  const f = fixture()
  f.update(); f.update({ autoRetry: false })
  assert.equal(f.timers.size, 0)
  assert.equal(f.controller.getState().manual, true)
  const g = fixture()
  g.update({ retryKey: '' })
  assert.equal(g.timers.size, 0)
  assert.equal(g.controller.getState().manual, true)
})

test('unavailable sessionStorage does not prevent bounded recovery', () => {
  const c = createRetryController({ retry() {}, storage: { getItem() { throw Error() } }, setTimer: () => 1, clearTimer() {} })
  c.update({ retryKey: 'one', error: 'Offline' })
  assert.equal(c.getState().scheduled, true)
  c.dispose()
})
