<template>
  <div class="ensemble-panel">
    <!-- Creating / loading -->
    <div v-if="stage === 'creating'" class="center-state">
      <div class="pulse-ring"></div>
      <span>{{ loadingText }}</span>
    </div>

    <!-- Could not create or load -->
    <div v-else-if="stage === 'error'" class="center-state">
      <p class="error-text">{{ errorMessage }}</p>
      <button type="button" class="btn secondary" @click="init">↻</button>
    </div>

    <!-- Review before starting -->
    <div v-else-if="stage === 'review' && ensemble" class="scroll-area">
      <section class="block">
        <h2 class="block-title">{{ $t('ensemble.reviewTitle') }}</h2>
        <p class="lead">{{ $t('ensemble.reviewDesc', { runs: ensemble.n_replicates, rounds: ensemble.max_rounds }) }}</p>
        <p class="hint">{{ $t('ensemble.seedNote') }}</p>
      </section>

      <section v-if="cost" class="block cost-block">
        <span class="field-label">{{ $t('ensemble.costTitle') }}</span>
        <span class="cost-value mono">{{ $t('ensemble.costValue', { calls: formatCount(cost.llm_calls_upper_bound) }) }}</span>
        <p class="hint">{{ $t('ensemble.costBreakdown', { sim: formatCount(cost.simulation_calls), poll: formatCount(cost.poll_calls) }) }}</p>
      </section>

      <section class="block">
        <h3 class="block-subtitle">{{ $t('ensemble.questionsTitle') }}</h3>
        <p class="hint">{{ $t('ensemble.questionsDesc') }}</p>
        <p v-if="ensemble.questions_source === 'fallback'" class="notice warn">{{ $t('ensemble.fallbackNote') }}</p>

        <p v-if="questions.length === 0" class="empty-note">{{ $t('ensemble.noQuestions') }}</p>

        <div v-for="(question, index) in questions" :key="question.uid" class="question-card">
          <div class="question-row">
            <label class="field grow">
              <span class="field-label">{{ $t('ensemble.questionText') }} · {{ question.id }}</span>
              <textarea
                class="input"
                rows="2"
                maxlength="500"
                v-model="question.text"
              ></textarea>
            </label>
            <button
              type="button"
              class="icon-btn"
              :title="$t('ensemble.removeQuestion')"
              @click="removeQuestion(index)"
            >×</button>
          </div>

          <div class="question-row">
            <label class="field type-field">
              <span class="field-label">{{ $t('ensemble.questionType') }}</span>
              <select class="input" v-model="question.type">
                <option value="probability">{{ $t('ensemble.typeProbability') }}</option>
                <option value="choice">{{ $t('ensemble.typeChoice') }}</option>
                <option value="number">{{ $t('ensemble.typeNumber') }}</option>
              </select>
            </label>
            <label v-if="question.type === 'choice'" class="field grow">
              <span class="field-label">{{ $t('ensemble.options') }}</span>
              <input class="input" type="text" v-model="question.optionsText" />
            </label>
            <label v-if="question.type === 'number'" class="field unit-field">
              <span class="field-label">{{ $t('ensemble.unit') }}</span>
              <input class="input" type="text" maxlength="20" v-model="question.unit" />
            </label>
          </div>
        </div>

        <div class="editor-actions">
          <button
            type="button"
            class="btn secondary"
            :disabled="questions.length >= MAX_QUESTIONS"
            @click="addQuestion"
          >+ {{ $t('ensemble.addQuestion') }}</button>
        </div>
        <p v-if="validationFailed" class="error-text">{{ $t('ensemble.questionsInvalid') }}</p>
      </section>

      <p v-if="actionError" class="error-text">{{ actionError }}</p>
      <div class="actions">
        <button
          type="button"
          class="btn primary large"
          :disabled="validationFailed || busy !== ''"
          @click="start"
        >
          {{ busy === 'start' ? $t('ensemble.starting') : $t('ensemble.start', { runs: ensemble.n_replicates }) }}
        </button>
      </div>
    </div>

    <!-- Running and results -->
    <div v-else-if="ensemble" class="scroll-area">
      <section class="block status-block">
        <div class="status-line">
          <span class="chip" :class="`chip-${ensemble.status}`">{{ $t(`ensemble.ensembleStatus.${ensemble.status}`) }}</span>
          <span class="status-text mono">{{ $t('ensemble.progress', { done: finishedCount, total: ensemble.n_replicates }) }}</span>
          <button
            v-if="isActive"
            type="button"
            class="btn secondary small push-right"
            :disabled="busy !== ''"
            @click="stop"
          >{{ busy === 'stop' ? $t('ensemble.stopping') : $t('ensemble.stop') }}</button>
        </div>
        <div class="bar"><div class="bar-fill" :style="{ width: overallPercent + '%' }"></div></div>
        <p v-if="ensemble.status === 'aggregating'" class="hint">{{ $t('ensemble.aggregating') }}</p>
      </section>

      <section class="block">
        <h3 class="block-subtitle">{{ $t('ensemble.runningTitle') }}</h3>
        <!-- Why a run seems stuck: the model refusing requests, from the run that is working now -->
        <RunHealthBanner v-if="isActive && workingRun" :health="workingRun.health" />
        <ul class="run-list">
          <li v-for="run in ensemble.replicates" :key="run.simulation_id" class="run-row">
            <span class="run-name">{{ $t('ensemble.runLabel', { index: run.index }) }}</span>
            <span class="chip small" :class="`chip-${run.status}`">{{ $t(`ensemble.status.${run.status}`) }}</span>
            <div class="bar slim"><div class="bar-fill" :class="`fill-${run.status}`" :style="{ width: runPercent(run) + '%' }"></div></div>
            <span class="run-round mono">{{ $t('ensemble.round', { current: run.current_round || 0, total: run.total_rounds || ensemble.max_rounds }) }}</span>
            <span class="run-seed mono">{{ $t('ensemble.seed', { seed: run.seed }) }}</span>
            <span v-if="run.error" class="run-error">{{ run.error }}</span>
            <!-- What this run is doing right now (the full-width line under its row) -->
            <div v-if="run.status === 'running'" class="run-live">
              <RunStatusLine :activity="run.activity" :poll="run.poll" :active="true" />
            </div>
          </li>
        </ul>
      </section>

      <p v-if="ensemble.status === 'partial'" class="notice warn">
        {{ $t('ensemble.partialNote', { ok: ensemble.progress.completed, total: ensemble.n_replicates }) }}
      </p>
      <p v-if="ensemble.status === 'failed'" class="notice error">
        {{ $t('ensemble.failedNote') }}<template v-if="ensemble.error"> {{ ensemble.error }}</template>
      </p>
      <p v-if="ensemble.status === 'stopped'" class="notice">{{ $t('ensemble.stoppedNote') }}</p>

      <!-- Runs that were cut off can continue; finished runs are kept -->
      <section v-if="resumeInfo && resumeInfo.resumable" class="block resume-block">
        <h3 class="block-subtitle">{{ $t('resume.ensembleTitle') }}</h3>
        <p class="lead">{{ $t('resume.ensembleOffer', { count: resumingCount }) }}</p>
        <ul class="resume-list">
          <li v-for="item in resumeInfo.replicates.filter(r => r.action !== 'skip')" :key="item.simulation_id" class="mono">
            {{ item.action === 'resume'
              ? $t('resume.ensembleRunLine', { index: runIndex(item.simulation_id), round: item.round })
              : $t('resume.ensembleRunRestart', { index: runIndex(item.simulation_id) }) }}
          </li>
        </ul>
        <p class="hint">{{ resumeMemoryRestored ? $t('resume.memoryRestoredNote') : $t('resume.memoryNote') }}</p>
        <p v-if="resumeInexact" class="hint">{{ $t('resume.inexactNote') }}</p>
        <button type="button" class="btn primary" :disabled="busy !== ''" @click="resume">
          {{ busy === 'resume' ? $t('resume.resuming') : $t('resume.ensembleButton') }}
        </button>
      </section>

      <section v-if="summary" class="block">
        <EnsembleSummaryTable :summary="summary" />
      </section>

      <p v-if="actionError" class="error-text">{{ actionError }}</p>
      <div v-if="summary" class="actions">
        <button
          type="button"
          class="btn primary large"
          :disabled="busy !== ''"
          @click="makeReport"
        >
          <span v-if="busy === 'report'" class="spinner"></span>
          {{ busy === 'report' ? $t('ensemble.generatingReport') : $t('ensemble.generateReport') }}
          <span v-if="busy !== 'report'">→</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  createEnsemble,
  getEnsemble,
  getEnsembleSummary,
  getSimulationConfig,
  listEnsembles,
  putEnsembleOutcomeQuestions,
  startEnsemble,
  stopEnsemble,
  resumeEnsemble,
  getEnsembleResumeInfo
} from '../api/simulation'
import { generateReport } from '../api/report'
import EnsembleSummaryTable from './EnsembleSummaryTable.vue'
import RunHealthBanner from './RunHealthBanner.vue'
import RunStatusLine from './RunStatusLine.vue'

const props = defineProps({
  simulationId: String,
  // How many runs the user asked for in step 2
  runs: { type: Number, default: 5 },
  // The per-run round cap from step 2 (the cost guard); read from the config when missing
  maxRounds: Number,
  // An ensemble to continue (from the page address), instead of creating one
  ensembleId: String
})

const emit = defineEmits(['add-log', 'update-status'])

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const MAX_QUESTIONS = 3
const ACTIVE_STATUSES = ['running', 'aggregating']
const TERMINAL_STATUSES = ['completed', 'partial', 'failed', 'stopped']

// 'creating' | 'review' | 'running' | 'results' | 'error'
const stage = ref('creating')
const ensemble = ref(null)
const summary = ref(null)
const questions = ref([])
const busy = ref('') // 'start' | 'stop' | 'report'
const errorMessage = ref('')
const actionError = ref('')
const loadingKey = ref('preparing')

let savedQuestionsJson = '[]'
let nextUid = 1
let pollTimer = null
let polling = false

const log = (key, params = {}) => emit('add-log', t(`ensemble.log.${key}`, params))
const reason = (err) => err?.message || t('common.unknownError')

const loadingText = computed(() => (
  loadingKey.value === 'loading'
    ? t('ensemble.loading')
    : t('ensemble.preparing', { runs: props.runs })
))

const cost = computed(() => ensemble.value?.cost_estimate || null)
const isActive = computed(() => ACTIVE_STATUSES.includes(ensemble.value?.status))
// The run that is working right now (the banner and the status line describe this one)
// What resuming would do to each cut-off run (only fetched for a stopped, failed or partial ensemble)
const resumeInfo = ref(null)
const resumingCount = computed(() => (resumeInfo.value?.replicates || []).filter(r => r.action !== 'skip').length)
// true only when every run that would continue has its agents' chat memory saved in its checkpoint
const resumeMemoryRestored = computed(() => {
  const resuming = (resumeInfo.value?.replicates || []).filter(r => r.action === 'resume')
  return resuming.length > 0 && resuming.every(r => r.memory === true)
})
const resumeInexact = computed(() => (resumeInfo.value?.replicates || []).some(r => r.action === 'resume' && r.exact === false))
const runIndex = (simulationId) => {
  const run = (ensemble.value?.replicates || []).find(item => item.simulation_id === simulationId)
  return t('ensemble.runLabel', { index: run?.index ?? '?' })
}
const loadResumeInfo = async () => {
  resumeInfo.value = null
  if (!ensemble.value || !['stopped', 'failed', 'partial'].includes(ensemble.value.status)) return
  try {
    const res = await getEnsembleResumeInfo(ensemble.value.ensemble_id)
    resumeInfo.value = res.data
  } catch (err) {
    resumeInfo.value = null
  }
}
const workingRun = computed(() => (ensemble.value?.replicates || []).find((run) => run.status === 'running'))
const formatCount = (value) => (Number.isFinite(value) ? Math.round(value).toLocaleString() : '–')

// --- progress --------------------------------------------------------------------------------

const finishedCount = computed(() => {
  const progress = ensemble.value?.progress || {}
  return (progress.completed || 0) + (progress.failed || 0) + (progress.stopped || 0)
})

const runPercent = (run) => {
  if (run.status === 'completed') return 100
  const total = run.total_rounds || ensemble.value?.max_rounds || 0
  return total ? Math.min(100, Math.round(((run.current_round || 0) / total) * 100)) : 0
}

const overallPercent = computed(() => {
  const runs = ensemble.value?.replicates || []
  if (!runs.length) return 0
  const sum = runs.reduce((total, run) => total + runPercent(run), 0)
  return Math.round(sum / runs.length)
})

// --- outcome questions -------------------------------------------------------------------------

const parseOptions = (text) => (text || '').split(/[,，、]/).map(option => option.trim()).filter(Boolean)

const toEditable = (question) => ({
  uid: nextUid++,
  id: question.id,
  text: question.text || '',
  type: question.type,
  optionsText: (question.options || []).join(', '),
  unit: question.unit || '',
  stance_map: question.stance_map || null
})

// What the backend expects. Stance mappings of options that no longer exist are dropped.
const serializeQuestions = (list) => list.map((question) => {
  const item = { id: question.id, text: question.text.trim(), type: question.type }
  if (question.type === 'choice') {
    item.options = parseOptions(question.optionsText)
    const canonical = new Map(item.options.map(option => [option.toLowerCase(), option]))
    const stanceMap = {}
    for (const [option, stance] of Object.entries(question.stance_map || {})) {
      const match = canonical.get(String(option).trim().toLowerCase())
      if (match) stanceMap[match] = stance
    }
    if (Object.keys(stanceMap).length) item.stance_map = stanceMap
  }
  if (question.type === 'number') item.unit = (question.unit || '').trim()
  return item
})

const questionIsValid = (question) => {
  if (!question.text.trim()) return false
  if (question.type === 'number') return !!(question.unit || '').trim()
  if (question.type === 'choice') {
    const options = parseOptions(question.optionsText)
    const distinct = new Set(options.map(option => option.toLowerCase()))
    return options.length >= 2 && options.length <= 8 && distinct.size === options.length
  }
  return true
}

const validationFailed = computed(() => !questions.value.every(questionIsValid))
const questionsChanged = computed(() => JSON.stringify(serializeQuestions(questions.value)) !== savedQuestionsJson)

const addQuestion = () => {
  if (questions.value.length >= MAX_QUESTIONS) return
  const used = new Set(questions.value.map(question => question.id))
  let counter = 1
  while (used.has(`q${counter}`)) counter += 1
  questions.value.push(toEditable({ id: `q${counter}`, text: '', type: 'probability' }))
}

const removeQuestion = (index) => {
  questions.value.splice(index, 1)
}

// --- loading, creating and following an ensemble ------------------------------------------------

const adopt = (data, { keepQuestions = false } = {}) => {
  ensemble.value = data
  if (keepQuestions) return
  questions.value = (data.outcome_questions || []).map(toEditable)
  savedQuestionsJson = JSON.stringify(serializeQuestions(questions.value))
}

const roundsFromConfig = async () => {
  const res = await getSimulationConfig(props.simulationId)
  const timeConfig = res.data?.time_config || {}
  const minutes = timeConfig.minutes_per_round || 60
  return Math.max(1, Math.floor(((timeConfig.total_simulation_hours || 24) * 60) / minutes))
}

const create = async () => {
  const rounds = props.maxRounds || await roundsFromConfig()
  log('creating', { runs: props.runs, rounds })
  const res = await createEnsemble({
    simulation_id: props.simulationId,
    n_replicates: props.runs,
    max_rounds: rounds
  })
  adopt(res.data)
  log('created', { id: res.data.ensemble_id })
  // Keep the id in the address, so a reload returns to this ensemble instead of creating another
  router.replace({ query: { ...route.query, ensemble: res.data.ensemble_id } })
}

const loadExisting = async (id) => {
  try {
    const res = await getEnsemble(id)
    return res.data?.base_simulation_id === props.simulationId ? res.data : null
  } catch (err) {
    return null
  }
}

// An ensemble that is already running is continued, never duplicated: a second one would
// pay for every run again. One that has not started is only reused when the address names it,
// because its runs were cloned from the scenario as it was when the ensemble was created.
const findUnfinished = async () => {
  try {
    const res = await listEnsembles(props.simulationId)
    return (res.data || []).find(item => ACTIVE_STATUSES.includes(item.status)) || null
  } catch (err) {
    return null
  }
}

const stageFor = (status) => {
  if (status === 'created') return 'review'
  if (ACTIVE_STATUSES.includes(status)) return 'running'
  return 'results'
}

const enterStage = async () => {
  const status = ensemble.value.status
  stage.value = stageFor(status)
  emit('update-status', stage.value === 'results' && status !== 'failed' ? 'completed' : 'processing')
  if (stage.value === 'running') startPolling()
  if (stage.value === 'results') await settle()
}

const init = async () => {
  stage.value = 'creating'
  loadingKey.value = props.ensembleId ? 'loading' : 'preparing'
  errorMessage.value = ''
  actionError.value = ''
  emit('update-status', 'processing')
  try {
    let existing = props.ensembleId ? await loadExisting(props.ensembleId) : null
    if (!existing) existing = await findUnfinished()
    if (existing) {
      adopt(existing)
      log('resumed', { id: existing.ensemble_id, status: t(`ensemble.ensembleStatus.${existing.status}`) })
    } else {
      await create()
    }
    await enterStage()
  } catch (err) {
    errorMessage.value = t(ensemble.value ? 'ensemble.loadFailed' : 'ensemble.createFailed', { error: reason(err) })
    stage.value = 'error'
    emit('update-status', 'error')
    emit('add-log', errorMessage.value)
  }
}

// A finished ensemble: fetch the summary (completed and partial ones have one)
const settle = async () => {
  stopPolling()
  const status = ensemble.value.status
  if (['completed', 'partial'].includes(status) && !summary.value) {
    try {
      const res = await getEnsembleSummary(ensemble.value.ensemble_id)
      summary.value = res.data
    } catch (err) {
      actionError.value = t('ensemble.loadFailed', { error: reason(err) })
    }
  }
  await loadResumeInfo()
  emit('update-status', status === 'failed' ? 'error' : 'completed')
}

const poll = async () => {
  if (polling || !ensemble.value) return
  polling = true
  try {
    const res = await getEnsemble(ensemble.value.ensemble_id)
    adopt(res.data, { keepQuestions: true })
    if (TERMINAL_STATUSES.includes(res.data.status)) {
      stage.value = 'results'
      log('finished', { id: res.data.ensemble_id, status: t(`ensemble.ensembleStatus.${res.data.status}`) })
      await settle()
    }
  } catch (err) {
    console.warn('Could not refresh the ensemble:', err)
  } finally {
    polling = false
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(poll, 3000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// --- actions --------------------------------------------------------------------------------

const start = async () => {
  if (!ensemble.value || busy.value) return
  busy.value = 'start'
  actionError.value = ''
  const id = ensemble.value.ensemble_id
  try {
    if (questionsChanged.value) {
      const saved = await putEnsembleOutcomeQuestions(id, serializeQuestions(questions.value))
      adopt(saved.data)
    }
    const started = await startEnsemble(id)
    adopt(started.data, { keepQuestions: true })
    log('started', { id })
    stage.value = 'running'
    emit('update-status', 'processing')
    startPolling()
  } catch (err) {
    actionError.value = t('ensemble.startFailed', { error: reason(err) })
    emit('add-log', actionError.value)
  } finally {
    busy.value = ''
  }
}

const stop = async () => {
  if (!ensemble.value || busy.value) return
  busy.value = 'stop'
  actionError.value = ''
  const id = ensemble.value.ensemble_id
  log('stopping', { id })
  try {
    const stopped = await stopEnsemble(id)
    adopt(stopped.data, { keepQuestions: true })
    await poll()
  } catch (err) {
    actionError.value = t('ensemble.stopFailed', { error: reason(err) })
    emit('add-log', actionError.value)
  } finally {
    busy.value = ''
  }
}

const resume = async () => {
  if (!ensemble.value || busy.value) return
  busy.value = 'resume'
  actionError.value = ''
  const id = ensemble.value.ensemble_id
  try {
    const resumed = await resumeEnsemble(id)
    adopt(resumed.data, { keepQuestions: true })
    resumeInfo.value = null
    summary.value = null
    log('resumed', { id, status: t(`ensemble.ensembleStatus.${resumed.data.status}`) })
    stage.value = 'running'
    emit('update-status', 'processing')
    startPolling()
  } catch (err) {
    actionError.value = t('resume.failed', { error: reason(err) })
    emit('add-log', actionError.value)
  } finally {
    busy.value = ''
  }
}

const makeReport = async () => {
  if (!ensemble.value || busy.value) return
  busy.value = 'report'
  actionError.value = ''
  const id = ensemble.value.ensemble_id
  try {
    const res = await generateReport({ simulation_id: props.simulationId, ensemble_id: id })
    const reportId = res.data.report_id
    log('reportStarted', { id, reportId })
    // The report page may open before the report has been saved; the ensemble id in the address
    // lets it show the statistics table right away instead of waiting for the report record.
    router.push({ name: 'Report', params: { reportId }, query: { ensemble: id } })
  } catch (err) {
    actionError.value = t('ensemble.reportFailed', { error: reason(err) })
    emit('add-log', actionError.value)
    busy.value = ''
  }
}

onMounted(init)
onUnmounted(stopPolling)
</script>

<style scoped>
.ensemble-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--c-ffffff);
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: var(--c-222222);
}

.scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px 28px;
}

.center-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  font-size: 13px;
  color: var(--c-666666);
}

.pulse-ring {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid var(--c-ff5722);
  animation: ring-pulse 1.4s ease-out infinite;
}

@keyframes ring-pulse {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(1.5); opacity: 0; }
}

.block {
  margin-bottom: 22px;
}

.block-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 700;
  color: var(--c-000000);
}

.block-subtitle {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--c-333333);
}

.lead {
  margin: 0 0 8px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--c-333333);
}

.hint {
  margin: 4px 0 8px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--c-888888);
}

.empty-note {
  margin: 10px 0;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--c-777777);
  background: var(--c-fafafa);
  border: 1px dashed var(--c-dddddd);
  border-radius: 6px;
}

.cost-block {
  padding: 12px 14px;
  background: var(--c-fafafa);
  border: 1px solid var(--c-eaeaea);
  border-radius: 6px;
}

.cost-value {
  margin-left: 10px;
  font-size: 15px;
  font-weight: 700;
  color: var(--c-000000);
}

.field-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--c-999999);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.grow { flex: 1; min-width: 0; }
.type-field { width: 190px; }
.unit-field { width: 120px; }

.question-card {
  margin-top: 10px;
  padding: 12px;
  border: 1px solid var(--c-e5e5e5);
  border-radius: 6px;
  background: var(--c-ffffff);
}

.question-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.question-row + .question-row {
  margin-top: 8px;
}

.input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--c-dddddd);
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 12px;
  font-family: inherit;
  background: var(--c-fafafa);
}

textarea.input {
  resize: vertical;
  line-height: 1.5;
}

.input:focus {
  outline: none;
  border-color: var(--c-ff5722);
  background: var(--c-ffffff);
}

.icon-btn {
  border: none;
  background: transparent;
  color: var(--c-aaaaaa);
  font-size: 20px;
  line-height: 1;
  padding: 18px 6px 0;
  cursor: pointer;
}

.icon-btn:hover { color: var(--c-e53935); }

.editor-actions {
  margin-top: 10px;
}

.actions {
  margin-top: 8px;
}

.btn {
  border-radius: 4px;
  border: 1px solid var(--c-dddddd);
  background: var(--c-ffffff);
  color: var(--c-222222);
  font-size: 12px;
  font-family: inherit;
  padding: 6px 12px;
  cursor: pointer;
}

.btn.primary {
  background: var(--c-000000);
  color: var(--c-ffffff);
  border-color: var(--c-000000);
}

.btn.large {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
}

.btn.small {
  padding: 4px 10px;
  font-size: 11px;
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.error-text {
  margin: 8px 0;
  font-size: 12px;
  color: var(--c-c62828);
}

.notice {
  margin: 0 0 18px;
  padding: 9px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--c-555555);
  background: var(--c-f6f6f6);
  border-radius: 4px;
}

.notice.warn {
  color: var(--c-6b5b2e);
  background: var(--c-fffaeb);
  border: 1px solid var(--c-f1e3b5);
}

.notice.error {
  color: var(--c-c62828);
  background: var(--c-fff5f5);
  border: 1px solid var(--c-f3cfcf);
}

/* --- status and runs --- */
.status-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.push-right { margin-left: auto; }

.status-text {
  font-size: 12px;
  color: var(--c-555555);
}

.chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  background: var(--c-eeeeee);
  color: var(--c-555555);
  white-space: nowrap;
}

.chip.small {
  padding: 1px 8px;
  font-size: 10px;
}

.chip-running,
.chip-aggregating { background: var(--c-fff0ea); color: var(--c-e64a19); }
.chip-completed { background: var(--c-e8f5e9); color: var(--c-2e7d32); }
.chip-partial { background: var(--c-fff6dd); color: var(--c-8a6d1d); }
.chip-failed { background: var(--c-fdecea); color: var(--c-c62828); }

.bar {
  height: 6px;
  border-radius: 3px;
  background: var(--c-eeeeee);
  overflow: hidden;
}

.bar.slim {
  height: 4px;
  flex: 1;
  min-width: 60px;
}

.bar-fill {
  height: 100%;
  background: var(--c-ff5722);
  transition: width 0.4s ease;
}

.bar-fill.fill-completed { background: var(--c-43a047); }
.bar-fill.fill-failed { background: var(--c-e53935); }
.bar-fill.fill-stopped { background: var(--c-9e9e9e); }

.run-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
}

.run-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid var(--c-f0f0f0);
  font-size: 12px;
}

.run-name {
  width: 64px;
  font-weight: 600;
}

.run-live {
  flex-basis: 100%;
  padding-left: 74px;
  margin-top: -2px;
}

.run-live :deep(.run-status) {
  margin: 0;
}

.run-round,
.run-seed {
  color: var(--c-888888);
  font-size: 11px;
  white-space: nowrap;
}

.run-error {
  flex-basis: 100%;
  padding-left: 74px;
  color: var(--c-c62828);
  font-size: 11px;
}

.mono { font-family: 'JetBrains Mono', monospace; }

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-right: 8px;
  border: 2px solid var(--c-ffffff-a400);
  border-top-color: var(--c-ffffff);
  border-radius: 50%;
  vertical-align: -2px;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
