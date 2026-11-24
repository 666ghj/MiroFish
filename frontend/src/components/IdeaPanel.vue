<template>
  <div class="panel">
    <!-- Idea + clarity -->
    <section class="card card--hero" :class="{ flash: isChanged('/one_liner') }">
      <div class="hero-row">
        <div class="hero-text">
          <div class="eyebrow">The idea, so far</div>
          <IdeaClaim
            :claim="state.one_liner"
            path="/one_liner"
            :sources="state.sources"
            :changed="isChanged('/one_liner')"
            placeholder="Describe your idea in the chat. A one-line summary will appear here."
            @edit="fwdEdit" @lock="fwdLock"
          />
        </div>
        <div class="ring" role="img" :aria-label="`Idea clarity ${clarity.score} out of 100`">
          <svg viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="32" cy="32" r="27" class="ring-track" />
            <circle cx="32" cy="32" r="27" class="ring-fill" :style="{ strokeDashoffset: ringOffset }" />
          </svg>
          <div class="ring-num">{{ clarity.score }}</div>
          <div class="ring-label">Clarity</div>
        </div>
      </div>
      <div class="sections">
        <div v-for="name in SECTION_ORDER" :key="name" class="sec">
          <div class="sec-top"><span>{{ name }}</span><span>{{ v(name) }}</span></div>
          <div class="sec-track"><div class="sec-fill" :style="{ width: v(name) + '%' }"></div></div>
        </div>
      </div>
      <p v-if="clarity.last_change_reason" class="drop-note">{{ clarity.last_change_reason }}</p>
      <p v-if="clarity.top_missing?.length" class="missing">
        <strong>To sharpen it:</strong> {{ clarity.top_missing.join(' · ') }}
      </p>
      <p class="caption">Clarity measures how complete and specific the idea is, not whether it is good.</p>
    </section>

    <!-- Problem and customer -->
    <section class="card">
      <h3>Problem and customer</h3>
      <IdeaClaim v-for="f in PROBLEM_FIELDS" :key="f.path" v-bind="claimProps(f)" @edit="fwdEdit" @lock="fwdLock" />
    </section>

    <!-- Solution and model -->
    <section class="card">
      <h3>Solution and business model</h3>
      <IdeaClaim v-for="f in SOLUTION_FIELDS" :key="f.path" v-bind="claimProps(f)" @edit="fwdEdit" @lock="fwdLock" />
    </section>

    <!-- Could / won't work -->
    <section class="card card--split">
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
        <p v-if="!state.what_wont_work.length" class="empty">No red flags recorded yet.</p>
      </div>
    </section>

    <!-- Why hasn't this been built -->
    <section class="card" :class="{ flash: isChanged('/why_not_built') }">
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

      <div class="search-meta">
        <template v-if="search.searched_at">
          Searched {{ search.providers.map(providerName).join(', ') }}
          <span v-if="search.unavailable.length"> · not used: {{ search.unavailable.join(', ') }}</span>.
          A company missing here does not mean nobody has built it.
        </template>
        <template v-else>Research runs automatically once the problem and solution are clear.</template>
      </div>
      <button type="button" class="btn-research" :disabled="busy || confidential || (search.sweeps || 0) >= 3"
              @click="$emit('research')">
        {{ search.searched_at ? 'Research again' : 'Research now' }}
      </button>
      <span v-if="confidential" class="muted-note">Confidential mode is on: no searches.</span>
    </section>

    <!-- Why now + challenges -->
    <section class="card">
      <h3>Why now</h3>
      <IdeaClaim
        v-for="(c, i) in state.why_now" :key="'wn' + i"
        :claim="c" :path="`/why_now/${i}`" :sources="state.sources"
        :changed="isChanged(`/why_now/${i}`)" @edit="fwdEdit" @lock="fwdLock"
      />
      <p v-if="!state.why_now.length" class="empty">What changed recently that makes this possible? Not covered yet.</p>
      <h3 class="mt">Key challenges</h3>
      <template v-for="kind in CHALLENGES" :key="kind.id">
        <IdeaClaim
          v-for="(c, i) in state.challenges[kind.id]" :key="kind.id + i"
          :claim="c" :path="`/challenges/${kind.id}/${i}`" :label="kind.label" :sources="state.sources"
          :changed="isChanged(`/challenges/${kind.id}/${i}`)" @edit="fwdEdit" @lock="fwdLock"
        />
      </template>
      <p v-if="!hasChallenges" class="empty">None recorded yet.</p>
    </section>

    <!-- Riskiest assumptions -->
    <section class="card" :class="{ flash: isChanged('/risky_assumptions') }">
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
      <p v-if="!state.risky_assumptions.length" class="empty">The riskiest assumptions appear as the idea takes shape.</p>
    </section>

    <!-- Objections + next questions -->
    <section class="card card--split">
      <div>
        <h3>Open concerns</h3>
        <ul class="plain">
          <li v-for="(o, i) in state.open_objections" :key="'ob' + i">{{ o.text }}</li>
        </ul>
        <p v-if="!state.open_objections.length" class="empty">None open.</p>
      </div>
      <div>
        <h3>Questions coming up</h3>
        <ol class="plain">
          <li v-for="(q, i) in state.open_questions" :key="'q' + i">{{ q.question }}</li>
        </ol>
      </div>
    </section>

    <!-- Sources -->
    <details v-if="sourceList.length" class="card sources">
      <summary>Sources ({{ sourceList.length }})</summary>
      <a v-for="s in sourceList" :key="s.id" :href="s.url" target="_blank" rel="noopener" class="source">
        <span class="src-prov">{{ providerName(s.provider) }}</span>
        <span class="src-title">{{ s.title }}</span>
      </a>
    </details>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import IdeaClaim from './IdeaClaim.vue'

const props = defineProps({
  state: { type: Object, required: true },
  changed: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  confidential: { type: Boolean, default: false },
})
const emit = defineEmits(['edit', 'lock', 'research'])

const PROBLEM_FIELDS = [
  { path: '/problem/statement', label: 'Problem', key: ['problem', 'statement'] },
  { path: '/problem/who', label: 'Who has it', key: ['problem', 'who'] },
  { path: '/problem/workaround', label: 'What they do today', key: ['problem', 'workaround'] },
  { path: '/problem/frequency', label: 'How often', key: ['problem', 'frequency'] },
  { path: '/problem/severity', label: 'What it costs', key: ['problem', 'severity'] },
  { path: '/customer/early_adopters', label: 'First customers', key: ['customer', 'early_adopters'] },
  { path: '/customer/buyer', label: 'Who signs off', key: ['customer', 'buyer'] },
]
const SOLUTION_FIELDS = [
  { path: '/solution/core', label: 'What it does', key: ['solution', 'core'] },
  { path: '/solution/smallest_version', label: 'Smallest version', key: ['solution', 'smallest_version'] },
  { path: '/business_model/who_pays', label: 'Who pays', key: ['business_model', 'who_pays'] },
  { path: '/business_model/price_anchor', label: 'Price anchor', key: ['business_model', 'price_anchor'] },
]
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

const SECTION_ORDER = ['Problem', 'Customer', 'Solution', 'Market', 'Business model', 'Risks and tests']
const clarity = computed(() => props.state.clarity || { score: 0, by_section: {} })
const v = (name) => clarity.value.by_section?.[name] ?? 0
const ringOffset = computed(() => 169.6 * (1 - (clarity.value.score || 0) / 100))
const wnb = computed(() => props.state.why_not_built)
const search = computed(() => wnb.value.search || { providers: [], unavailable: [] })
const hasChallenges = computed(() => CHALLENGES.some(k => props.state.challenges[k.id]?.length))
const sourceList = computed(() => Object.entries(props.state.sources || {}).map(([id, s]) => ({ id, ...s })))

function isChanged(prefix) {
  return props.changed.some(p => p === prefix || p.startsWith(prefix + '/'))
}

function claimProps(f) {
  return {
    claim: props.state[f.key[0]][f.key[1]], path: f.path, label: f.label,
    sources: props.state.sources, changed: isChanged(f.path),
  }
}

function fwdEdit(path, text) { emit('edit', path, text) }
function fwdLock(path, locked) { emit('lock', path, locked) }

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch (_) { return '' }
}

function providerName(p) {
  return { tavily: 'Web (Tavily)', exa: 'Companies (Exa)', hn: 'Hacker News', github: 'GitHub' }[p] || p
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
.card h3 { font-size: 13px; font-weight: 650; color: var(--text-primary); margin: 0 0 6px 2px; }
.card .mt { margin-top: 14px; }
.card--split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.h-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.h-row h3 { margin: 0; }
.eyebrow { font-size: 11px; font-weight: 600; color: var(--accent); margin: 0 0 2px 12px; }
.empty { font-size: 12.5px; color: #5a5a5a; padding: 6px 12px; }
.muted-note { font-size: 11.5px; color: var(--text-tertiary); margin-left: 8px; }

.card--hero { background: linear-gradient(180deg, #0f0f0f, #0a0a0a); }
.hero-row { display: flex; gap: 16px; align-items: flex-start; }
.hero-text { flex: 1; min-width: 0; }
.hero-text :deep(.claim-text) { font-size: 17px; font-weight: 600; line-height: 1.4; }
.ring { position: relative; width: 76px; height: 76px; flex-shrink: 0; text-align: center; }
.ring svg { width: 76px; height: 76px; transform: rotate(-90deg); }
.ring-track { fill: none; stroke: #1f1f1f; stroke-width: 6; }
.ring-fill { fill: none; stroke: var(--accent); stroke-width: 6; stroke-linecap: round; stroke-dasharray: 169.6; transition: stroke-dashoffset 0.6s ease; }
.ring-num { position: absolute; top: 20px; left: 0; right: 0; font-size: 20px; font-weight: 700; }
.ring-label { position: absolute; top: 44px; left: 0; right: 0; font-size: 9.5px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }
.sections { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 14px; margin: 12px 12px 4px; }
.sec-top { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.sec-track { height: 4px; border-radius: 999px; background: rgba(59, 130, 246, 0.14); overflow: hidden; }
.sec-fill { height: 100%; background: var(--accent); border-radius: 999px; transition: width 0.6s ease; }
.missing { font-size: 12px; color: var(--text-secondary); margin: 10px 12px 0; line-height: 1.5; }
.missing strong { color: var(--text-primary); }
.drop-note { font-size: 12px; color: #fcd34d; margin: 8px 12px 0; }
.caption { font-size: 11px; color: #5a5a5a; margin: 6px 12px 0; }

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
  padding: 9px 11px; border: 1px solid #1f1f1f; border-radius: 8px; text-decoration: none;
  transition: border-color 0.15s;
}
.company:hover { border-color: #3a3a3a; }
.co-name { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.co-host { grid-row: 1; grid-column: 2; font-size: 11px; color: #93c5fd; }
.co-note { grid-column: 1 / -1; font-size: 12px; color: var(--text-tertiary); }
.dead { font-size: 10px; font-weight: 700; color: #fca5a5; margin-left: 6px; text-transform: uppercase; }
.search-meta { font-size: 11.5px; line-height: 1.5; color: var(--text-tertiary); margin: 12px 2px 8px; }
.btn-research {
  font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 7px;
  border: 1px solid #333; background: #141414; color: var(--text-primary);
}
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

@media (max-width: 1100px) { .card--split { grid-template-columns: 1fr; } .sections { grid-template-columns: repeat(2, 1fr); } }
@media (prefers-reduced-motion: reduce) { .card, .ring-fill, .sec-fill { transition: none; } }
</style>
