<template>
  <div class="sim-page">

    <!-- Navbar -->
    <nav class="sim-nav">
      <router-link to="/" class="sim-nav-brand">GTM SIM LAB</router-link>
      <div class="sim-nav-center">
        <span class="sim-nav-step-item" :class="{ active: true }">1. Brief</span>
        <span class="sim-nav-arrow">→</span>
        <span class="sim-nav-step-item">2. Personas</span>
        <span class="sim-nav-arrow">→</span>
        <span class="sim-nav-step-item">3. Messages</span>
        <span class="sim-nav-arrow">→</span>
        <span class="sim-nav-step-item">4. Report</span>
      </div>
      <div class="sim-nav-right">
        <router-link to="/studio" class="sim-nav-studio">Napkin</router-link>
        <button class="sim-nav-demo" @click="loadDemo" type="button">Load example</button>
      </div>
    </nav>

    <!-- Body -->
    <div class="sim-body">

      <!-- Left: Form -->
      <div class="sim-left">
        <div class="sim-left-top">
          <h1 class="sim-title">New GTM Simulation</h1>
          <p class="sim-subtitle">Describe your product and target buyer. The AI generates personas, tests outreach angles, simulates reactions, and produces a GTM strategy report.</p>
        </div>
        <div v-if="fromStudio" class="sim-prefill" role="status">
          Filled in from Napkin. Review every field, add a product name if it is missing, then run the simulation.
        </div>
        <GTMBriefForm
          :loading="loading"
          :initialData="demoData"
          :hideParams="true"
          @submit="handleSubmit"
        />
      </div>

      <!-- Right: Simulation Scale Panel -->
      <div class="sim-right">

        <!-- Buyer network (sticky so it stays visible while you tune the audience) -->
        <div class="sim-agent-section">
          <div class="sim-agent-header">
            <span class="sim-agent-label">Buyer network</span>
            <span class="sim-agent-hint">
              {{ numPersonas > 120 ? 'showing 120 of ' + numPersonas : numPersonas + ' buyers' }} · hover a dot
            </span>
          </div>
          <div class="sim-viz-wrap">
            <HeroViz :count="numPersonas" :audience="audience" />
          </div>
        </div>

        <!-- Scale header -->
        <div class="sim-scale-header">
          <span class="sim-scale-label">Simulation Scale</span>
          <span class="sim-scale-hint">Drag to set number of AI buyer personas</span>
        </div>

        <!-- Count display + slider -->
        <div class="sim-count-block">
          <div class="sim-count-row">
            <div class="sim-count-display">
              <span class="sim-count-num">{{ numPersonas }}</span>
              <span class="sim-count-unit">personas</span>
            </div>
            <div class="sim-count-meta">
              <span class="sim-count-time">{{ timeEstimate }}</span>
              <span class="sim-count-cost">~${{ costEstimate }}</span>
            </div>
          </div>
          <input
            v-model.number="numPersonas"
            type="range"
            class="sim-slider"
            min="6" max="500" step="1"
          />
          <div class="sim-slider-ticks">
            <span>6</span><span>50</span><span>100</span><span>200</span><span>500</span>
          </div>
        </div>

        <!-- Message angles -->
        <div class="sim-angles-block">
          <div class="sim-angles-label">Outreach angles to test</div>
          <div class="sim-pills">
            <button
              v-for="n in [2, 3, 4, 5]"
              :key="n"
              class="sim-pill"
              :class="{ active: numMessages === n }"
              @click="numMessages = n"
              type="button"
            >
              <span class="sim-pill-num">{{ n }}</span>
              <span class="sim-pill-label">{{ angleNames[n] }}</span>
            </button>
          </div>
        </div>

        <!-- Audience: buyer mix, colors, regions, behavior -->
        <div class="sim-audience">
          <AudienceBuilder v-model="audience" :count="numPersonas" />
        </div>

        <!-- Market intelligence for the selected regions -->
        <div class="sim-audience">
          <MarketIntel :regions="audience.regions" :live="audience.live_market !== false" />
        </div>

        <!-- Reaction math -->
        <div class="sim-math-strip">
          <div class="sim-math-item">
            <span class="sim-math-big">{{ numPersonas * numMessages }}</span>
            <span class="sim-math-desc">total reactions</span>
          </div>
          <div class="sim-math-div"></div>
          <div class="sim-math-item">
            <span class="sim-math-big">{{ numPersonas }}</span>
            <span class="sim-math-desc">personas</span>
          </div>
          <div class="sim-math-op">×</div>
          <div class="sim-math-item">
            <span class="sim-math-big">{{ numMessages }}</span>
            <span class="sim-math-desc">angles</span>
          </div>
        </div>

      </div>
    </div>

    <!-- Error toast -->
    <div v-if="submitError" class="sim-error-toast">
      {{ submitError }}
      <button @click="submitError = ''" class="sim-error-close">×</button>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import GTMBriefForm from '../components/GTMBriefForm.vue'
import HeroViz from '../components/HeroViz.vue'
import AudienceBuilder from '../components/AudienceBuilder.vue'
import MarketIntel from '../components/MarketIntel.vue'
import { defaultAudience } from '../utils/audience.js'
import { submitGTMBrief, getGTMPreview } from '../api/gtm.js'
import { setGTMBrief, setSimulationPreview } from '../store/gtmSimulation.js'
import { MOCK_GTM_PREVIEW } from '../mock/gtm_preview.js'
import { DEMO_BRIEF } from '../mock/gtm_demo.js'
import { estimateRun } from '../utils/gtmFormatter.js'

const router = useRouter()

const loading    = ref(false)
const submitError = ref('')
const demoData   = ref(null)
const numPersonas = ref(12)
const numMessages = ref(3)

// Audience settings are a per-browser convenience: remembered locally, sent with the brief.
const AUDIENCE_KEY = 'gtm.audience.v1'
function loadAudience() {
  try {
    const saved = JSON.parse(localStorage.getItem(AUDIENCE_KEY) || 'null')
    if (saved && saved.mix && saved.colors) {
      const base = defaultAudience()
      return { ...base, ...saved, traits: { ...base.traits, ...(saved.traits || {}) } }
    }
  } catch (_) {}
  return defaultAudience()
}
const audience = ref(loadAudience())
watch(audience, (val) => {
  try { localStorage.setItem(AUDIENCE_KEY, JSON.stringify(val)) } catch (_) {}
}, { deep: true })

const angleNames = { 2: 'Pain · ROI', 3: '+Curiosity', 4: '+Feature', 5: '+Social' }

const estimate = computed(() => estimateRun(numPersonas.value, numMessages.value))
const timeEstimate = computed(() => estimate.value.time)
const costEstimate = computed(() => estimate.value.cost)

const fromStudio = ref(false)
onMounted(() => {
  try {
    const prefill = JSON.parse(localStorage.getItem('gtm.prefill.v1') || 'null')
    if (prefill) {
      demoData.value = prefill
      fromStudio.value = true
      localStorage.removeItem('gtm.prefill.v1')
    }
  } catch (_) {}
})

function loadDemo() {
  demoData.value = { ...DEMO_BRIEF }
}

async function handleSubmit(payload) {
  loading.value = true
  submitError.value = ''

  const fullPayload = {
    ...payload,
    num_personas: numPersonas.value,
    num_messages: numMessages.value,
    audience: audience.value,
  }

  try {
    setGTMBrief(fullPayload)
    const res = await submitGTMBrief(fullPayload)
    if (!res.success) throw new Error(res.error || 'Submission failed')

    const briefId = res.data.brief_id
    let preview = MOCK_GTM_PREVIEW
    try {
      const pr = await getGTMPreview(briefId)
      if (pr.success && pr.data) preview = pr.data
    } catch (_) {}

    setSimulationPreview(briefId, preview)
    router.push({ name: 'GTMPersonas', params: { briefId } })
  } catch (err) {
    submitError.value = err.message || 'Submission failed. Check your connection and try again.'
    loading.value = false
  }
}
</script>

<style scoped>
/* ── Page shell ─────────────────────────────────────────── */
.sim-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  overflow: hidden;
}

/* ── Navbar ─────────────────────────────────────────────── */
.sim-nav-studio { font-size: 12px; color: var(--text-secondary); text-decoration: none; margin-right: 12px; }
.sim-nav-studio:hover { color: var(--text-primary); }
.sim-prefill {
  font-size: 12.5px; line-height: 1.5; color: #93c5fd; background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; padding: 10px 14px; margin-bottom: 16px;
}
.sim-nav {
  height: 52px;
  flex-shrink: 0;
  background: rgba(0,0,0,0.85);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border-subtle);
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 0 24px;
  z-index: 20;
}

.sim-nav-brand {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  color: var(--text-primary);
  text-decoration: none;
}

.sim-nav-center {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-family: var(--font-mono);
}

.sim-nav-step-item {
  color: var(--text-tertiary);
  padding: 3px 8px;
  border-radius: 4px;
  transition: color 0.15s;
}

.sim-nav-step-item.active {
  color: var(--accent);
  background: var(--accent-dim);
}

.sim-nav-arrow { color: var(--border-muted); font-size: 10px; }

.sim-nav-right { display: flex; justify-content: flex-end; }

.sim-nav-demo {
  font-size: 11px;
  font-family: var(--font-sans);
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border-muted);
  border-radius: 5px;
  padding: 5px 12px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.sim-nav-demo:hover { color: var(--accent); border-color: var(--accent); }

/* ── Body ───────────────────────────────────────────────── */
.sim-body {
  display: grid;
  grid-template-columns: 1fr 440px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── Left panel ─────────────────────────────────────────── */
.sim-left {
  border-right: 1px solid var(--border-subtle);
  overflow-y: auto;
  padding: 32px 40px 80px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.sim-left-top {
  margin-bottom: 24px;
}

.sim-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.sim-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 480px;
}

/* ── Right panel ────────────────────────────────────────── */
.sim-right {
  background: var(--bg-surface);
  overflow-y: auto;
  padding: 20px 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Scale header */
.sim-scale-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.sim-scale-label {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
}

.sim-scale-hint {
  font-size: 10px;
  color: var(--text-tertiary);
}

/* Count display */
.sim-count-block {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 14px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sim-count-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
}

.sim-count-display {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.sim-count-num {
  font-family: var(--font-mono);
  font-size: 36px;
  font-weight: 800;
  color: var(--accent);
  letter-spacing: -0.04em;
  line-height: 1;
}

.sim-count-unit {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  margin-bottom: 3px;
}

.sim-count-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.sim-count-time {
  font-size: 11px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.sim-count-cost {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

/* Slider */
.sim-slider {
  width: 100%;
  height: 5px;
  -webkit-appearance: none;
  appearance: none;
  background: linear-gradient(to right, var(--accent) 0%, var(--accent) calc(((var(--v,12) - 6) / 494) * 100%), var(--border-muted) calc(((var(--v,12) - 6) / 494) * 100%), var(--border-muted) 100%);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
  border: none;
  padding: 0;
}
.sim-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  border: 3px solid var(--bg-card);
  box-shadow: 0 0 8px rgba(59,130,246,0.5);
}
.sim-slider::-moz-range-thumb {
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--accent);
  border: 3px solid var(--bg-card);
}

.sim-slider-ticks {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  margin-top: -2px;
}

/* Message angle pills */
.sim-angles-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sim-angles-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-tertiary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.sim-pills {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}

.sim-pill {
  padding: 8px 4px;
  border: 1px solid var(--border-muted);
  border-radius: 7px;
  background: var(--bg-card);
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.sim-pill.active {
  border-color: var(--accent);
  background: var(--accent-dim);
}

.sim-pill-num {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 800;
  color: var(--text-secondary);
  line-height: 1;
}

.sim-pill-label {
  font-size: 8px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.sim-pill.active .sim-pill-num  { color: var(--accent); }
.sim-pill.active .sim-pill-label { color: rgba(59,130,246,0.7); }

/* Agent viz section */
.sim-agent-section {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sim-agent-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.sim-agent-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-tertiary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.sim-agent-hint {
  font-size: 9px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.sim-viz-wrap {
  height: 300px;
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
}

.sim-agent-section {
  position: sticky;
  top: -20px;
  z-index: 5;
  margin: -20px -20px 0;
  padding: 16px 20px 14px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
}

.sim-audience {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-card);
  padding: 16px;
}

/* Math strip */
.sim-math-strip {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.sim-math-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}

.sim-math-big {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.03em;
  line-height: 1;
}

.sim-math-desc {
  font-size: 9px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.sim-math-div {
  flex: 1;
  height: 1px;
  background: var(--border-subtle);
}

.sim-math-op {
  font-size: 14px;
  color: var(--text-tertiary);
  font-weight: 700;
}

/* Error toast */
.sim-error-toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(248,113,113,0.12);
  border: 1px solid rgba(248,113,113,0.3);
  border-radius: 8px;
  padding: 12px 20px;
  font-size: 13px;
  color: var(--red);
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 100;
  max-width: 480px;
}

.sim-error-close {
  background: none;
  border: none;
  color: var(--red);
  font-size: 18px;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

/* ── Responsive ─────────────────────────────────────────── */
@media (max-width: 900px) {
  .sim-page { height: auto; overflow: auto; }
  .sim-body { grid-template-columns: 1fr; overflow: auto; }
  .sim-right { border-top: 1px solid var(--border-subtle); }
  .sim-agent-section { position: static; }
  .sim-left { overflow: visible; padding: 24px 20px 40px; }
  .sim-nav-center { display: none; }
}
</style>
