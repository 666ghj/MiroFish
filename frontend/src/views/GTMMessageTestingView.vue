<template>
  <div class="mt-page">

    <!-- Header -->
    <header class="mt-header">
      <div class="mt-brand" @click="goHome">GTM SIM LAB</div>

      <div v-if="brief" class="mt-brief-summary">
        <span class="mt-brief-product">{{ brief.product_name }}</span>
        <span class="mt-brief-sep">·</span>
        <span class="mt-brief-goal">{{ goalLabel }}</span>
      </div>

      <div class="mt-step-badge">Step 3 / 5 — Message Testing</div>
    </header>

    <main class="mt-main">

      <!-- Loading state -->
      <div v-if="viewState === 'loading'" class="mt-loading">
        <div class="mt-loading-title">Simulating Buyer Reactions</div>
        <div class="mt-steps">
          <div
            v-for="(step, i) in loadingSteps"
            :key="i"
            class="mt-step"
            :class="{ done: i < loadingStep, active: i === loadingStep }"
          >
            <span class="mt-step-dot">{{ i < loadingStep ? '–' : i === loadingStep ? '>' : '·' }}</span>
            <span class="mt-step-label">{{ step }}</span>
          </div>
        </div>
        <div class="mt-loading-sub">
          Each persona responds independently based on their goals, objections, and skepticism level.
        </div>
      </div>

      <!-- Error state -->
      <div v-else-if="viewState === 'error'" class="mt-error">
        <div class="mt-error-icon">!</div>
        <div class="mt-error-title">Simulation Error</div>
        <div class="mt-error-msg">{{ errorMsg || 'Message simulation failed. Loading example results so you can explore the UI.' }}</div>
        <button class="mt-btn-primary" @click="retryLoad">Retry</button>
      </div>

      <!-- Ready state -->
      <div v-else-if="viewState === 'ready'" class="mt-content">

        <!-- Mock data warning -->
        <div v-if="isMockData" class="mt-mock-banner">
          {{ mockReason
            ? `Sample data, not your results — the simulation could not run (${mockReason}). These reactions were not generated from your brief.`
            : 'Demo mode — backend unreachable. Showing sample messages and reactions, not generated from your brief.' }}
          <a href="https://github.com/sanketmuchhala/GTM-SImulator#quick-start" target="_blank" rel="noopener" class="mt-mock-link">Run locally →</a>
        </div>

        <!-- Winner banner -->
        <div class="mt-winner-banner" v-if="winner">
          <div class="mt-winner-left">
            <span class="mt-winner-star">WINNER</span>
            <div>
              <div class="mt-winner-label">WINNING ANGLE</div>
              <div class="mt-winner-angle">{{ angleLabel(winner.winner_angle) }}</div>
            </div>
          </div>
          <div class="mt-winner-stats" v-if="winnerSummary">
            <span>Avg interest <strong>{{ winnerSummary.average_interest_score }}</strong></span>
            <span class="mt-sep">·</span>
            <span class="mt-pos">{{ winnerSummary.positive_count }} interested</span>
            <span class="mt-sep">·</span>
            <span class="mt-neu">→ {{ winnerSummary.neutral_count }} neutral</span>
            <span class="mt-sep">·</span>
            <span class="mt-neg">{{ winnerSummary.negative_count }} objections</span>
          </div>
          <div v-if="winner.runs > 1" class="mt-stability" :class="`mt-stability--${winner.stability}`">
            Won {{ winner.run_winners.filter(id => id === winner.winner_message_id).length }} of {{ winner.runs }} simulation runs
            · {{ stabilityLabel(winner.stability) }}
          </div>
          <div v-if="winner.close_test" class="mt-close-test">
            {{ winner.note }}
          </div>
        </div>

        <!-- 3-column message cards -->
        <div class="mt-cards">
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="mt-card"
            :class="{
              'mt-card--winner': winner && winner.winner_message_id === msg.id,
              'mt-card--selected': selectedAngle === msg.angle,
            }"
            @click="selectedAngle = msg.angle"
          >
            <div v-if="winner && winner.winner_message_id === msg.id" class="mt-card-winner-strip">
              WINNER
            </div>
            <div class="mt-card-header">
              <span class="mt-card-angle">{{ angleLabel(msg.angle) }}</span>
              <span class="mt-card-avg" v-if="summaryFor(msg.id)">
                {{ summaryFor(msg.id).average_interest_score }} avg
              </span>
            </div>
            <div class="mt-card-subject">{{ msg.subject_line }}</div>
            <div class="mt-card-body">{{ msg.body }}</div>
            <div class="mt-card-reasoning">{{ msg.target_persona_reasoning }}</div>
            <div class="mt-card-counts" v-if="summaryFor(msg.id)">
              <span class="mt-pos">{{ summaryFor(msg.id).positive_count }} interested</span>
              <span class="mt-neu">→ {{ summaryFor(msg.id).neutral_count }}</span>
              <span class="mt-neg">{{ summaryFor(msg.id).negative_count }} objections</span>
            </div>
            <div v-if="summaryFor(msg.id)" class="mt-card-rec">
              {{ summaryFor(msg.id).recommendation }}
            </div>
          </div>
        </div>

        <!-- Reaction table -->
        <div class="mt-reactions-section">
          <div class="mt-reactions-header">
            <div class="mt-reactions-title">Buyer Reactions</div>
            <div class="mt-angle-toggle">
              <button
                v-for="msg in messages"
                :key="msg.id"
                class="mt-toggle-btn"
                :class="{ active: selectedAngle === msg.angle }"
                @click="selectedAngle = msg.angle"
              >
                {{ angleLabel(msg.angle) }}
                <span v-if="winner && winner.winner_message_id === msg.id" class="mt-winner-tag"> WINNER</span>
              </button>
            </div>
          </div>

          <div class="mt-table-wrapper">
            <table class="mt-table">
              <thead>
                <tr>
                  <th>Persona</th>
                  <th>Interest</th>
                  <th>Clarity</th>
                  <th>Trust</th>
                  <th>Verdict</th>
                  <th>Simulated Reply</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="rxn in selectedReactions"
                  :key="rxn.id"
                  :class="`mt-row--${rxn.verdict}`"
                >
                  <td class="mt-td-persona">
                    <div class="mt-persona-name">{{ personaName(rxn.persona_id) }}</div>
                    <div class="mt-persona-title">{{ personaTitle(rxn.persona_id) }}</div>
                  </td>
                  <td class="mt-td-score">
                    <div class="mt-score-bar-wrap">
                      <div
                        class="mt-score-bar"
                        :class="rxn.interest_score >= 7 ? 'mt-score-bar--high' : rxn.interest_score >= 5 ? 'mt-score-bar--mid' : 'mt-score-bar--low'"
                        :style="{ width: rxn.interest_score * 10 + '%' }"
                      ></div>
                    </div>
                    <span class="mt-score-val">{{ rxn.interest_score.toFixed(1) }}</span>
                  </td>
                  <td class="mt-td-score">
                    <span class="mt-score-val">{{ rxn.clarity_score.toFixed(1) }}</span>
                  </td>
                  <td class="mt-td-score">
                    <span class="mt-score-val">{{ rxn.trust_score.toFixed(1) }}</span>
                  </td>
                  <td>
                    <span class="mt-verdict" :class="`mt-verdict--${rxn.verdict}`">
                      {{ rxn.verdict === 'positive' ? 'Interested' : rxn.verdict === 'neutral' ? 'Neutral' : 'Objection' }}
                    </span>
                  </td>
                  <td class="mt-td-reply">{{ rxn.simulated_reply }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Objections + triggers for selected angle -->
          <div class="mt-insights" v-if="summaryFor(selectedMessageId)">
            <div class="mt-insight-block">
              <div class="mt-insight-label">Objections Raised</div>
              <ul class="mt-insight-list">
                <li v-for="obj in summaryFor(selectedMessageId).top_objections" :key="obj">{{ obj }}</li>
              </ul>
            </div>
            <div class="mt-insight-block">
              <div class="mt-insight-label">Best Match</div>
              <div class="mt-insight-chips">
                <span v-for="pid in summaryFor(selectedMessageId).best_fit_personas" :key="pid" class="mt-chip mt-chip--green">
                  {{ personaName(pid) || pid }}
                </span>
              </div>
            </div>
            <div class="mt-insight-block">
              <div class="mt-insight-label">Weakest Match</div>
              <div class="mt-insight-chips">
                <span v-for="pid in summaryFor(selectedMessageId).worst_fit_personas" :key="pid" class="mt-chip mt-chip--red">
                  {{ personaName(pid) || pid }}
                </span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </main>

    <!-- Footer nav -->
    <footer class="mt-footer" v-if="viewState !== 'loading'">
      <button class="mt-btn-ghost" @click="goToPersonas">← Edit Personas</button>
      <button class="mt-btn-primary" @click="continueToReport">Continue to GTM Report →</button>
    </footer>

  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getGTMState, getPersonas, setMessageResults, getMessageResults } from '../store/gtmSimulation'
import { getGTMBrief } from '../api/gtm'
import { generateMessages, getMessages, generateReactions, getReactions } from '../api/gtm'
import { MOCK_MESSAGES, MOCK_REACTIONS_RESULT } from '../mock/gtm_messages'

const router = useRouter()
const route = useRoute()
const briefId = computed(() => route.params.briefId)

// State
const viewState = ref('loading')
const errorMsg = ref('')
const brief = ref(null)
const isMockData = ref(false)
const mockReason = ref(null)

function stabilityLabel(stability) {
  return {
    stable: 'stable signal',
    leaning: 'leaning, not conclusive',
    unstable: 'unstable — treat as a tie',
  }[stability] ?? ''
}
const messages = ref([])
const reactions = ref([])
const summaries = ref([])
const winner = ref(null)
const personas = ref([])
const selectedAngle = ref('pain_first')
const totalPersonas = ref(12)

// Loading animation
const loadingSteps = [
  'Loading 12 buyer personas...',
  'Generating 3 message variants...',
  'Simulating 36 buyer reactions...',
  'Scoring results...',
]
const loadingStep = ref(0)
let loadingTimer = null

function startLoadingAnimation() {
  loadingStep.value = 0
  loadingTimer = setInterval(() => {
    if (loadingStep.value < loadingSteps.length - 1) {
      loadingStep.value++
    }
  }, 1800)
}

function stopLoadingAnimation() {
  if (loadingTimer) {
    clearInterval(loadingTimer)
    loadingTimer = null
  }
  loadingStep.value = loadingSteps.length
}

onUnmounted(() => {
  if (loadingTimer) clearInterval(loadingTimer)
})

// Computed helpers
const goalLabel = computed(() => {
  const map = {
    first_10_customers: 'First 10 Customers',
    expand_segment: 'Expand Segment',
    new_market: 'New Market',
    reactivate_churned: 'Reactivate Churned',
  }
  return map[brief.value?.gtm_goal] ?? brief.value?.gtm_goal ?? ''
})

const winnerSummary = computed(() =>
  winner.value ? summaries.value.find(s => s.message_id === winner.value.winner_message_id) : null
)

const selectedMessageId = computed(() => {
  const msg = messages.value.find(m => m.angle === selectedAngle.value)
  return msg?.id ?? null
})

const selectedReactions = computed(() =>
  reactions.value.filter(r => r.message_id === selectedMessageId.value)
)

const personaMap = computed(() => {
  const m = {}
  for (const p of personas.value) {
    m[p.id] = p
  }
  return m
})

function personaName(pid) {
  return personaMap.value[pid]?.name ?? pid
}

function personaTitle(pid) {
  return personaMap.value[pid]?.title ?? ''
}

function summaryFor(messageId) {
  return summaries.value.find(s => s.message_id === messageId) ?? null
}

function angleLabel(angle) {
  return {
    pain_first: 'Pain-First',
    roi_first: 'ROI-First',
    curiosity_first: 'Curiosity-First',
  }[angle] ?? angle
}

// Data loading
async function loadBrief() {
  const state = getGTMState()
  if (state.brief) {
    brief.value = state.brief
    return
  }
  try {
    const res = await getGTMBrief(briefId.value)
    if (res.data?.success) brief.value = res.data.data
    else if (res.success) brief.value = res.data
  } catch (_) {}
}

async function loadAll() {
  startLoadingAnimation()

  try {
    // 1. Load brief (best-effort)
    await loadBrief()

    // 2. Load personas (for name lookup)
    const cachedPersonas = getPersonas()
    if (cachedPersonas?.length) {
      personas.value = cachedPersonas
      totalPersonas.value = cachedPersonas.length
    }

    // 3. Check store cache for messages + reactions
    const cached = getMessageResults()
    if (cached.messages?.length && cached.reactionResult?.reactions?.length) {
      applyResults(cached.messages, cached.reactionResult)
      stopLoadingAnimation()
      viewState.value = 'ready'
      return
    }

    // 4. Fetch or generate messages
    let msgs
    try {
      const msgRes = await generateMessages(briefId.value)
      const msgData = msgRes.data ?? msgRes
      msgs = msgData.data ?? msgData
    } catch (_) {
      msgs = null
    }
    if (!Array.isArray(msgs) || !msgs.length) {
      msgs = MOCK_MESSAGES
      isMockData.value = true
    }

    // 5. Fetch or generate reactions
    let reactionResult
    try {
      const rxnRes = await generateReactions(briefId.value)
      const rxnData = rxnRes.data ?? rxnRes
      reactionResult = rxnData.data ?? rxnData
    } catch (_) {
      reactionResult = null
    }
    if (!reactionResult?.reactions?.length) {
      reactionResult = MOCK_REACTIONS_RESULT
      isMockData.value = true
    }

    // 6. Persist to store
    setMessageResults({ messages: msgs, ...reactionResult })

    applyResults(msgs, reactionResult)
    stopLoadingAnimation()
    viewState.value = 'ready'
  } catch (err) {
    stopLoadingAnimation()
    // Full fallback
    applyResults(MOCK_MESSAGES, MOCK_REACTIONS_RESULT)
    viewState.value = 'ready'
  }
}

function applyResults(msgs, rxnResult) {
  messages.value = msgs
  reactions.value = rxnResult.reactions ?? []
  summaries.value = rxnResult.summaries ?? []
  winner.value = rxnResult.winner ?? null
  if (rxnResult.source === 'mock') {
    isMockData.value = true
    mockReason.value = rxnResult.mock_reason ?? 'LLM unavailable'
  }
  // Default selected angle to winner's angle or first
  if (winner.value?.winner_angle) {
    selectedAngle.value = winner.value.winner_angle
  } else if (msgs.length) {
    selectedAngle.value = msgs[0].angle
  }
}

async function retryLoad() {
  viewState.value = 'loading'
  errorMsg.value = ''
  await loadAll()
}

function goHome() {
  router.push({ name: 'Home' })
}

function goToPersonas() {
  router.push({ name: 'GTMPersonas', params: { briefId: briefId.value } })
}

function continueToReport() {
  router.push({ name: 'GTMReport', params: { briefId: briefId.value } })
}

// Init
loadAll()
</script>

<style scoped>
.mt-page {
  min-height: 100vh;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  display: flex;
  flex-direction: column;
}

/* Header */
.mt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 32px;
  border-bottom: 1px solid #1f1f1f;
  background: #0a0a0a;
  position: sticky;
  top: 0;
  z-index: 10;
}

.mt-brand {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--accent);
  cursor: pointer;
}

.mt-brief-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.mt-brief-product { font-weight: 600; color: var(--text-primary); }
.mt-brief-sep     { color: var(--border-muted); }
.mt-brief-goal    { color: var(--text-secondary); }

.mt-step-badge {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent);
  background: var(--accent-dim);
  border: 1px solid rgba(59, 130, 246, 0.25);
  padding: 4px 10px;
  border-radius: 4px;
}

/* Main */
.mt-main { flex: 1; padding: 32px; max-width: 1280px; margin: 0 auto; width: 100%; box-sizing: border-box; }

/* Loading */
.mt-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  gap: 24px;
}

.mt-loading-title {
  font-size: 22px;
  font-weight: 700;
  color: #ededed;
}

.mt-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 320px;
}

.mt-step {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #737373;
  transition: color 0.3s;
}

.mt-step.done { color: #4ade80; }
.mt-step.active { color: var(--accent); }

.mt-step-dot { font-size: 10px; width: 14px; text-align: center; }

.mt-loading-sub {
  font-size: 13px;
  color: #737373;
}

/* Error */
.mt-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 0;
}

.mt-error-icon { font-size: 36px; }
.mt-error-title { font-size: 18px; font-weight: 700; color: #ededed; }
.mt-error-msg { font-size: 14px; color: #a3a3a3; text-align: center; max-width: 400px; }

/* Winner banner — refined, not overwhelming */
.mt-mock-banner {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 12px;
  color: var(--red);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.mt-stability {
  flex-basis: 100%;
  font-size: 12px;
  color: #a3a3a3;
}
.mt-stability--stable { color: var(--green, #4ade80); }
.mt-stability--unstable { color: var(--red, #f87171); }
.mt-mock-link {
  color: var(--red);
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
  margin-left: auto;
}

.mt-winner-banner {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
  padding: 16px 20px;
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.mt-winner-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mt-winner-star {
  font-size: 18px;
  color: var(--amber);
}

.mt-winner-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--accent);
  text-transform: uppercase;
}

.mt-winner-angle {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
}

.mt-winner-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.mt-sep { color: var(--border-muted); }

.mt-close-test {
  font-size: 12px;
  color: var(--amber);
  border-top: 1px solid rgba(245, 158, 11, 0.2);
  padding-top: 8px;
  margin-top: 4px;
  flex-basis: 100%;
}

/* Message cards */
.mt-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 36px;
}

.mt-card {
  background: #121212;
  border: 1px solid #1f1f1f;
  border-radius: 10px;
  padding: 20px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.mt-card:hover {
  border-color: #3d3d3d;
}

.mt-card--winner {
  border: 2px solid var(--accent);
  background: var(--bg-card);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.08);
}

.mt-card-winner-strip {
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-align: center;
  padding: 4px;
  margin: -20px -20px 12px -20px;
  border-radius: 8px 8px 0 0;
}

.mt-card--selected {
  border-color: var(--accent);
  outline: 1px solid rgba(59, 130, 246, 0.3);
}

.mt-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.mt-card-star { color: #f59e0b; font-size: 14px; }

.mt-card-angle {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--accent);
  text-transform: uppercase;
  flex: 1;
}

.mt-card-avg {
  font-size: 13px;
  font-weight: 600;
  color: #ededed;
}

.mt-card-subject {
  font-size: 13px;
  font-weight: 600;
  color: #ededed;
  margin-bottom: 8px;
}

.mt-card-body {
  font-size: 12px;
  color: #a3a3a3;
  line-height: 1.6;
  margin-bottom: 10px;
  white-space: pre-line;
}

.mt-card-reasoning {
  font-size: 11px;
  color: #737373;
  font-style: italic;
  margin-bottom: 10px;
}

.mt-card-counts {
  display: flex;
  gap: 10px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.mt-card-rec {
  font-size: 11px;
  color: #8a8a8a;
  border-top: 1px solid #1f1f1f;
  padding-top: 8px;
}

/* Verdict colors */
.mt-pos { color: #4ade80; }
.mt-neu { color: #f59e0b; }
.mt-neg { color: #f87171; }

/* Reactions section */
.mt-reactions-section {
  background: #121212;
  border: 1px solid #1f1f1f;
  border-radius: 12px;
  padding: 24px;
}

.mt-reactions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.mt-reactions-title {
  font-size: 15px;
  font-weight: 700;
  color: #ededed;
}

.mt-angle-toggle {
  display: flex;
  gap: 6px;
}

.mt-toggle-btn {
  background: transparent;
  border: 1px solid #2e2e2e;
  color: #a3a3a3;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
}

.mt-toggle-btn:hover {
  border-color: var(--accent);
  color: #ededed;
}

.mt-toggle-btn.active {
  background: rgba(59, 130, 246, 0.15);
  border-color: var(--accent);
  color: #ededed;
}

/* Table */
.mt-table-wrapper {
  overflow-x: auto;
  margin-bottom: 20px;
}

.mt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.mt-table th {
  text-align: left;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #737373;
  border-bottom: 1px solid #1f1f1f;
}

.mt-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #1a1a1a;
  color: #c8c8e0;
  vertical-align: middle;
}

.mt-row--positive td { border-left: 2px solid #4ade80; }
.mt-row--neutral td { border-left: 2px solid #f59e0b; }
.mt-row--negative td { border-left: 2px solid #f87171; }

.mt-row--positive td:not(:first-child) { border-left: none; }
.mt-row--neutral td:not(:first-child) { border-left: none; }
.mt-row--negative td:not(:first-child) { border-left: none; }

.mt-td-persona { min-width: 150px; }
.mt-persona-name { font-weight: 600; color: #ededed; font-size: 13px; }
.mt-persona-title { font-size: 11px; color: #8a8a8a; margin-top: 2px; }

.mt-td-score {
  min-width: 80px;
}

.mt-score-bar-wrap {
  height: 6px;
  background: var(--border-subtle);
  border-radius: 3px;
  width: 64px;
  display: inline-block;
  margin-right: 6px;
  vertical-align: middle;
}

.mt-score-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.mt-score-bar--high { background: #4ade80; }
.mt-score-bar--mid  { background: #f59e0b; }
.mt-score-bar--low  { background: #f87171; }

.mt-score-val {
  font-size: 13px;
  font-weight: 600;
  color: #ededed;
  vertical-align: middle;
}

.mt-verdict {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
}

.mt-verdict--positive {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
}

.mt-verdict--neutral {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.mt-verdict--negative {
  background: rgba(248, 113, 113, 0.12);
  color: #f87171;
}

.mt-td-reply {
  font-size: 12px;
  color: #a3a3a3;
  font-style: italic;
  min-width: 200px;
  max-width: 300px;
}

/* Insights — grouped conclusion block */
.mt-insights {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 16px;
  margin-top: 4px;
  background: var(--bg-elevated);
  border-radius: 0 0 10px 10px;
  border-top: 1px solid var(--border-subtle);
}

.mt-insight-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-tertiary);
  margin-bottom: 8px;
  text-transform: uppercase;
}

.mt-insight-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.mt-insight-list li {
  font-size: 12px;
  color: var(--text-secondary);
  padding-left: 8px;
  border-left: 2px solid var(--border-muted);
  line-height: 1.4;
}

.mt-insight-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mt-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
}

.mt-chip--green {
  background: rgba(74, 222, 128, 0.1);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.2);
}

.mt-chip--red {
  background: rgba(248, 113, 113, 0.1);
  color: #f87171;
  border: 1px solid rgba(248, 113, 113, 0.2);
}

/* Footer */
.mt-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 32px;
  border-top: 1px solid #1f1f1f;
  background: #0a0a0a;
}

/* Buttons */
.mt-btn-primary {
  background: var(--accent);
  color: #fff;
  border: none;
  font-size: 14px;
  font-weight: 600;
  padding: 10px 22px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.mt-btn-primary:hover {
  background: #5254cc;
}

.mt-btn-ghost {
  background: transparent;
  color: #a3a3a3;
  border: 1px solid #2e2e2e;
  font-size: 14px;
  font-weight: 500;
  padding: 10px 18px;
  border-radius: 8px;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.mt-btn-ghost:hover {
  color: #ededed;
  border-color: var(--accent);
}

/* Responsive */
@media (max-width: 900px) {
  .mt-cards {
    grid-template-columns: 1fr;
  }
  .mt-insights {
    grid-template-columns: 1fr;
  }
  .mt-header {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
