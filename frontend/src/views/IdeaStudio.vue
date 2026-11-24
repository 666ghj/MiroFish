<template>
  <div class="studio" :data-busy="busy ? 'true' : 'false'" :data-team="teamRunning ? 'running' : 'idle'">
    <!-- Top bar -->
    <header class="bar">
      <router-link to="/" class="brand">
        <img src="/favicon.svg" alt="" width="22" height="22" />
        <span>{{ $brand.name }}</span>
      </router-link>
      <span class="bar-title"><strong>{{ $brand.idea }}</strong> <span class="bar-sub">talk an idea through</span></span>
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
        <span v-if="workingCount" class="tab-working">{{ workingCount }} agents</span>
        <span v-if="unseen" class="tab-dot" aria-label="updated"></span>
      </button>
    </div>

    <div class="body">
      <!-- Chat -->
      <section class="chat" :class="{ hide: tab !== 'chat' }" aria-label="Conversation">
        <div class="thread-wrap">
          <div ref="scroller" class="messages" role="log" aria-live="polite" aria-relevant="additions" @scroll="onScroll">
            <div ref="threadInner" class="thread">
              <!-- First visit: what this is and how to start -->
              <div v-if="isFresh" class="welcome">
                <div class="welcome-faces" aria-hidden="true">
                  <span v-for="(a, i) in FACES" :key="a.id" :style="{ '--c': a.color, '--i': i }"></span>
                </div>
                <h2>What are you thinking of building?</h2>
                <p>Rough is fine. Your co-founder asks one question at a time while a team of agents looks up who already does it,
                  pokes holes in it, and sizes it.</p>
                <div class="starters" aria-label="Ways to start">
                  <button v-for="(st, i) in STARTERS" :key="st.title" type="button" class="starter" :style="{ '--i': i }" @click="useStarter(st)">
                    <span class="starter-icon" aria-hidden="true"><svg viewBox="0 0 16 16"><path :d="st.icon" /></svg></span>
                    <span class="starter-title">{{ st.title }}</span>
                    <span class="starter-desc">{{ st.desc }}</span>
                  </button>
                </div>
              </div>

              <template v-else>
                <ChatMessage v-for="(m, i) in messages" :key="i" :m="m" :is-last="i === lastAiIndex" :busy="busy"
                             @answer="answerNow" @quick="(t) => send(t)" @act="actOpen" />
              </template>

              <div v-if="error" class="error" role="alert">
                <span>{{ error }}</span>
                <button type="button" class="link" @click="retry">Try again</button>
              </div>
            </div>
          </div>
          <transition name="jump">
            <button v-if="!atBottom" type="button" class="jump" @click="scrollDown(true)">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3.5 8.5L8 13l4.5-4.5" /></svg>Latest
            </button>
          </transition>
        </div>

        <form class="composer" :class="{ busy }" @submit.prevent="send()">
          <span v-if="busy" class="progress" aria-hidden="true"></span>
          <textarea
            ref="composer"
            v-model="draft"
            rows="1"
            maxlength="4000"
            :placeholder="busy ? 'Your team is working. Type your next thought...' : (answering ? 'Your answer...' : (messages.length > 1 ? 'Reply to your co-founder...' : 'Describe your idea, however rough...'))"
            aria-label="Message your AI co-founder"
            :disabled="!state"
            @input="autoGrow"
            @keydown.enter.exact.prevent="send()"
          ></textarea>
          <div class="tools">
            <button type="button" class="tool" :disabled="busy || confidential || !state || (state.why_not_built.search.sweeps || 0) >= 3"
                    :title="confidential ? 'Confidential mode is on, so nothing is searched' : 'Look up who already does this'" @click="research">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5" /></svg>Research
            </button>
            <span v-if="confidential" class="tool-note">Confidential: search off</span>
            <span class="tools-spacer"></span>
            <span class="kbd-hint"><kbd>Enter</kbd> send · <kbd>Shift</kbd> <kbd>Enter</kbd> new line</span>
            <button v-if="busy" type="button" class="send send--stop" aria-label="Stop" @click="stop">
              <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4.5" y="4.5" width="7" height="7" rx="1.5" /></svg>
            </button>
            <button v-else type="submit" class="send" :disabled="!draft.trim()" aria-label="Send">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3.5M3.5 8L8 3.5 12.5 8" /></svg>
            </button>
          </div>
        </form>
        <div class="fine">
          A thinking tool, not investment, legal, or financial advice.
          <button type="button" class="privacy-link" :aria-expanded="privacyOpen" aria-controls="privacy-card"
                  @click.stop="privacyOpen = !privacyOpen">How your idea is handled</button>
          <div v-if="privacyOpen" id="privacy-card" class="privacy-card" role="dialog" aria-label="How your idea is handled" @click.stop>
            <div class="privacy-head">
              <span>How your idea is handled</span>
              <button type="button" class="privacy-x" aria-label="Close" @click="privacyOpen = false">✕</button>
            </div>
            <ul>
              <li><strong>Stored:</strong> only in this browser. There is no account and no server copy. "New idea" clears it; Export saves a file.</li>
              <li><strong>AI:</strong> each message is sent through OpenRouter to the model provider. API providers say they do not train on it, but some keep requests briefly for abuse monitoring. We do not promise zero retention.</li>
              <li><strong>Search:</strong> only short category phrases are sent to Tavily, Exa, Hacker News, and GitHub, never your full description. The exact phrases are listed under "Why hasn't this been built yet?".</li>
              <li><strong>Confidential mode</strong> turns search off. For a stealth idea, run this open-source app yourself with your own API key.</li>
            </ul>
          </div>
        </div>
      </section>

      <!-- Live panel -->
      <aside class="side" :class="{ hide: tab !== 'panel' }" aria-label="Live idea">
        <div class="views" role="tablist" aria-label="Panel view">
          <button role="tab" type="button" :aria-selected="view === 'overview'" :class="{ on: view === 'overview' }" @click="view = 'overview'">
            Overview
          </button>
          <button role="tab" type="button" :aria-selected="view === 'team'" :class="{ on: view === 'team' }" @click="view = 'team'">
            Agents
            <span class="faces" aria-hidden="true">
              <span v-for="a in FACES" :key="a.id" class="face" :class="{ busy: isWorking(a.id) }" :style="{ '--c': a.color }"></span>
            </span>
            <span v-if="workingCount" class="working-count">{{ workingCount }} working</span>
          </button>
          <span class="views-glider" :class="view" aria-hidden="true"></span>
        </div>

        <div v-if="state" class="view-body">
          <transition name="view" mode="out-in">
            <IdeaDashboard
              v-if="view === 'overview'"
              key="overview"
              :state="state"
              :changed="changed"
              :last-change="lastChange"
              :updating="updating"
              :busy="busy"
              :confidential="confidential"
              :chief="team.chief?.output || null"
              @open="openDetail"
              @ask="draftAbout"
              @research="research"
              @send-brief="sendBrief"
              @team="view = 'team'"
            />
            <AgentTeam
              v-else
              key="team"
              :state="state"
              :team="team"
              :live="live"
              :team-running="teamRunning"
              :last-question="lastQuestion"
              :last-change="lastChange"
              @open="openAgent"
              @run="runTeam({ force: true })"
            />
          </transition>
        </div>

        <!-- Detail drawer: the full, editable picture, opened at the tile you clicked -->
        <transition name="drawer">
          <div v-if="drawerOpen && state" class="drawer" role="dialog" aria-label="Idea details" @keydown.esc="drawerOpen = false">
            <div class="drawer-head">
              <button v-if="drawerAgent" type="button" class="drawer-back" @click="drawerAgent = null; drawerOpen = false" aria-label="Back to the team">←</button>
              <span>{{ drawerAgent ? 'Agent report' : 'Details' }}</span>
              <span class="drawer-hint">{{ drawerAgent ? 'Esc to close.' : 'Edit or lock any field. Esc to close.' }}</span>
              <button ref="drawerClose" type="button" class="drawer-x" aria-label="Close details" @click="drawerOpen = false">✕</button>
            </div>
            <div ref="drawerBody" class="drawer-body">
              <AgentDetail
                v-if="drawerAgent"
                :key="drawerAgent"
                :id="drawerAgent"
                :team="team"
                :live="live"
                @rerun="(id) => runTeam({ only: [id], force: true })"
                @section="(sec) => { drawerAgent = null; openDetail(sec) }"
                @switch="(id) => { drawerAgent = id }"
              />
              <IdeaPanel
                v-else
                :state="state"
                :changed="changed"
                :last-change="lastChange"
                :busy="busy"
                :confidential="confidential"
                @edit="onEdit"
                @lock="onLock"
                @research="research"
                @send-brief="sendBrief"
                @unpark="unparkItem"
                @ask="(t) => { drawerOpen = false; draftAbout(t) }"
              />
            </div>
          </div>
        </transition>
      </aside>
    </div>

    <div class="sr-only" role="status" aria-live="polite">{{ announce }}</div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import IdeaPanel from '../components/IdeaPanel.vue'
import IdeaDashboard from '../components/IdeaDashboard.vue'
import AgentTeam from '../components/AgentTeam.vue'
import AgentDetail from '../components/AgentDetail.vue'
import ChatMessage from '../components/ChatMessage.vue'
import { AGENTS, SPECIALIST_IDS } from '../utils/agents'
import { newIdea, streamIdeaTurn, streamIdeaTeam, editIdeaField, lockIdeaField, ideaToBrief } from '../api/idea.js'

const STORE_KEY = 'idea-studio.v1'
const STARTERS = [
  { title: 'I have an idea', desc: 'Describe it roughly and sharpen it together.', text: 'My idea is ',
    icon: 'M8 2.5a4 4 0 00-2.4 7.2c.5.4.9.9.9 1.3h3c0-.4.4-.9.9-1.3A4 4 0 008 2.5zM6.5 13h3' },
  { title: 'Help me find one', desc: 'Start from problems you have seen, not from scratch.',
    text: "I want to start something but I don't have an idea yet. Here is what I know well: ",
    icon: 'M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5' },
  { title: 'Poke holes in mine', desc: 'Stress-test an idea you already believe in.',
    text: 'I have an idea I believe in. Please challenge it hard: ', icon: 'M8 2.5l6 10.5H2zM8 6.5v3M8 11.2v.3' },
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
const privacyOpen = ref(false)
const updating = ref(false)
const drawerOpen = ref(false)
const drawerBody = ref(null)
const drawerClose = ref(null)
const drawerAgent = ref(null)

// ── Agent team state ────────────────────────────────────────────────────────
const view = ref('overview')
const team = ref({})              // persisted specialist outputs: {id: {output, fingerprint, source, turn}}
const live = ref({})              // transient status per agent: {id: {status, missing, at}}
const teamRunning = ref(false)
let teamPending = false
const FACES = AGENTS.slice(0, 10)
const isWorking = (id) => ['running', 'queued'].includes(live.value[id]?.status)
const workingCount = computed(() => AGENTS.filter(a => isWorking(a.id)).length)
const lastQuestion = computed(() => {
  const last = [...messages.value].reverse().find(m => m.role === 'assistant' && !m.streaming && m.content)
  if (!last || messages.value.length <= 1) return ''
  const bold = [...last.content.matchAll(/\*\*([^*]+)\*\*/g)].map(m => m[1])
  if (bold.length) return bold[bold.length - 1]
  const q = last.content.split(/(?<=[.!?])\s+/).reverse().find(t => t.trim().endsWith('?'))
  return (q || '').trim()
})
// ── Work trace: which agent is doing what, shown inside the chat message ─────
let traceMsg = null          // the assistant message the team run reports into
function traceLive(m) { return !!m.trace?.some(s => s.status === 'running' || s.status === 'queued') }
function step(m, id, patch) {
  if (!m) return
  if (!m.trace) m.trace = []
  const i = m.trace.findIndex(s => s.id === id)
  const t = Date.now()
  if (i === -1) {
    m.trace.push({ id, status: 'running', detail: '', t0: t, ...patch })
  } else {
    const cur = m.trace[i]
    const next = { ...cur, ...patch }
    if (patch.status === 'running' && cur.status !== 'running') next.t0 = t
    if (['done', 'failed'].includes(patch.status) && !cur.t1) next.t1 = t
    m.trace.splice(i, 1, next)
  }
}
function finishOpenSteps(m, status = 'done') {
  for (const s of m?.trace || []) if (s.status === 'running' || s.status === 'queued') step(m, s.id, { status })
}
function readSummary(items) {
  if (!items.length) return 'understood'
  const parked = items.filter(a => a.kind === 'parked').length
  const bits = []
  if (parked) bits.push(`Parked ${parked} ${parked === 1 ? 'topic' : 'topics'}`)
  if (items.some(a => a.kind === 'idea_updated')) bits.push('Updated your idea')
  if (items.some(a => a.kind === 'unparked')) bits.push('Brought a topic back')
  return bits.join(' · ').toLowerCase() || 'understood'
}

function setLive(id, patch) { live.value = { ...live.value, [id]: { ...(live.value[id] || {}), ...patch } } }
const savedAt = ref('')
const isFresh = computed(() => messages.value.length <= 1 && !busy.value)
const lastAiIndex = computed(() => { for (let i = messages.value.length - 1; i >= 0; i--) if (messages.value[i].role === 'assistant') return i; return -1 })
const answering = ref(false)
const atBottom = ref(true)
const threadInner = ref(null)
let controller = null
let resizeObs = null
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
      state: state.value, confidential: confidential.value, team: team.value,
      messages: messages.value.filter(m => !m.streaming).map(({ role, content, notice, actions, trace, ask, research }) => ({ role, content, notice, actions, ask, research,
        trace: (trace || []).map(t => ({ ...t, faces: undefined, status: ['running', 'queued'].includes(t.status) ? 'done' : t.status })) })),
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
      team.value = saved.team && typeof saved.team === 'object' ? saved.team : {}
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
    team.value = {}
    live.value = {}
    view.value = 'overview'
    save()
  } catch (e) {
    error.value = 'Could not reach the server. Is the backend running on port 5001?'
  }
  focusComposer()
}

function exportIdea() {
  const blob = new Blob([JSON.stringify({ state: state.value, messages: messages.value, team: team.value }, null, 2)],
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
    messages.value = data.messages.map(({ role, content, notice, actions }) => ({ role, content, notice, actions: Array.isArray(actions) ? actions : [] }))
    team.value = data.team && typeof data.team === 'object' ? data.team : {}
    live.value = {}
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
  answering.value = false
  nextTick(autoGrow)
  error.value = ''
  busy.value = true
  const history = messages.value.filter(m => !m.streaming).slice(-HISTORY_SENT)
    .map(({ role, content }) => ({ role, content }))
  messages.value.push({ role: 'user', content })
  const reply = { role: 'assistant', content: '', streaming: true, notice: null, trace: [] }
  messages.value.push(reply)
  const live = messages.value[messages.value.length - 1]
  status.value = ''
  step(live, 'read', { status: 'running' })
  scrollDown(true)
  setLive('cofounder', { status: 'running' })

  lastPayload = { state: state.value, messages: history, content, research: !!opts.research,
                  confidential: confidential.value }
  let ok = false
  controller = new AbortController()
  try {
    await streamIdeaTurn(lastPayload, (ev) => onEvent(ev, live), controller.signal)
    if (live.streaming) throw new Error('The reply ended unexpectedly.')
    ok = true
  } catch (e) {
    finishOpenSteps(live, 'failed')
    messages.value.splice(messages.value.indexOf(live), 1)
    messages.value.splice(messages.value.length - 1, 1)   // drop the unanswered user message
    draft.value = content
    nextTick(autoGrow)
    error.value = e.name === 'AbortError' ? '' : (e.message || 'Something went wrong.')
  } finally {
    controller = null
    busy.value = false
    updating.value = false
    status.value = ''
    for (const id of ['cofounder', 'analyst', 'researcher']) {
      if (isWorking(id)) setLive(id, { status: ok ? 'done' : 'idle', at: Date.now() })
    }
    save()
    focusComposer()
  }
  if (ok) { traceMsg = live; runTeam() }
}

// ── Agent team ──────────────────────────────────────────────────────────────
async function runTeam(opts = {}) {
  if (!state.value) return
  if (teamRunning.value) { teamPending = true; return }
  teamRunning.value = true
  const only = opts.only || null
  const target = opts.only ? null : traceMsg
  traceMsg = null
  teamTrace = target
  try {
    await streamIdeaTeam({ state: state.value, team: team.value, only, force: !!opts.force }, (ev) => onTeamEvent(ev, only))
  } catch (e) {
    for (const id of SPECIALIST_IDS) if (isWorking(id)) setLive(id, { status: 'failed' })
    if (target) step(target, 'team', { status: 'failed', detail: 'The team could not run this time' })
  } finally {
    if (target && traceLive(target)) finishOpenSteps(target)
    teamTrace = null
    teamRunning.value = false
    save()
    if (teamPending) { teamPending = false; runTeam() }
  }
}

let teamTrace = null
function teamFaces(doneIds) {
  return SPECIALIST_IDS.filter(id => ['queued', 'running', 'done'].includes(live.value[id]?.status) || doneIds.includes(id))
    .map(id => ({ color: AGENTS.find(a => a.id === id).color, on: doneIds.includes(id) }))
}
let teamDone = []
function onTeamEvent(ev, only) {
  const m = teamTrace
  if (m && ev.type === 'plan') {
    teamDone = []
    const n = ev.agents.filter(a => a.status === 'queued').length
    if (n) step(m, 'team', { status: 'running', detail: `${n} specialists working` })
  }
  if (m && ev.type === 'agent' && ev.status === 'done') {
    teamDone.push(ev.id)
    const name = AGENTS.find(a => a.id === ev.id)?.name || ev.id
    step(m, 'team', { detail: `${name.toLowerCase()} reported` })
  }
  if (m && ev.type === 'done' && m.trace?.some(s => s.id === 'team')) {
    const chief = team.value.chief?.output
    const VERD = { keep_going: 'Keep going', narrow: 'Narrow it', rethink: 'Rethink' }
    step(m, 'team', { status: 'done',
      detail: chief && teamDone.includes('chief') ? `Chief of staff says ${VERD[chief.verdict].toLowerCase()}`
        : `${ev.ran} ${ev.ran === 1 ? 'specialist' : 'specialists'} reported` })
  }
  if (ev.type === 'plan') {
    for (const a of ev.agents) {
      if (only && !only.includes(a.id) && a.status !== 'waiting') continue
      setLive(a.id, { status: a.status, missing: a.missing || [] })
    }
  } else if (ev.type === 'agent') {
    if (ev.status === 'done') {
      team.value = { ...team.value, [ev.id]: { output: ev.output, fingerprint: ev.fingerprint, source: ev.source, turn: ev.turn } }
      setLive(ev.id, { status: 'done', at: Date.now(), missing: [] })
    } else {
      setLive(ev.id, { status: ev.status, missing: ev.missing || [], error: ev.error || '' })
    }
  } else if (ev.type === 'error') {
    throw new Error(ev.error)
  }
}

// ── What the app did with a message (chips under the reply) ────────────────
const ACT_LABEL = { parked: 'Parked', already_parked: 'Already parked', unparked: 'Brought back', idea_updated: 'Idea updated',
  researched: 'Searched', research_skipped: 'Search skipped' }
const ACT_SECTION = { parked: 'sec-parked', already_parked: 'sec-parked', unparked: 'sec-parked', idea_updated: 'sec-idea',
  researched: 'sec-wnb' }
const ACT_ICON = {
  parked: 'M4 2.5h8v11l-4-2.8-4 2.8z', already_parked: 'M4 2.5h8v11l-4-2.8-4 2.8z', unparked: 'M3 8h10M8.5 3.5L13 8l-4.5 4.5',
  idea_updated: 'M3 13l1-3.5L10.5 3 13 5.5 6.5 12z', researched: 'M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5',
  research_skipped: 'M8 3v6M8 11.5v.5',
}
function actOpen(a) { if (ACT_SECTION[a.kind]) { tab.value = 'panel'; openDetail(ACT_SECTION[a.kind]) } }

function unparkItem(id) {
  if (!state.value) return
  state.value = { ...state.value, parked: (state.value.parked || []).filter(p => p.id !== id) }
  save()
}

function openAgent(id) {
  drawerAgent.value = id
  drawerOpen.value = true
  nextTick(() => { if (drawerBody.value) drawerBody.value.scrollTop = 0; drawerClose.value?.focus() })
}

function onEvent(ev, live) {
  switch (ev.type) {
    case 'actions':
      step(live, 'read', { status: 'done', detail: readSummary(ev.items || []) })
      live.actions = ev.items || []
      if ((ev.items || []).some(a => a.kind === 'idea_updated')) flash((ev.items.find(a => a.kind === 'idea_updated').paths) || [])
      break
    case 'start':
      if (live.trace?.find(s => s.id === 'read')?.status === 'running') step(live, 'read', { status: 'done', detail: 'understood' })
      step(live, 'cofounder', { status: 'running', detail: 'thinking' })
      break
    case 'searching':
      step(live, 'cofounder', { status: 'queued', detail: 'Waiting for the research' })
      step(live, 'research', { status: 'running', detail: `searching "${(ev.terms || [''])[0]}"` })
      live._query = (ev.terms || [''])[0]
      live.trace.sort((a, b) => ['read', 'research', 'cofounder', 'analyst', 'team'].indexOf(a.id) - ['read', 'research', 'cofounder', 'analyst', 'team'].indexOf(b.id))
      setLive('researcher', { status: 'running' })
      status.value = 'Researching who already does this (web, companies, Hacker News, GitHub)...'
      break
    case 'sources':
      step(live, 'research', { detail: `reading ${ev.count} results` })
      status.value = `Found ${ev.count} results. Reading them...`
      break
    case 'research': {
      setLive('researcher', { status: 'done', at: Date.now() })
      const n = ev.competitors?.length || 0
      step(live, 'research', { status: 'done', detail: n ? `${n} ${n === 1 ? 'company' : 'companies'} found` : 'no companies found' })
      step(live, 'cofounder', { status: 'running', detail: 'thinking' })
      live.research = { query: live._query || '', competitors: (ev.competitors || []).slice(0, 6).map(name => ({ name, url: '' })),
                        predecessors: (ev.predecessors || []).slice(0, 3).map(name => ({ name, url: '' })) }
      scrollDown()
      status.value = n ? `Found ${n} ${n === 1 ? 'company' : 'companies'} already doing this. Thinking...` : 'Research done. Thinking...'
      break
    }
    case 'evidence_skipped':
      step(live, 'research', { status: 'failed', detail: ev.reason })
      step(live, 'cofounder', { status: 'running', detail: 'thinking' })
      live.notice = ev.reason
      break
    case 'delta':
      status.value = ''
      if (!live.content) {
        if (live.trace?.find(s => s.id === 'research')?.status === 'running') step(live, 'research', { status: 'done', detail: 'done' })
        step(live, 'cofounder', { status: 'running', detail: 'writing' })
      }
      live.content += ev.text
      live.tail = ev.text.length
      scrollDown()
      break
    case 'reply':
      live.content = ev.content
      live.streaming = false
      if (ev.notice) live.notice = ev.notice
      if (Array.isArray(ev.actions)) live.actions = ev.actions
      status.value = ''
      updating.value = true
      step(live, 'cofounder', { status: 'done', detail: ev.source === 'scripted' ? 'used a scripted question' : 'replied' })
      step(live, 'analyst', { status: 'running', detail: 'updating the live idea' })
      live.tail = 0
      live.ask = ev.ask || null
      if (ev.research) live.research = ev.research
      scrollDown()
      setLive('cofounder', { status: 'done', at: Date.now() })
      setLive('analyst', { status: 'running' })
      break
    case 'state':
      updating.value = false
      {
        const n = (ev.applied || []).length
        const labels = [...new Set((ev.applied || []).map(labelFor))].slice(0, 3).join(', ')
        step(live, 'analyst', { status: 'done', detail: n ? `${n} ${n === 1 ? 'field' : 'fields'} updated${labels ? ': ' + labels : ''}` : 'nothing new to record' })
      }
      setLive('analyst', { status: 'done', at: Date.now() })
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

function openDetail(sectionId) {
  drawerAgent.value = null
  drawerOpen.value = true
  nextTick(() => {
    const target = drawerBody.value?.querySelector(`#${sectionId}`)
    if (target) target.scrollIntoView({ block: 'start' })
    else if (drawerBody.value) drawerBody.value.scrollTop = 0
    drawerClose.value?.focus()
  })
}

function useStarter(s) {
  draft.value = s.text
  nextTick(autoGrow)
  focusComposer(true)
}

function draftAbout(text) {
  draft.value = text
  nextTick(autoGrow)
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

// Stick to the newest message unless the founder scrolled up to read
function scrollDown(force = false) {
  if (force) atBottom.value = true
  if (!atBottom.value) return
  nextTick(() => { const el = scroller.value; if (el) el.scrollTo({ top: el.scrollHeight, behavior: force ? 'smooth' : 'auto' }) })
}
function onScroll() {
  const el = scroller.value
  if (el) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
function autoGrow() {
  const el = composer.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 180) + 'px'
}
function answerNow() { answering.value = true; focusComposer(true) }
function stop() { controller?.abort() }

function focusComposer(toEnd = false) {
  nextTick(() => {
    const el = composer.value
    if (!el) return
    el.focus()
    if (toEnd) el.setSelectionRange(el.value.length, el.value.length)
  })
}

watch(tab, (t) => { if (t === 'panel') unseen.value = false })
function onKey(e) {
  if (e.key !== 'Escape') return
  if (privacyOpen.value) privacyOpen.value = false
  else if (drawerOpen.value) { drawerOpen.value = false; drawerAgent.value = null }
}
function onDocClick() { privacyOpen.value = false }
onUnmounted(() => {
  resizeObs?.disconnect()
  controller?.abort()
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('click', onDocClick)
})
watch(confidential, save)

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  // Content grows while streaming and while cards animate in: keep the newest in view
  if ('ResizeObserver' in window) {
    resizeObs = new ResizeObserver(() => scrollDown())
    nextTick(() => threadInner.value && resizeObs.observe(threadInner.value))
  }
  document.addEventListener('click', onDocClick)
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
.chat { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid #161616; background: #000; }
.thread-wrap { position: relative; flex: 1; min-height: 0; display: flex; }
.messages { flex: 1; overflow-y: auto; padding: 28px 24px 24px;
  -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 20px); mask-image: linear-gradient(180deg, transparent 0, #000 20px); }
.thread { max-width: 680px; margin: 0 auto; display: flex; flex-direction: column; gap: 26px; }

/* Welcome */
.welcome { display: flex; flex-direction: column; align-items: flex-start; gap: 14px; padding-top: 6vh; }
.welcome-faces { display: flex; margin-bottom: 4px; }
.welcome-faces span { width: 18px; height: 18px; border-radius: 50%; margin-left: -5px; border: 2px solid #000;
  background: radial-gradient(circle at 35% 35%, color-mix(in srgb, var(--c) 80%, #fff), var(--c));
  animation: face-in 500ms var(--ease-out) both, float 3.2s ease-in-out infinite;
  animation-delay: calc(var(--i) * 60ms), calc(600ms + var(--i) * 0.25s); }
.welcome-faces span:first-child { margin-left: 0; }
@keyframes face-in { from { opacity: 0; transform: translateY(8px) scale(0.6); } to { opacity: 1; transform: none; } }
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
.welcome h2 { font-family: 'Space Grotesk', var(--font-sans); font-size: 28px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.15;
  text-wrap: balance; animation: rise-in var(--dur-3) var(--ease-out) 120ms both; }
.welcome p { font-size: 14.5px; line-height: 1.6; color: var(--text-secondary); max-width: 52ch; animation: rise-in var(--dur-3) var(--ease-out) 200ms both; }
.starters { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
.starter { position: relative; text-align: left; display: flex; flex-direction: column; gap: 4px; padding: 14px; border-radius: 14px;
  border: 1px solid #1f1f1f; background: #0a0a0a; color: inherit; overflow: hidden;
  animation: rise-in var(--dur-3) var(--ease-out) both; animation-delay: calc(280ms + var(--i) * 70ms);
  transition: border-color var(--dur-2) ease, transform var(--dur-2) var(--ease-out), background var(--dur-2) ease; }
.starter:hover { border-color: #333; background: #0e0e0e; transform: translateY(-2px); }
.starter-icon { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; margin-bottom: 6px;
  background: rgba(59, 130, 246, 0.1); box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.25); }
.starter-icon svg { width: 14px; height: 14px; fill: none; stroke: #93c5fd; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.starter-title { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.starter-desc { font-size: 12.5px; line-height: 1.45; color: var(--text-tertiary); }

.error { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #fca5a5; padding: 10px 12px; border-radius: 10px;
  background: rgba(248, 113, 113, 0.06); border: 1px solid rgba(248, 113, 113, 0.2); animation: pop-in var(--dur-2) var(--ease-out) both; }
.link { background: none; border: none; color: #93c5fd; text-decoration: underline; font-size: 13px; padding: 0; }

.jump { position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 999px; border: 1px solid #2a2a2a; background: rgba(20, 20, 20, 0.9);
  color: var(--text-primary); backdrop-filter: blur(6px); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5); }
.jump svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.jump-enter-active, .jump-leave-active { transition: opacity var(--dur-2) ease, transform var(--dur-2) var(--ease-out); }
.jump-enter-from, .jump-leave-to { opacity: 0; transform: translate(-50%, 6px); }

/* Composer */
.composer { position: relative; max-width: 680px; width: calc(100% - 32px); margin: 0 auto; padding: 12px 12px 8px; overflow: hidden;
  border: 1px solid #262626; border-radius: 18px; background: #0c0c0c;
  transition: border-color var(--dur-2) ease, box-shadow var(--dur-2) ease; }
.composer:focus-within { border-color: #3a3f4a; box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.07); }
.progress { position: absolute; top: 0; left: 0; right: 0; height: 2px; overflow: hidden; }
.progress::after { content: ''; position: absolute; top: 0; left: 0; width: 40%; height: 100%;
  background: linear-gradient(90deg, transparent, #60a5fa, #5eead4, transparent); animation: travel 1.4s ease-in-out infinite; }
@keyframes travel { from { transform: translateX(-100%); } to { transform: translateX(260%); } }
.composer textarea { display: block; width: 100%; resize: none; border: none; background: transparent; color: var(--text-primary);
  font: inherit; font-size: 15px; line-height: 1.5; min-height: 24px; max-height: 180px; outline: none; padding: 2px 4px; }
.composer textarea::placeholder { color: #5a5a5a; }
.tools { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.tool { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 550; padding: 5px 10px; border-radius: 999px;
  border: 1px solid #262626; background: transparent; color: var(--text-secondary); }
.tool:hover:not(:disabled) { color: var(--text-primary); border-color: rgba(45, 212, 191, 0.5); }
.tool:disabled { opacity: 0.4; cursor: default; }
.tool svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
.tool-note { font-size: 11.5px; color: var(--text-tertiary); }
.tools-spacer { flex: 1; }
.kbd-hint { font-size: 11px; color: #4a4a4a; white-space: nowrap; }
.kbd-hint kbd { font-family: inherit; font-size: 10.5px; padding: 0 4px; border-radius: 4px; border: 1px solid #2a2a2a; color: #6b6b6b; }
.send { width: 32px; height: 32px; border-radius: 50%; border: none; display: grid; place-items: center; flex-shrink: 0;
  background: #f5f5f5; color: #000; transition: transform var(--dur-1) var(--ease-out), background var(--dur-2) ease, opacity var(--dur-2) ease; }
.send:hover:not(:disabled) { transform: scale(1.06); }
.send:disabled { background: #222; color: #555; }
.send svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.send--stop { background: #222; color: #f5f5f5; box-shadow: 0 0 0 1px #3a3a3a; animation: pop-in var(--dur-2) var(--ease-out) both; }
.send--stop svg { fill: currentColor; stroke: none; }
.fine { position: relative; max-width: 680px; width: 100%; margin: 0 auto; font-size: 11px; line-height: 1.45; color: #4a4a4a; padding: 8px 20px 12px; }
.privacy-link {
  background: none; border: none; padding: 0; margin-left: 4px; font-size: 11px;
  color: #8a8a8a; text-decoration: underline; text-underline-offset: 2px; cursor: pointer;
}
.privacy-link:hover { color: var(--text-primary); }
.privacy-card {
  animation: pop-in var(--dur-2) var(--ease-out) both; transform-origin: bottom left;
  position: absolute; left: 12px; right: 12px; bottom: calc(100% + 8px); z-index: 20;
  background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 10px; padding: 12px 14px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.6); font-size: 12px; line-height: 1.5; color: #9a9a9a;
}
.privacy-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: 12.5px; font-weight: 650; color: var(--text-primary); }
.privacy-x { width: 24px; height: 24px; border-radius: 6px; border: 1px solid #2a2a2a; background: transparent; color: var(--text-secondary); font-size: 11px; }
.privacy-x:hover { color: var(--text-primary); border-color: #444; }
.privacy-card ul { margin: 0; padding-left: 16px; display: flex; flex-direction: column; gap: 6px; }
.privacy-card strong { color: #d4d4d4; }

/* Panel */
.side { position: relative; overflow: hidden; padding: 12px 16px 14px; background: #050505; min-height: 0;
  display: flex; flex-direction: column; gap: 10px; }
.view-body { flex: 1; min-height: 0; }
.view-body > * { height: 100%; }
.view-enter-active { transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out); }
.view-leave-active { transition: opacity var(--dur-1) ease, transform var(--dur-1) ease; }
.view-enter-from { opacity: 0; transform: translateY(6px); }
.view-leave-to { opacity: 0; transform: translateY(-4px); }

/* Overview / Agents switch with a sliding highlight */
.views { position: relative; display: inline-grid; grid-template-columns: auto auto; align-self: flex-start;
  padding: 3px; border-radius: 10px; background: #0d0d0d; border: 1px solid #1c1c1c; }
.views button { position: relative; z-index: 1; display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 600;
  padding: 6px 14px; border: none; background: transparent; color: var(--text-tertiary); border-radius: 7px; }
.views button.on { color: var(--text-primary); }
.views button:hover:not(.on) { color: var(--text-secondary); }
.views-glider { position: absolute; top: 3px; bottom: 3px; left: 3px; border-radius: 7px; background: #1a1a1a;
  border: 1px solid #2a2a2a; transition: transform var(--dur-2) var(--ease-out), width var(--dur-2) var(--ease-out); }
.views-glider.overview { width: 88px; transform: translateX(0); }
.views-glider.team { width: calc(100% - 94px); transform: translateX(88px); }
.faces { display: inline-flex; }
.face { width: 9px; height: 9px; border-radius: 50%; background: var(--c); border: 1.5px solid #0d0d0d; margin-left: -3px; opacity: 0.55;
  transition: opacity var(--dur-2) ease, transform var(--dur-2) var(--ease-out); }
.face:first-child { margin-left: 0; }
.face.busy { opacity: 1; transform: translateY(-2px); animation: bob 1s ease-in-out infinite; }
.face.busy:nth-child(2n) { animation-delay: 0.15s; }
.face.busy:nth-child(3n) { animation-delay: 0.3s; }
@keyframes bob { 50% { transform: translateY(0); } }
.working-count { font-size: 11px; font-weight: 600; color: #93c5fd; animation: fade-in var(--dur-2) ease both; }

.drawer-back { width: 28px; height: 28px; border-radius: 7px; border: 1px solid #262626; background: transparent; color: var(--text-secondary); }
.drawer-back:hover { color: var(--text-primary); border-color: #3a3a3a; }
.drawer {
  position: absolute; inset: 0; z-index: 10; display: flex; flex-direction: column;
  background: #050505; border-left: 1px solid #1f1f1f;
}
.drawer-head {
  display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-bottom: 1px solid #1a1a1a;
  font-size: 13px; font-weight: 650;
}
.drawer-hint { font-size: 11.5px; font-weight: 400; color: var(--text-tertiary); flex: 1; }
.drawer-x {
  width: 28px; height: 28px; border-radius: 7px; border: 1px solid #262626; background: transparent;
  color: var(--text-secondary); font-size: 12px;
}
.drawer-x:hover { color: var(--text-primary); border-color: #3a3a3a; }
.drawer-body { flex: 1; overflow-y: auto; padding: 16px 18px 40px; }
.drawer-enter-active, .drawer-leave-active { transition: transform 0.22s ease, opacity 0.22s ease; }
.drawer-enter-from, .drawer-leave-to { transform: translateX(24px); opacity: 0; }

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
  .tab-working { font-size: 10.5px; color: #93c5fd; margin-left: 6px; }
  .starters { grid-template-columns: 1fr; }
  .kbd-hint { display: none; }
  .messages { padding: 20px 14px; }
  .tab-dot { position: absolute; top: 8px; right: 28%; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
  .body { grid-template-columns: 1fr; }
  .chat { border-right: none; }
  .hide { display: none; }
  .side { padding: 14px 12px 32px; overflow-y: auto; }
  .drawer { position: fixed; top: 0; }
  .messages { padding: 16px 14px 10px; }
  .composer { margin: 0 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .typing i, .spinner { animation: none; }
  .drawer-enter-active, .drawer-leave-active { transition: none; }
}
</style>
