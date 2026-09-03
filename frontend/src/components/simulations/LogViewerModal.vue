<template>
  <teleport to="#app-modals">
    <div class="log-scrim" @click.self="close">
      <section
        class="log-modal"
        role="dialog"
        aria-modal="true"
        :aria-label="heading"
        @keydown.esc.stop="close"
      >
        <header class="log-head">
          <div class="log-title-block">
            <h2 class="log-title">{{ heading }}</h2>
            <span class="log-path">{{ meta.path || sourceLabel }}</span>
          </div>

          <span class="log-live" :class="{ 'is-live': isLive }">
            <i class="dot" />{{ isLive ? $t('simulations.logs.live') : $t('simulations.logs.notLive') }}
          </span>

          <button
            ref="closeButton"
            type="button"
            class="icon-btn"
            :aria-label="$t('simulations.logs.close')"
            :title="$t('simulations.logs.close')"
            @click="close"
          >
            <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path d="M3.5 3.5 L12.5 12.5 M12.5 3.5 L3.5 12.5" fill="none"
                stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          </button>
        </header>

        <div class="log-toolbar">
          <div class="log-sources" role="tablist" :aria-label="heading">
            <button
              v-for="source in LOG_SOURCES"
              :key="source.id"
              type="button"
              role="tab"
              class="source-tab"
              :class="{ 'is-active': activeSource === source.id }"
              :aria-selected="activeSource === source.id"
              @click="selectSource(source.id)"
            >
              {{ source.label }}
            </button>
          </div>

          <div class="log-tools">
            <span class="log-count">{{ $t('simulations.logs.lineCount', { count: lines.length }) }}</span>

            <label class="log-toggle">
              <input v-model="wrap" type="checkbox" />
              {{ $t('simulations.logs.wrap') }}
            </label>

            <button
              type="button"
              class="tool-btn"
              :class="{ 'is-on': follow }"
              :aria-pressed="follow"
              @click="toggleFollow"
            >
              {{ follow ? $t('simulations.logs.unfollow') : $t('simulations.logs.follow') }}
            </button>

            <button type="button" class="tool-btn" :disabled="!lines.length" @click="copyLog">
              {{ copied ? $t('simulations.logs.copied') : $t('simulations.logs.copy') }}
            </button>

            <button type="button" class="tool-btn" :disabled="!lines.length" @click="downloadLog">
              {{ $t('simulations.logs.download') }}
            </button>
          </div>
        </div>

        <p v-if="meta.truncated && lines.length" class="log-note">
          {{ $t('simulations.logs.truncated', { count: lines.length }) }}
        </p>

        <div ref="well" class="log-well" :class="{ 'is-wrapped': wrap }" @scroll="onScroll">
          <p v-if="loading && !lines.length" class="log-state">
            {{ $t('simulations.logs.loading') }}
          </p>

          <p v-else-if="error" class="log-state is-error">
            {{ $t('simulations.logs.loadFailed', { error }) }}
            <button type="button" class="tool-btn" @click="reload">{{ $t('common.retry') }}</button>
          </p>

          <div v-else-if="!lines.length" class="log-state">
            <strong>{{ $t('simulations.logs.empty') }}</strong>
            <span>{{ $t('simulations.logs.emptyDesc') }}</span>
          </div>

          <pre v-else class="log-lines"><span
            v-for="(line, index) in lines"
            :key="`${index}-${line.slice(0, 24)}`"
            class="log-line"
            :class="lineTone(line)"
          >{{ line }}</span></pre>
        </div>
      </section>
    </div>
  </teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSimulationLogs } from '../../api/simulation'
import { formatSimulationId } from '../../utils/simulationFormat'

const props = defineProps({
  simulationId: { type: String, required: true },
  // Used for the dialog heading only; the caller already resolved the fallback
  // copy for a simulation with no project behind it.
  name: { type: String, default: '' }
})

const emit = defineEmits(['close'])

const { t } = useI18n()

// The four windows the backend exposes, in the order a reader wants them: the
// simulation's own log first, the two platform action streams next, and the
// application log last - that one is the only trace a simulation leaves before
// it has a simulation.log of its own. Twitter and Reddit are product names and
// stay as they are written.
const LOG_SOURCES = Object.freeze([
  { id: 'main', label: 'Simulation' },
  { id: 'twitter', label: 'Twitter' },
  { id: 'reddit', label: 'Reddit' },
  { id: 'backend', label: 'Backend' }
])

// Enough history to scroll through without letting a multi-hour run grow the
// buffer until the tab stalls.
const MAX_BUFFERED_LINES = 4000
const POLL_INTERVAL_MS = 2000

const activeSource = ref('main')
const lines = ref([])
const meta = ref({})
const loading = ref(false)
const error = ref('')
const follow = ref(true)
const wrap = ref(false)
const copied = ref(false)
const isLive = ref(false)

const well = ref(null)
const closeButton = ref(null)

let nextOffset = null
let pollTimer = null
let copyTimer = null
// A request in flight when the viewer closes still runs its finally block, and
// without this it would schedule a poll nothing is left to cancel.
let disposed = false

const heading = computed(() =>
  props.name
    ? t('simulations.logs.titleFor', { name: props.name })
    : t('simulations.logs.title')
)

const sourceLabel = computed(
  () => LOG_SOURCES.find((source) => source.id === activeSource.value)?.label || ''
)

const lineTone = (line) => {
  const upper = line.toUpperCase()
  if (upper.includes('ERROR') || upper.includes('TRACEBACK') || upper.includes('CRITICAL')) {
    return 'is-error'
  }
  if (upper.includes('WARNING') || upper.includes('WARN ')) return 'is-warn'
  return ''
}

const scrollToEnd = async () => {
  await nextTick()
  const element = well.value
  if (element) element.scrollTop = element.scrollHeight
}

// Following is switched off the moment the reader scrolls away from the end,
// so a poll never yanks the view back out from under them, and switched on
// again when they scroll back down to it.
const onScroll = () => {
  const element = well.value
  if (!element) return
  const atEnd = element.scrollHeight - element.scrollTop - element.clientHeight < 24
  follow.value = atEnd
}

const applyWindow = (data, { replace }) => {
  const incoming = Array.isArray(data.lines) ? data.lines : []

  // Every run reopens simulation.log with mode='w', so a restart truncates the
  // file and the offset held here points past its new end. The backend flags
  // that, and the buffer starts again rather than showing two runs spliced.
  if (replace || data.restarted) {
    lines.value = incoming
  } else if (incoming.length) {
    lines.value = lines.value.concat(incoming).slice(-MAX_BUFFERED_LINES)
  }

  meta.value = data
  nextOffset = typeof data.next_offset === 'number' ? data.next_offset : null
  isLive.value = data.live === true
}

const fetchWindow = async ({ replace = false } = {}) => {
  const params = { source: activeSource.value }
  if (!replace && nextOffset !== null) params.offset = nextOffset

  const res = await getSimulationLogs(props.simulationId, params)
  applyWindow(res.data || {}, { replace })
}

const load = async ({ replace = false } = {}) => {
  if (replace) {
    loading.value = true
    error.value = ''
  }

  try {
    await fetchWindow({ replace })
    error.value = ''
    if (follow.value) await scrollToEnd()
  } catch (err) {
    // A polling failure must not wipe the window already on screen.
    if (replace) lines.value = []
    error.value = err.message || t('common.unknownError')
  } finally {
    if (replace) loading.value = false
    scheduleNextPoll()
  }
}

// Polling stops on a terminal run, because the file will not change again, and
// while the tab is hidden, because nobody is reading it.
const scheduleNextPoll = () => {
  clearTimeout(pollTimer)
  pollTimer = null
  if (disposed || !isLive.value || document.visibilityState !== 'visible') return
  pollTimer = setTimeout(() => load(), POLL_INTERVAL_MS)
}

const onVisibilityChange = () => {
  if (document.visibilityState === 'visible') {
    if (isLive.value && !pollTimer) load()
  } else {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

const toggleFollow = () => {
  follow.value = !follow.value
  if (follow.value) scrollToEnd()
}

const selectSource = (source) => {
  if (source === activeSource.value) return
  activeSource.value = source
  nextOffset = null
  follow.value = true
  reload()
}

const reload = () => {
  clearTimeout(pollTimer)
  pollTimer = null
  nextOffset = null
  load({ replace: true })
}

const copyLog = async () => {
  try {
    await navigator.clipboard.writeText(lines.value.join('\n'))
    copied.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (err) {
    error.value = t('simulations.logs.copyFailed')
  }
}

const downloadLog = () => {
  const blob = new Blob([lines.value.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${formatSimulationId(props.simulationId)}-${activeSource.value}.log`
  anchor.click()
  URL.revokeObjectURL(url)
}

const close = () => emit('close')

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  closeButton.value?.focus()
  load({ replace: true })
})

onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('visibilitychange', onVisibilityChange)
  clearTimeout(pollTimer)
  clearTimeout(copyTimer)
})
</script>

<style scoped>
.log-scrim {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: var(--bg-scrim);
}

.log-modal {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1040px;
  height: 100%;
  max-height: 760px;
  overflow: hidden;
  background: var(--bg-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg), var(--edge-highlight);
}

.log-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}

.log-title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  margin-right: auto;
}

.log-title {
  overflow: hidden;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.log-path {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.log-live {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.log-live .dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-pill);
  background: var(--neutral-dot);
}

.log-live.is-live {
  color: var(--accent);
}

.log-live.is-live .dot {
  background: var(--accent);
  animation: log-pulse 1.2s infinite;
}

@keyframes log-pulse {
  50% { opacity: 0.35; }
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
}

.icon-btn .icon {
  width: 12px;
  height: 12px;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-subtle);
}

.log-sources {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--bg-inset);
  border-radius: var(--radius-md);
}

.source-tab {
  padding: 5px 12px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}

.source-tab:hover {
  color: var(--text-primary);
}

.source-tab.is-active {
  background: var(--bg-raised);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
}

.log-tools {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-left: auto;
}

.log-count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.log-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.log-toggle input {
  accent-color: var(--accent);
  cursor: pointer;
}

.tool-btn {
  padding: 5px 12px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.tool-btn:not(:disabled):hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tool-btn:disabled {
  opacity: 0.5;
}

.tool-btn.is-on {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent);
}

.log-note {
  padding: 8px 20px;
  background: var(--warning-soft);
  border-bottom: 1px solid var(--warning-border);
  font-size: 12px;
  color: var(--warning);
}

.log-well {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px 20px;
  background: var(--term-bg);
}

.log-lines {
  display: flex;
  flex-direction: column;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.65;
  color: var(--term-fg);
}

.log-line {
  white-space: pre;
}

.log-well.is-wrapped .log-line {
  white-space: pre-wrap;
  word-break: break-word;
}

.log-line.is-error {
  color: var(--term-error);
}

.log-line.is-warn {
  color: var(--term-warn);
}

.log-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 56px 20px;
  font-size: 13px;
  color: var(--term-dim);
  text-align: center;
}

.log-state strong {
  font-size: 14px;
  color: var(--text-secondary);
}

.log-state.is-error {
  color: var(--danger);
}

@media (max-width: 860px) {
  .log-scrim {
    padding: 12px;
  }

  .log-tools {
    margin-left: 0;
  }
}
</style>
