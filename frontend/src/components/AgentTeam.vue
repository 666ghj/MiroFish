<template>
  <div class="team">
    <!-- Header -->
    <div class="team-head">
      <div>
        <div class="team-title">Your AI team</div>
        <div class="team-sub" aria-live="polite">
          <template v-if="working">{{ working }} of {{ AGENTS.length }} agents working</template>
          <template v-else-if="doneCount">{{ doneCount }} of {{ AGENTS.length }} agents reported</template>
          <template v-else>Specialists start once the problem and solution are clear</template>
        </div>
      </div>
      <button type="button" class="run" :disabled="teamRunning || !canRun" @click="$emit('run')"
              :title="canRun ? 'Re-run every specialist on the current idea' : 'Describe the problem and solution first'">
        <svg viewBox="0 0 16 16" aria-hidden="true" :class="{ spin: teamRunning }"><path d="M13 8a5 5 0 11-1.5-3.6M13 2.5v2.8h-2.8" /></svg>
        {{ teamRunning ? 'Team working' : 'Run team' }}
      </button>
    </div>

    <!-- Pipeline: who hands off to whom -->
    <ol class="pipe" aria-label="How the team works">
      <li v-for="(s, i) in STAGES" :key="s.key" class="pipe-node" :class="{ active: stageState(s) === 'running', done: stageState(s) === 'done' }">
        <span class="pipe-dot" aria-hidden="true"></span>
        <span class="pipe-label">{{ s.label }}</span>
        <span class="pipe-count">{{ stageDone(s) }}/{{ s.ids.length }}</span>
        <span v-if="i < STAGES.length - 1" class="pipe-line" :class="{ flowing: stageState(STAGES[i + 1]) === 'running' }" aria-hidden="true"><i></i></span>
      </li>
    </ol>

    <!-- Chief of staff: the team's call -->
    <button type="button" class="chief" :class="[`chief--${chief?.verdict || 'none'}`, { working: status('chief') === 'running' }]"
            @click="$emit('open', 'chief')">
      <span class="avatar avatar--lg" :style="{ '--c': BY_ID.chief.color }" aria-hidden="true">
        <svg viewBox="0 0 16 16"><path :d="BY_ID.chief.icon" /></svg>
      </span>
      <span class="chief-body">
        <span class="chief-top">
          <span class="chief-name">Chief of staff</span>
          <span v-if="chief" class="verdict" :class="`tone--${VERDICT[chief.verdict].tone}`">{{ VERDICT[chief.verdict].label }}</span>
          <span v-else-if="status('chief') === 'running'" class="pill pill--run">Weighing the team</span>
        </span>
        <transition name="swap" mode="out-in">
          <span v-if="status('chief') === 'running' && !chief" key="sk" class="skeleton"><i></i><i></i></span>
          <span v-else-if="chief" :key="team.chief.fingerprint" class="chief-text">
            <span class="chief-headline">{{ chief.headline }}</span>
            <span class="actions">
              <span v-for="(a, i) in chief.next_actions" :key="i" class="action"><b>{{ i + 1 }}</b>{{ a }}</span>
            </span>
          </span>
          <span v-else key="empty" class="chief-empty">Weighs in once at least three teammates have reported, then calls your next move.</span>
        </transition>
      </span>
    </button>

    <!-- Agents -->
    <div class="grid">
      <button v-for="(a, i) in GRID" :key="a.id" type="button" class="card"
              :class="[`st--${status(a.id)}`, { fresh: justDone(a.id) }]"
              :style="{ '--c': a.color, '--i': i }" @click="$emit('open', a.id)">
        <span class="card-top">
          <span class="avatar" aria-hidden="true"><svg viewBox="0 0 16 16"><path :d="a.icon" /></svg></span>
          <span class="card-name">{{ a.name }}</span>
          <span class="pill" :class="`pill--${status(a.id)}`">{{ STATUS_LABEL[status(a.id)] }}</span>
        </span>
        <span class="card-role">{{ a.role }}</span>
        <transition name="swap" mode="out-in">
          <span v-if="status(a.id) === 'running' && !headline(a.id)" key="sk" class="skeleton"><i></i><i></i></span>
          <span v-else-if="status(a.id) === 'waiting' && !headline(a.id)" key="w" class="card-wait">
            Needs {{ (live[a.id]?.missing || []).join(', ') || 'more detail' }}
          </span>
          <span v-else :key="'h' + (team[a.id]?.fingerprint || headline(a.id))" class="card-headline">
            {{ headline(a.id) || 'Nothing yet.' }}
          </span>
        </transition>
        <ul v-if="preview(a.id).length && !['running', 'waiting'].includes(status(a.id))" class="preview">
          <li v-for="(it, j) in preview(a.id)" :key="j" :style="{ '--j': j }" :title="it.text">
            <span v-if="it.tag" class="tag" :class="`tag--${it.tone || 'plain'}`">{{ it.tag }}</span>{{ it.text }}
          </li>
        </ul>
        <span class="card-foot">
          <template v-if="metric(a.id)">
            <span class="metric" :class="metric(a.id).cls">{{ metric(a.id).text }}</span>
          </template>
          <span v-if="live[a.id]?.status === 'failed'" class="failed">Could not finish, last result kept</span>
        </span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { AGENTS, BY_ID, VERDICT, money } from '../utils/agents'

const props = defineProps({
  state: { type: Object, required: true },
  team: { type: Object, default: () => ({}) },       // persisted outputs per specialist
  live: { type: Object, default: () => ({}) },       // transient status per agent id
  teamRunning: { type: Boolean, default: false },
  lastQuestion: { type: String, default: '' },
  lastChange: { type: Object, default: null },
})
defineEmits(['open', 'run'])

const GRID = AGENTS.filter(a => a.id !== 'chief')
const STAGES = [
  { key: 'talk', label: 'Conversation', ids: ['cofounder', 'analyst', 'researcher'] },
  { key: 'spec', label: 'Specialists', ids: ['skeptic', 'customers', 'market', 'pitch', 'gtm'] },
  { key: 'test', label: 'Experiments', ids: ['experiments'] },
  { key: 'chief', label: 'Chief of staff', ids: ['chief'] },
]
const STATUS_LABEL = { idle: 'Idle', queued: 'Queued', running: 'Working', done: 'Done', fresh: 'Up to date', waiting: 'Waiting', failed: 'Retry' }
const WNB = { unknown: 'Not researched', nobody_tried: 'Nobody found', tried_and_failed: 'Tried and failed',
  exists_unknown: 'Little traction', crowded_funded: 'Crowded' }

const chief = computed(() => props.team.chief?.output || null)
const canRun = computed(() => !!(props.state.problem.statement.text && props.state.solution.core.text))

function status(id) {
  const s = props.live[id]?.status
  if (s === 'failed') return props.team[id] ? 'done' : 'failed'
  if (s && s !== 'idle') return s
  if (props.team[id] || conversationHas(id)) return 'done'
  return BY_ID[id].kind === 'specialist' ? 'waiting' : 'idle'
}
function conversationHas(id) {
  if (id === 'cofounder') return !!props.lastQuestion
  if (id === 'analyst') return (props.state.meta?.turn || 0) > 0
  if (id === 'researcher') return !!(props.state.why_not_built.search.searched_at || props.state.why_not_built.competitors.length)
  return false
}
const working = computed(() => AGENTS.filter(a => ['running', 'queued'].includes(status(a.id))).length)
const doneCount = computed(() => AGENTS.filter(a => ['done', 'fresh'].includes(status(a.id))).length)

function stageDone(s) { return s.ids.filter(id => ['done', 'fresh'].includes(status(id))).length }
function stageState(s) {
  if (s.ids.some(id => ['running', 'queued'].includes(status(id)))) return 'running'
  return stageDone(s) === s.ids.length ? 'done' : 'idle'
}

function headline(id) {
  if (id === 'cofounder') return props.lastQuestion ? `Asked: ${props.lastQuestion}` : ''
  if (id === 'analyst') {
    if (props.lastChange?.labels?.length) return `Recorded ${props.lastChange.labels.slice(0, 4).join(', ')}`
    return (props.state.meta?.turn || 0) > 0 ? 'Keeping the live idea in sync with what you say.' : ''
  }
  if (id === 'researcher') {
    const w = props.state.why_not_built
    const n = w.competitors.length
    if (!w.search.searched_at && !n) return ''
    return w.summary.text || (n ? `Found ${n} ${n === 1 ? 'company' : 'companies'} in this space.` : 'No companies found in what was searched.')
  }
  return props.team[id]?.output?.headline || ''
}

function metric(id) {
  const o = props.team[id]?.output
  const st = props.state
  switch (id) {
    case 'cofounder': return st.meta?.turn ? { text: `${st.meta.turn} ${st.meta.turn === 1 ? 'turn' : 'turns'}` } : null
    case 'analyst': return st.meta?.turn ? { text: `Completeness ${st.clarity.score}` } : null
    case 'researcher': {
      const w = st.why_not_built
      return w.search.searched_at ? { text: `${WNB[w.classification]} · ${Object.keys(st.sources || {}).length} sources` } : null
    }
    case 'skeptic': {
      if (!o?.risks?.length) return null
      const f = o.risks.filter(r => r.severity === 'fatal').length
      const m = o.risks.filter(r => r.severity === 'major').length
      return { text: [f && `${f} fatal`, m && `${m} major`].filter(Boolean).join(' · ') || `${o.risks.length} minor`, cls: f ? 'bad' : 'warn' }
    }
    case 'customers': return o?.tally ? { text: `${o.tally.yes} yes · ${o.tally.maybe} maybe · ${o.tally.no} no`, cls: 'tally' } : null
    case 'market': return o?.estimate ? { text: `≈ ${money(o.estimate)} a year · estimate`, cls: 'big' } : null
    case 'pitch': return o?.one_liners?.length ? { text: `${o.one_liners.length} one-liners · 30s pitch` } : null
    case 'gtm': return o?.channel ? { text: o.channel } : null
    case 'experiments': return o?.tests?.length ? { text: `${o.tests.length} tests · ${Math.min(...o.tests.map(t => t.days || 0))} to ${Math.max(...o.tests.map(t => t.days || 0))} days` } : null
  }
  return null
}

// Two or three key items under the headline, one line each
function preview(id) {
  const o = props.team[id]?.output
  const st = props.state
  switch (id) {
    case 'cofounder': return (st.open_questions || []).slice(0, 2).map(q => ({ tag: 'Next', text: q.question }))
    case 'analyst': return (st.clarity?.top_missing || []).slice(0, 2).map(m => ({ tag: 'Missing', text: typeof m === 'string' ? m : (m.label || m.path || '') }))
    case 'researcher': return st.why_not_built.competitors.slice(0, 3).map(c => ({ text: c.name }))
    case 'skeptic': return (o?.risks || []).map(r => ({ tag: r.severity, tone: r.severity === 'fatal' ? 'bad' : r.severity === 'major' ? 'warn' : 'plain', text: r.title }))
    case 'customers': return (o?.panel || []).map(p => ({ tag: { yes: 'Yes', maybe: 'Maybe', no: 'No' }[p.would_try], tone: { yes: 'good', maybe: 'warn', no: 'bad' }[p.would_try], text: p.persona }))
    case 'market': return o?.count ? [{ text: `${o.count.toLocaleString()} ${o.unit} × ${money(o.price_per_year)}/yr` }, ...(o.assumptions || []).slice(0, 1).map(t => ({ tag: 'If', text: t }))] : []
    case 'pitch': return (o?.one_liners || []).slice(0, 2).map(t => ({ text: `"${t}"` }))
    case 'gtm': return (o?.week_one || []).slice(0, 3).map((t, i) => ({ tag: `Day ${i * 2 + 1}`, text: t }))
    case 'experiments': return (o?.tests || []).map(t => ({ tag: `${t.days}d`, text: t.method }))
  }
  return []
}

// Brief highlight when an agent finishes
const recent = ref({})
watch(() => props.live, (now) => {
  for (const [id, v] of Object.entries(now)) {
    if (v?.status === 'done' && v.at && !recent.value[id + v.at]) {
      recent.value = { ...recent.value, [id + v.at]: true, [id]: v.at }
      setTimeout(() => { if (recent.value[id] === v.at) recent.value = { ...recent.value, [id]: 0 } }, 1600)
    }
  }
}, { deep: true })
function justDone(id) { return !!recent.value[id] }
</script>

<style scoped>
@property --a { syntax: '<angle>'; inherits: false; initial-value: 0deg; }

.team { height: 100%; display: flex; flex-direction: column; gap: 10px; min-height: 0; }

.team-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.team-title { font-size: 15px; font-weight: 650; letter-spacing: -0.01em; }
.team-sub { font-size: 11.5px; color: var(--text-tertiary); margin-top: 2px; }
.run { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; padding: 6px 12px;
  border-radius: 8px; border: 1px solid #2a2a2a; background: #111; color: var(--text-primary); }
.run:hover:not(:disabled) { border-color: var(--accent); }
.run:disabled { opacity: 0.55; cursor: default; }
.run svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.run svg.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Pipeline */
.pipe { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.pipe-node { position: relative; display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-tertiary); min-width: 0; }
.pipe-dot { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid #3a3a3a; background: #050505; flex-shrink: 0; z-index: 1;
  transition: background var(--dur-2) ease, border-color var(--dur-2) ease; }
.pipe-node.done .pipe-dot { background: var(--text-secondary); border-color: var(--text-secondary); }
.pipe-node.active .pipe-dot { border-color: var(--accent); background: var(--accent); box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.5); animation: ping 1.4s ease-out infinite; }
.pipe-node.active .pipe-label { color: var(--text-primary); }
@keyframes ping { 0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.55); } 100% { box-shadow: 0 0 0 7px rgba(59, 130, 246, 0); } }
.pipe-label { white-space: nowrap; }
.pipe-count { font-variant-numeric: tabular-nums; color: #555; }
.pipe-line { flex: 1; height: 1px; background: #262626; margin: 0 8px; position: relative; overflow: hidden; min-width: 12px; }
.pipe-line.flowing i { position: absolute; top: -1px; left: 0; width: 24px; height: 3px; border-radius: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent); animation: flow 1.1s linear infinite; }
@keyframes flow { from { transform: translateX(-24px); } to { transform: translateX(400%); } }

/* Chief banner */
.chief { display: flex; gap: 12px; align-items: flex-start; text-align: left; width: 100%; padding: 12px 14px;
  border-radius: 12px; border: 1px solid #1f1f1f; background: linear-gradient(180deg, #101010, #0a0a0a); color: inherit;
  animation: rise-in var(--dur-3) var(--ease-out) both; position: relative; }
.chief:hover { border-color: #333; }
.chief--keep_going { border-color: rgba(74, 222, 128, 0.28); }
.chief--narrow { border-color: rgba(245, 158, 11, 0.28); }
.chief--rethink { border-color: rgba(248, 113, 113, 0.3); }
.chief.working { border-color: transparent; }
.chief-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.chief-top { display: flex; align-items: center; gap: 8px; }
.chief-name { font-size: 12px; font-weight: 650; color: var(--text-secondary); }
.verdict { font-size: 11px; font-weight: 650; padding: 2px 9px; border-radius: 999px; border: 1px solid; animation: pop-in var(--dur-2) var(--ease-out) both; }
.tone--good { color: #86efac; border-color: rgba(74, 222, 128, 0.4); background: rgba(74, 222, 128, 0.08); }
.tone--warn { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.08); }
.tone--bad { color: #fca5a5; border-color: rgba(248, 113, 113, 0.45); background: rgba(248, 113, 113, 0.08); }
.chief-text { display: flex; flex-direction: column; gap: 7px; }
.chief-headline { font-size: 14px; font-weight: 600; line-height: 1.35; color: var(--text-primary); }
.actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.action { font-size: 11.5px; line-height: 1.4; color: var(--text-secondary); display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.action b { display: inline-grid; place-items: center; width: 15px; height: 15px; margin-right: 5px; border-radius: 4px;
  font-size: 9.5px; background: #1c1c1c; color: var(--text-primary); vertical-align: 1px; }
.chief-empty { font-size: 12px; color: #5f5f5f; line-height: 1.45; }

/* Grid of agents */
.grid { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr); gap: 10px; }
.card { position: relative; min-height: 0; overflow: hidden; text-align: left; color: inherit; padding: 12px;
  border-radius: 12px; border: 1px solid #1c1c1c; background: #0a0a0a; display: flex; flex-direction: column; gap: 6px;
  animation: rise-in var(--dur-3) var(--ease-out) both; animation-delay: calc(var(--i) * 35ms); isolation: isolate; }
.card:hover { border-color: #2e2e2e; background: #0d0d0d; }
.card:hover .avatar { transform: translateY(-1px); }

/* Working: a slow light runs around the border in the agent's color */
.card.st--running, .chief.working { border-color: transparent; }
.card.st--running::before, .chief.working::before {
  content: ''; position: absolute; inset: 0; border-radius: inherit; padding: 1px; z-index: -1;
  background: conic-gradient(from var(--a), transparent 0 70%, var(--c, var(--accent)) 85%, transparent 100%) border-box;
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor; mask-composite: exclude; animation: orbit 2.2s linear infinite;
}
.chief.working { --c: #e5e5e5; }
@keyframes orbit { to { --a: 360deg; } }
.card.st--running .avatar::after { content: ''; position: absolute; inset: -3px; border-radius: 10px;
  border: 1px solid var(--c); opacity: 0; animation: breathe 1.6s ease-out infinite; }
@keyframes breathe { 0% { opacity: 0.7; transform: scale(0.92); } 100% { opacity: 0; transform: scale(1.25); } }
.card.st--waiting { opacity: 0.6; }
.card.st--waiting:hover { opacity: 0.85; }
.card.fresh { animation: settle 1.6s var(--ease-out); }
@keyframes settle { 0% { box-shadow: 0 0 0 1px var(--c), 0 0 24px -6px var(--c); } 100% { box-shadow: 0 0 0 1px transparent, 0 0 0 0 transparent; } }

.card-top { display: flex; align-items: center; gap: 8px; min-width: 0; }
.avatar { position: relative; width: 26px; height: 26px; border-radius: 8px; flex-shrink: 0; display: grid; place-items: center;
  background: color-mix(in srgb, var(--c) 14%, transparent); border: 1px solid color-mix(in srgb, var(--c) 35%, transparent);
  transition: transform var(--dur-2) var(--ease-out); }
.avatar svg { width: 14px; height: 14px; fill: none; stroke: var(--c); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.avatar--lg { width: 34px; height: 34px; border-radius: 10px; --c: #e5e5e5; }
.avatar--lg svg { width: 17px; height: 17px; }
.card-name { font-size: 12.5px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
.pill { font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 999px; color: #6b6b6b; border: 1px solid #262626; white-space: nowrap; }
.pill--running, .pill--queued, .pill--run { color: #93c5fd; border-color: rgba(59, 130, 246, 0.4); }
.pill--done { color: var(--text-secondary); }
.pill--fresh { color: #6b6b6b; }
.pill--failed { color: #fca5a5; border-color: rgba(248, 113, 113, 0.4); }
.card-role { font-size: 11px; color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-headline { font-size: 12.5px; line-height: 1.42; color: var(--text-primary); display: -webkit-box; -webkit-line-clamp: 3;
  -webkit-box-orient: vertical; overflow: hidden; }
.card.st--waiting .card-headline, .card-wait { color: #5f5f5f; font-size: 12px; line-height: 1.4; }
.card-foot { margin-top: auto; display: flex; align-items: center; gap: 8px; min-width: 0; }
.metric { font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  animation: fade-in var(--dur-3) ease both; }
.metric.big { font-size: 12.5px; font-weight: 650; color: #bbf7d0; }
.metric.bad { color: #fca5a5; }
.metric.warn { color: #fcd34d; }
.failed { font-size: 10.5px; color: #fca5a5; }

.preview { list-style: none; margin: 2px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; min-height: 0; overflow: hidden; }
.preview li { font-size: 11.5px; line-height: 1.35; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  animation: rise-in var(--dur-3) var(--ease-out) both; animation-delay: calc(120ms + var(--j) * 50ms); }
.tag { display: inline-block; font-size: 9.5px; font-weight: 650; text-transform: uppercase; letter-spacing: 0.04em; padding: 0 5px; margin-right: 6px;
  border-radius: 4px; border: 1px solid #2c2c2c; color: var(--text-tertiary); vertical-align: 1px; }
.tag--bad { color: #fca5a5; border-color: rgba(248, 113, 113, 0.4); }
.tag--warn { color: #fcd34d; border-color: rgba(245, 158, 11, 0.35); }
.tag--good { color: #86efac; border-color: rgba(74, 222, 128, 0.35); }
.card-headline { -webkit-line-clamp: 2; }

/* Loading skeleton: two shimmering lines */
.skeleton { display: flex; flex-direction: column; gap: 6px; padding-top: 2px; }
.skeleton i { display: block; height: 9px; border-radius: 4px;
  background: linear-gradient(90deg, #151515 0%, #222 50%, #151515 100%); background-size: 200% 100%; animation: shimmer 1.3s ease-in-out infinite; }
.skeleton i:nth-child(2) { width: 65%; }
@keyframes shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }

/* Content swaps cross-fade */
.swap-enter-active { transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out); }
.swap-leave-active { transition: opacity var(--dur-1) ease; }
.swap-enter-from { opacity: 0; transform: translateY(4px); }
.swap-leave-to { opacity: 0; }

@media (max-width: 900px) {
  .team { height: auto; }
  .grid { grid-template-columns: 1fr 1fr; grid-auto-rows: auto; }
  .card { min-height: 130px; }
  .actions { grid-template-columns: 1fr; }
  .pipe-label { font-size: 10px; }
  .pipe-count { display: none; }
}
@media (max-width: 520px) { .grid { grid-template-columns: 1fr; } }
</style>
