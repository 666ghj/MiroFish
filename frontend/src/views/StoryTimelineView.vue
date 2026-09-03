<template>
  <div class="story-timeline">
    <nav class="sim-nav">
      <router-link :to="`/story/${simId}`" active-class="active">Story</router-link>
      <router-link :to="`/godmode/${simId}`" active-class="active">God Mode</router-link>
      <router-link :to="`/world/${simId}`" active-class="active">World</router-link>
    </nav>

    <header class="page-header">
      <div class="header-left">
        <h1>Story Timeline</h1>
        <p class="sim-id">Simulation: <code>{{ simId }}</code></p>
      </div>
      <div class="controls">
        <label class="tone-field">
          Tone
          <input v-model="tone" placeholder="e.g. dark political thriller" />
        </label>
        <button @click="initChars" :disabled="busy" class="secondary">
          Init Characters
        </button>
        <button @click="refresh" :disabled="busy" class="secondary">
          {{ loading ? 'Loading…' : 'Refresh' }}
        </button>
        <button @click="translateNext" :disabled="busy" class="primary">
          {{ translating ? 'Generating…' : 'Translate Next Round' }}
        </button>
      </div>
    </header>

    <div v-if="error" class="error">{{ error }}</div>

    <section v-if="characters.length" class="character-roster">
      <h2>Characters</h2>
      <div class="cards">
        <CharacterCard
          v-for="c in characters"
          :key="c.id"
          :character="c"
          :has-recent-action="recentCharacters.has(c.name)"
        />
      </div>
    </section>

    <div v-if="beats.length === 0 && !loading" class="empty">
      No story yet. Initialize characters, then translate rounds to generate the narrative.
    </div>

    <StoryBeat v-for="beat in beats" :key="beat.round" :beat="beat" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  getFullStory,
  translateRound,
  getCharacters,
  initCharacters,
} from '../api/narrative'
import StoryBeat from '../components/StoryBeat.vue'
import CharacterCard from '../components/CharacterCard.vue'

const route = useRoute()
const simId = route.params.simulationId

const beats = ref([])
const characters = ref([])
const loading = ref(false)
const translating = ref(false)
const initting = ref(false)
const error = ref('')
const tone = ref('dark political thriller')

const busy = computed(() => loading.value || translating.value || initting.value)

// Characters that acted in the most recent beat — highlighted in the roster
const recentCharacters = computed(() => {
  const last = beats.value[beats.value.length - 1]
  return new Set(last?.characters || [])
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const res = await getFullStory(simId)
    beats.value = res.beats || []
    await loadCharacters()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message || 'Failed to load story'
  } finally {
    loading.value = false
  }
}

async function loadCharacters() {
  try {
    const res = await getCharacters(simId)
    characters.value = res.characters || []
  } catch (e) {
    // non-fatal — characters may not be initialized yet
  }
}

async function initChars() {
  initting.value = true
  error.value = ''
  try {
    await initCharacters(simId)
    await loadCharacters()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message || 'Failed to initialize characters'
  } finally {
    initting.value = false
  }
}

async function translateNext() {
  translating.value = true
  error.value = ''
  try {
    const nextRound = beats.value.length + 1
    await translateRound({ sim_id: simId, round: nextRound, tone: tone.value })
    await refresh()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message || 'Translation failed'
  } finally {
    translating.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.story-timeline {
  max-width: 840px;
  margin: 0 auto;
  padding: 2rem 1.5rem 6rem;
}
.sim-nav {
  display: flex;
  gap: 1.25rem;
  padding: 0.75rem 0;
  margin-bottom: 1rem;
  border-bottom: 1px solid #e5ddc4;
  font-size: 0.9rem;
}
.sim-nav a {
  color: #7d6b3f;
  text-decoration: none;
  font-weight: 500;
}
.sim-nav a.active {
  color: #c9a45b;
  border-bottom: 2px solid #c9a45b;
  padding-bottom: 0.15rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 2rem;
  margin-bottom: 2rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid #e5ddc4;
  flex-wrap: wrap;
}
.header-left h1 {
  margin: 0 0 0.25rem;
  font-family: Georgia, serif;
  color: #2a2416;
  font-size: 1.8rem;
}
.sim-id {
  margin: 0;
  font-size: 0.85rem;
  color: #7d6b3f;
}
.sim-id code {
  background: #eadfb8;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
}
.controls {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
  flex-wrap: wrap;
}
.tone-field {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.75rem;
  color: #7d6b3f;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.tone-field input {
  padding: 0.45rem 0.6rem;
  border: 1px solid #d4c893;
  border-radius: 4px;
  font-size: 0.9rem;
  min-width: 220px;
  background: #faf7f0;
}
button {
  padding: 0.55rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 500;
}
button.primary {
  background: #c9a45b;
  color: white;
}
button.secondary {
  background: transparent;
  color: #7d6b3f;
  border: 1px solid #d4c893;
}
button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.error {
  background: #ffe5e5;
  color: #8b0000;
  padding: 0.85rem 1rem;
  border-radius: 4px;
  margin-bottom: 1.5rem;
  font-size: 0.9rem;
}
.character-roster {
  margin-bottom: 2.5rem;
  padding: 1.25rem;
  background: #f5efd9;
  border-radius: 6px;
}
.character-roster h2 {
  margin: 0 0 0.75rem;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #7d6b3f;
  font-weight: 600;
}
.cards {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.empty {
  text-align: center;
  color: #999;
  padding: 3rem 1rem;
  font-style: italic;
  border: 1px dashed #d4c893;
  border-radius: 6px;
}
</style>
