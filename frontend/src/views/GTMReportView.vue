<template>
  <div class="gr-page">

    <!-- Header -->
    <header class="gr-header">
      <div class="gr-brand" @click="goHome">GTM SIM LAB</div>

      <div v-if="brief" class="gr-brief-summary">
        <span class="gr-brief-product">{{ brief.product_name }}</span>
        <span class="gr-brief-sep">·</span>
        <span class="gr-brief-goal">{{ goalLabel }}</span>
      </div>

      <div class="gr-step-badge">Step 4 / 5 — GTM Report</div>
    </header>

    <main class="gr-main">

      <!-- Loading state -->
      <div v-if="viewState === 'loading'" class="gr-loading">
        <div class="gr-loading-title">Generating GTM Report</div>
        <div class="gr-steps">
          <div
            v-for="(step, i) in loadingSteps"
            :key="i"
            class="gr-step"
            :class="{ done: i < loadingStep, active: i === loadingStep }"
          >
            <span class="gr-step-dot">{{ i < loadingStep ? '–' : i === loadingStep ? '>' : '·' }}</span>
            <span class="gr-step-label">{{ step }}</span>
          </div>
        </div>
        <div class="gr-loading-sub">Building your personalized GTM playbook from 36 simulated buyer reactions.</div>
      </div>

      <!-- Error state -->
      <div v-else-if="viewState === 'error'" class="gr-error">
        <div class="gr-error-icon">!</div>
        <div class="gr-error-title">Report Generation Failed</div>
        <div class="gr-error-msg">{{ errorMsg || 'Report generation failed. Showing a sample report so you can preview the output.' }}</div>
        <button class="gr-btn-primary" @click="retryLoad">Retry</button>
      </div>

      <!-- Ready state -->
      <div v-else-if="viewState === 'ready'" class="gr-content">

        <!-- Mock data warning -->
        <div v-if="isMockData" class="gr-mock-banner">
          Demo mode — backend unreachable. This report is sample data, not generated from your brief.
          <a href="https://github.com/sanketmuchhala/GTM-SImulator#quick-start" target="_blank" rel="noopener" class="gr-mock-link">Run locally →</a>
        </div>

        <!-- Metric strip -->
        <div class="gr-metric-strip">
          <div class="gr-metric">
            <span class="gr-metric-val">{{ icpConfidencePct }}%</span>
            <span class="gr-metric-label">ICP Fit</span>
          </div>
          <div class="gr-metric-sep"></div>
          <div class="gr-metric">
            <span class="gr-metric-val" :class="`gr-readiness-val--${report.buyer_readiness?.label}`">
              {{ report.buyer_readiness?.score }}/10
            </span>
            <span class="gr-metric-label">Buyer Readiness</span>
          </div>
          <div class="gr-metric-sep"></div>
          <div class="gr-metric">
            <span class="gr-metric-val">{{ angleLabel(report.winning_message?.angle) }}</span>
            <span class="gr-metric-label">Best Angle</span>
          </div>
          <div class="gr-metric-sep"></div>
          <div class="gr-metric">
            <span class="gr-metric-val">{{ report.seven_day_experiment?.length || 7 }}-Day</span>
            <span class="gr-metric-label">Experiment Ready</span>
          </div>
        </div>

        <!-- Executive Summary -->
        <section class="gr-section gr-summary-section">
          <div class="gr-section-label">Executive Summary</div>
          <div class="gr-summary-text">{{ report.executive_summary }}</div>
          <div class="gr-confidence-note">
            Strong directional signal — based on 36 simulated buyer reactions.
            Validate with real outbound before committing to this strategy.
          </div>
        </section>

        <!-- ICP + Buyer Readiness row -->
        <div class="gr-two-col">

          <!-- Best ICP -->
          <section class="gr-card gr-icp-card">
            <div class="gr-card-label">Best ICP Segment</div>
            <div class="gr-icp-segment">{{ report.best_icp?.segment }}</div>
            <div class="gr-icp-confidence" v-if="report.best_icp?.confidence_score !== undefined">
              <div class="gr-conf-bar-wrap">
                <div class="gr-conf-bar" :style="{ width: Math.round((report.best_icp.confidence_score || 0) * 100) + '%' }"></div>
              </div>
              <span class="gr-conf-label">{{ Math.round((report.best_icp.confidence_score || 0) * 100) }}% ICP fit</span>
            </div>
            <div class="gr-icp-reasoning">{{ report.best_icp?.reasoning }}</div>
          </section>

          <!-- Buyer Readiness -->
          <section class="gr-card gr-readiness-card">
            <div class="gr-card-label">Buyer Readiness</div>
            <div class="gr-readiness-score-row">
              <div class="gr-readiness-gauge">
                <div
                  class="gr-readiness-fill"
                  :class="`gr-readiness--${report.buyer_readiness?.label}`"
                  :style="{ width: ((report.buyer_readiness?.score || 0) / 10 * 100) + '%' }"
                ></div>
              </div>
              <span class="gr-readiness-num">{{ report.buyer_readiness?.score }}</span>
              <span class="gr-readiness-denom">&nbsp;/ 10</span>
            </div>
            <div
              class="gr-readiness-label-badge"
              :class="`gr-readiness--${report.buyer_readiness?.label}`"
            >
              {{ (report.buyer_readiness?.label || '').toUpperCase() }}
            </div>
            <div class="gr-readiness-reasoning">{{ report.buyer_readiness?.reasoning }}</div>
          </section>
        </div>

        <!-- Winning Message -->
        <section class="gr-card gr-winner-card">
          <div class="gr-card-label">
            <span class="gr-winner-star">WINNER</span>
            Winning Message — {{ angleLabel(report.winning_message?.angle) }}
            <span class="gr-winner-score">{{ report.winning_message?.average_score }} avg</span>
          </div>
          <div class="gr-winner-subject">{{ report.winning_message?.recommended_subject_line }}</div>
          <div class="gr-winner-body">{{ report.winning_message?.recommended_body }}</div>
          <div class="gr-winner-reasoning" v-if="report.winning_message?.reasoning">
            <span class="gr-why-label">Why it wins:</span> {{ report.winning_message.reasoning }}
          </div>
        </section>

        <!-- Objections + Risk Signals row -->
        <div class="gr-two-col">

          <!-- Top Objections -->
          <section class="gr-card gr-objections-card">
            <div class="gr-card-label">Top Objections</div>
            <div
              v-for="(obj, i) in report.top_objections"
              :key="i"
              class="gr-objection-item"
            >
              <div class="gr-objection-header">
                <span class="gr-objection-text">{{ obj.objection }}</span>
                <span class="gr-objection-freq">×{{ obj.frequency }}</span>
              </div>
              <div class="gr-objection-response" v-if="obj.suggested_response">
                <span class="gr-response-label">Response:</span> {{ obj.suggested_response }}
              </div>
            </div>
          </section>

          <!-- Risk Signals -->
          <section class="gr-card gr-risks-card">
            <div class="gr-card-label">Risk Signals</div>
            <div
              v-for="(risk, i) in report.risk_signals"
              :key="i"
              class="gr-risk-item"
              :class="`gr-risk-item--${risk.severity}`"
            >
              <div class="gr-risk-header">
                <span class="gr-risk-sev" :class="`gr-sev--${risk.severity}`">
                  {{ risk.severity?.toUpperCase() }}
                </span>
                <span class="gr-risk-signal">{{ risk.signal }}</span>
              </div>
              <div class="gr-risk-mitigation" v-if="risk.mitigation">
                {{ risk.mitigation }}
              </div>
            </div>
          </section>
        </div>

        <!-- Recommended Workflow -->
        <section class="gr-card gr-workflow-card">
          <div class="gr-card-label">{{ report.recommended_workflow?.title || 'Recommended Workflow' }}</div>
          <ol class="gr-workflow-steps">
            <li
              v-for="(step, i) in report.recommended_workflow?.steps"
              :key="i"
              class="gr-workflow-step"
            >
              {{ step }}
            </li>
          </ol>
        </section>

        <!-- 7-Day Experiment -->
        <section class="gr-experiment-section">
          <div class="gr-section-label">7-Day Outbound Experiment</div>
          <div class="gr-day-grid">
            <div
              v-for="day in report.seven_day_experiment"
              :key="day.day"
              class="gr-day-card"
              :class="{ 'gr-day-card--active': selectedDay === day.day }"
              @click="selectedDay = day.day"
            >
              <div class="gr-day-num">Day {{ day.day }}</div>
              <div class="gr-day-goal">{{ day.goal }}</div>
            </div>
          </div>
          <div class="gr-day-detail" v-if="selectedDayData">
            <div class="gr-day-detail-header">Day {{ selectedDayData.day }} — {{ selectedDayData.goal }}</div>
            <div class="gr-day-detail-row">
              <span class="gr-day-detail-key">Action</span>
              <span class="gr-day-detail-val">{{ selectedDayData.action }}</span>
            </div>
            <div class="gr-day-detail-row">
              <span class="gr-day-detail-key">Success metric</span>
              <span class="gr-day-detail-val">{{ selectedDayData.success_metric }}</span>
            </div>
          </div>
        </section>

        <!-- Next Experiment -->
        <section class="gr-card gr-next-card" v-if="report.next_experiment">
          <div class="gr-card-label">Next Experiment to Run</div>
          <div class="gr-next-text">{{ report.next_experiment }}</div>
        </section>

        <!-- Simulation note -->
        <div class="gr-sim-note">
          <strong>Simulation note</strong> — All personas, reactions, and scores are AI-generated.
          This is directional signal, not real buyer data. Run real outbound to validate.
        </div>

      </div>
    </main>

    <!-- Footer -->
    <footer class="gr-footer" v-if="viewState !== 'loading'">
      <button class="gr-btn-ghost" @click="goToMessages">← Edit Messages</button>
      <div class="gr-footer-right">
        <button class="gr-btn-primary" @click="handleDownload" :disabled="!report">
          ↓ Download GTM Report
        </button>
        <button class="gr-btn-ghost" @click="handleStartOver">Start Over</button>
      </div>
    </footer>

  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getGTMState, setReport, getReport, resetGTMState, getPersonas, getMessageResults } from '../store/gtmSimulation'
import { getGTMBrief } from '../api/gtm'
import { generateReport } from '../api/gtm'
import { downloadGTMReport } from '../utils/downloadMarkdown'
import { MOCK_REPORT } from '../mock/gtm_report'

const router = useRouter()
const route = useRoute()
const briefId = computed(() => route.params.briefId)

const viewState = ref('loading')
const errorMsg = ref('')
const isMockData = ref(false)
const brief = ref(null)
const report = ref(null)
const selectedDay = ref(1)

// Loading animation
const loadingSteps = [
  'Loading simulation results...',
  'Analyzing buyer insights...',
  'Generating recommendations...',
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

// Computed
const goalLabel = computed(() => {
  const map = {
    first_10_customers: 'First 10 Customers',
    expand_segment: 'Expand Segment',
    new_market: 'New Market',
    reactivate_churned: 'Reactivate Churned',
  }
  return map[brief.value?.gtm_goal] ?? brief.value?.gtm_goal ?? ''
})

const selectedDayData = computed(() =>
  (report.value?.seven_day_experiment || []).find(d => d.day === selectedDay.value) ?? null
)

const icpConfidencePct = computed(() =>
  Math.round((report.value?.best_icp?.confidence_score || 0) * 100)
)

function angleLabel(angle) {
  return { pain_first: 'Pain-First', roi_first: 'ROI-First', curiosity_first: 'Curiosity-First' }[angle] ?? angle
}

// Data loading
async function loadBrief() {
  const state = getGTMState()
  if (state.brief) { brief.value = state.brief; return }
  try {
    const res = await getGTMBrief(briefId.value)
    if (res.data?.success) brief.value = res.data.data
    else if (res.success) brief.value = res.data
  } catch (_) {}
}

async function loadAll() {
  startLoadingAnimation()
  try {
    await loadBrief()

    // Store cache
    const cached = getReport()
    if (cached) {
      report.value = cached
      selectedDay.value = 1
      stopLoadingAnimation()
      viewState.value = 'ready'
      return
    }

    // Generate via API
    let rpt = null
    try {
      const res = await generateReport(briefId.value)
      const resData = res.data ?? res
      rpt = resData.data ?? resData
    } catch (_) {
      rpt = null
    }

    if (!rpt || !rpt.executive_summary) {
      rpt = MOCK_REPORT
      isMockData.value = true
    }

    setReport(rpt)
    report.value = rpt
    selectedDay.value = 1
    stopLoadingAnimation()
    viewState.value = 'ready'
  } catch (err) {
    stopLoadingAnimation()
    // Full fallback
    const fallback = MOCK_REPORT
    setReport(fallback)
    report.value = fallback
    selectedDay.value = 1
    viewState.value = 'ready'
  }
}

async function retryLoad() {
  viewState.value = 'loading'
  errorMsg.value = ''
  await loadAll()
}

function handleDownload() {
  if (!report.value) return
  const { messages, reactionResult } = getMessageResults()
  downloadGTMReport({
    report: report.value,
    brief: brief.value,
    personas: getPersonas(),
    messages,
    reactions: reactionResult?.reactions ?? [],
    summaries: reactionResult?.summaries ?? [],
    winner: reactionResult?.winner ?? null,
  })
}

function handleStartOver() {
  resetGTMState()
  router.push({ name: 'Home' })
}

function goHome() {
  router.push({ name: 'Home' })
}

function goToMessages() {
  router.push({ name: 'GTMMessages', params: { briefId: briefId.value } })
}

// Init
loadAll()
</script>

<style scoped>
.gr-page {
  min-height: 100vh;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  display: flex;
  flex-direction: column;
}

/* Header */
.gr-header {
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

.gr-brand {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--accent);
  cursor: pointer;
}

.gr-brief-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.gr-brief-product { font-weight: 600; color: var(--text-primary); }
.gr-brief-sep     { color: var(--border-muted); }
.gr-brief-goal    { color: var(--text-secondary); }

.gr-step-badge {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent);
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.25);
  padding: 4px 10px;
  border-radius: 4px;
}

/* Main */
.gr-main {
  flex: 1;
  padding: 32px;
  max-width: 1140px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* Loading */
.gr-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  gap: 24px;
}

.gr-loading-title {
  font-size: 22px;
  font-weight: 700;
}

.gr-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 300px;
}

.gr-step {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #737373;
  transition: color 0.3s;
}
.gr-step.done { color: #4ade80; }
.gr-step.active { color: var(--accent); }
.gr-step-dot { font-size: 10px; width: 14px; text-align: center; }

.gr-loading-sub { font-size: 13px; color: #737373; }

/* Error */
.gr-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 0;
}
.gr-error-icon { font-size: 36px; }
.gr-error-title { font-size: 18px; font-weight: 700; }
.gr-error-msg { font-size: 14px; color: #a3a3a3; text-align: center; max-width: 400px; }

/* Content */
.gr-mock-banner {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 12px;
  color: var(--red);
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.gr-mock-link {
  color: var(--red);
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
  margin-left: auto;
}

.gr-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* Section label (standalone, outside a card) */
.gr-section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: var(--text-tertiary);
  text-transform: uppercase;
  margin-bottom: 12px;
}

/* Shared card */
.gr-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 24px;
}

.gr-card-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--text-tertiary);
  text-transform: uppercase;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* Executive Summary — clean left-accent, no gradient clutter */
.gr-summary-section {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  padding: 28px 28px 24px;
}

.gr-summary-text {
  font-size: 15px;
  line-height: 1.8;
  color: #d0d0e8;
  font-weight: 400;
}

.gr-confidence-note {
  margin-top: 16px;
  padding: 10px 14px;
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(245, 158, 11, 0.18);
  border-radius: 6px;
  font-size: 12px;
  color: #c8a860;
  line-height: 1.5;
}

/* Two-column row */
.gr-two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

/* ICP Card */
.gr-icp-segment {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 14px;
  line-height: 1.5;
}

.gr-icp-confidence {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.gr-conf-bar-wrap {
  flex: 1;
  height: 6px;
  background: var(--border-subtle);
  border-radius: 3px;
}

.gr-conf-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.6s ease;
}

.gr-conf-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  white-space: nowrap;
}

.gr-icp-reasoning {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
}

/* Readiness Card */
.gr-readiness-score-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.gr-readiness-gauge {
  flex: 1;
  height: 8px;
  background: var(--border-subtle);
  border-radius: 4px;
  overflow: hidden;
}

.gr-readiness-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.6s ease;
}

.gr-readiness--high   { background: var(--green); }
.gr-readiness--medium { background: var(--amber); }
.gr-readiness--low    { background: var(--red); }

.gr-readiness-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}
.gr-readiness-denom { font-size: 14px; color: var(--text-tertiary); }

.gr-readiness-label-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 3px 8px;
  border-radius: 4px;
  margin-bottom: 14px;
}

.gr-readiness-reasoning {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
}

/* Winning Message */
.gr-winner-card {
  border-color: rgba(59, 130, 246, 0.25);
  border-left: 3px solid var(--accent);
}

.gr-winner-star  { color: var(--amber); font-size: 13px; }

.gr-winner-score {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0;
  text-transform: none;
}

.gr-winner-subject {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  line-height: 1.4;
}

.gr-winner-body {
  font-size: 13px;
  color: #9898b8;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px 18px;
  white-space: pre-line;
  line-height: 1.75;
  margin-bottom: 14px;
}

.gr-winner-reasoning {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
}

.gr-why-label { font-weight: 700; color: var(--accent); }

/* Objections */
.gr-objection-item {
  padding: 14px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.gr-objection-item:last-child { border-bottom: none; padding-bottom: 0; }

.gr-objection-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}

.gr-objection-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
  line-height: 1.4;
}

.gr-objection-freq {
  font-size: 11px;
  font-weight: 700;
  color: var(--amber);
  background: rgba(245, 158, 11, 0.1);
  padding: 2px 7px;
  border-radius: 4px;
  white-space: nowrap;
}

.gr-objection-response {
  font-size: 12px;
  color: #a3a3a3;
  line-height: 1.65;
  padding-left: 12px;
  border-left: 2px solid var(--border-muted);
}

.gr-response-arrow { color: var(--green); font-weight: 700; }

/* Risk Signals */
.gr-risk-item {
  padding: 14px;
  border-radius: 8px;
  background: var(--bg-elevated);
  margin-bottom: 8px;
}
.gr-risk-item:last-child { margin-bottom: 0; }

.gr-risk-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.gr-risk-sev {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 3px;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.gr-sev--high   { background: rgba(248,113,113,0.15); color: var(--red); }
.gr-sev--medium { background: rgba(245,158,11,0.15);  color: var(--amber); }
.gr-sev--low    { background: rgba(74,222,128,0.12);  color: var(--green); }

.gr-risk-signal {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.gr-risk-mitigation {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.65;
}

/* Workflow */
.gr-workflow-steps {
  list-style: none;
  padding: 0;
  margin: 0;
  counter-reset: wf;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.gr-workflow-step {
  counter-increment: wf;
  display: flex;
  gap: 14px;
  font-size: 13px;
  color: #c8c8e0;
  line-height: 1.65;
}

.gr-workflow-step::before {
  content: counter(wf);
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  background: var(--accent-dim);
  border: 1px solid rgba(59, 130, 246,0.3);
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  margin-top: 2px;
  flex-shrink: 0;
}

/* 7-Day Experiment */
.gr-experiment-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.gr-day-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
}

.gr-day-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 6px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  user-select: none;
}

.gr-day-card:hover { border-color: var(--border-muted); }

.gr-day-card--active {
  border-color: var(--accent);
  background: var(--accent-dim);
}

.gr-day-num {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--accent);
  margin-bottom: 5px;
}

.gr-day-goal {
  font-size: 10px;
  color: var(--text-secondary);
  line-height: 1.35;
}

.gr-day-detail {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 20px;
}

.gr-day-detail-header {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.gr-day-detail-row {
  display: flex;
  gap: 16px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.gr-day-detail-row:last-child { border-bottom: none; }

.gr-day-detail-key {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-tertiary);
  text-transform: uppercase;
  min-width: 110px;
  padding-top: 3px;
}

.gr-day-detail-val {
  font-size: 13px;
  color: #c8c8e0;
  line-height: 1.65;
}

/* Next Experiment */
.gr-next-text {
  font-size: 14px;
  color: #c8c8e0;
  line-height: 1.75;
}

/* Disclaimer */
/* Simulation note (replaces old disclaimer) */
.gr-sim-note {
  background: rgba(59, 130, 246, 0.06);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
  color: #8888cc;
  line-height: 1.5;
}

/* Metric strip */
.gr-metric-strip {
  display: flex;
  align-items: center;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 16px 28px;
}

.gr-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: 1;
}

.gr-metric-val {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.gr-metric-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--text-tertiary);
  text-transform: uppercase;
}

.gr-metric-sep {
  width: 1px;
  height: 32px;
  background: var(--border-subtle);
  flex-shrink: 0;
}

.gr-readiness-val--high   { color: var(--green); }
.gr-readiness-val--medium { color: var(--amber); }
.gr-readiness-val--low    { color: var(--red); }

/* Risk severity: no left borders (cards now have bg color from .gr-risk-item) */
.gr-risk-item--high   { border-color: rgba(248,113,113,0.2); }
.gr-risk-item--medium { border-color: rgba(245,158,11,0.2); }
.gr-risk-item--low    { border-color: rgba(74,222,128,0.15); }

/* Footer */
.gr-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 32px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}

.gr-footer-right {
  display: flex;
  gap: 12px;
  align-items: center;
}

/* Buttons */
.gr-btn-primary {
  background: var(--accent);
  color: #fff;
  border: none;
  font-size: 14px;
  font-weight: 600;
  padding: 10px 22px;
  border-radius: 8px;
  transition: background 0.2s;
}
.gr-btn-primary:hover    { background: #5254cc; }
.gr-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

.gr-btn-ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-muted);
  font-size: 14px;
  font-weight: 500;
  padding: 10px 18px;
  border-radius: 8px;
  transition: color 0.2s, border-color 0.2s;
}
.gr-btn-ghost:hover { color: var(--text-primary); border-color: var(--accent); }

/* Responsive */
@media (max-width: 800px) {
  .gr-two-col  { grid-template-columns: 1fr; }
  .gr-day-grid { grid-template-columns: repeat(4, 1fr); }
  .gr-header { flex-wrap: wrap; gap: 8px; }
  .gr-footer { flex-wrap: wrap; gap: 10px; }
}
</style>
