<template>
  <div class="dash">
    <!-- 1. The idea -->
    <section class="tile tile--hero" :class="{ glow: changedAny(['/one_liner']) }">
      <div class="hero-main">
        <button type="button" class="tile-head" @click="$emit('open', 'sec-idea')">
          <span>The idea</span><span class="open" aria-hidden="true">↗</span>
        </button>
        <p class="one-liner" :class="{ muted: !state.one_liner.text }">
          {{ state.one_liner.text || 'Your idea in one line appears here once you describe it.' }}
        </p>
        <div class="bars" aria-label="Completeness by part">
          <div v-for="name in SECTIONS" :key="name" class="bar" :title="`${name}: ${v(name)} of 100`">
            <span class="bar-name">{{ name }}</span>
            <span class="bar-track"><span class="bar-fill" :style="{ width: v(name) + '%' }"></span></span>
          </div>
        </div>
        <p class="ticker" aria-live="off">
          <template v-if="updating"><span class="pulse" aria-hidden="true"></span>Updating the picture...</template>
          <template v-else-if="lastChange && lastChange.labels.length">
            <span class="dot" aria-hidden="true"></span>Updated: {{ lastChange.labels.join(', ') }}
          </template>
          <template v-else>Talk it through on the left; this fills in as you go.</template>
        </p>
      </div>
      <div class="hero-side">
        <div class="score" role="img" :aria-label="`Completeness ${score} out of 100`">
          <div class="score-num">{{ shownScore }}</div>
          <div class="score-label">Completeness</div>
        </div>
        <button type="button" class="btn-send" :disabled="busy || score < 60" @click="$emit('send-brief')"
                :title="score >= 60 ? 'Open the GTM simulation with this idea filled in' : `Unlocks at 60 (now ${score})`">
          Test with buyers →
        </button>
        <span class="unlock">{{ score >= 60 ? 'Ready to simulate' : `Unlocks at 60` }}</span>
      </div>
    </section>

    <!-- 2. Problem and customer -->
    <section class="tile" :class="{ glow: changedAny(['/problem', '/customer']) }">
      <button type="button" class="tile-head" @click="$emit('open', 'sec-problem')">
        <span>Problem and customer</span><span class="open" aria-hidden="true">↗</span>
      </button>
      <dl class="facts">
        <template v-for="f in filled(PROBLEM)" :key="f.path">
          <dt>{{ f.label }}</dt>
          <dd :class="`st--${claimOf(f).status}`" :title="claimOf(f).text">{{ claimOf(f).text }}</dd>
        </template>
      </dl>
      <div v-if="empty(PROBLEM).length" class="gaps">
        <button v-for="f in empty(PROBLEM)" :key="f.path" type="button" class="gap" @click="$emit('ask', f.starter)">+ {{ f.label }}</button>
      </div>
    </section>

    <!-- 3. Solution and money -->
    <section class="tile" :class="{ glow: changedAny(['/solution', '/business_model', '/why_now']) }">
      <button type="button" class="tile-head" @click="$emit('open', 'sec-solution')">
        <span>Solution and money</span><span class="open" aria-hidden="true">↗</span>
      </button>
      <dl class="facts">
        <template v-for="f in filled(SOLUTION)" :key="f.path">
          <dt>{{ f.label }}</dt>
          <dd :class="`st--${claimOf(f).status}`" :title="claimOf(f).text">{{ claimOf(f).text }}</dd>
        </template>
        <template v-if="state.why_now.length">
          <dt>Why now</dt>
          <dd :class="`st--${state.why_now[0].status}`" :title="state.why_now[0].text">{{ state.why_now[0].text }}</dd>
        </template>
      </dl>
      <div v-if="empty(SOLUTION).length || !state.why_now.length" class="gaps">
        <button v-for="f in empty(SOLUTION)" :key="f.path" type="button" class="gap" @click="$emit('ask', f.starter)">+ {{ f.label }}</button>
        <button v-if="!state.why_now.length" type="button" class="gap"
                @click="$emit('ask', 'What changed recently that makes this possible now is ')">+ Why now</button>
      </div>
    </section>

    <!-- 4. Why hasn't this been built -->
    <section class="tile" :class="{ glow: changedAny(['/why_not_built']) }">
      <button type="button" class="tile-head" @click="$emit('open', 'sec-wnb')">
        <span>Why not built yet?</span>
        <span class="badge" :class="`wnb--${wnb.classification}`">{{ WNB[wnb.classification] }}</span>
      </button>
      <p v-if="wnb.summary.text" class="summary" :title="wnb.summary.text">{{ wnb.summary.text }}</p>
      <div v-if="wnb.competitors.length" class="names">
        <a v-for="c in wnb.competitors.slice(0, 4)" :key="c.name" :href="c.url" target="_blank" rel="noopener" class="name">{{ c.name }}</a>
        <span v-if="wnb.competitors.length > 4" class="more">+{{ wnb.competitors.length - 4 }}</span>
      </div>
      <p v-else-if="!wnb.search.searched_at" class="muted-line">Not researched yet. It runs once the problem and solution are clear.</p>
      <p v-else class="muted-line">No companies found in what was searched. That does not prove nobody built it.</p>
      <div class="tile-foot">
        <button type="button" class="mini" :disabled="busy || confidential || (wnb.search.sweeps || 0) >= 3" @click="$emit('research')">
          {{ wnb.search.searched_at ? 'Research again' : 'Research now' }}
        </button>
        <span v-if="confidential" class="foot-note">Confidential: no searches</span>
        <span v-else-if="sourceCount" class="foot-note">{{ sourceCount }} {{ sourceCount === 1 ? 'source' : 'sources' }}</span>
      </div>
    </section>

    <!-- 5. Riskiest assumptions -->
    <section class="tile" :class="{ glow: changedAny(['/risky_assumptions']) }">
      <button type="button" class="tile-head" @click="$emit('open', 'sec-risks')">
        <span>Riskiest assumptions</span><span class="count" v-if="state.risky_assumptions.length">{{ state.risky_assumptions.length }}</span>
      </button>
      <ol v-if="state.risky_assumptions.length" class="risks">
        <li v-for="a in state.risky_assumptions.slice(0, 2)" :key="a.text">
          <span class="impact" :class="`impact--${a.impact}`">{{ a.impact }}</span>
          <span class="risk-text" :title="a.text">{{ a.text }}</span>
          <span v-if="a.test?.method" class="risk-test" :title="a.test.method">Test: {{ a.test.method }}</span>
        </li>
      </ol>
      <p v-else class="muted-line">These appear as the idea takes shape, each with the cheapest test that could prove it wrong.</p>
    </section>

    <!-- 6. Could work / won't -->
    <section class="tile" :class="{ glow: changedAny(['/what_could_work', '/what_wont_work', '/challenges']) }">
      <button type="button" class="tile-head" @click="$emit('open', 'sec-work')">
        <span>Could work · red flags</span><span class="open" aria-hidden="true">↗</span>
      </button>
      <ul class="pairs">
        <li v-for="c in state.what_could_work.slice(0, 2)" :key="'c' + c.text" class="good" :title="c.text">{{ c.text }}</li>
        <li v-for="c in state.what_wont_work.slice(0, 2)" :key="'w' + c.text" class="bad" :class="`sev--${c.severity}`" :title="c.text">{{ c.text }}</li>
      </ul>
      <p v-if="!state.what_could_work.length && !state.what_wont_work.length" class="muted-line">Nothing yet.</p>
    </section>

    <!-- 7. Next up -->
    <section class="tile tile--wide" :class="{ glow: changedAny(['/open_objections']) }">
      <button type="button" class="tile-head" @click="$emit('open', 'sec-next')">
        <span>Next up</span>
        <span v-if="state.open_objections.length" class="concerns">{{ state.open_objections.length }} open
          {{ state.open_objections.length === 1 ? 'concern' : 'concerns' }}</span>
      </button>
      <p class="next" :title="state.open_questions[0]?.question">{{ state.open_questions[0]?.question || 'Describe the idea to begin.' }}</p>
      <button v-if="(state.parked || []).length" type="button" class="parked-pill" @click="$emit('open', 'sec-parked')"
              :title="state.parked.map(p => p.text).join(' · ')">
        Parked {{ state.parked.length }}
        <span v-if="state.parked.some(p => p.priority === 'top')" class="pp-top" aria-label="has top priority items"></span>
      </button>
      <button type="button" class="team-call" @click="$emit('team')" :title="chief ? chief.headline : 'See what your AI team is working on'">
        <template v-if="chief">
          <span class="call" :class="`call--${chief.verdict}`">{{ VERDICTS[chief.verdict] }}</span>
          <span class="call-text">{{ chief.next_actions[0] }}</span>
        </template>
        <span v-else class="call-text">Your AI team</span>
        <span aria-hidden="true">→</span>
      </button>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch, onUnmounted } from 'vue'
import { tweenNumber } from '../motion'

const props = defineProps({
  state: { type: Object, required: true },
  changed: { type: Array, default: () => [] },
  lastChange: { type: Object, default: null },
  updating: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  confidential: { type: Boolean, default: false },
  chief: { type: Object, default: null },
})
defineEmits(['open', 'ask', 'research', 'send-brief', 'team'])
const VERDICTS = { keep_going: 'Keep going', narrow: 'Narrow it', rethink: 'Rethink' }

const SECTIONS = ['Problem', 'Customer', 'Solution', 'Market', 'Business model', 'Risks and tests']
const PROBLEM = [
  { path: '/problem/statement', label: 'Problem', k: ['problem', 'statement'], starter: 'The core problem is ' },
  { path: '/problem/who', label: 'Who', k: ['problem', 'who'], starter: 'The people who have this problem are ' },
  { path: '/problem/workaround', label: 'Today', k: ['problem', 'workaround'], starter: 'Today they get around it by ' },
  { path: '/problem/frequency', label: 'How often', k: ['problem', 'frequency'], starter: 'It happens about ' },
  { path: '/problem/severity', label: 'Cost', k: ['problem', 'severity'], starter: 'The last time it happened, it cost ' },
  { path: '/customer/early_adopters', label: 'First buyers', k: ['customer', 'early_adopters'], starter: 'The first customers I would go after are ' },
]
const SOLUTION = [
  { path: '/solution/core', label: 'Does', k: ['solution', 'core'], starter: 'What the product actually does is ' },
  { path: '/solution/smallest_version', label: 'Smallest', k: ['solution', 'smallest_version'], starter: 'The smallest version I could ship is ' },
  { path: '/business_model/who_pays', label: 'Who pays', k: ['business_model', 'who_pays'], starter: 'The one who pays would be ' },
  { path: '/business_model/price_anchor', label: 'Price', k: ['business_model', 'price_anchor'], starter: 'For price, today they spend ' },
]
const WNB = {
  unknown: 'Not researched', nobody_tried: 'Nobody found', tried_and_failed: 'Tried and failed',
  exists_unknown: 'Little traction', crowded_funded: 'Crowded',
}

const score = computed(() => props.state.clarity?.score ?? 0)
// The big number counts up to its new value instead of jumping
const shownScore = ref(score.value)
let stopTween = () => {}
watch(score, (to, from) => { stopTween(); stopTween = tweenNumber(from ?? 0, to, (n) => { shownScore.value = n }) })
onUnmounted(() => stopTween())
const v = (name) => props.state.clarity?.by_section?.[name] ?? 0
const wnb = computed(() => props.state.why_not_built)
const sourceCount = computed(() => Object.keys(props.state.sources || {}).length)

function claimOf(f) { return props.state[f.k[0]][f.k[1]] }
function filled(list) { return list.filter(f => (claimOf(f).text || '').trim()) }
function empty(list) { return list.filter(f => !(claimOf(f).text || '').trim()) }
function changedAny(prefixes) {
  return props.changed.some(p => prefixes.some(x => p === x || p.startsWith(x + '/')))
}
</script>

<style scoped>
/* Overview that fits one screen: fixed grid, content clamped, details in the drawer */
.dash {
  height: 100%;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: auto minmax(0, 1fr) minmax(0, 1fr) minmax(0, 0.8fr) auto;
  grid-template-areas:
    "hero hero"
    "a b"
    "c d"
    "e e"
    "f f";
  gap: 10px;
}
.tile {
  min-height: 0;
  overflow: hidden;
  border: 1px solid #1f1f1f;
  border-radius: 12px;
  background: #0a0a0a;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.8s ease, background 0.8s ease;
}
/* Tiles settle in one after another on load */
.tile { animation: rise-in var(--dur-3) var(--ease-out) both; }
.tile:nth-of-type(2) { animation-delay: 40ms; } .tile:nth-of-type(3) { animation-delay: 80ms; }
.tile:nth-of-type(4) { animation-delay: 120ms; } .tile:nth-of-type(5) { animation-delay: 160ms; }
.tile:nth-of-type(6) { animation-delay: 200ms; } .tile:nth-of-type(7) { animation-delay: 240ms; }
/* New facts, chips, and names fade in where they land */
.facts dd, .facts dt, .gap, .name, .risks li, .pairs li, .badge, .next { animation: fade-in var(--dur-3) ease both; }
.tile-head .open { transition: transform var(--dur-1) var(--ease-out), color var(--dur-1) ease; }
.tile-head:hover .open { transform: translate(1px, -1px); }
.tile:has(.tile-head:hover) { border-color: #2c2c2c; }
.tile.glow { border-color: rgba(59, 130, 246, 0.5); background: #0b0f17; }
.tile--hero { grid-area: hero; flex-direction: row; gap: 16px; background: linear-gradient(180deg, #0f0f0f, #0a0a0a); }
.tile:nth-of-type(2) { grid-area: a; }
.tile:nth-of-type(3) { grid-area: b; }
.tile:nth-of-type(4) { grid-area: c; }
.tile:nth-of-type(5) { grid-area: d; }
.tile:nth-of-type(6) { grid-area: e; }
.tile--wide { grid-area: f; flex-direction: row; align-items: center; gap: 14px; padding: 10px 14px; }

.tile-head {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: none; border: none; padding: 0; width: 100%; text-align: left;
  font-size: 12px; font-weight: 650; color: var(--text-primary); cursor: pointer;
}
.tile--wide .tile-head { width: auto; flex-shrink: 0; }
.tile-head:hover .open, .tile-head:focus-visible .open { color: #93c5fd; }
.open { font-size: 12px; color: #4a4a4a; }
.count, .concerns { font-size: 11px; font-weight: 600; color: var(--text-tertiary); background: #161616; border-radius: 999px; padding: 1px 8px; }
.concerns { color: #fcd34d; background: rgba(245, 158, 11, 0.1); margin-left: 8px; }

/* Hero */
.hero-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.one-liner {
  font-size: 16px; font-weight: 600; line-height: 1.4; color: var(--text-primary);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.one-liner.muted { color: #5a5a5a; font-weight: 500; font-style: italic; }
.bars { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.bar { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.bar-name { font-size: 10.5px; color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { height: 5px; border-radius: 999px; background: rgba(59, 130, 246, 0.14); overflow: hidden; }
.bar-fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; transition: width 0.6s ease; }
.ticker { font-size: 11.5px; color: var(--text-tertiary); display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 16px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
.pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.25; } }
.hero-side { display: flex; flex-direction: column; align-items: flex-end; justify-content: space-between; gap: 6px; flex-shrink: 0; }
.score { text-align: right; }
.score-num { font-size: 48px; font-weight: 650; line-height: 1; letter-spacing: -0.03em; }
.score-label { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.btn-send { font-size: 12.5px; font-weight: 600; padding: 7px 12px; border-radius: 8px; border: none; background: var(--accent); color: #fff; white-space: nowrap; }
.btn-send:hover:not(:disabled) { background: var(--accent-hover); }
.btn-send:disabled { background: #1a1a1a; color: #555; cursor: not-allowed; }
.unlock { font-size: 10.5px; color: var(--text-tertiary); }

/* Facts: one line each, full text on hover and in the drawer */
.facts {
  display: grid; grid-template-columns: auto minmax(0, 1fr); align-content: start; gap: 5px 10px; margin: 0;
  min-height: 0; flex: 1 1 auto; overflow: hidden; padding-bottom: 12px;
  -webkit-mask-image: linear-gradient(180deg, #000 calc(100% - 12px), transparent);
  mask-image: linear-gradient(180deg, #000 calc(100% - 12px), transparent);
}
.facts dt { font-size: 11px; color: var(--text-tertiary); padding-top: 1px; white-space: nowrap; }
.facts dd { margin: 0; font-size: 12.5px; line-height: 1.35; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.facts dd.st--ai_inference { color: #b5b5b5; font-style: italic; }
.facts dd.st--evidence { color: #bbf7d0; }
.facts dd.st--contradiction { color: #fcd34d; }
.gaps { display: flex; flex-wrap: wrap; gap: 5px; margin-top: auto; flex-shrink: 0; }
.gap {
  font-size: 11px; color: var(--text-tertiary); padding: 2px 8px; border-radius: 999px;
  border: 1px dashed #333; background: transparent; transition: color 0.15s, border-color 0.15s;
}
.gap:hover { color: var(--text-primary); border-color: var(--accent); }

/* Why not built */
.badge { font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; border: 1px solid #333; color: var(--text-secondary); white-space: nowrap; }
.wnb--crowded_funded, .wnb--tried_and_failed { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); }
.wnb--nobody_tried { color: #93c5fd; border-color: rgba(59, 130, 246, 0.4); }
.wnb--exists_unknown { color: #86efac; border-color: rgba(74, 222, 128, 0.35); }
.summary { font-size: 12px; line-height: 1.45; color: var(--text-secondary); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.names { display: flex; flex-wrap: wrap; gap: 5px; }
.name { font-size: 11.5px; color: var(--text-primary); text-decoration: none; padding: 2px 8px; border-radius: 6px; background: #151515; border: 1px solid #262626; }
.name:hover { border-color: #3a3a3a; }
.more { font-size: 11.5px; color: var(--text-tertiary); align-self: center; }
.muted-line { font-size: 12px; line-height: 1.45; color: #5f5f5f; }
.tile-foot { display: flex; align-items: center; gap: 8px; margin-top: auto; }
.mini { font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid #333; background: #141414; color: var(--text-primary); }
.mini:hover:not(:disabled) { border-color: var(--accent); }
.mini:disabled { opacity: 0.45; cursor: not-allowed; }
.foot-note { font-size: 11px; color: var(--text-tertiary); }

/* Risks */
.risks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.risks li { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 8px; }
.impact { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 1px 5px; border-radius: 4px; border: 1px solid #333; color: var(--text-secondary); align-self: start; margin-top: 2px; }
.impact--major { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); }
.impact--fatal { color: #fca5a5; border-color: rgba(248, 113, 113, 0.45); }
.risk-text { font-size: 12.5px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.risk-test { grid-column: 2; font-size: 11.5px; color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Could / won't */
.pairs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; min-height: 0; }
.pairs li { font-size: 12.5px; line-height: 1.35; padding-left: 16px; position: relative; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text-secondary); }
.pairs li::before { position: absolute; left: 0; top: 0; font-weight: 700; }
.pairs li.good::before { content: '+'; color: #86efac; }
.pairs li.bad::before { content: '!'; color: #fcd34d; }
.pairs li.bad.sev--critical::before { color: #fca5a5; }

/* Next up + the team's call */
.parked-pill { flex-shrink: 0; display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 600;
  color: #fcd34d; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 999px; padding: 3px 10px;
  animation: pop-in var(--dur-2) var(--ease-out) both; }
.parked-pill:hover { border-color: rgba(245, 158, 11, 0.6); }
.pp-top { width: 6px; height: 6px; border-radius: 50%; background: #fcd34d; }
.team-call { margin-left: 8px; flex-shrink: 1; min-width: 0; max-width: 48%; display: inline-flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-secondary); background: #111; border: 1px solid #262626; border-radius: 999px; padding: 4px 6px 4px 6px; }
.team-call:hover { border-color: #3a3a3a; color: var(--text-primary); }
.team-call > span:last-child { padding-right: 6px; color: var(--text-tertiary); }
.call { font-size: 10.5px; font-weight: 650; padding: 2px 8px; border-radius: 999px; white-space: nowrap; animation: pop-in var(--dur-2) var(--ease-out) both; }
.call--keep_going { color: #86efac; background: rgba(74, 222, 128, 0.1); }
.call--narrow { color: #fcd34d; background: rgba(245, 158, 11, 0.1); }
.call--rethink { color: #fca5a5; background: rgba(248, 113, 113, 0.1); }
.call-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; padding-left: 4px; }
.next { flex: 1; font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }

@media (max-width: 900px) {
  .dash { height: auto; grid-template-columns: 1fr; grid-template-rows: none;
          grid-template-areas: "hero" "a" "b" "c" "d" "e" "f"; }
  .tile--hero { flex-direction: column; }
  .hero-side { flex-direction: row; align-items: center; width: 100%; }
  .bars { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
/* Short windows: never clip or overlap; let the overview scroll instead */
@media (max-height: 780px) and (min-width: 901px) {
  .dash { height: auto !important; grid-template-rows: none; grid-auto-rows: auto; align-content: start; }
  .tile { overflow: visible; min-height: auto; }
  .tile > *, .hero-main > * { flex-shrink: 0; }
  .facts, .pairs, .risks { overflow: visible; -webkit-mask-image: none; mask-image: none; padding-bottom: 0; }
}
@media (prefers-reduced-motion: reduce) { .tile, .bar-fill { transition: none; } .pulse { animation: none; } }
</style>
