<template>
  <div class="trace" :class="{ live, collapsed: !expanded }" :aria-label="summary" role="group">
    <!-- Collapsed: a quiet summary pill once everything is done -->
    <button v-if="!live" type="button" class="pill" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="faces" aria-hidden="true">
        <span v-for="s in steps" :key="s.id" class="face" :style="{ '--c': meta(s.id).color }"></span>
      </span>
      <span class="pill-text">{{ summary }}</span>
      <svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
    </button>

    <!-- Expanded: one row per agent -->
    <transition name="unfold">
      <ol v-if="live || expanded" class="rows">
        <li v-for="(s, i) in steps" :key="s.id" class="row" :class="`row--${s.status}`" :style="{ '--c': meta(s.id).color, '--i': i }">
          <span class="node" aria-hidden="true">
            <svg v-if="s.status === 'done'" class="tick" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" /></svg>
            <svg v-else viewBox="0 0 16 16"><path :d="meta(s.id).icon" /></svg>
          </span>
          <span class="who">{{ meta(s.id).name }}</span>
          <span class="what" :class="{ shimmer: s.status === 'running' }">{{ s.detail || meta(s.id).doing }}</span>
          <span v-if="s.id === 'team' && s.status === 'running' && s.faces?.length" class="team-faces" aria-hidden="true">
            <span v-for="(c, j) in s.faces" :key="j" class="tf" :class="{ on: c.on }" :style="{ '--c': c.color, '--j': j }"></span>
          </span>
          <span class="time">{{ elapsed(s) }}</span>
          <span v-if="i < steps.length - 1" class="rail" aria-hidden="true"></span>
        </li>
      </ol>
    </transition>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },    // [{id, status: queued|running|done|failed, detail, t0, t1, faces?}]
  live: { type: Boolean, default: false },
})

const META = {
  read: { name: 'Reader', doing: 'Reading your message', color: '#818cf8',
    icon: 'M2.5 8s2-4 5.5-4 5.5 4 5.5 4-2 4-5.5 4S2.5 8 2.5 8zM8 6.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z' },
  research: { name: 'Researcher', doing: 'Searching the web, companies, Hacker News, GitHub', color: '#2dd4bf',
    icon: 'M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5' },
  cofounder: { name: 'Co-founder', doing: 'Thinking', color: '#60a5fa', icon: 'M3 4.5h10v6H7l-3 2.5v-2.5H3z' },
  analyst: { name: 'Analyst', doing: 'Updating the live idea', color: '#a3a3a3', icon: 'M4 2.5h6l2.5 2.5v8.5H4zM6.5 7.5h4M6.5 10h4' },
  team: { name: 'Team', doing: 'Specialists working', color: '#e5e5e5',
    icon: 'M5.5 7a2 2 0 100-4 2 2 0 000 4zM10.5 7a2 2 0 100-4 2 2 0 000 4zM2 13c.5-2.5 2-3.5 3.5-3.5S8.5 10.5 9 13M7 13c.5-2.5 2-3.5 3.5-3.5S13.5 10.5 14 13' },
}
const meta = (id) => META[id] || META.cofounder

const expanded = ref(false)
const now = ref(Date.now())
let timer = null
watch(() => props.steps.some(s => s.status === 'running'), (running) => {
  clearInterval(timer)
  if (running) timer = setInterval(() => { now.value = Date.now() }, 100)
}, { immediate: true })
onUnmounted(() => clearInterval(timer))

function secs(ms) { return ms < 10000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms / 1000) + 's' }
function elapsed(s) {
  if (!s.t0) return ''
  if (s.status === 'queued') return ''
  return secs(Math.max(0, (s.t1 || now.value) - s.t0))
}
const total = computed(() => {
  const t0 = Math.min(...props.steps.map(s => s.t0 || Infinity))
  const t1 = Math.max(...props.steps.map(s => s.t1 || 0))
  return isFinite(t0) && t1 > t0 ? secs(t1 - t0) : ''
})
const summary = computed(() => {
  const n = props.steps.length
  const failed = props.steps.filter(s => s.status === 'failed').length
  return `${n} ${n === 1 ? 'agent' : 'agents'} worked on this${total.value ? ' · ' + total.value : ''}${failed ? ` · ${failed} could not finish` : ''}`
})
</script>

<style scoped>
@property --a { syntax: '<angle>'; inherits: false; initial-value: 0deg; }

.trace { margin-bottom: 10px; }

/* Summary pill */
.pill { display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px 4px 7px; border-radius: 999px;
  border: 1px solid #1f1f1f; background: #0a0a0a; color: var(--text-tertiary); font-size: 11.5px;
  animation: fade-in var(--dur-3) ease both; }
.pill:hover { color: var(--text-secondary); border-color: #2e2e2e; }
.faces { display: inline-flex; }
.face { width: 8px; height: 8px; border-radius: 50%; background: var(--c); border: 1.5px solid #0a0a0a; margin-left: -3px; opacity: 0.8; }
.face:first-child { margin-left: 0; }
.chev { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round;
  transition: transform var(--dur-2) var(--ease-out); }
.pill[aria-expanded="true"] .chev { transform: rotate(180deg); }
.collapsed:not(.live) .pill + .rows { margin-top: 8px; }

/* Rows */
.rows { list-style: none; margin: 0; padding: 10px 12px; display: flex; flex-direction: column; gap: 0;
  border: 1px solid #1a1a1a; border-radius: 12px; background: linear-gradient(180deg, #0c0c0c, #080808); }
.trace:not(.live) .rows { margin-top: 8px; }
.row { position: relative; display: grid; grid-template-columns: 22px auto minmax(0, 1fr) auto auto; align-items: center;
  column-gap: 10px; min-height: 30px; font-size: 12.5px; animation: rise-in var(--dur-2) var(--ease-out) both; }

/* The agent node: an orbiting light while it works, a check when done */
.node { position: relative; width: 22px; height: 22px; border-radius: 7px; display: grid; place-items: center; isolation: isolate;
  background: color-mix(in srgb, var(--c) 12%, #0b0b0b); border: 1px solid color-mix(in srgb, var(--c) 30%, transparent);
  transition: background var(--dur-2) ease, border-color var(--dur-2) ease; z-index: 1; }
.node svg { width: 12px; height: 12px; fill: none; stroke: var(--c); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.row--running .node { border-color: transparent; }
.row--running .node::before { content: ''; position: absolute; inset: -1px; border-radius: 8px; padding: 1px; z-index: -1;
  background: conic-gradient(from var(--a), transparent 0 55%, var(--c) 80%, transparent 100%) border-box;
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude;
  animation: orbit 1.4s linear infinite; }
.row--running .node::after { content: ''; position: absolute; inset: -4px; border-radius: 10px; border: 1px solid var(--c);
  opacity: 0; animation: breathe 1.6s ease-out infinite; }
@keyframes orbit { to { --a: 360deg; } }
@keyframes breathe { 0% { opacity: 0.55; transform: scale(0.9); } 100% { opacity: 0; transform: scale(1.3); } }
.row--done .node { background: color-mix(in srgb, var(--c) 18%, #0b0b0b); }
.tick { stroke-dasharray: 16; stroke-dashoffset: 16; animation: draw 360ms var(--ease-out) forwards; }
@keyframes draw { to { stroke-dashoffset: 0; } }
.row--queued { opacity: 0.45; }
.row--failed .node { border-color: rgba(248, 113, 113, 0.5); }

.who { font-weight: 650; color: var(--text-primary); white-space: nowrap; }
.what { color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.row--done .what { color: var(--text-tertiary); }
.row--failed .what { color: #fca5a5; }
/* Working text: a light sweeps across the words */
.shimmer { background: linear-gradient(90deg, #6b6b6b 0%, #6b6b6b 35%, #f5f5f5 50%, #6b6b6b 65%, #6b6b6b 100%);
  background-size: 250% 100%; -webkit-background-clip: text; background-clip: text; color: transparent;
  animation: sweep 1.8s linear infinite; }
.shimmer::after { content: '…'; }
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -150% 0; } }
.time { font-size: 11px; color: #555; font-variant-numeric: tabular-nums; min-width: 34px; text-align: right; }
.row--running .time { color: var(--text-tertiary); }

/* Rail connecting the nodes */
.rail { position: absolute; left: 10.5px; top: 25px; height: 10px; width: 1px; background: #262626; }
.row--done .rail { background: color-mix(in srgb, var(--c) 40%, #262626); }

/* Team: the specialists as dots that light up as each one reports */
.team-faces { display: inline-flex; gap: 3px; }
.tf { width: 6px; height: 6px; border-radius: 50%; background: var(--c); opacity: 0.25; animation: bob 1s ease-in-out infinite;
  animation-delay: calc(var(--j) * 0.12s); transition: opacity var(--dur-2) ease; }
.tf.on { opacity: 1; animation: none; }
@keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }

.unfold-enter-active { transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out); }
.unfold-leave-active { transition: opacity var(--dur-1) ease; }
.unfold-enter-from { opacity: 0; transform: translateY(-4px); }
.unfold-leave-to { opacity: 0; }

@media (max-width: 520px) { .what { white-space: normal; } .row { grid-template-columns: 22px auto minmax(0, 1fr) auto; } .team-faces { display: none; } }
</style>
