<template>
  <article class="story-beat">
    <header class="beat-header">
      <span class="round-badge">Round {{ beat.round }}</span>
      <span v-if="beat.characters && beat.characters.length" class="characters">
        {{ beat.characters.join(' · ') }}
      </span>
      <span v-if="beat.platform" class="platform-tag">{{ beat.platform }}</span>
    </header>
    <div class="prose">
      <p v-for="(para, i) in paragraphs" :key="i">{{ para }}</p>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  beat: { type: Object, required: true },
})

const paragraphs = computed(() =>
  (props.beat.prose || '').split(/\n\n+/).filter(p => p.trim())
)
</script>

<style scoped>
.story-beat {
  margin: 0 0 2.5rem;
  padding: 1.5rem 1.75rem;
  border-left: 3px solid #c9a45b;
  background: #faf7f0;
  border-radius: 0 4px 4px 0;
}
.beat-header {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 0.75rem;
  font-size: 0.8rem;
  color: #7d6b3f;
  flex-wrap: wrap;
}
.round-badge {
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.characters {
  font-style: italic;
}
.platform-tag {
  margin-left: auto;
  padding: 0.15rem 0.5rem;
  background: #eadfb8;
  border-radius: 999px;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.prose p {
  line-height: 1.75;
  margin: 0 0 1rem;
  font-family: Georgia, 'Times New Roman', serif;
  color: #2a2416;
  font-size: 1.05rem;
}
.prose p:last-child {
  margin-bottom: 0;
}
</style>
