<template>
  <!-- Founder -->
  <div v-if="m.role === 'user'" class="msg msg--user">
    <div class="you">{{ m.content }}</div>
  </div>

  <!-- Co-founder and the team -->
  <article v-else class="msg msg--ai" :class="{ working: m.streaming || teamWorking }">
    <div class="avatar" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="M3 4.5h10v6H7l-3 2.5v-2.5H3z" /></svg></div>
    <div class="col">
      <AgentActivity v-if="m.trace?.length" :steps="m.trace" />

      <!-- Research: what was searched and found, as data -->
      <section v-if="m.research" class="research" aria-label="Research results">
        <div class="rs-head">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5" /></svg>
          <span>Searched</span><span class="rs-q">"{{ m.research.query }}"</span>
        </div>
        <div v-if="m.research.competitors?.length" class="rs-row">
          <span class="rs-label">Closest</span>
          <component :is="c.url ? 'a' : 'span'" v-for="(c, i) in m.research.competitors" :key="c.name" class="co"
                     :href="c.url || undefined" target="_blank" rel="noopener" :style="{ '--i': i }">{{ c.name }}</component>
        </div>
        <p v-else class="rs-none">No companies doing this turned up. That does not prove nobody has tried.</p>
        <div v-if="m.research.predecessors?.length" class="rs-row">
          <span class="rs-label">Shut down</span>
          <component :is="c.url ? 'a' : 'span'" v-for="(c, i) in m.research.predecessors" :key="c.name" class="co co--dead"
                     :href="c.url || undefined" target="_blank" rel="noopener" :style="{ '--i': i + 3 }">{{ c.name }}</component>
        </div>
      </section>

      <div v-if="m.streaming" class="body" aria-live="off">
        <p v-for="(para, i) in streamParas" :key="i">
          <template v-if="i === streamParas.length - 1">{{ para.slice(0, Math.max(0, para.length - tail)) }}<span class="fresh" :key="m.content.length">{{ para.slice(Math.max(0, para.length - tail)) }}</span></template>
          <template v-else>{{ para }}</template>
        </p>
      </div>
      <div v-else-if="parsed.body" class="body" v-html="parsed.bodyHtml"></div>

      <div v-if="m.notice" class="notice">{{ m.notice }}</div>

      <!-- What the app did with the message -->
      <ul v-if="receipts.length" class="receipts" aria-label="What the app did">
        <li v-for="(a, j) in receipts" :key="j" :class="`rc--${a.kind}`" :style="{ '--j': j }">
          <button type="button" @click="$emit('act', a)">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path :d="ICON[a.kind] || ICON.parked" /></svg>
            <b>{{ LABEL[a.kind] }}</b>
            <span v-if="a.priority === 'top'" class="top">Top priority</span>
            <span class="rc-text">{{ a.text }}</span>
          </button>
        </li>
      </ul>

      <QuestionCard v-if="m.streaming" pending />
      <QuestionCard v-else-if="parsed.question" :question="parsed.question" :reason="m.ask?.reason || ''" :active="isLast && !busy"
                    @answer="$emit('answer')" @quick="(t) => $emit('quick', t)" />
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import AgentActivity from './AgentActivity.vue'
import QuestionCard from './QuestionCard.vue'

const props = defineProps({
  m: { type: Object, required: true },
  isLast: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
defineEmits(['answer', 'quick', 'act'])

const LABEL = { parked: 'Parked', already_parked: 'Already parked', unparked: 'Brought back', idea_updated: 'Idea updated',
  research_skipped: 'Search skipped' }
const ICON = {
  parked: 'M4.5 2.5h7v11l-3.5-2.5-3.5 2.5z', already_parked: 'M4.5 2.5h7v11l-3.5-2.5-3.5 2.5z',
  unparked: 'M3 8h10M8.5 3.5L13 8l-4.5 4.5', idea_updated: 'M3 13l1-3.5L10.5 3 13 5.5 6.5 12z', research_skipped: 'M8 3v6M8 11.5v.5',
}

const teamWorking = computed(() => !!props.m.trace?.some(s => s.status === 'running' || s.status === 'queued'))
const receipts = computed(() => (props.m.actions || []).filter(a => a.kind !== 'researched'))
const tail = computed(() => props.m.tail || 0)

const esc = (s) => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

// While streaming: show text up to where the bold question starts (the card takes the question)
const streamParas = computed(() => {
  let t = props.m.content || ''
  const cut = t.indexOf('**')
  if (cut !== -1) t = t.slice(0, cut)
  return t.trim().split(/\n{2,}/).map(p => p.replace(/\n/g, ' ')).filter(Boolean)
})

// Finished: split into research facts (shown as a card), body, and the question
const parsed = computed(() => {
  let text = (props.m.content || '').trim()
  if (props.m.research && /^I searched (for|the web)/.test(text)) text = text.replace(/^[^\n]*(\n+|$)/, '').trim()
  let question = ''
  const bold = [...text.matchAll(/\*\*([^*]+?\?)\*\*/g)]
  if (bold.length) {
    const last = bold[bold.length - 1]
    question = last[1].trim()
    text = (text.slice(0, last.index) + text.slice(last.index + last[0].length)).trim()
  } else {
    const m = text.match(/([^.!?\n]*\?)\s*$/)
    if (m && props.m.ask) { question = m[1].trim(); text = text.slice(0, m.index).trim() }
  }
  const bodyHtml = text.split(/\n{2,}/).filter(Boolean)
    .map(p => `<p>${esc(p).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')}</p>`).join('')
  return { body: text, bodyHtml, question }
})
</script>

<style scoped>
.msg { display: flex; gap: 12px; animation: rise-in var(--dur-3) var(--ease-out) both; }
.msg--user { justify-content: flex-end; animation-name: send-in; }
@keyframes send-in { from { opacity: 0; transform: translate(8px, 6px) scale(0.98); } to { opacity: 1; transform: none; } }
.you { max-width: 82%; padding: 9px 14px; border-radius: 16px 16px 4px 16px; background: #1a1a1c; border: 1px solid #26262a;
  font-size: 14.5px; line-height: 1.55; color: var(--text-primary); white-space: pre-wrap; overflow-wrap: anywhere; }

.avatar { position: relative; width: 26px; height: 26px; flex-shrink: 0; margin-top: 1px; border-radius: 50%; display: grid; place-items: center;
  background: radial-gradient(circle at 30% 30%, rgba(147, 197, 253, 0.35), rgba(59, 130, 246, 0.12)); box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.35); }
.avatar svg { width: 12px; height: 12px; fill: none; stroke: #bfdbfe; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.working .avatar { animation: halo 1.6s ease-out infinite; }
@keyframes halo { 0% { box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.6), 0 0 0 0 rgba(96, 165, 250, 0.35); }
  100% { box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.6), 0 0 0 8px rgba(96, 165, 250, 0); } }
.col { flex: 1; min-width: 0; }

.body { font-size: 14.5px; line-height: 1.65; color: #d4d4d4; overflow-wrap: anywhere; }
.body :deep(p), .body p { margin: 0 0 10px; }
.body :deep(p:last-child), .body p:last-child { margin-bottom: 0; }
.body :deep(strong) { color: #fff; font-weight: 600; }
/* The newest words fade in as they stream */
.fresh { animation: ink 420ms ease-out both; }
@keyframes ink { from { opacity: 0; filter: blur(2px); } to { opacity: 1; filter: none; } }

.notice { margin-top: 10px; font-size: 12px; color: #fcd34d; background: rgba(245, 158, 11, 0.07); border: 1px solid rgba(245, 158, 11, 0.22);
  border-radius: 8px; padding: 6px 10px; }

/* Research card */
.research { margin-bottom: 12px; padding: 10px 12px; border-radius: 12px; background: #0b0d0d; border: 1px solid rgba(45, 212, 191, 0.18);
  display: flex; flex-direction: column; gap: 8px; animation: rise-in var(--dur-3) var(--ease-out) both; }
.rs-head { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-tertiary); min-width: 0; }
.rs-head svg { width: 13px; height: 13px; fill: none; stroke: #5eead4; stroke-width: 1.6; stroke-linecap: round; flex-shrink: 0; }
.rs-head span:nth-child(2) { color: #5eead4; font-weight: 600; }
.rs-q { color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.rs-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.rs-label { font-size: 10.5px; font-weight: 650; letter-spacing: 0.06em; text-transform: uppercase; color: #555; margin-right: 2px; }
.co { font-size: 12.5px; padding: 3px 9px; border-radius: 7px; background: #141616; border: 1px solid #232727; color: var(--text-primary);
  text-decoration: none; animation: pop-in var(--dur-2) var(--ease-out) both; animation-delay: calc(80ms + var(--i) * 45ms); }
a.co:hover { border-color: rgba(45, 212, 191, 0.5); }
.co--dead { color: var(--text-tertiary); text-decoration: line-through; text-decoration-color: #555; }
.rs-none { font-size: 12.5px; color: var(--text-tertiary); margin: 0; }

/* Receipts: what the app actually did */
.receipts { list-style: none; margin: 12px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.receipts li { animation: rise-in var(--dur-2) var(--ease-out) both; animation-delay: calc(var(--j) * 60ms); }
.receipts button { display: inline-flex; align-items: center; gap: 7px; max-width: 100%; padding: 2px 0; background: none; border: none;
  font-size: 12.5px; color: var(--text-tertiary); text-align: left; }
.receipts button:hover { color: var(--text-secondary); }
.receipts svg { width: 13px; height: 13px; flex-shrink: 0; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.receipts b { font-weight: 600; color: var(--text-secondary); flex-shrink: 0; }
.rc--parked svg, .rc--already_parked svg { stroke: #fcd34d; }
.rc--idea_updated svg { stroke: #93c5fd; }
.rc--research_skipped svg { stroke: #fca5a5; }
.top { font-size: 9.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #fcd34d; flex-shrink: 0; }
.rc-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
</style>
