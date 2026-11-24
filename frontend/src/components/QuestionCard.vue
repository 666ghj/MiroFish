<template>
  <!-- Waiting for the question: the card holds its place so nothing jumps -->
  <div v-if="pending" class="q q--pending" aria-hidden="true">
    <span class="eyebrow"><span class="spark"></span>Writing your next question</span>
    <span class="bar"></span><span class="bar bar--short"></span>
  </div>

  <!-- Current question: interactive -->
  <section v-else-if="active" class="q q--active" aria-label="Next question">
    <header class="eyebrow">
      <span class="spark"></span>
      <span>Next question</span>
      <span v-if="reason" class="for">· fills in {{ reason }}</span>
    </header>
    <p class="text">
      <template v-for="(w, i) in words" :key="i"><span class="w" :style="{ '--i': i }">{{ w }}</span>{{ i < words.length - 1 ? ' ' : '' }}</template>
    </p>
    <div class="replies" role="group" aria-label="Quick replies">
      <button type="button" class="r r--answer" @click="$emit('answer')">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10v6H7l-3 2.5v-2.5H3z" /></svg>Answer
      </button>
      <button type="button" class="r" @click="$emit('quick', 'I am not sure. Can you give me a hint, without answering it for me?')">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 13h4M6.5 11h3M8 2.5a4 4 0 00-2.4 7.2c.5.4.9.9.9 1.3h3c0-.4.4-.9.9-1.3A4 4 0 008 2.5z" /></svg>Give me a hint
      </button>
      <button type="button" class="r" @click="$emit('quick', `I don't know yet.`)">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 6a2 2 0 113 1.7c-.6.4-1 .8-1 1.5M8 11.5v.5" /></svg>Not sure yet
      </button>
      <button type="button" class="r" @click="$emit('quick', 'Park this question for later.')">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5h7v11l-3.5-2.5-3.5 2.5z" /></svg>Park it
      </button>
    </div>
  </section>

  <!-- Earlier questions: a quiet quote -->
  <p v-else class="q q--past"><span class="past-mark" aria-hidden="true">Q</span>{{ question }}</p>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  question: { type: String, default: '' },
  reason: { type: String, default: '' },
  active: { type: Boolean, default: false },
  pending: { type: Boolean, default: false },
})
defineEmits(['answer', 'quick'])
const words = computed(() => props.question.split(/\s+/).filter(Boolean))
</script>

<style scoped>
.q { margin-top: 14px; }

.q--active, .q--pending {
  position: relative; padding: 14px 16px 14px; border-radius: 14px; border: 1px solid rgba(96, 165, 250, 0.22);
  background: radial-gradient(120% 140% at 0% 0%, rgba(59, 130, 246, 0.10), transparent 55%), #0a0b0d;
  animation: card-in 420ms var(--ease-out) both;
}
@keyframes card-in { from { opacity: 0; transform: translateY(8px) scale(0.985); } to { opacity: 1; transform: none; } }

.eyebrow { display: flex; align-items: center; gap: 6px; font-size: 10.5px; font-weight: 650; letter-spacing: 0.08em;
  text-transform: uppercase; color: #93c5fd; }
.for { text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--text-tertiary); font-size: 11.5px; }
.spark { width: 6px; height: 6px; border-radius: 50%; background: #60a5fa; box-shadow: 0 0 10px #60a5fa; }
.q--pending .spark { animation: blink 1.2s ease-in-out infinite; }
@keyframes blink { 50% { opacity: 0.3; } }

.text { margin: 8px 0 12px; font-family: 'Space Grotesk', var(--font-sans); font-size: 17.5px; font-weight: 600; line-height: 1.4;
  letter-spacing: -0.01em; color: #f5f5f5; text-wrap: balance; }
/* Words settle in one after another */
.w { display: inline-block; animation: word 380ms var(--ease-out) both; animation-delay: calc(120ms + var(--i) * 28ms); }
@keyframes word { from { opacity: 0; transform: translateY(5px); filter: blur(3px); } to { opacity: 1; transform: none; filter: none; } }

.replies { display: flex; flex-wrap: wrap; gap: 6px; }
.r { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 550; padding: 6px 11px; border-radius: 999px;
  border: 1px solid #262626; background: #111; color: var(--text-secondary);
  animation: pop-in var(--dur-2) var(--ease-out) both; }
.r:nth-child(1) { animation-delay: 380ms; } .r:nth-child(2) { animation-delay: 430ms; }
.r:nth-child(3) { animation-delay: 480ms; } .r:nth-child(4) { animation-delay: 530ms; }
.r:hover { color: var(--text-primary); border-color: #3a3a3a; background: #161616; transform: translateY(-1px); }
.r svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.r--answer { background: #e5e7eb; color: #0a0a0a; border-color: transparent; }
.r--answer:hover { background: #fff; color: #000; border-color: transparent; }

.bar { display: block; height: 12px; margin-top: 10px; border-radius: 6px; width: 85%;
  background: linear-gradient(90deg, #14161a, #22252b, #14161a); background-size: 200% 100%; animation: shimmer 1.3s ease-in-out infinite; }
.bar--short { width: 55%; margin-top: 8px; }
@keyframes shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }

.q--past { display: flex; gap: 8px; align-items: baseline; font-size: 13.5px; line-height: 1.5; color: var(--text-secondary);
  font-weight: 500; }
.past-mark { flex-shrink: 0; font-size: 10px; font-weight: 700; color: #4b5563; border: 1px solid #262626; border-radius: 4px;
  padding: 0 4px; line-height: 16px; }

@media (prefers-reduced-motion: reduce) { .w { animation: none; } }
</style>
