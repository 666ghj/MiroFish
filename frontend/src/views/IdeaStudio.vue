<template>
  <div class="studio" :data-busy="busy ? 'true' : 'false'">
    <!-- Top bar -->
    <header class="bar">
      <router-link to="/" class="brand">
        <img src="/favicon.svg" alt="" width="22" height="22" />
        <span>GTM Simulation Lab</span>
      </router-link>
      <span class="bar-title"><strong>Napkin</strong> <span class="bar-sub">talk an idea through</span></span>
      <span class="bar-spacer"></span>
      <span v-if="savedAt" class="saved" :title="'Saved in this browser at ' + savedAt">Saved in this browser</span>
      <label class="conf" :title="'Confidential mode: nothing is searched on the web'">
        <input type="checkbox" v-model="confidential" />
        <span class="switch" aria-hidden="true"></span>
        Confidential
      </label>
      <div class="menu">
        <button type="button" class="btn-ghost" @click="exportIdea" :disabled="!state">Export</button>
        <button type="button" class="btn-ghost" @click="fileInput?.click()">Import</button>
        <button type="button" class="btn-ghost btn-new" @click="startNew">New idea</button>
        <input ref="fileInput" type="file" accept="application/json" class="hidden" @change="importIdea" />
      </div>
    </header>

    <!-- Mobile tabs -->
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'chat'" :class="{ on: tab === 'chat' }" @click="tab = 'chat'">Chat</button>
      <button role="tab" :aria-selected="tab === 'panel'" :class="{ on: tab === 'panel' }" @click="tab = 'panel'">
        Live idea <span class="tab-score">{{ state?.clarity?.score ?? 0 }}</span>
        <span v-if="unseen" class="tab-dot" aria-label="updated"></span>
      </button>
    </div>

    <div class="body">
      <!-- Chat -->
      <section class="chat" :class="{ hide: tab !== 'chat' }" aria-label="Conversation">
        <div ref="scroller" class="messages" role="log" aria-live="polite" aria-relevant="additions">
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="`msg--${m.role}`">
            <div v-if="m.role === 'assistant'" class="avatar" aria-hidden="true">AI</div>
            <div class="bubble">
              <div class="bubble-text" v-html="render(m.content)" :aria-live="m.streaming ? 'off' : null"></div>
              <span v-if="m.streaming && !m.content" class="typing" aria-hidden="true"><i></i><i></i><i></i></span>
              <div v-if="m.notice" class="notice">{{ m.notice }}</div>
            </div>
          </div>
          <div v-if="isFresh" class="starters" aria-label="Ways to start">
            <button v-for="s in STARTERS" :key="s.title" type="button" class="starter" @click="useStarter(s)">
              <span class="starter-title">{{ s.title }}</span>
              <span class="starter-desc">{{ s.desc }}</span>
            </button>
          </div>
          <div v-if="status" class="status" role="status">
            <span class="spinner" aria-hidden="true"></span>{{ status }}
          </div>
          <div v-if="error" class="error" role="alert">
            {{ error }} <button type="button" class="link" @click="retry">Try again</button>
          </div>
        </div>

        <form class="composer" @submit.prevent="send()">
          <textarea
            ref="composer"
            v-model="draft"
            rows="2"
            maxlength="4000"
            :placeholder="messages.length > 1 ? 'Reply to your co-founder...' : 'Describe your idea, however rough...'"
            aria-label="Message your AI co-founder"
            :disabled="!state"
            @keydown.enter.exact.prevent="send()"
          ></textarea>
          <button type="submit" class="send" :disabled="busy || !draft.trim()" aria-label="Send">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 8h10M8.5 3.5L13 8l-4.5 4.5" /></svg>
          </button>
        </form>
        <div class="fine">
          A thinking tool, not investment, legal, or financial advice.
          <details class="privacy">
            <summary>How your idea is handled</summary>
            <ul>
              <li><strong>Stored:</strong> only in this browser. There is no account and no server copy. "New idea" clears it; Export saves a file.</li>
              <li><strong>AI:</strong> each message is sent through OpenRouter to the model provider. API providers say they do not train on it, but some keep requests briefly for abuse monitoring. We do not promise zero retention.</li>
              <li><strong>Search:</strong> only short category phrases are sent to Tavily, Exa, Hacker News, and GitHub, never your full description. The exact phrases are listed under "Why hasn't this been built yet?".</li>
              <li><strong>Confidential mode</strong> turns search off. For a stealth idea, run this open-source app yourself with your own API key.</li>
            </ul>
          </details>
        </div>
      </section>

      <!-- Live panel -->
      <aside class="side" :class="{ hide: tab !== 'panel' }" aria-label="Live idea analysis">
        <IdeaPanel
          v-if="state"
          :state="state"
          :changed="changed"
          :last-change="lastChange"
          :busy="busy"
          :confidential="confidential"
          @edit="onEdit"
          @lock="onLock"
          @research="research"
          @send-brief="sendBrief"
          @ask="draftAbout"
        />
      </aside>
    </div>

    <div class="sr-only" role="status" aria-live="polite">{{ announce }}</div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import IdeaPanel from '../components/IdeaPanel.vue'
import { newIdea, streamIdeaTurn, editIdeaField, lockIdeaField, ideaToBrief } from '../api/idea.js'

const STORE_KEY = 'idea-studio.v1'
const STARTERS = [
  { title: 'I have an idea', desc: 'Describe it roughly and sharpen it together.', text: 'My idea is ' },
  { title: 'Help me find one', desc: 'Start from problems you have seen, not from scratch.',
    text: "I want to start something but I don't have an idea yet. Here is what I know well: " },
  { title: 'Poke holes in mine', desc: 'Stress-test an idea you already believe in.',
    text: 'I have an idea I believe in. Please challenge it hard: ' },
]
const PATH_LABELS = [
  ['/one_liner', 'One-liner'], ['/problem/statement', 'Problem'], ['/problem/who', 'Who has it'],
  ['/problem/workaround', 'What they do today'], ['/problem/frequency', 'How often'], ['/problem/severity', 'What it costs'],
  ['/customer/early_adopters', 'First customers'], ['/customer/buyer', 'Who signs off'], ['/customer', 'Customer'],
  ['/solution/core', 'What it does'], ['/solution', 'Solution'], ['/business_model', 'Business model'],
  ['/why_now', 'Why now'], ['/what_could_work', 'What could work'], ['/what_wont_work', 'Red flags'],
  ['/challenges', 'Challenges'], ['/why_not_built/competitors', 'Competitors'], ['/why_not_built/predecessors', 'Tried before'],
  ['/why_not_built', 'Why not built'], ['/risky_assumptions', 'Risky assumptions'], ['/open_objections', 'Open concerns'],
]
const PREFILL_KEY = 'gtm.prefill.v1'
const router = useRouter()
const HISTORY_SENT = 12

const state = ref(null)
const messages = ref([])
const draft = ref('')
const busy = ref(false)
const status = ref('')
const error = ref('')
const changed = ref([])
const announce = ref('')
const confidential = ref(false)
const lastChange = ref(null)
const savedAt = ref('')
const isFresh = computed(() => messages.value.length <= 1 && !busy.value)
const tab = ref('chat')
const unseen = ref(false)
const scroller = ref(null)
const composer = ref(null)
const fileInput = ref(null)
let lastPayload = null
let clearTimer = null

// ── Persistence (browser only) ──────────────────────────────────────────────
function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      state: state.value, confidential: confidential.value,
      messages: messages.value.filter(m => !m.streaming).map(({ role, content, notice }) => ({ role, content, notice })),
    }))
    savedAt.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch (_) {}
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null')
    if (saved?.state && Array.isArray(saved.messages)) {
      state.value = saved.state
      messages.value = saved.messages
      confidential.value = !!saved.confidential
      return true
    }
  } catch (_) {}
  return false
}

async function startNew() {
  if (messages.value.length > 1 && !confirm('Start a new idea? The current one stays only if you export it first.')) return
  error.value = ''
  try {
    const res = await newIdea()
    state.value = res.data.state
    messages.value = [{ role: 'assistant', content: res.data.opening }]
    changed.value = []
    lastChange.value = null
    save()
  } catch (e) {
    error.value = 'Could not reach the server. Is the backend running on port 5001?'
  }
  focusComposer()
}

function exportIdea() {
  const blob = new Blob([JSON.stringify({ state: state.value, messages: messages.value }, null, 2)],
    { type: 'application/json' })
  const a = document.createElement('a')
  const name = (state.value?.one_liner?.text || 'idea').slice(0, 40).replace(/[^a-z0-9]+/gi, '-').toLowerCase()
  a.href = URL.createObjectURL(blob)
  a.download = `idea-studio-${name || 'idea'}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

async function importIdea(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  try {
    const data = JSON.parse(await file.text())
    if (!data?.state || !Array.isArray(data.messages)) throw new Error('not an Idea Studio export')
    // The server re-validates the state on the next turn; nothing imported is trusted.
    state.value = data.state
    messages.value = data.messages.map(({ role, content, notice }) => ({ role, content, notice }))
    changed.value = []
    save()
  } catch (err) {
    error.value = `Could not import that file: ${err.message}`
  }
}

// ── Turn ────────────────────────────────────────────────────────────────────
async function send(text, opts = {}) {
  const content = (text ?? draft.value).trim()
  if (!content || busy.value || !state.value) return
  draft.value = ''
  error.value = ''
  busy.value = true
  const history = messages.value.filter(m => !m.streaming).slice(-HISTORY_SENT)
    .map(({ role, content }) => ({ role, content }))
  messages.value.push({ role: 'user', content })
  const reply = { role: 'assistant', content: '', streaming: true, notice: null }
  messages.value.push(reply)
  const live = messages.value[messages.value.length - 1]
  status.value = ''
  scrollDown()

  lastPayload = { state: state.value, messages: history, content, research: !!opts.research,
                  confidential: confidential.value }
  try {
    await streamIdeaTurn(lastPayload, (ev) => onEvent(ev, live))
    if (live.streaming) throw new Error('The reply ended unexpectedly.')
  } catch (e) {
    messages.value.splice(messages.value.indexOf(live), 1)
    messages.value.splice(messages.value.length - 1, 1)   // drop the unanswered user message
    draft.value = content
    error.value = e.message || 'Something went wrong.'
  } finally {
    busy.value = false
    status.value = ''
    save()
    focusComposer()
  }
}

function onEvent(ev, live) {
  switch (ev.type) {
    case 'searching':
      status.value = 'Researching who already does this (web, companies, Hacker News, GitHub)...'
      break
    case 'sources':
      status.value = `Found ${ev.count} results. Reading them...`
      break
    case 'research': {
      const n = ev.competitors?.length || 0
      status.value = n ? `Found ${n} ${n === 1 ? 'company' : 'companies'} already doing this. Thinking...` : 'Research done. Thinking...'
      break
    }
    case 'evidence_skipped':
      live.notice = ev.reason
      break
    case 'delta':
      status.value = ''
      live.content += ev.text
      scrollDown()
      break
    case 'reply':
      live.content = ev.content
      live.streaming = false
      if (ev.notice) live.notice = ev.notice
      status.value = 'Updating the live idea...'
      break
    case 'state':
      state.value = ev.state
      flash(ev.applied || [])
      lastChange.value = {
        turn: ev.state.meta?.turn,
        summary: ev.summary || '',
        labels: [...new Set((ev.applied || []).map(labelFor))],
      }
      if (ev.notice) live.notice = [live.notice, ev.notice].filter(Boolean).join(' ')
      announce.value = `Live idea updated: ${(ev.applied || []).length} ${(ev.applied || []).length === 1 ? 'field' : 'fields'}. Clarity ${ev.state.clarity.score}.`
      if (tab.value !== 'panel' && (ev.applied || []).length) unseen.value = true
      break
    case 'error':
      throw new Error(ev.error)
  }
}

function research() {
  send('Look up who already does this and who has tried it before.', { research: true })
}

function labelFor(path) {
  const hit = PATH_LABELS.find(([prefix]) => path === prefix || path.startsWith(prefix + '/'))
  return hit ? hit[1] : 'Idea'
}

function useStarter(s) {
  draft.value = s.text
  focusComposer(true)
}

function draftAbout(text) {
  draft.value = text
  tab.value = 'chat'
  focusComposer(true)
}

function retry() {
  if (lastPayload) send(lastPayload.content, { research: lastPayload.research })
}

function flash(paths) {
  changed.value = paths
  clearTimeout(clearTimer)
  clearTimer = setTimeout(() => { changed.value = [] }, 2200)
}

// ── Handoff to the GTM simulation ──────────────────────────────────────────
async function sendBrief() {
  error.value = ''
  try {
    const res = await ideaToBrief(state.value)
    try { localStorage.setItem(PREFILL_KEY, JSON.stringify(res.data.brief)) } catch (_) {}
    router.push({ name: 'Simulate', query: { from: 'studio' } })
  } catch (e) {
    error.value = 'Could not build the brief. ' + (e.message || '')
  }
}

// ── Founder edits ───────────────────────────────────────────────────────────
async function onEdit(path, text) {
  try {
    const res = await editIdeaField(state.value, path, text)
    state.value = res.data.state
    flash([path])
    save()
  } catch (e) { error.value = e.message }
}

async function onLock(path, locked) {
  try {
    const res = await lockIdeaField(state.value, path, locked)
    state.value = res.data.state
    save()
  } catch (e) { error.value = e.message }
}

// ── Rendering helpers ───────────────────────────────────────────────────────
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

function render(text) {
  return escapeHtml(text || '')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function scrollDown() {
  nextTick(() => { if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight })
}

function focusComposer(toEnd = false) {
  nextTick(() => {
    const el = composer.value
    if (!el) return
    el.focus()
    if (toEnd) el.setSelectionRange(el.value.length, el.value.length)
  })
}

watch(tab, (t) => { if (t === 'panel') unseen.value = false })
watch(confidential, save)

onMounted(async () => {
  if (!load()) await startNew()
  scrollDown()
  focusComposer()
})
</script>

<style scoped>
.studio {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #000;
  color: var(--text-primary);
  font-family: var(--font-sans);
}
.hidden { display: none; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.bar {
  height: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 20px;
  border-bottom: 1px solid #1a1a1a;
}
.brand { display: inline-flex; align-items: center; gap: 8px; font-weight: 650; font-size: 14px; color: var(--text-primary); text-decoration: none; }
.brand img { border-radius: 5px; }
.bar-title { font-size: 14px; color: var(--text-primary); padding-left: 14px; border-left: 1px solid #262626; }
.bar-sub { font-size: 12.5px; color: var(--text-tertiary); margin-left: 6px; font-weight: 400; }
.saved { font-size: 11.5px; color: var(--text-tertiary); display: inline-flex; align-items: center; gap: 6px; }
.saved::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
.starters { display: grid; grid-template-columns: 1fr; gap: 8px; margin-left: 38px; }
.starter {
  text-align: left; display: flex; flex-direction: column; gap: 2px; padding: 12px 14px;
  border: 1px solid #222; border-radius: 10px; background: #0b0b0b; transition: border-color 0.15s;
}
.starter:hover { border-color: var(--accent); }
.starter-title { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.starter-desc { font-size: 12.5px; color: var(--text-tertiary); }
.bar-spacer { flex: 1; }
.menu { display: flex; gap: 6px; }
.btn-ghost {
  font-size: 12.5px; font-weight: 600; padding: 6px 11px; border-radius: 7px;
  border: 1px solid #262626; background: transparent; color: var(--text-secondary);
}
.btn-ghost:hover { color: var(--text-primary); border-color: #3a3a3a; }
.conf { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-secondary); cursor: pointer; }
.conf input { position: absolute; opacity: 0; pointer-events: none; }
.switch { width: 28px; height: 16px; border-radius: 999px; background: #2a2a2a; position: relative; transition: background 0.15s; }
.switch::after { content: ''; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: #fff; transition: transform 0.15s; }
.conf input:checked + .switch { background: var(--accent); }
.conf input:checked + .switch::after { transform: translateX(12px); }
.conf input:focus-visible + .switch { box-shadow: 0 0 0 2px var(--accent); }

.tabs { display: none; }

.body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 42fr) minmax(0, 58fr);
}

/* Chat */
.chat { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid #1a1a1a; }
.messages { flex: 1; overflow-y: auto; padding: 24px 22px 12px; display: flex; flex-direction: column; gap: 16px; }
.msg { display: flex; gap: 10px; max-width: 100%; }
.msg--user { justify-content: flex-end; }
.avatar {
  width: 28px; height: 28px; flex-shrink: 0; border-radius: 8px; display: grid; place-items: center;
  font-size: 10px; font-weight: 700; color: #93c5fd; background: rgba(59, 130, 246, 0.12);
}
.bubble { max-width: 86%; }
.msg--user .bubble { background: #161616; border: 1px solid #222; border-radius: 12px 12px 4px 12px; padding: 10px 13px; }
.bubble-text { font-size: 14.5px; line-height: 1.6; color: var(--text-primary); overflow-wrap: anywhere; }
.msg--assistant .bubble-text :deep(strong) { display: inline; color: #fff; font-weight: 650; }
.notice { margin-top: 8px; font-size: 12px; color: #fcd34d; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 7px; padding: 6px 9px; }
.typing { display: inline-flex; gap: 4px; padding: 6px 0; }
.typing i { width: 6px; height: 6px; border-radius: 50%; background: #555; animation: blink 1.2s infinite; }
.typing i:nth-child(2) { animation-delay: 0.2s; }
.typing i:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.25; } 40% { opacity: 1; } }
.status { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-secondary); padding-left: 38px; }
.spinner { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #333; border-top-color: var(--accent); animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error { font-size: 12.5px; color: #fca5a5; padding-left: 38px; }
.link { background: none; border: none; color: #93c5fd; text-decoration: underline; font-size: 12.5px; padding: 0; }

.composer { display: flex; gap: 8px; align-items: flex-end; margin: 0 16px; padding: 10px; border: 1px solid #262626; border-radius: 12px; background: #0b0b0b; }
.composer:focus-within { border-color: #3a3a3a; }
.composer textarea {
  flex: 1; resize: none; border: none; background: transparent; color: var(--text-primary);
  font: inherit; font-size: 14.5px; line-height: 1.5; max-height: 160px; outline: none;
}
.send {
  width: 34px; height: 34px; border-radius: 9px; border: none; background: var(--accent); color: #fff;
  display: grid; place-items: center; flex-shrink: 0;
}
.send:disabled { background: #1f1f1f; color: #555; }
.send svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.fine { font-size: 11px; line-height: 1.45; color: #555; padding: 8px 18px 12px; }
.privacy summary { cursor: pointer; color: #8a8a8a; display: inline; margin-left: 4px; }
.privacy summary:hover { color: var(--text-primary); }
.privacy ul { margin: 8px 0 0; padding-left: 16px; display: flex; flex-direction: column; gap: 5px; color: #8a8a8a; }
.privacy strong { color: #c4c4c4; }

/* Panel */
.side { overflow-y: auto; padding: 20px 22px 40px; background: #050505; }

@media (max-width: 900px) {
  .bar { padding: 0 12px; gap: 8px; }
  .brand span, .bar-sub, .saved, .menu .btn-ghost:not(.btn-new) { display: none; }
  .bar-title { border-left: none; padding-left: 0; }
  .starters { margin-left: 0; }
  .tabs { display: flex; border-bottom: 1px solid #1a1a1a; }
  .tabs button {
    flex: 1; padding: 10px; font-size: 13px; font-weight: 600; background: none; border: none;
    color: var(--text-secondary); border-bottom: 2px solid transparent; position: relative;
  }
  .tabs button.on { color: var(--text-primary); border-bottom-color: var(--accent); }
  .tab-score { font-size: 11px; color: #93c5fd; margin-left: 4px; }
  .tab-dot { position: absolute; top: 8px; right: 28%; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
  .body { grid-template-columns: 1fr; }
  .chat { border-right: none; }
  .hide { display: none; }
  .side { padding: 14px 12px 32px; }
  .messages { padding: 16px 14px 10px; }
  .composer { margin: 0 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .typing i, .spinner { animation: none; }
}
</style>
