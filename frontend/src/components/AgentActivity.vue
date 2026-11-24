<template>
  <div class="activity" :class="{ live }">
    <button type="button" class="line" :aria-expanded="open" :disabled="live" @click="open = !open">
      <span class="faces" aria-hidden="true">
        <span v-for="s in steps" :key="s.id" class="face" :class="[`face--${s.status}`, { current: live && s.id === current?.id }]"
              :style="{ '--c': meta(s.id).color }">
          <svg viewBox="0 0 16 16"><path :d="meta(s.id).icon" /></svg>
        </span>
      </span>
      <transition name="swap" mode="out-in">
        <span v-if="live && current" :key="current.id + current.detail" class="text">
          <b>{{ meta(current.id).name }}</b>
          <span class="doing">{{ current.detail || meta(current.id).doing }}</span>
        </span>
        <span v-else key="done" class="text text--done">
          {{ names }}<span v-if="total" class="sep">·</span>{{ total }}
          <span v-if="teamLine" class="sep">·</span><span v-if="teamLine" class="team-line">{{ teamLine }}</span>
        </span>
      </transition>
      <span v-if="live && current?.t0" class="clock">{{ elapsed(current) }}</span>
      <svg v-if="!live" class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
    </button>

    <transition name="unfold">
      <ol v-if="open && !live" class="steps">
        <li v-for="s in steps" :key="s.id" :style="{ '--c': meta(s.id).color }" :class="`st--${s.status}`">
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
  read: { name: 'Reader', doing: 'reading your message', color: '#a5b4fc',
    icon: 'M2.5 8s2-4 5.5-4 5.5 4 5.5 4-2 4-5.5 4S2.5 8 2.5 8zM8 6.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z' },
  research: { name: 'Researcher', doing: 'searching', color: '#5eead4', icon: 'M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5' },
  cofounder: { name: 'Co-founder', doing: 'thinking', color: '#93c5fd', icon: 'M3 4.5h10v6H7l-3 2.5v-2.5H3z' },
  analyst: { name: 'Analyst', doing: 'updating the live idea', color: '#d4d4d4', icon: 'M4 2.5h6l2.5 2.5v8.5H4zM6.5 7.5h4M6.5 10h4' },
  team: { name: 'Team', doing: 'specialists working', color: '#fcd34d',
    icon: 'M5.5 7a2 2 0 100-4 2 2 0 000 4zM10.5 7a2 2 0 100-4 2 2 0 000 4zM2 13c.5-2.5 2-3.5 3.5-3.5S8.5 10.5 9 13M7 13c.5-2.5 2-3.5 3.5-3.5S13.5 10.5 14 13' },
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
const names = computed(() => props.steps.filter(s => s.id !== 'team').map(s => meta(s.id).name).join(', '))
const teamLine = computed(() => props.steps.find(s => s.id === 'team' && s.status === 'done')?.detail || '')
</script>

<style scoped>
.activity { margin-bottom: 8px; }
.line { display: inline-flex; align-items: center; gap: 10px; max-width: 100%; min-height: 28px; padding: 0; background: none;
  border: none; color: var(--text-tertiary); font-size: 12.5px; text-align: left; }
.line:not(:disabled):hover { color: var(--text-secondary); }
.line:disabled { cursor: default; }

/* Faces: one per agent; the working one is lit with a soft pulse */
.faces { display: inline-flex; flex-shrink: 0; }
.face { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; margin-left: -6px;
  background: #0d0d0d; border: 1.5px solid #000; box-shadow: 0 0 0 1px #262626;
  transition: transform var(--dur-2) var(--ease-out), box-shadow var(--dur-2) ease, opacity var(--dur-2) ease;
  animation: pop-in var(--dur-2) var(--ease-out) both; }
.face:first-child { margin-left: 0; }
.face svg { width: 11px; height: 11px; fill: none; stroke: var(--c); stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.face--queued { opacity: 0.35; }
.face--done { background: color-mix(in srgb, var(--c) 16%, #0b0b0b); }
.face--failed { box-shadow: 0 0 0 1px rgba(248, 113, 113, 0.6); }
.face.current { transform: scale(1.18); z-index: 1; box-shadow: 0 0 0 1px var(--c); animation: pulse 1.5s ease-out infinite; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 1px var(--c), 0 0 0 0 color-mix(in srgb, var(--c) 45%, transparent); }
  100% { box-shadow: 0 0 0 1px var(--c), 0 0 0 7px transparent; }
}

.text { display: inline-flex; align-items: baseline; gap: 6px; min-width: 0; white-space: nowrap; overflow: hidden; }
.text b { font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
.doing { overflow: hidden; text-overflow: ellipsis; color: transparent; min-width: 0;
  background: linear-gradient(90deg, #737373 0%, #737373 40%, #e5e5e5 50%, #737373 60%, #737373 100%);
  background-size: 300% 100%; -webkit-background-clip: text; background-clip: text; animation: sweep 2s linear infinite; }
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -200% 0; } }
.text--done { overflow: hidden; text-overflow: ellipsis; display: inline-block; }
.sep { margin: 0 6px; color: #3a3a3a; }
.team-line { color: var(--text-secondary); }
.clock { font-size: 11px; color: #555; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.chev { width: 12px; height: 12px; flex-shrink: 0; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
  transition: transform var(--dur-2) var(--ease-out); }
.line[aria-expanded="true"] .chev { transform: rotate(180deg); }

.steps { list-style: none; margin: 6px 0 4px; padding: 0 0 0 4px; display: flex; flex-direction: column; gap: 6px; }
.steps li { display: grid; grid-template-columns: 8px auto minmax(0, 1fr) auto; align-items: baseline; gap: 10px; font-size: 12px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--c); align-self: center; }
.st--failed .dot { background: #f87171; }
.name { color: var(--text-primary); font-weight: 600; }
.detail { color: var(--text-tertiary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.t { color: #555; font-size: 11px; font-variant-numeric: tabular-nums; }

.swap-enter-active { transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out); }
.swap-leave-active { transition: opacity var(--dur-1) ease; }
.swap-enter-from { opacity: 0; transform: translateY(4px); }
.swap-leave-to { opacity: 0; }
.unfold-enter-active { transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out); }
.unfold-enter-from { opacity: 0; transform: translateY(-4px); }
</style>
