<template>
  <div class="activity">
    <button type="button" class="line" :aria-expanded="open" :disabled="live" @click="open = !open">
      <!-- One mark: the working agent's color, breathing while it works -->
      <span class="mark" :class="{ on: live }" :style="{ '--c': live && current ? meta(current.id).color : '#525252' }" aria-hidden="true"></span>

      <transition name="swap" mode="out-in">
        <span v-if="live && current" :key="current.id + current.detail" class="text">
          <b>{{ meta(current.id).name }}</b>
          <span class="doing">{{ current.detail || meta(current.id).doing }}</span>
        </span>
        <span v-else key="done" class="text text--done">{{ doneLine }}</span>
      </transition>

      <!-- Progress: one short segment per agent, filled in its color when done -->
      <span class="segs" aria-hidden="true">
        <span v-for="s in steps" :key="s.id" class="seg" :class="`seg--${s.status}`" :style="{ '--c': meta(s.id).color }"></span>
      </span>
      <span class="clock">{{ live && current?.t0 ? elapsed(current) : total }}</span>
      <svg v-if="!live" class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
    </button>

    <transition name="unfold">
      <ol v-if="open && !live" class="steps">
        <li v-for="s in steps" :key="s.id" :class="`st--${s.status}`" :style="{ '--c': meta(s.id).color }">
          <span class="dot" aria-hidden="true"></span>
          <span class="name">{{ meta(s.id).name }}</span>
          <span class="detail">{{ s.detail || meta(s.id).doing }}</span>
          <span class="t">{{ elapsed(s) }}</span>
        </li>
      </ol>
    </transition>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },     // [{id, status: queued|running|done|failed, detail, t0, t1}]
})

const META = {
  read: { name: 'Reader', doing: 'reading your message', color: '#a5b4fc' },
  research: { name: 'Researcher', doing: 'searching', color: '#5eead4' },
  cofounder: { name: 'Co-founder', doing: 'thinking', color: '#93c5fd' },
  analyst: { name: 'Analyst', doing: 'updating the live idea', color: '#d4d4d4' },
  team: { name: 'Team', doing: 'specialists working', color: '#fcd34d' },
}
const meta = (id) => META[id] || META.cofounder

const open = ref(false)
const live = computed(() => props.steps.some(s => s.status === 'running' || s.status === 'queued'))
const current = computed(() => [...props.steps].reverse().find(s => s.status === 'running') || props.steps.find(s => s.status === 'queued'))

const now = ref(Date.now())
let timer = null
watch(live, (on) => { clearInterval(timer); if (on) timer = setInterval(() => { now.value = Date.now() }, 200) }, { immediate: true })
onUnmounted(() => clearInterval(timer))

const secs = (ms) => (ms < 10000 ? (ms / 1000).toFixed(1) : Math.round(ms / 1000)) + 's'
function elapsed(s) { return s.t0 && s.status !== 'queued' ? secs(Math.max(0, (s.t1 || now.value) - s.t0)) : '' }
const total = computed(() => {
  const t0 = Math.min(...props.steps.map(s => s.t0 || Infinity))
  const t1 = Math.max(...props.steps.map(s => s.t1 || 0))
  return isFinite(t0) && t1 > t0 ? secs(t1 - t0) : ''
})
const doneLine = computed(() => {
  const n = props.steps.length
  const team = props.steps.find(s => s.id === 'team' && s.status === 'done')?.detail
  return team ? `${n} agents worked on this. ${team.charAt(0).toUpperCase() + team.slice(1)}` : `${n} agents worked on this`
})
</script>

<style scoped>
.activity { margin-bottom: 10px; min-width: 0; }
/* A full-width row: everything inside truncates instead of leaking */
.line { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; min-height: 24px; padding: 0; background: none;
  border: none; color: var(--text-tertiary); font-size: 12.5px; text-align: left; }
.line:not(:disabled):hover { color: var(--text-secondary); }
.line:disabled { cursor: default; }

.mark { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: var(--c); transition: background var(--dur-2) ease; }
.mark.on { box-shadow: 0 0 0 0 var(--c); animation: breathe 1.4s ease-out infinite; }
@keyframes breathe { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 55%, transparent); } 100% { box-shadow: 0 0 0 6px transparent; } }

.text { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 6px; white-space: nowrap; overflow: hidden; }
.text b { font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
.doing { min-width: 0; overflow: hidden; text-overflow: ellipsis; color: transparent;
  background: linear-gradient(90deg, #737373 0%, #737373 40%, #e5e5e5 50%, #737373 60%, #737373 100%);
  background-size: 300% 100%; -webkit-background-clip: text; background-clip: text; animation: sweep 2s linear infinite; }
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -200% 0; } }
.text--done { display: block; overflow: hidden; text-overflow: ellipsis; }

.segs { display: flex; gap: 3px; flex-shrink: 0; }
.seg { width: 12px; height: 3px; border-radius: 2px; background: #262626; transition: background var(--dur-3) ease; }
.seg--running { background: linear-gradient(90deg, #262626, var(--c), #262626); background-size: 200% 100%; animation: run 1s linear infinite; }
.seg--done { background: var(--c); opacity: 0.8; }
.seg--failed { background: #f87171; }
@keyframes run { from { background-position: 100% 0; } to { background-position: -100% 0; } }
.clock { font-size: 11px; color: #555; font-variant-numeric: tabular-nums; flex-shrink: 0; min-width: 30px; text-align: right; }
.chev { width: 12px; height: 12px; flex-shrink: 0; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
  transition: transform var(--dur-2) var(--ease-out); }
.line[aria-expanded="true"] .chev { transform: rotate(180deg); }

.steps { list-style: none; margin: 8px 0 2px 15px; padding: 0; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.steps li { display: grid; grid-template-columns: 6px auto minmax(0, 1fr) auto; align-items: baseline; gap: 10px; font-size: 12px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--c); align-self: center; }
.st--failed .dot { background: #f87171; }
.name { color: var(--text-primary); font-weight: 600; white-space: nowrap; }
.detail { color: var(--text-tertiary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.t { color: #555; font-size: 11px; font-variant-numeric: tabular-nums; }

.swap-enter-active { transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out); }
.swap-leave-active { transition: opacity var(--dur-1) ease; }
.swap-enter-from { opacity: 0; transform: translateY(3px); }
.swap-leave-to { opacity: 0; }
.unfold-enter-active { transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out); }
.unfold-enter-from { opacity: 0; transform: translateY(-3px); }
</style>
