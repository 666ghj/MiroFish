<template>
  <div class="detail" :style="{ '--c': agent.color }">
    <header class="d-head">
      <span class="avatar" aria-hidden="true"><svg viewBox="0 0 16 16"><path :d="agent.icon" /></svg></span>
      <div class="d-id">
        <h2>{{ agent.name }}</h2>
        <p>{{ agent.role }}</p>
      </div>
      <button v-if="agent.kind === 'specialist'" type="button" class="rerun" :disabled="running || !!missing.length" @click="$emit('rerun', id)">
        {{ running ? 'Working...' : 'Run again' }}
      </button>
    </header>

    <p v-if="missing.length" class="note">Waiting for {{ missing.join(', ') }}. Tell your co-founder about it in the chat.</p>
    <p v-if="entry?.source === 'sample'" class="note note--warn">Sample output: MOCK_MODE is on, so this is not about your idea.</p>

    <!-- Conversation agents point at the parts of the idea they maintain -->
    <template v-if="agent.kind === 'conversation'">
      <p class="lead">{{ CONV_COPY[id] }}</p>
      <button type="button" class="jump" @click="$emit('section', CONV_SECTION[id])">{{ CONV_JUMP[id] }} →</button>
    </template>

    <template v-else-if="!out">
      <div v-if="running" class="skeleton"><i></i><i></i><i></i></div>
      <p v-else-if="!missing.length" class="lead muted">No report yet. It runs automatically after your next message, or press Run again.</p>
    </template>

    <template v-else>
      <p class="lead">{{ out.headline }}</p>

      <!-- Skeptic -->
      <ol v-if="id === 'skeptic'" class="list">
        <li v-for="(r, i) in out.risks" :key="i" :style="{ '--i': i }">
          <div class="row"><span class="sev" :class="`sev--${r.severity}`">{{ r.severity }}</span><strong>{{ r.title }}</strong></div>
          <p>{{ r.why }}</p>
          <p class="sub"><span>Defuse it with</span> {{ r.answer_with }}</p>
        </li>
      </ol>

      <!-- Customer panel -->
      <template v-else-if="id === 'customers'">
        <p class="label-note">Synthetic buyers role-played by AI from your target customer. Useful for objections, not as proof of demand.</p>
        <div class="quotes">
          <figure v-for="(p, i) in out.panel" :key="i" class="quote" :style="{ '--i': i }">
            <figcaption><span class="try" :class="`try--${p.would_try}`">{{ TRY[p.would_try] }}</span>{{ p.persona }}</figcaption>
            <blockquote>"{{ p.reaction }}"</blockquote>
            <p class="sub"><span>Objection</span> {{ p.objection }}</p>
            <p class="sub"><span>Would pay if</span> {{ p.would_pay_if }}</p>
          </figure>
        </div>
      </template>

      <!-- Market sizer -->
      <template v-else-if="id === 'market'">
        <div class="equation" aria-label="Market estimate">
          <div><span class="num">{{ out.count.toLocaleString() }}</span><span class="cap">{{ out.unit }}</span></div>
          <span class="op">×</span>
          <div><span class="num">{{ money(out.price_per_year) }}</span><span class="cap">per year each</span></div>
          <span class="op">=</span>
          <div class="total"><span class="num">≈ {{ money(out.estimate) }}</span><span class="cap">a year · {{ out.confidence }} confidence</span></div>
        </div>
        <dl class="kv">
          <dt>Count basis</dt><dd>{{ out.count_basis }}</dd>
          <dt>Price basis</dt><dd>{{ out.price_basis }}</dd>
          <dt>If it works</dt><dd>{{ out.bigger_market }}</dd>
        </dl>
        <h3>Assumptions to check</h3>
        <ul class="bullets"><li v-for="(a, i) in out.assumptions" :key="i">{{ a }}</li></ul>
        <p class="label-note">A rough model estimate, multiplied in code. Check the count and price yourself before quoting it.</p>
      </template>

      <!-- Pitch writer -->
      <template v-else-if="id === 'pitch'">
        <h3>One-liners</h3>
        <ul class="lines">
          <li v-for="(l, i) in out.one_liners" :key="i" :style="{ '--i': i }">
            <span>{{ l }}</span>
            <button type="button" class="copy" @click="copy(l, i)">{{ copied === i ? 'Copied' : 'Copy' }}</button>
          </li>
        </ul>
        <h3>30-second pitch</h3>
        <p class="block">{{ out.elevator }}</p>
        <p class="sub"><span>Stop saying</span> "{{ out.avoid }}"</p>
      </template>

      <!-- GTM strategist -->
      <template v-else-if="id === 'gtm'">
        <dl class="kv">
          <dt>Channel</dt><dd><strong>{{ out.channel }}</strong>. {{ out.why_channel }}</dd>
          <dt>Hook</dt><dd>{{ out.message_angle }}</dd>
        </dl>
        <h3>First 10 customers</h3>
        <ol class="steps"><li v-for="(s, i) in out.first_10" :key="i">{{ s }}</li></ol>
        <h3>This week</h3>
        <ul class="checks"><li v-for="(s, i) in out.week_one" :key="i">{{ s }}</li></ul>
      </template>

      <!-- Experiment designer -->
      <ol v-else-if="id === 'experiments'" class="list">
        <li v-for="(t, i) in out.tests" :key="i" :style="{ '--i': i }">
          <div class="row"><strong>{{ t.assumption }}</strong></div>
          <p>{{ t.method }}</p>
          <div class="chips"><span>{{ t.cost || '$0' }}</span><span>{{ t.days }} {{ t.days === 1 ? 'day' : 'days' }}</span></div>
          <p class="sub"><span>Passes if</span> {{ t.pass_if }}</p>
        </li>
      </ol>

      <!-- Chief of staff -->
      <template v-else-if="id === 'chief'">
        <span class="verdict" :class="`tone--${VERDICT[out.verdict].tone}`">{{ VERDICT[out.verdict].label }}</span>
        <p class="block">{{ out.why }}</p>
        <h3>Next moves</h3>
        <ol class="steps"><li v-for="(a, i) in out.next_actions" :key="i">{{ a }}</li></ol>
        <template v-if="out.disagreement">
          <h3>Where the team disagrees</h3>
          <p class="block">{{ out.disagreement }}</p>
        </template>
        <h3>Read the team</h3>
        <div class="team-links">
          <button v-for="u in USES" :key="u" type="button" class="team-link" :style="{ '--c': BY_ID[u].color }" @click="$emit('switch', u)">
            <span class="dot"></span>{{ BY_ID[u].name }}
          </button>
        </div>
      </template>

      <p class="meta">Updated on turn {{ entry.turn ?? '?' }}. Re-runs on its own when the parts of the idea it reads change.</p>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { BY_ID, VERDICT, money } from '../utils/agents'

const props = defineProps({
  id: { type: String, required: true },
  team: { type: Object, default: () => ({}) },
  live: { type: Object, default: () => ({}) },
})
defineEmits(['rerun', 'section', 'switch'])

const TRY = { yes: 'Would try', maybe: 'Maybe', no: 'Would not' }
const USES = ['skeptic', 'customers', 'market', 'pitch', 'gtm', 'experiments']
const CONV_COPY = {
  cofounder: 'Talks the idea through with you. It asks one question at a time, picked by code from what is still missing, and pushes back when a claim has no evidence. It guides; it does not hand you an idea.',
  analyst: 'After every reply it writes what you said into the live idea: your words stay yours, its guesses are marked as guesses, and locked fields are never changed.',
  researcher: 'Searches the web, company databases, Hacker News, and GitHub for who already does this and who tried before. Only short category phrases are sent, never your description. Off in Confidential mode.',
}
const CONV_SECTION = { cofounder: 'sec-next', analyst: 'sec-idea', researcher: 'sec-wnb' }
const CONV_JUMP = { cofounder: 'See questions coming up', analyst: 'See the live idea', researcher: 'See what it found' }

const agent = computed(() => BY_ID[props.id])
const entry = computed(() => props.team[props.id] || null)
const out = computed(() => entry.value?.output || null)
const running = computed(() => ['running', 'queued'].includes(props.live[props.id]?.status))
const missing = computed(() => props.live[props.id]?.status === 'waiting' ? (props.live[props.id].missing || []) : [])

const copied = ref(-1)
async function copy(text, i) {
  try { await navigator.clipboard.writeText(text); copied.value = i; setTimeout(() => { copied.value = -1 }, 1200) } catch (_) {}
}
</script>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 12px; animation: rise-in var(--dur-2) var(--ease-out) both; }
.d-head { display: flex; align-items: center; gap: 12px; }
.avatar { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; flex-shrink: 0;
  background: color-mix(in srgb, var(--c) 14%, transparent); border: 1px solid color-mix(in srgb, var(--c) 35%, transparent); }
.avatar svg { width: 18px; height: 18px; fill: none; stroke: var(--c); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.d-id { flex: 1; min-width: 0; }
.d-id h2 { font-size: 16px; font-weight: 650; }
.d-id p { font-size: 12px; color: var(--text-tertiary); margin-top: 2px; }
.rerun { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid #2a2a2a; background: #111; color: var(--text-primary); }
.rerun:hover:not(:disabled) { border-color: var(--c); }
.rerun:disabled { opacity: 0.5; cursor: default; }

.lead { font-size: 15px; font-weight: 600; line-height: 1.45; color: var(--text-primary); }
.lead.muted { font-size: 13px; font-weight: 400; color: var(--text-tertiary); }
.note { font-size: 12px; color: var(--text-secondary); padding: 8px 10px; border-radius: 8px; background: #111; border: 1px solid #222; }
.note--warn { color: #fcd34d; border-color: rgba(245, 158, 11, 0.3); }
.label-note { font-size: 11.5px; color: var(--text-tertiary); line-height: 1.5; }
h3 { font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-tertiary); margin-top: 6px; }
.block { font-size: 13px; line-height: 1.6; color: var(--text-secondary); }
.meta { font-size: 11px; color: #555; margin-top: 8px; }
.jump { align-self: flex-start; font-size: 12.5px; font-weight: 600; color: #93c5fd; background: none; border: none; padding: 0; }
.jump:hover { color: #bfdbfe; }

.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.list li, .quote { padding: 12px; border-radius: 10px; border: 1px solid #1f1f1f; background: #0a0a0a;
  display: flex; flex-direction: column; gap: 6px; animation: rise-in var(--dur-3) var(--ease-out) both; animation-delay: calc(var(--i, 0) * 60ms); }
.list p, .quote p { font-size: 12.5px; line-height: 1.5; color: var(--text-secondary); margin: 0; }
.row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.sub { font-size: 12px !important; }
.sub span { color: var(--text-tertiary); margin-right: 4px; }
.sev { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 1px 6px; border-radius: 4px; border: 1px solid #333; color: var(--text-secondary); }
.sev--major { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); }
.sev--fatal { color: #fca5a5; border-color: rgba(248, 113, 113, 0.45); }

.quotes { display: flex; flex-direction: column; gap: 10px; margin: 0; }
.quote { margin: 0; }
figcaption { font-size: 12px; color: var(--text-tertiary); display: flex; align-items: center; gap: 8px; }
blockquote { margin: 0; font-size: 14px; line-height: 1.5; color: var(--text-primary); font-style: italic; }
.try { font-size: 10.5px; font-weight: 650; padding: 1px 8px; border-radius: 999px; border: 1px solid #333; font-style: normal; }
.try--yes { color: #86efac; border-color: rgba(74, 222, 128, 0.4); }
.try--maybe { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); }
.try--no { color: #fca5a5; border-color: rgba(248, 113, 113, 0.45); }

.equation { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 14px; border-radius: 12px; border: 1px solid #1f1f1f; background: #0a0a0a; }
.equation > div { display: flex; flex-direction: column; gap: 2px; animation: rise-in var(--dur-3) var(--ease-out) both; }
.equation > div:nth-of-type(2) { animation-delay: 80ms; }
.equation > div:nth-of-type(3) { animation-delay: 160ms; }
.num { font-size: 20px; font-weight: 650; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.total .num { color: #bbf7d0; font-size: 24px; }
.cap { font-size: 11px; color: var(--text-tertiary); }
.op { color: #555; font-size: 16px; }

.kv { display: grid; grid-template-columns: auto 1fr; gap: 8px 14px; margin: 0; font-size: 12.5px; line-height: 1.5; }
.kv dt { color: var(--text-tertiary); }
.kv dd { margin: 0; color: var(--text-secondary); }
.kv strong { color: var(--text-primary); }
.bullets, .steps, .checks { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; line-height: 1.5; color: var(--text-secondary); }
.checks { list-style: none; padding-left: 0; }
.checks li::before { content: ''; display: inline-block; width: 11px; height: 11px; border: 1.5px solid #444; border-radius: 3px; margin-right: 8px; vertical-align: -1px; }

.lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.lines li { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 9px; border: 1px solid #1f1f1f; background: #0a0a0a;
  font-size: 13.5px; color: var(--text-primary); animation: rise-in var(--dur-3) var(--ease-out) both; animation-delay: calc(var(--i, 0) * 60ms); }
.lines li span { flex: 1; }
.copy { font-size: 11px; padding: 3px 8px; border-radius: 6px; border: 1px solid #2a2a2a; background: transparent; color: var(--text-tertiary); }
.copy:hover { color: var(--text-primary); border-color: #444; }
.chips { display: flex; gap: 6px; }
.chips span { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: #151515; border: 1px solid #262626; color: var(--text-secondary); }

.verdict { align-self: flex-start; font-size: 12px; font-weight: 650; padding: 3px 11px; border-radius: 999px; border: 1px solid; animation: pop-in var(--dur-2) var(--ease-out) both; }
.tone--good { color: #86efac; border-color: rgba(74, 222, 128, 0.4); background: rgba(74, 222, 128, 0.08); }
.tone--warn { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.08); }
.tone--bad { color: #fca5a5; border-color: rgba(248, 113, 113, 0.45); background: rgba(248, 113, 113, 0.08); }
.team-links { display: flex; flex-wrap: wrap; gap: 6px; }
.team-link { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid #262626; background: #0d0d0d; color: var(--text-secondary); }
.team-link:hover { color: var(--text-primary); border-color: var(--c); }
.team-link .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--c); }

.skeleton { display: flex; flex-direction: column; gap: 8px; }
.skeleton i { display: block; height: 11px; border-radius: 5px; background: linear-gradient(90deg, #151515, #222, #151515); background-size: 200% 100%; animation: shimmer 1.3s ease-in-out infinite; }
.skeleton i:nth-child(2) { width: 80%; } .skeleton i:nth-child(3) { width: 55%; }
@keyframes shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }
</style>
