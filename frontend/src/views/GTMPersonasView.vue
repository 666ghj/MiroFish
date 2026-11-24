<template>
  <div class="personas-page">

    <!-- Header -->
    <header class="pg-header">
      <div class="pg-brand" @click="goHome">GTM SIM LAB</div>

      <div v-if="brief" class="pg-brief-summary">
        <span class="pg-brief-product">{{ brief.product_name }}</span>
        <span class="pg-brief-sep">·</span>
        <span class="pg-brief-goal">{{ goalLabel }}</span>
      </div>

      <div class="pg-step-badge">Step 2 of 5 · Buyer Personas</div>
    </header>

    <!-- Main content -->
    <main class="pg-main">

      <!-- Loading state -->
      <div v-if="viewState === 'loading'" class="pg-loading">
        <div class="pg-loading-title">AI-Generating {{ numPersonas }} Buyer Personas</div>
        <div class="pg-steps">
          <div
            v-for="(step, i) in loadingSteps"
            :key="i"
            class="pg-step"
            :class="{ done: i < loadingStep, active: i === loadingStep }"
          >
            <span class="pg-step-dot">{{ i < loadingStep ? '–' : i === loadingStep ? '>' : '·' }}</span>
            <span class="pg-step-label">{{ step }}</span>
          </div>
        </div>
        <div class="pg-loading-sub">Simulating how {{ numPersonas }} different buyer types would evaluate your product.</div>
      </div>

      <!-- Error state -->
      <div v-else-if="viewState === 'error'" class="pg-error">
        <div class="pg-error-title">Persona generation failed</div>
        <div class="pg-error-msg">{{ errorMsg || 'The AI service may be unavailable, so sample personas are shown instead.' }}</div>
        <button class="pg-btn-secondary" @click="retryGeneration">Retry</button>
      </div>

      <!-- Persona grid -->
      <div v-else-if="viewState === 'ready'" class="pg-ready">

        <!-- Mock data warning -->
        <div v-if="isMockData" class="pg-mock-banner">
          Demo mode: the server is unreachable. Showing sample personas, not generated from your brief.
          <a href="https://github.com/sanketmuchhala/GTM-SImulator#quick-start" target="_blank" rel="noopener" class="pg-mock-link">Run locally →</a>
        </div>

        <!-- Summary bar -->
        <div class="pg-summary-bar">
          <div class="pg-summary-stats">
            <span class="pg-stat">
              <span class="pg-stat-num">{{ personas.length }}</span>
              <span class="pg-stat-label">personas</span>
            </span>
            <span class="pg-stat-sep">·</span>
            <span class="pg-stat">
              <span class="pg-stat-num" style="color:var(--green)">{{ interestedCount }}</span>
              <span class="pg-stat-label">interested</span>
            </span>
            <span class="pg-stat-sep">·</span>
            <span class="pg-stat">
              <span class="pg-stat-num" style="color:var(--amber)">{{ neutralCount }}</span>
              <span class="pg-stat-label">neutral</span>
            </span>
            <span class="pg-stat-sep">·</span>
            <span class="pg-stat">
              <span class="pg-stat-num" style="color:var(--red)">{{ objectionCount }}</span>
              <span class="pg-stat-label">objections</span>
            </span>
            <span class="pg-stat-sep">·</span>
            <span class="pg-stat">
              <span class="pg-stat-label">best angle:</span>
              <span class="pg-stat-num angle">{{ bestAngle }}</span>
            </span>
          </div>

          <div class="pg-filter-row">
            <button
              v-for="f in filters"
              :key="f.value"
              class="pg-filter-btn"
              :class="{ active: activeFilter === f.value }"
              @click="activeFilter = f.value"
            >
              {{ f.label }}
            </button>
          </div>

          <div class="pg-confidence-note">
            Directional signal. Validate your top segments with real outreach before committing.
          </div>
        </div>

        <!-- Grid -->
        <div class="pg-grid">
          <PersonaCard
            v-for="persona in filteredPersonas"
            :key="persona.id"
            :persona="persona"
            :compact="false"
            :dark="true"
            :colors="brief?.audience?.colors"
          />
        </div>

      </div>
    </main>

    <!-- Footer -->
    <footer v-if="viewState === 'ready'" class="pg-footer">
      <button class="pg-btn-secondary" @click="goHome">← Edit Brief</button>
      <button class="pg-btn-primary" @click="continueToMessageTesting">
        Continue to Message Testing →
      </button>
    </footer>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PersonaCard from '../components/PersonaCard.vue'
import { generatePersonas, getGTMBrief } from '../api/gtm.js'
import { getGTMState, setPersonas, getPersonas } from '../store/gtmSimulation.js'
import { MOCK_PERSONAS_FULL } from '../mock/gtm_preview.js'

const props = defineProps({ briefId: String })
const route = useRoute()
const router = useRouter()

const briefId = computed(() => props.briefId || route.params.briefId)

// View state machine
const viewState = ref('loading') // 'loading' | 'ready' | 'error'
const errorMsg = ref('')
const personas = ref([])
const brief = ref(null)
const isMockData = ref(false)

// Resolved persona count - read from store brief, fall back to 12
const numPersonas = computed(() => {
  const n = brief.value?.num_personas
  return (n && n > 0) ? n : 12
})

// Loading animation - dynamic text
const loadingSteps = computed(() => [
  'Analyzing your GTM brief...',
  'Identifying buyer segments...',
  `Generating ${numPersonas.value} buyer personas...`,
])
const loadingStep = ref(0)
let loadingTimer = null

function startLoadingAnimation() {
  loadingStep.value = 0
  loadingTimer = setInterval(() => {
    if (loadingStep.value < loadingSteps.length - 1) {
      loadingStep.value++
    }
  }, 2000)
}

function stopLoadingAnimation() {
  if (loadingTimer) {
    clearInterval(loadingTimer)
    loadingTimer = null
  }
}

// Computed stats
const interestedCount = computed(() => personas.value.filter(p => p.reaction === 'interested').length)
const neutralCount = computed(() => personas.value.filter(p => p.reaction === 'neutral').length)
const objectionCount = computed(() => personas.value.filter(p => p.reaction === 'objection').length)

const bestAngle = computed(() => {
  if (!personas.value.length) return '-'
  const counts = {}
  for (const p of personas.value) {
    const a = p.likely_message_angle || 'unknown'
    counts[a] = (counts[a] || 0) + 1
  }
  const winner = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
  const labels = { pain_led: 'Pain-Led', roi_led: 'ROI-Led', social_proof_led: 'Social Proof' }
  return labels[winner?.[0]] ?? winner?.[0] ?? '-'
})

const goalLabel = computed(() => {
  const map = {
    first_10_customers: 'First 10 Customers',
    expand_segment: 'Expand Segment',
    new_market: 'New Market',
    reactivate_churned: 'Reactivate Churned',
  }
  return map[brief.value?.gtm_goal] ?? brief.value?.gtm_goal ?? ''
})

// Filters
const filters = [
  { label: 'All', value: 'all' },
  { label: 'Interested', value: 'interested' },
  { label: 'Neutral', value: 'neutral' },
  { label: 'Objection', value: 'objection' },
]
const activeFilter = ref('all')

const filteredPersonas = computed(() => {
  if (activeFilter.value === 'all') return personas.value
  return personas.value.filter(p => p.reaction === activeFilter.value)
})

// Load brief from store or API
async function loadBrief() {
  const state = getGTMState()
  if (state.brief) {
    brief.value = state.brief
    return
  }
  try {
    const res = await getGTMBrief(briefId.value)
    if (res.success) brief.value = res.data
    else brief.value = res
  } catch (_) { /* brief display is optional */ }
}

// Load personas from store cache → API → mock fallback
async function loadPersonas() {
  // 1. Try in-memory store cache
  const cached = getPersonas()
  if (cached?.length) {
    personas.value = cached
    viewState.value = 'ready'
    stopLoadingAnimation()
    return
  }

  // 2. Call the generation API - pass the count from the saved brief
  try {
    const count = numPersonas.value
    const res = await generatePersonas(briefId.value, count)
    const data = res.data ?? res
    if (Array.isArray(data) && data.length) {
      personas.value = data
      setPersonas(data)
      isMockData.value = false
      viewState.value = 'ready'
    } else {
      throw new Error('Empty persona list returned')
    }
  } catch (err) {
    // 3. Backend unreachable (Vercel demo, no keys, offline) - show mock with banner
    console.warn('Persona generation failed, using sample data:', err.message)
    personas.value = MOCK_PERSONAS_FULL
    setPersonas(MOCK_PERSONAS_FULL)
    isMockData.value = true
    viewState.value = 'ready'
  }
  stopLoadingAnimation()
}

async function retryGeneration() {
  viewState.value = 'loading'
  errorMsg.value = ''
  isMockData.value = false
  startLoadingAnimation()
  await loadPersonas()
}

function goHome() {
  router.push({ name: 'Home' })
}

function continueToMessageTesting() {
  router.push({ name: 'GTMMessages', params: { briefId: briefId.value } })
}

onMounted(async () => {
  startLoadingAnimation()
  await loadBrief()
  await loadPersonas()
})
</script>

<style scoped>
/* ── Page shell ────────────────────────────────────────────── */
.personas-page {
  min-height: 100vh;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  display: flex;
  flex-direction: column;
}

/* ── Header ────────────────────────────────────────────────── */
.pg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  height: 56px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  position: sticky;
  top: 0;
  z-index: 10;
  flex-shrink: 0;
}

.pg-brand {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--accent);
  cursor: pointer;
}

.pg-brief-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.pg-brief-product { font-weight: 600; color: var(--text-primary); }
.pg-brief-sep     { color: var(--border-muted); }
.pg-brief-goal    { color: var(--text-secondary); }

.pg-step-badge {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent);
  background: var(--accent-dim);
  border: 1px solid rgba(59, 130, 246, 0.25);
  padding: 4px 10px;
  border-radius: 4px;
}

/* ── Main ──────────────────────────────────────────────────── */
.pg-main {
  flex: 1;
  padding: 32px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* ── Loading ───────────────────────────────────────────────── */
.pg-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  gap: 24px;
}

.pg-loading-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.pg-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 300px;
}

.pg-step {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--text-tertiary);
  transition: color 0.3s;
}

.pg-step.done   { color: var(--green); }
.pg-step.active { color: var(--accent); }
.pg-step-dot    { font-size: 10px; width: 14px; text-align: center; }

.pg-loading-sub {
  font-size: 13px;
  color: var(--text-tertiary);
}

/* ── Error ─────────────────────────────────────────────────── */
.pg-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 0;
}

.pg-error-title { font-size: 18px; font-weight: 700; color: var(--red); }
.pg-error-msg   { font-size: 13px; color: var(--text-secondary); text-align: center; max-width: 400px; }

/* ── Summary bar ───────────────────────────────────────────── */
.pg-summary-bar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 24px;
}

.pg-summary-stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.pg-stat         { display: flex; align-items: center; gap: 5px; }
.pg-stat-num     { font-weight: 700; color: var(--text-primary); font-size: 15px; }
.pg-stat-num.angle { color: var(--accent); }
.pg-stat-label   { color: var(--text-tertiary); font-size: 12px; }
.pg-stat-sep     { color: var(--border-muted); }

/* ── Filter buttons ────────────────────────────────────────── */
.pg-filter-row { display: flex; gap: 6px; flex-wrap: wrap; }

.pg-filter-btn {
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--border-muted);
  border-radius: 20px;
  background: transparent;
  color: var(--text-secondary);
  transition: all 0.15s;
}

.pg-filter-btn:hover,
.pg-filter-btn.active {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--text-primary);
}

/* ── Mock data banner ──────────────────────────────────────── */
.pg-mock-banner {
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.25);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 12px;
  color: var(--red);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.pg-mock-link {
  color: var(--red);
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
  margin-left: auto;
}

/* ── Confidence note ───────────────────────────────────────── */
.pg-confidence-note {
  font-size: 12px;
  color: #c8a860;
  padding: 8px 12px;
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(245, 158, 11, 0.18);
  border-radius: 6px;
}

/* ── Persona grid ──────────────────────────────────────────── */
.pg-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

@media (max-width: 1024px) { .pg-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px)  { .pg-grid { grid-template-columns: 1fr; } .pg-main { padding: 20px 16px; } }

/* ── Footer ────────────────────────────────────────────────── */
.pg-footer {
  padding: 16px 32px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-surface);
  flex-shrink: 0;
}

.pg-btn-primary {
  background: var(--accent);
  color: #fff;
  border: none;
  font-size: 14px;
  font-weight: 600;
  padding: 10px 22px;
  border-radius: 8px;
  transition: background 0.2s;
}
.pg-btn-primary:hover { background: #5254cc; }

.pg-btn-secondary {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-muted);
  font-size: 14px;
  font-weight: 500;
  padding: 10px 18px;
  border-radius: 8px;
  transition: color 0.2s, border-color 0.2s;
}
.pg-btn-secondary:hover { color: var(--text-primary); border-color: var(--accent); }
</style>
