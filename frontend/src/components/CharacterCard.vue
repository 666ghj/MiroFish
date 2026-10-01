<template>
  <div class="character-card" :class="{ 'has-action': hasRecentAction }">
    <div class="name">{{ character.name }}</div>
    <div class="emotions">
      <span v-for="(val, emo) in topEmotions" :key="emo" class="emotion">
        <span class="emo-label">{{ emo }}</span>
        <span class="emo-bar">
          <span class="emo-bar-fill" :style="{ width: (val * 100) + '%' }"></span>
        </span>
        <span class="emo-val">{{ val.toFixed(2) }}</span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  character: { type: Object, required: true },
  hasRecentAction: { type: Boolean, default: false },
})

// Surface the top 3 emotions by magnitude; hide anything at exactly 0
const topEmotions = computed(() => {
  const current = props.character.emotional_state?.current || {}
  const sorted = Object.entries(current)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
  return Object.fromEntries(sorted)
})
</script>

<style scoped>
.character-card {
  display: inline-block;
  padding: 0.75rem 1rem;
  margin: 0.3rem;
  background: #2a2416;
  color: #faf7f0;
  border-radius: 6px;
  font-size: 0.85rem;
  min-width: 180px;
  vertical-align: top;
  border: 1px solid transparent;
  transition: border-color 120ms ease;
}
.character-card.has-action {
  border-color: #c9a45b;
}
.name {
  font-weight: 600;
  margin-bottom: 0.5rem;
  font-size: 0.95rem;
}
.emotions {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 0.7rem;
  opacity: 0.92;
}
.emotion {
  display: grid;
  grid-template-columns: 55px 1fr 35px;
  gap: 0.5rem;
  align-items: center;
}
.emo-label {
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #c9a45b;
}
.emo-bar {
  height: 4px;
  background: #3d3520;
  border-radius: 2px;
  overflow: hidden;
}
.emo-bar-fill {
  display: block;
  height: 100%;
  background: #c9a45b;
}
.emo-val {
  text-align: right;
  color: #e5ddc4;
}
</style>
