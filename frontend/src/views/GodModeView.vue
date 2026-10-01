<template>
  <div class="godmode">
    <nav class="sim-nav">
      <router-link :to="`/story/${simId}`">Story</router-link>
      <router-link :to="`/godmode/${simId}`" class="active">God Mode</router-link>
      <router-link :to="`/world/${simId}`">World</router-link>
    </nav>

    <h1>God Mode</h1>
    <p class="subtitle">Author-controlled interventions. Changes take effect on the next translated round.</p>

    <section class="card inject">
      <h2>⚡ Inject World Event</h2>
      <p class="hint">A new world event the narrator will weave into the next scene. (Current enforcement: <strong>hard</strong> — opening line MUST reference it.)</p>
      <textarea v-model="eventDesc" rows="3"
                placeholder="A stranger arrives at the market, carrying a sealed letter."></textarea>
      <div class="row">
        <input v-model.number="eventRound" type="number" min="0"
               placeholder="Round (optional — defaults to next round)" />
        <button @click="doInject" :disabled="busy || !eventDesc">Inject</button>
      </div>
    </section>

    <section class="card emotion">
      <h2>💭 Modify Character Emotions</h2>
      <p class="hint">Overwrite any emotion directly. Unchanged emotions keep their current values.</p>
      <select v-model="emoCharId" @change="onEmoCharChange">
        <option value="">Select character…</option>
        <option v-for="c in aliveChars" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <div v-if="emoCharId" class="sliders">
        <div v-for="emo in emotions" :key="emo" class="slider-row">
          <label>{{ emo }}</label>
          <input type="range" min="0" max="1" step="0.05" v-model.number="emoValues[emo]" />
          <span>{{ emoValues[emo].toFixed(2) }}</span>
        </div>
        <button @click="doModifyEmotion" :disabled="busy">Apply</button>
      </div>
    </section>

    <section class="card kill">
      <h2>☠ Kill Character</h2>
      <p class="warning">
        Irreversible in v1. Auto-appends a death event to the world log so
        the narrator knows they're gone.
      </p>
      <select v-model="killCharId" @change="killConfirm = ''">
        <option value="">Select character…</option>
        <option v-for="c in aliveChars" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <input v-if="killCharId" v-model="killConfirm"
             :placeholder="`Type '${selectedKillName}' to confirm`" />
      <button @click="doKill" :disabled="busy || !canKill" class="danger">
        Kill {{ selectedKillName }}
      </button>
    </section>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="success" class="success">{{ success }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getCharacters, injectEvent, modifyEmotion, killCharacter } from '../api/narrative'

const route = useRoute()
const simId = route.params.simulationId

const emotions = ['anger', 'fear', 'joy', 'sadness', 'trust', 'surprise']

const characters = ref([])
const busy = ref(false)
const error = ref('')
const success = ref('')

const eventDesc = ref('')
const eventRound = ref(null)

const emoCharId = ref('')
const emoValues = ref(Object.fromEntries(emotions.map(e => [e, 0])))

const killCharId = ref('')
const killConfirm = ref('')

const aliveChars = computed(() =>
  characters.value.filter(c => (c.status || 'alive') !== 'dead')
)

const selectedKillName = computed(() => {
  const c = characters.value.find(c => c.id === killCharId.value)
  return c?.name || ''
})

// Typed-name confirmation — case-insensitive, whitespace-trimmed
const canKill = computed(() =>
  killCharId.value &&
  selectedKillName.value &&
  killConfirm.value.trim().toLowerCase() === selectedKillName.value.toLowerCase()
)

async function loadCharacters() {
  try {
    const res = await getCharacters(simId)
    characters.value = res.characters || []
  } catch (e) { /* non-fatal */ }
}

// When the user selects a character for emotion editing, preload current values
function onEmoCharChange() {
  const c = characters.value.find(c => c.id === emoCharId.value)
  if (c) {
    const current = c.emotional_state?.current || {}
    emoValues.value = Object.fromEntries(emotions.map(e => [e, current[e] ?? 0]))
  }
}

function flash(msg) {
  success.value = msg
  setTimeout(() => { success.value = '' }, 2500)
}

async function doInject() {
  busy.value = true
  error.value = ''
  try {
    await injectEvent(simId, eventDesc.value, eventRound.value || null)
    flash('Event injected — appears in the next translated round.')
    eventDesc.value = ''
    eventRound.value = null
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function doModifyEmotion() {
  busy.value = true
  error.value = ''
  try {
    await modifyEmotion(simId, emoCharId.value, emoValues.value)
    flash('Emotions updated.')
    await loadCharacters()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function doKill() {
  busy.value = true
  error.value = ''
  try {
    const name = selectedKillName.value
    await killCharacter(simId, killCharId.value)
    flash(`${name} has been killed.`)
    killCharId.value = ''
    killConfirm.value = ''
    await loadCharacters()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

onMounted(loadCharacters)
</script>

<style scoped>
.godmode {
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
.hint { color: #7d6b3f; font-size: 0.85rem; margin: 0 0 0.75rem; }
.warning {
  color: #8b0000; font-size: 0.85rem; margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem; background: #ffe5e5; border-radius: 4px;
}
textarea, input, select {
  width: 100%; padding: 0.5rem 0.65rem; border: 1px solid #d4c893;
  border-radius: 4px; font-size: 0.9rem; background: white; margin-bottom: 0.5rem;
  font-family: inherit; box-sizing: border-box;
}
.row { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; }
button {
  padding: 0.5rem 1rem; background: #c9a45b; color: white;
  border: none; border-radius: 4px; cursor: pointer; font-weight: 500;
}
button:disabled { opacity: 0.4; cursor: not-allowed; }
button.danger { background: #8b0000; }
button.danger:disabled { background: #8b0000; opacity: 0.3; }
.sliders { margin-top: 0.75rem; }
.slider-row {
  display: grid; grid-template-columns: 80px 1fr 50px;
  gap: 0.5rem; align-items: center; font-size: 0.85rem;
  margin-bottom: 0.35rem;
}
.slider-row label { text-transform: uppercase; letter-spacing: 0.05em; color: #7d6b3f; font-size: 0.75rem; }
.error { background: #ffe5e5; color: #8b0000; padding: 0.85rem 1rem; border-radius: 4px; margin-top: 1rem; }
.success { background: #e5f7e5; color: #2a6b2a; padding: 0.85rem 1rem; border-radius: 4px; margin-top: 1rem; }
</style>
