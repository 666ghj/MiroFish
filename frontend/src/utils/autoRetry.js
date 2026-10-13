export const RETRY_DELAYS = [2000, 5000, 10000]
const PREFIX = 'miro-recovery:'

// An attempt lasts until a new failure or explicit completion, including time spent
// polling a resumed background job. Clearing an error is not a successful operation.
export function createRetryController({ retry, onChange = () => {}, storage,
  setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let key = ''
  let attempts = 0
  let timer = null
  let inFlight = false
  let sawClear = false
  let disposed = false
  let lastError = ''
  let input = { error: '', busy: false, autoRetry: true, completed: false }
  const cancel = () => { if (timer !== null) clearTimer(timer); timer = null }
  const persist = () => { try { storage?.setItem(PREFIX + key, String(attempts)) } catch {} }
  const read = () => {
    try { return Math.min(RETRY_DELAYS.length, Math.max(0, Number(storage?.getItem(PREFIX + key)) || 0)) }
    catch { return 0 }
  }
  const snapshot = () => ({ attempts, inFlight, scheduled: timer !== null,
    attempt: timer !== null ? attempts + 1 : attempts,
    max: RETRY_DELAYS.length, lastError,
    manual: !!input.error && !inFlight && timer === null && (!input.autoRetry || !key || attempts >= RETRY_DELAYS.length) })
  const publish = () => onChange(snapshot())
  const reset = () => {
    cancel()
    attempts = 0
    inFlight = false
    sawClear = false
    lastError = ''
    try { storage?.removeItem(PREFIX + key) } catch {}
  }
  const run = automatic => {
    if (disposed || input.busy || inFlight || !input.error) return false
    cancel()
    if (!automatic) reset()
    else { attempts += 1; persist() }
    lastError = input.error
    inFlight = true
    sawClear = false
    publish()
    retry({ automatic })
    return true
  }
  const reconcile = () => {
    if (disposed) return
    if (input.completed && !input.error && !input.busy) reset()
    else {
      if (input.error) lastError = input.error
      if (inFlight && !input.error) sawClear = true
      if (inFlight && sawClear && input.error && !input.busy) inFlight = false
      if (!input.autoRetry) { cancel(); inFlight = false }
      if (!input.error || input.busy || !input.autoRetry) cancel()
      if (input.error && !input.busy && input.autoRetry && key && !inFlight && timer === null && attempts < RETRY_DELAYS.length) {
        timer = setTimer(() => { timer = null; run(true) }, RETRY_DELAYS[attempts])
      }
    }
    publish()
  }
  return {
    update(next) {
      if (disposed) return
      const nextKey = next.retryKey || ''
      if (nextKey !== key) {
        cancel()
        key = nextKey
        attempts = read()
        inFlight = false
        sawClear = false
        lastError = ''
      }
      input = { ...input, ...next }
      reconcile()
    },
    manualRetry() { return run(false) },
    getState: snapshot,
    dispose() { disposed = true; cancel() },
  }
}
