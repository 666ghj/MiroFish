<template>
  <div class="world-builder">
    <nav class="sim-nav">
      <router-link :to="`/story/${simId}`">Story</router-link>
      <router-link :to="`/godmode/${simId}`">God Mode</router-link>
      <router-link :to="`/world/${simId}`" class="active">World</router-link>
    </nav>

    <h1>World Builder</h1>
    <p class="subtitle">Ground your story. Rules shape the world; locations shape the scenes.</p>

    <section class="card">
      <h2>World Rules</h2>
      <p class="hint">One rule per line. These appear in every translation prompt as background context.</p>
      <textarea v-model="rulesText" rows="6" placeholder="Magic is forbidden
Winter is near
The kingdom is divided"></textarea>
      <button @click="saveRules" :disabled="busy">Save Rules</button>
    </section>

    <section class="card">
      <h2>Locations</h2>
      <p class="hint">
        Each location's <strong>atmosphere</strong> is a short mood phrase — it anchors
        the opening visual of every scene set there.
      </p>

      <div v-if="locations.length" class="location-list">
        <div v-for="loc in locations" :key="loc.id" class="location-item">
          <div class="loc-header">
            <strong>{{ loc.name }}</strong>
            <span class="loc-id">{{ loc.id }}</span>
          </div>
          <p v-if="loc.description" class="loc-desc">{{ loc.description }}</p>
          <p v-if="loc.atmosphere" class="loc-atmosphere">"{{ loc.atmosphere }}"</p>
        </div>
      </div>
      <p v-else class="muted">No locations yet.</p>

      <form @submit.prevent="addLocation" class="location-form">
        <div class="form-row">
          <input v-model="newLoc.id" placeholder="id (e.g. iron_tower)" required />
          <input v-model="newLoc.name" placeholder="Name (The Iron Tower)" required />
        </div>
        <input v-model="newLoc.description" placeholder="Description (what it looks like)" />
        <input v-model="newLoc.atmosphere"
               placeholder="Atmosphere — short mood phrase (e.g. oppressive silence, dust in shafts of cold light)" />
        <button type="submit" :disabled="busy">Add / Update Location</button>
      </form>
    </section>

    <section class="card">
      <h2>Event Log</h2>
      <p class="hint">World events, newest first. Populated by God Mode interventions.</p>
      <ol v-if="events.length" class="event-log">
        <li v-for="e in events" :key="e.id" :class="`evt-${e.type}`">
          <span class="event-round">Round {{ e.round }}</span>
          <span class="event-type">{{ e.type }}</span>
          <span class="event-desc">{{ e.description }}</span>
        </li>
      </ol>
      <p v-else class="muted">No events yet.</p>
    </section>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="success" class="success">{{ success }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getWorld, setWorldRules, upsertLocation } from '../api/narrative'

const route = useRoute()
const simId = route.params.simulationId

const world = ref({ rules: [], locations: {}, event_log: [] })
const rulesText = ref('')
const newLoc = ref({ id: '', name: '', description: '', atmosphere: '' })
const busy = ref(false)
const error = ref('')
const success = ref('')

const locations = computed(() => Object.values(world.value.locations || {}))
// Event log: show newest first for readability
const events = computed(() => (world.value.event_log || []).slice().reverse())

async function load() {
  try {
    const res = await getWorld(simId)
    world.value = res
    rulesText.value = (res.rules || []).join('\n')
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  }
}

function flash(msg) {
  success.value = msg
  setTimeout(() => { success.value = '' }, 2500)
}

async function saveRules() {
  busy.value = true
  error.value = ''
  try {
    const rules = rulesText.value.split('\n').map(r => r.trim()).filter(Boolean)
    await setWorldRules(simId, rules)
    flash('Rules saved.')
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function addLocation() {
  busy.value = true
  error.value = ''
  try {
    // Only send non-empty optional fields so backend stores a clean record
    const payload = { id: newLoc.value.id, name: newLoc.value.name }
    if (newLoc.value.description) payload.description = newLoc.value.description
    if (newLoc.value.atmosphere) payload.atmosphere = newLoc.value.atmosphere

    await upsertLocation(simId, payload)
    flash(`Location ${newLoc.value.name} saved.`)
    newLoc.value = { id: '', name: '', description: '', atmosphere: '' }
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.world-builder {
  max-width: 840px;
  margin: 0 auto;
  padding: 2rem 1.5rem 6rem;
}
.sim-nav {
  display: flex; gap: 1.25rem;
  padding: 0.75rem 0; margin-bottom: 1.5rem;
  border-bottom: 1px solid #e5ddc4; font-size: 0.9rem;
}
.sim-nav a { color: #7d6b3f; text-decoration: none; font-weight: 500; }
.sim-nav a.active { color: #c9a45b; border-bottom: 2px solid #c9a45b; padding-bottom: 0.15rem; }
h1 {
  font-family: Georgia, serif; color: #2a2416;
  margin: 0 0 0.5rem; font-size: 1.8rem;
}
.subtitle {
  color: #7d6b3f; font-size: 0.9rem; margin: 0 0 1.5rem;
}
.card {
  background: #faf7f0; border: 1px solid #e5ddc4; border-radius: 6px;
  padding: 1.25rem 1.5rem; margin-bottom: 1.5rem;
}
.card h2 { margin: 0 0 0.5rem; font-size: 1.1rem; color: #2a2416; }
.hint, .muted {
  color: #7d6b3f; font-size: 0.85rem; margin: 0 0 0.75rem;
}
.muted { font-style: italic; }
textarea, input {
  width: 100%; padding: 0.5rem 0.65rem; border: 1px solid #d4c893;
  border-radius: 4px; font-size: 0.9rem; background: white; margin-bottom: 0.5rem;
  font-family: inherit; box-sizing: border-box;
}
textarea { resize: vertical; font-family: Georgia, serif; }
button {
  padding: 0.5rem 1rem; background: #c9a45b; color: white;
  border: none; border-radius: 4px; cursor: pointer; font-weight: 500;
}
button:disabled { opacity: 0.5; cursor: wait; }
.location-list {
  margin-bottom: 1rem;
  border: 1px solid #e5ddc4;
  border-radius: 4px;
  overflow: hidden;
}
.location-item {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5ddc4;
  background: white;
}
.location-item:last-child { border-bottom: none; }
.loc-header {
  display: flex; justify-content: space-between; align-items: baseline;
}
.loc-header strong { color: #2a2416; font-size: 0.95rem; }
.loc-id {
  font-family: 'SF Mono', Menlo, monospace; font-size: 0.75rem;
  color: #7d6b3f; background: #f5efd9; padding: 0.1rem 0.4rem; border-radius: 3px;
}
.loc-desc { margin: 0.35rem 0 0; color: #5a4f2f; font-size: 0.88rem; }
.loc-atmosphere {
  margin: 0.35rem 0 0; color: #8b7a40; font-size: 0.85rem;
  font-style: italic; font-family: Georgia, serif;
}
.location-form {
  margin-top: 0.75rem; padding-top: 0.75rem;
  border-top: 1px dashed #d4c893;
}
.form-row {
  display: grid; grid-template-columns: 1fr 2fr; gap: 0.5rem;
}
.event-log { list-style: none; padding: 0; margin: 0; }
.event-log li {
  display: grid;
  grid-template-columns: 80px 160px 1fr;
  gap: 0.75rem;
  padding: 0.55rem 0;
  border-bottom: 1px dashed #e5ddc4;
  font-size: 0.88rem;
  align-items: baseline;
}
.event-log li:last-child { border-bottom: none; }
.event-round { color: #c9a45b; font-weight: 600; }
.event-type {
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 0.72rem; color: #7d6b3f;
  text-transform: uppercase; letter-spacing: 0.03em;
}
.evt-god_mode_death .event-type { color: #8b0000; }
.evt-god_mode_injection .event-type { color: #a0571a; }
.error { background: #ffe5e5; color: #8b0000; padding: 0.85rem 1rem; border-radius: 4px; margin-top: 1rem; }
.success { background: #e5f7e5; color: #2a6b2a; padding: 0.85rem 1rem; border-radius: 4px; margin-top: 1rem; }
</style>
