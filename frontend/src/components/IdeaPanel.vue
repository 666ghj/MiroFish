<template>
  <div class="panel">
    <!-- The idea + completeness -->
    <section id="sec-idea" class="card card--hero" :class="{ flash: isChanged('/one_liner') }">
      <div class="hero-row">
        <div class="hero-text">
          <div class="eyebrow">The idea, so far</div>
          <IdeaClaim
            :claim="state.one_liner"
            path="/one_liner"
            :sources="state.sources"
            :changed="isChanged('/one_liner')"
            placeholder="Your idea in one line will appear here once you describe it."
            @edit="fwdEdit" @lock="fwdLock"
          />
        </div>
        <div class="score" role="img" :aria-label="`Completeness ${clarity.score} out of 100`">
          <div class="score-num">{{ clarity.score }}</div>
          <div class="score-label">Completeness</div>
        </div>
      </div>

      <div class="checklist" aria-label="Completeness by part">
        <div v-for="name in SECTION_ORDER" :key="name" class="check">
          <span class="check-name">{{ name }}</span>
          <span class="check-track"><span class="check-fill" :style="{ width: v(name) + '%' }"></span></span>
          <span class="check-val">{{ v(name) }}</span>
        </div>
      </div>
      <p v-if="clarity.last_change_reason" class="drop-note">{{ clarity.last_change_reason }}</p>
      <p class="caption">
        How much of the idea is pinned down, with your own specifics counting most. It is not a verdict on whether the idea is good.
      </p>

      <div class="handoff">
        <button type="button" class="btn-send" :disabled="busy || clarity.score < 60" @click="$emit('send-brief')">
          Test it with buyer personas <span aria-hidden="true">→</span>
        </button>
        <span class="handoff-note">
          {{ clarity.score >= 60 ? 'Opens the GTM simulation with your idea filled in.' : `Unlocks at 60 (now ${clarity.score}).` }}
        </span>
      </div>
    </section>

    <!-- What changed on the last turn -->
    <section v-if="lastChange && lastChange.labels.length" class="changed" aria-label="What changed on the last turn">
      <div class="changed-head">
        <span class="changed-dot" aria-hidden="true"></span>
        What changed{{ lastChange.turn ? ` after message ${lastChange.turn}` : '' }}
      </div>
      <p v-if="lastChange.summary" class="changed-summary">{{ lastChange.summary }}</p>
      <div class="chips">
        <span v-for="l in lastChange.labels" :key="l" class="tag">{{ l }}</span>
      </div>
    </section>

    <!-- Still open: compact instead of a wall of placeholders -->
    <section v-if="openItems.length" class="card card--open">
      <h3>Still open <span class="count">{{ openItems.length }}</span></h3>
      <p class="hint">Pick one to talk about next. It drafts a message for you; nothing is sent until you press enter.</p>
      <div class="chips">
        <button v-for="o in openItems" :key="o.path" type="button" class="open-chip" @click="$emit('ask', o.starter)">
          {{ o.label }}
        </button>
      </div>
    </section>

    <!-- Problem and customer -->
    <section id="sec-problem" v-if="filled(PROBLEM_FIELDS).length" class="card">
      <h3>Problem and customer</h3>
      <IdeaClaim v-for="f in filled(PROBLEM_FIELDS)" :key="f.path" v-bind="claimProps(f)" @edit="fwdEdit" @lock="fwdLock" />
    </section>

    <!-- Solution and model -->
    <section id="sec-solution" v-if="filled(SOLUTION_FIELDS).length" class="card">
      <h3>Solution and business model</h3>
      <IdeaClaim v-for="f in filled(SOLUTION_FIELDS)" :key="f.path" v-bind="claimProps(f)" @edit="fwdEdit" @lock="fwdLock" />
    </section>

    <!-- Could / won't work -->
    <section id="sec-work" v-if="state.what_could_work.length || state.what_wont_work.length" class="card card--split">
      <div>
        <h3>What could work</h3>
        <IdeaClaim
          v-for="(c, i) in state.what_could_work" :key="'cw' + i"
          :claim="c" :path="`/what_could_work/${i}`" :sources="state.sources"
          :changed="isChanged(`/what_could_work/${i}`)" @edit="fwdEdit" @lock="fwdLock"
        />
        <p v-if="!state.what_could_work.length" class="empty">Nothing yet.</p>
      </div>
      <div>
        <h3>What probably won't</h3>
        <div v-for="(c, i) in state.what_wont_work" :key="'ww' + i" class="sev-wrap">
          <span class="sev" :class="`sev--${c.severity}`">{{ c.severity }}</span>
          <IdeaClaim
            :claim="c" :path="`/what_wont_work/${i}`" :sources="state.sources"
            :changed="isChanged(`/what_wont_work/${i}`)" @edit="fwdEdit" @lock="fwdLock"
          />
        </div>
        <p v-if="!state.what_wont_work.length" class="empty">No red flags yet.</p>
      </div>
    </section>

    <!-- Why hasn't this been built -->
    <section id="sec-wnb" class="card" :class="{ flash: isChanged('/why_not_built') }">
      <div class="h-row">
        <h3>Why hasn't this been built yet?</h3>
        <span class="wnb-badge" :class="`wnb--${wnb.classification}`">{{ WNB_LABEL[wnb.classification] }}</span>
      </div>
      <p v-if="wnb.summary.text" class="wnb-summary">{{ wnb.summary.text }}</p>

      <div v-if="wnb.competitors.length" class="companies">
        <div class="sub">Already doing this</div>
        <a v-for="c in wnb.competitors" :key="c.name" :href="c.url" target="_blank" rel="noopener" class="company">
          <span class="co-name">{{ c.name }}</span>
          <span class="co-note">{{ c.note }}</span>
          <span class="co-host">{{ host(c.url) }} ↗</span>
        </a>
      </div>
      <div v-if="wnb.predecessors.length" class="companies">
        <div class="sub">Tried before</div>
        <a v-for="c in wnb.predecessors" :key="c.name" :href="c.url" target="_blank" rel="noopener" class="company">
          <span class="co-name">{{ c.name }} <span class="dead" v-if="c.status === 'dead'">shut down</span></span>
          <span class="co-note">{{ c.failure_reason }}</span>
          <span class="co-host">{{ host(c.url) }} ↗</span>
        </a>
      </div>
      <div v-if="wnb.blockers.length">
        <div class="sub">Structural blockers</div>
        <IdeaClaim
          v-for="(b, i) in wnb.blockers" :key="'b' + i"
          :claim="b" :path="`/why_not_built/blockers/${i}`" :label="BLOCKER_LABEL[b.type] || b.type"
          :sources="state.sources" :changed="isChanged(`/why_not_built/blockers/${i}`)"
          @edit="fwdEdit" @lock="fwdLock"
        />
      </div>

      <p class="search-meta">
        <template v-if="search.searched_at">
          Searched {{ search.providers.map(providerName).join(', ') }}<span v-if="search.unavailable.length">; not used: {{ search.unavailable.join(', ') }}</span>.
          Missing from this list does not mean nobody has built it.
        </template>
        <template v-else>Runs automatically once the problem and the solution are clear, or start it now.</template>
      </p>
      <div class="row">
        <button type="button" class="btn-research" :disabled="busy || confidential || (search.sweeps || 0) >= 3" @click="$emit('research')">
          {{ search.searched_at ? 'Research again' : 'Research now' }}
        </button>
        <span v-if="confidential" class="muted-note">Confidential mode is on: no searches.</span>
        <span v-else-if="(search.sweeps || 0) >= 3" class="muted-note">Research limit reached for this idea.</span>
      </div>
    </section>

    <!-- Why now + challenges -->
    <section v-if="state.why_now.length || hasChallenges" class="card">
      <template v-if="state.why_now.length">
        <h3>Why now</h3>
        <IdeaClaim
          v-for="(c, i) in state.why_now" :key="'wn' + i"
          :claim="c" :path="`/why_now/${i}`" :sources="state.sources"
          :changed="isChanged(`/why_now/${i}`)" @edit="fwdEdit" @lock="fwdLock"
        />
      </template>
      <template v-if="hasChallenges">
        <h3 :class="{ mt: state.why_now.length }">Key challenges</h3>
        <template v-for="kind in CHALLENGES" :key="kind.id">
          <IdeaClaim
            v-for="(c, i) in state.challenges[kind.id]" :key="kind.id + i"
            :claim="c" :path="`/challenges/${kind.id}/${i}`" :label="kind.label" :sources="state.sources"
            :changed="isChanged(`/challenges/${kind.id}/${i}`)" @edit="fwdEdit" @lock="fwdLock"
          />
        </template>
      </template>
    </section>

    <!-- Riskiest assumptions -->
    <section id="sec-risks" v-if="state.risky_assumptions.length" class="card" :class="{ flash: isChanged('/risky_assumptions') }">
      <h3>Riskiest assumptions and the cheapest tests</h3>
      <div v-for="(a, i) in state.risky_assumptions" :key="'ra' + i" class="risk">
        <div class="risk-top">
          <span class="rank">{{ a.rank }}</span>
          <span class="impact" :class="`impact--${a.impact}`">{{ a.impact }}</span>
        </div>
        <IdeaClaim
          :claim="a" :path="`/risky_assumptions/${i}`" :sources="state.sources"
          :changed="isChanged(`/risky_assumptions/${i}`)" @edit="fwdEdit" @lock="fwdLock"
        />
        <div v-if="a.test?.method" class="test">
          <div><strong>Test:</strong> {{ a.test.method }}</div>
          <div class="test-meta">
            <span v-if="a.test.cost_usd != null">${{ a.test.cost_usd }}</span>
            <span v-if="a.test.days != null">{{ a.test.days }} {{ a.test.days === 1 ? 'day' : 'days' }}</span>
            <span v-if="a.test.pass_criterion">Pass if: {{ a.test.pass_criterion }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Concerns + next questions -->
    <section id="sec-next" class="card" :class="{ 'card--split': state.open_objections.length }">
      <div v-if="state.open_objections.length">
        <h3>Open concerns</h3>
        <ul class="plain">
          <li v-for="(o, i) in state.open_objections" :key="'ob' + i">{{ o.text }}</li>
        </ul>
      </div>
      <div>
        <h3>Questions coming up</h3>
        <ol class="plain">
          <li v-for="(q, i) in state.open_questions" :key="'q' + i">{{ q.question }}</li>
        </ol>
      </div>
    </section>

    <!-- Sources + legend -->
    <details v-if="sourceList.length" class="card sources">
      <summary>Sources ({{ sourceList.length }})</summary>
      <a v-for="s in sourceList" :key="s.id" :href="s.url" target="_blank" rel="noopener" class="source">
        <span class="src-prov">{{ providerName(s.provider) }}</span>
        <span class="src-title">{{ s.title }}</span>
      </a>
    </details>
    <p class="legend">
      <span><b>You said</b> your words</span>
      <span><b>AI guess</b> inferred, edit it if wrong</span>
      <span><b>Evidence</b> backed by a linked source</span>
      <span><b>Lock</b> stops the AI changing a field</span>
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import IdeaClaim from './IdeaClaim.vue'

const props = defineProps({
  state: { type: Object, required: true },
  changed: { type: Array, default: () => [] },
  lastChange: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  confidential: { type: Boolean, default: false },
})
const emit = defineEmits(['edit', 'lock', 'research', 'send-brief', 'ask'])

const PROBLEM_FIELDS = [
  { path: '/problem/statement', label: 'Problem', key: ['problem', 'statement'], starter: 'The core problem is ' },
  { path: '/problem/who', label: 'Who has it', key: ['problem', 'who'], starter: 'The people who have this problem are ' },
  { path: '/problem/workaround', label: 'What they do today', key: ['problem', 'workaround'], starter: 'Today they get around it by ' },
  { path: '/problem/frequency', label: 'How often', key: ['problem', 'frequency'], starter: 'It happens about ' },
  { path: '/problem/severity', label: 'What it costs', key: ['problem', 'severity'], starter: 'The last time it happened, it cost ' },
  { path: '/customer/early_adopters', label: 'First customers', key: ['customer', 'early_adopters'], starter: 'The first customers I would go after are ' },
  { path: '/customer/buyer', label: 'Who signs off', key: ['customer', 'buyer'], starter: 'The person who would approve buying it is ' },
]
const SOLUTION_FIELDS = [
  { path: '/solution/core', label: 'What it does', key: ['solution', 'core'], starter: 'What the product actually does is ' },
  { path: '/solution/smallest_version', label: 'Smallest version', key: ['solution', 'smallest_version'], starter: 'The smallest version I could ship is ' },
  { path: '/business_model/who_pays', label: 'Who pays', key: ['business_model', 'who_pays'], starter: 'The one who pays would be ' },
  { path: '/business_model/price_anchor', label: 'Price', key: ['business_model', 'price_anchor'], starter: 'For price, today they spend ' },
]
const LIST_OPEN = [
  { path: '/why_now', label: 'Why now', starter: 'What changed recently that makes this possible now is ' },
  { path: '/risky_assumptions', label: 'Riskiest assumption', starter: 'The thing that must be true for this to work is ' },
]
const SECTION_ORDER = ['Problem', 'Customer', 'Solution', 'Market', 'Business model', 'Risks and tests']
const CHALLENGES = [
  { id: 'technical', label: 'Technical' }, { id: 'regulatory', label: 'Regulatory' },
  { id: 'go_to_market', label: 'Go to market' }, { id: 'capital', label: 'Capital' }, { id: 'team', label: 'Team' },
]
const WNB_LABEL = {
  unknown: 'Not researched', nobody_tried: 'Nobody found', tried_and_failed: 'Tried and failed',
  exists_unknown: 'Exists, little traction', crowded_funded: 'Crowded market',
}
const BLOCKER_LABEL = {
  regulation: 'Regulation', distribution: 'Distribution', unit_economics: 'Unit economics', tech_limits: 'Tech limits',
  incumbents: 'Incumbents', timing: 'Timing', capital: 'Capital', cold_start: 'Cold start', trust_liability: 'Trust',
}

const clarity = computed(() => props.state.clarity || { score: 0, by_section: {} })
const v = (name) => clarity.value.by_section?.[name] ?? 0
const wnb = computed(() => props.state.why_not_built)
const search = computed(() => wnb.value.search || { providers: [], unavailable: [] })
const hasChallenges = computed(() => CHALLENGES.some(k => props.state.challenges[k.id]?.length))
const sourceList = computed(() => Object.entries(props.state.sources || {}).map(([id, s]) => ({ id, ...s })))

function claimOf(f) { return props.state[f.key[0]][f.key[1]] }
function filled(fields) { return fields.filter(f => (claimOf(f).text || '').trim()) }

const openItems = computed(() => [
  ...[...PROBLEM_FIELDS, ...SOLUTION_FIELDS].filter(f => !(claimOf(f).text || '').trim()),
  ...LIST_OPEN.filter(l => !props.state[l.path.slice(1)]?.length),
])

function isChanged(prefix) {
  return props.changed.some(p => p === prefix || p.startsWith(prefix + '/'))
}

function claimProps(f) {
  return { claim: claimOf(f), path: f.path, label: f.label, sources: props.state.sources, changed: isChanged(f.path) }
}

function fwdEdit(path, text) { emit('edit', path, text) }
function fwdLock(path, locked) { emit('lock', path, locked) }

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch (_) { return '' }
}

function providerName(p) {
  return { tavily: 'the web', exa: 'company search', hn: 'Hacker News', github: 'GitHub' }[p] || p
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: 14px; }
.card {
  border: 1px solid #1f1f1f;
  border-radius: 12px;
  background: #0a0a0a;
  padding: 16px 16px 12px;
  transition: border-color 0.8s ease;
}
.card.flash { border-color: rgba(59, 130, 246, 0.45); }
.card h3 { font-size: 13px; font-weight: 650; color: var(--text-primary); margin: 0 0 6px 2px; display: flex; align-items: center; gap: 8px; }
.card .mt { margin-top: 14px; }
.card--split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.h-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.h-row h3 { margin: 0; }
.row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.eyebrow { font-size: 11px; font-weight: 600; color: var(--accent); margin: 0 0 2px 12px; }
.empty { font-size: 12.5px; color: #5a5a5a; padding: 6px 12px; }
.muted-note { font-size: 11.5px; color: var(--text-tertiary); }
.count { font-size: 11px; font-weight: 600; color: var(--text-tertiary); background: #161616; border-radius: 999px; padding: 1px 8px; }

/* Hero: one headline number, sans, with its parts underneath */
.card--hero { background: linear-gradient(180deg, #0f0f0f, #0a0a0a); }
.hero-row { display: flex; gap: 16px; align-items: flex-start; }
.hero-text { flex: 1; min-width: 0; }
.hero-text :deep(.claim-text) { font-size: 17px; font-weight: 600; line-height: 1.4; }
.score { text-align: right; flex-shrink: 0; padding: 4px 6px 0 0; }
.score-num { font-size: 48px; font-weight: 650; line-height: 1; letter-spacing: -0.03em; }
.score-label { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }

.checklist { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 22px; margin: 14px 12px 2px; }
.check { display: grid; grid-template-columns: 104px minmax(0, 1fr) 26px; align-items: center; gap: 10px; }
.check-name { font-size: 12px; color: var(--text-secondary); }
.check-track { height: 6px; border-radius: 999px; background: rgba(59, 130, 246, 0.14); overflow: hidden; }
.check-fill { display: block; height: 100%; border-radius: 999px; background: var(--accent); transition: width 0.6s ease; }
.check-val { font-size: 12px; font-weight: 600; text-align: right; color: var(--text-primary); }
.drop-note { font-size: 12px; color: #fcd34d; margin: 10px 12px 0; }
.caption { font-size: 11.5px; line-height: 1.5; color: #6b6b6b; margin: 10px 12px 0; }
.handoff { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 12px 12px 4px; }
.btn-send { font-size: 13px; font-weight: 600; padding: 8px 14px; border-radius: 8px; border: none; background: var(--accent); color: #fff; }
.btn-send:hover:not(:disabled) { background: var(--accent-hover); }
.btn-send:disabled { background: #1a1a1a; color: #555; cursor: not-allowed; }
.handoff-note { font-size: 11.5px; color: var(--text-tertiary); }

/* What changed */
.changed {
  border: 1px solid rgba(59, 130, 246, 0.3);
  background: rgba(59, 130, 246, 0.06);
  border-radius: 12px;
  padding: 12px 16px;
}
.changed-head { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 650; color: #93c5fd; }
.changed-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.changed-summary { font-size: 13px; line-height: 1.5; color: var(--text-primary); margin: 6px 0 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 11.5px; color: var(--text-secondary); padding: 2px 9px; border-radius: 999px; border: 1px solid #2a2a2a; background: #0d0d0d; }

/* Still open */
.card--open { padding-bottom: 14px; }
.hint { font-size: 12px; color: var(--text-tertiary); margin: 0 2px 10px; }
.open-chip {
  font-size: 12.5px; color: var(--text-secondary); padding: 5px 11px; border-radius: 999px;
  border: 1px dashed #333; background: transparent; transition: border-color 0.15s, color 0.15s;
}
.open-chip:hover { color: var(--text-primary); border-color: var(--accent); border-style: solid; }

.sev-wrap { position: relative; }
.sev, .impact {
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 1px 6px; border-radius: 4px; border: 1px solid #333; color: var(--text-secondary);
}
.sev { position: absolute; right: 64px; top: 12px; z-index: 1; }
.sev--high, .impact--major { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); }
.sev--critical, .impact--fatal { color: #fca5a5; border-color: rgba(248, 113, 113, 0.45); }

.wnb-badge { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 999px; border: 1px solid #333; color: var(--text-secondary); white-space: nowrap; }
.wnb--crowded_funded, .wnb--tried_and_failed { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); }
.wnb--nobody_tried { color: #93c5fd; border-color: rgba(59, 130, 246, 0.4); }
.wnb--exists_unknown { color: #86efac; border-color: rgba(74, 222, 128, 0.35); }
.wnb-summary { font-size: 13px; line-height: 1.55; color: var(--text-secondary); margin: 6px 2px 10px; }
.sub { font-size: 11px; font-weight: 600; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; margin: 10px 2px 6px; }
.companies { display: flex; flex-direction: column; gap: 6px; }
.company {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px;
  padding: 9px 11px; border: 1px solid #1f1f1f; border-radius: 8px; text-decoration: none; transition: border-color 0.15s;
}
.company:hover { border-color: #3a3a3a; }
.co-name { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.co-host { grid-row: 1; grid-column: 2; font-size: 11px; color: #93c5fd; }
.co-note { grid-column: 1 / -1; font-size: 12px; color: var(--text-tertiary); }
.dead { font-size: 10px; font-weight: 700; color: #fca5a5; margin-left: 6px; text-transform: uppercase; }
.search-meta { font-size: 11.5px; line-height: 1.5; color: var(--text-tertiary); margin: 12px 2px 8px; }
.btn-research { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 7px; border: 1px solid #333; background: #141414; color: var(--text-primary); }
.btn-research:hover:not(:disabled) { border-color: var(--accent); }
.btn-research:disabled { opacity: 0.45; cursor: not-allowed; }

.risk { border-top: 1px solid #161616; padding-top: 8px; margin-top: 4px; }
.risk:first-of-type { border-top: none; }
.risk-top { display: flex; align-items: center; gap: 8px; margin-left: 12px; }
.rank { width: 18px; height: 18px; border-radius: 50%; background: #1a1a1a; font-size: 11px; font-weight: 700; display: grid; place-items: center; }
.test { margin: 0 12px 8px; padding: 8px 10px; border-radius: 7px; background: rgba(59, 130, 246, 0.06); font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; }
.test strong { color: var(--text-primary); }
.test-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 4px; font-size: 11.5px; color: var(--text-tertiary); }

.plain { padding-left: 30px; margin: 0; font-size: 12.5px; line-height: 1.55; color: var(--text-secondary); }
.plain li { margin-bottom: 6px; }

.sources summary { cursor: pointer; font-size: 13px; font-weight: 600; }
.source { display: flex; gap: 10px; padding: 6px 2px; font-size: 12px; text-decoration: none; border-top: 1px solid #161616; }
.src-prov { color: var(--text-tertiary); min-width: 110px; }
.src-title { color: #93c5fd; }

.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 11.5px; color: #6b6b6b; margin: 2px 4px 0; }
.legend b { color: var(--text-secondary); font-weight: 600; margin-right: 4px; }

@media (max-width: 1100px) { .card--split { grid-template-columns: 1fr; } .checklist { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .card, .check-fill { transition: none; } }
</style>
