<template>
  <div class="workbench-panel">
    <div class="scroll-container">
      <!-- Step 01: Ontology -->
      <div class="step-card" :class="{ 'active': currentPhase === 0, 'completed': currentPhase > 0 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">01</span>
            <span class="step-title">{{ $t('step1.ontologyGeneration') }}</span>
          </div>
          <div class="step-status">
            <span v-if="currentPhase > 0" class="badge success">{{ $t('step1.ontologyCompleted') }}</span>
            <span v-else-if="currentPhase === 0" class="badge processing">{{ $t('step1.ontologyGenerating') }}</span>
            <span v-else class="badge pending">{{ $t('step1.ontologyPending') }}</span>
          </div>
        </div>
        
        <div class="card-content">
          <p class="api-note">POST /api/graph/ontology/generate</p>
          <p class="description">
            {{ $t('step1.ontologyDesc') }}
          </p>

          <!-- Loading / Progress -->
          <div v-if="currentPhase === 0 && ontologyProgress" class="progress-section">
            <div class="spinner-sm"></div>
            <span>{{ ontologyProgress.message || $t('step1.analyzingDocs') }}</span>
          </div>

          <!-- Detail Overlay -->
          <div v-if="selectedOntologyItem" class="ontology-detail-overlay">
            <div class="detail-header">
               <div class="detail-title-group">
                  <span class="detail-type-badge">{{ selectedOntologyItem.itemType === 'entity' ? 'ENTITY' : 'RELATION' }}</span>
                  <span class="detail-name">{{ selectedOntologyItem.name }}</span>
               </div>
               <button class="close-btn" @click="selectedOntologyItem = null">×</button>
            </div>
            <div class="detail-body">
               <div class="detail-desc">{{ selectedOntologyItem.description }}</div>
               
               <!-- Attributes -->
               <div class="detail-section" v-if="selectedOntologyItem.attributes?.length">
                  <span class="section-label">ATTRIBUTES</span>
                  <div class="attr-list">
                     <div v-for="attr in selectedOntologyItem.attributes" :key="attr.name" class="attr-item">
                        <span class="attr-name">{{ attr.name }}</span>
                        <span class="attr-type">({{ attr.type }})</span>
                        <span class="attr-desc">{{ attr.description }}</span>
                     </div>
                  </div>
               </div>

               <!-- Examples (Entity) -->
               <div class="detail-section" v-if="selectedOntologyItem.examples?.length">
                  <span class="section-label">EXAMPLES</span>
                  <div class="example-list">
                     <span v-for="ex in selectedOntologyItem.examples" :key="ex" class="example-tag">{{ ex }}</span>
                  </div>
               </div>

               <!-- Source/Target (Relation) -->
               <div class="detail-section" v-if="selectedOntologyItem.source_targets?.length">
                  <span class="section-label">CONNECTIONS</span>
                  <div class="conn-list">
                     <div v-for="(conn, idx) in selectedOntologyItem.source_targets" :key="idx" class="conn-item">
                        <span class="conn-node">{{ conn.source }}</span>
                        <span class="conn-arrow">→</span>
                        <span class="conn-node">{{ conn.target }}</span>
                     </div>
                  </div>
               </div>
            </div>
          </div>

          <!-- Generated Entity Tags -->
          <div v-if="projectData?.ontology?.entity_types" class="tags-container" :class="{ 'dimmed': selectedOntologyItem }">
            <span class="tag-label">GENERATED ENTITY TYPES</span>
            <div class="tags-list">
              <span 
                v-for="entity in projectData.ontology.entity_types" 
                :key="entity.name" 
                class="entity-tag clickable"
                @click="selectOntologyItem(entity, 'entity')"
              >
                {{ entity.name }}
              </span>
            </div>
          </div>

          <!-- Generated Relation Tags -->
          <div v-if="projectData?.ontology?.edge_types" class="tags-container" :class="{ 'dimmed': selectedOntologyItem }">
            <span class="tag-label">GENERATED RELATION TYPES</span>
            <div class="tags-list">
              <span 
                v-for="rel in projectData.ontology.edge_types" 
                :key="rel.name" 
                class="entity-tag clickable"
                @click="selectOntologyItem(rel, 'relation')"
              >
                {{ rel.name }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 02: Graph Build -->
      <div
        class="step-card"
        :class="{
          'active': currentPhase === 1 && !buildFailed,
          'completed': currentPhase > 1 && !buildFailed,
          'failed': buildFailed
        }"
      >
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">02</span>
            <span class="step-title">{{ $t('step1.graphRagBuild') }}</span>
          </div>
          <div class="step-status">
            <!-- The failure is read before the phase. A build that died is
                 still sitting on the build step, and rendering that as the
                 in-progress badge left a dead build showing '0%' forever:
                 nothing polls a project that has already failed, so the number
                 never moved again. -->
            <span v-if="buildFailed" class="badge failed">{{ $t('step1.buildFailed') }}</span>
            <span v-else-if="currentPhase > 1" class="badge success">{{ $t('step1.ontologyCompleted') }}</span>
            <span v-else-if="currentPhase === 1" class="badge processing">{{ buildProgress?.progress || 0 }}%</span>
            <span v-else class="badge pending">{{ $t('step1.ontologyPending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="api-note">POST /api/graph/build</p>
          <p class="description">
            {{ $t('step1.graphRagDesc') }}
          </p>
          
          <!-- Stats Cards -->
          <div class="stats-grid">
            <div class="stat-card">
              <span class="stat-value">{{ graphStats.nodes }}</span>
              <span class="stat-label">{{ $t('step1.entityNodes') }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ graphStats.edges }}</span>
              <span class="stat-label">{{ $t('step1.relationEdges') }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ graphStats.types }}</span>
              <span class="stat-label">{{ $t('step1.schemaTypes') }}</span>
            </div>
          </div>

          <!-- Nothing in the app used to POST /api/graph/build again after a
               failure, so a build that died on one episode could only be
               finished by deleting the project. The backend now resumes a
               recoverable batch on an ordinary (non-forced) build, so that is
               what the primary control sends; the forced rebuild deletes the
               graph the run left behind and re-ingests everything, so it is
               kept secondary and confirmed. -->
          <div v-if="buildFailed || retryingBuild" class="failure-panel">
            <p class="failure-message">{{ buildError || $t('step1.buildFailedDesc') }}</p>
            <p v-if="projectData?.graph_id" class="failure-note">{{ $t('step1.buildFailedGraphKept') }}</p>
            <p v-if="rebuildRequired" class="failure-note is-warning">{{ $t('step1.rebuildRequired') }}</p>

            <!-- Inert while a simulation is being created: that POST is being
                 answered over the graph a retry or a rebuild would rewrite, so
                 the two controls are never live at the same time. -->
            <button
              class="action-btn"
              :disabled="buildInFlight || creatingSimulation"
              @click="requestBuild(false)"
            >
              <span v-if="buildInFlight" class="spinner-sm"></span>
              {{ buildInFlight ? $t('step1.retryingBuild') : retryLabel }}
            </button>
            <p class="failure-hint">{{ retryHint }}</p>

            <!-- Offered only where there is a graph to delete. A failure that
                 never created one has nothing for the rebuild to do that the
                 retry above does not already do safely. -->
            <button
              v-if="projectData?.graph_id"
              class="destructive-btn"
              :disabled="buildInFlight || creatingSimulation"
              @click="confirmingRebuild = true"
            >
              {{ $t('step1.rebuildFromScratch') }}
            </button>
          </div>
        </div>
      </div>

      <!-- Step 03: Complete -->
      <div class="step-card" :class="{ 'active': currentPhase === 2, 'completed': currentPhase >= 2 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">03</span>
            <span class="step-title">{{ $t('step1.buildComplete') }}</span>
          </div>
          <div class="step-status">
            <span v-if="currentPhase >= 2" class="badge accent">{{ $t('step1.inProgress') }}</span>
          </div>
        </div>
        
        <div class="card-content">
          <p class="api-note">POST /api/simulation/create</p>
          <p class="description">{{ $t('step1.buildCompleteDesc') }}</p>
          <!-- Gated on the graph, not on the build having reported success. A
               build that ingested 61 of 62 episodes and then timed out on the
               last one is recorded as failed, but every episode it committed is
               still in FalkorDB behind the project's graph_id, and
               POST /api/simulation/create asks for nothing more than a project
               with one. This is the only button in the app that creates a
               simulation, so gating it on the build made a single timed-out
               episode permanently unrecoverable. -->
          <button
            class="action-btn"
            :disabled="!canEnterEnvSetup || creatingSimulation"
            @click="handleEnterEnvSetup"
          >
            <span v-if="creatingSimulation" class="spinner-sm"></span>
            {{ creatingSimulation ? $t('step1.creating') : $t('step1.enterEnvSetup') + ' ➝' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Bottom Info / Logs -->
    <div class="system-logs">
      <div class="log-header">
        <span class="log-title">SYSTEM DASHBOARD</span>
        <span class="log-id">{{ projectData?.project_id || 'NO_PROJECT' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div class="log-line" v-for="(log, idx) in systemLogs" :key="idx">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
      </div>
    </div>

    <!-- The rebuild deletes every episode the failed run committed, so it is
         never one click away from a user who came here to recover them. -->
    <ConfirmDialog
      :open="confirmingRebuild"
      :title="$t('step1.confirmRebuildTitle')"
      :body="$t('step1.confirmRebuildBody')"
      :confirm-label="$t('step1.confirmRebuild')"
      tone="danger"
      @confirm="handleRebuild"
      @cancel="confirmingRebuild = false"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { createSimulation } from '../api/simulation'
import ConfirmDialog from './simulations/ConfirmDialog.vue'

const router = useRouter()
const { t } = useI18n()

const props = defineProps({
  currentPhase: { type: Number, default: 0 },
  projectData: Object,
  ontologyProgress: Object,
  buildProgress: Object,
  graphData: Object,
  systemLogs: { type: Array, default: () => [] },
  // The build's failure travels on its own rather than as a phase: a dead
  // build stands on the build step without being in progress there.
  buildFailed: { type: Boolean, default: false },
  buildError: { type: String, default: '' },
  // The backend answered 409 'recoverable': the interrupted batch is gone, so
  // there is nothing left for a retry to resume.
  rebuildRequired: { type: Boolean, default: false },
  retryingBuild: { type: Boolean, default: false }
})

const emit = defineEmits(['next-step', 'retry-build'])

const selectedOntologyItem = ref(null)
const logContent = ref(null)
const creatingSimulation = ref(false)
const confirmingRebuild = ref(false)

// Everything that means 'a build is being driven right now', in the order the
// page learns it: MainView's request still in flight - it sets retryingBuild
// synchronously, before the first await, so the prop is already true on the
// re-render that follows the click - and then the build step itself while it is
// running. The second clause is not redundant with the status check below: it
// is the only one that holds when MainView could not read the project back
// after a reused build and is following the task instead, leaving projectData
// describing a state that is no longer current.
//
// Note the two clauses are disjoint in practice, not overlapping: starting a
// retry clears buildFailed synchronously, so a render never sees retryingBuild
// and buildFailed at once. That is why the failure panel is mounted on
// (buildFailed || retryingBuild) rather than buildFailed alone - otherwise the
// panel unmounts the instant retry begins and its in-flight state is dead
// markup that nothing can ever display.
const buildInFlight = computed(() => (
  props.retryingBuild
  || (props.currentPhase === 1 && !props.buildFailed)
))

// A graph_id alone does not mean the graph holds anything: graph.py saves it
// from its remember_graph callback at the very start of a build, before the
// first episode is ingested and while the project still reads
// 'graph_building'. Gating on the build's own status - not on a phase number -
// keeps a running build from handing the user a simulation over an empty
// graph, while a FAILED project that has a graph_id stays open: that is the
// 61-of-62 case this whole gate exists to unblock. The status is what the
// server last said, so an in-flight rebuild is read locally on top of it.
const canEnterEnvSetup = computed(() => (
  Boolean(props.projectData?.graph_id)
  && props.projectData?.status !== 'graph_building'
  && !buildInFlight.value
))

// The same button, described for what the backend will actually do with it.
// It resumes only where there is an ingest to resume: a failure that never got
// as far as creating the graph, or one the backend has already reported it
// cannot resume, starts a fresh build instead. Either way it deletes nothing,
// which is what keeps it the safe one of the two.
const canResumeBuild = computed(() => (
  Boolean(props.projectData?.graph_id) && !props.rebuildRequired
))

const retryLabel = computed(() => (
  canResumeBuild.value ? t('step1.resumeBuild') : t('step1.startFreshBuild')
))

const retryHint = computed(() => (
  canResumeBuild.value ? t('step1.resumeBuildHint') : t('step1.startFreshBuildHint')
))

// The single way a build request leaves this component, so that nothing can
// emit one past the two states that must not overlap with it: a build already
// being driven, and a create-simulation POST in flight over the graph a build
// would rewrite.
const requestBuild = (force) => {
  if (buildInFlight.value || creatingSimulation.value) return
  emit('retry-build', { force })
}

const handleRebuild = () => {
  confirmingRebuild.value = false
  requestBuild(true)
}

// The simulation is created here rather than in the environment-setup view so
// that the view is always reached with an id it can prepare against.
const handleEnterEnvSetup = async () => {
  if (!props.projectData?.project_id || !canEnterEnvSetup.value) {
    console.error('Missing project or knowledge graph information')
    return
  }

  creatingSimulation.value = true
  
  try {
    const res = await createSimulation({
      project_id: props.projectData.project_id,
      graph_id: props.projectData.graph_id,
      enable_twitter: true,
      enable_reddit: true
    })
    
    if (res.success && res.data?.simulation_id) {
      router.push({
        name: 'Simulation',
        params: { simulationId: res.data.simulation_id }
      })
    } else {
      console.error('Failed to create simulation:', res.error)
      alert(t('step1.createSimulationFailed', { error: res.error || t('common.unknownError') }))
    }
  } catch (err) {
    console.error('Simulation creation error:', err)
    alert(t('step1.createSimulationException', { error: err.message }))
  } finally {
    creatingSimulation.value = false
  }
}

const selectOntologyItem = (item, type) => {
  selectedOntologyItem.value = { ...item, itemType: type }
}

const graphStats = computed(() => {
  const nodes = props.graphData?.node_count || props.graphData?.nodes?.length || 0
  const edges = props.graphData?.edge_count || props.graphData?.edges?.length || 0
  const types = props.projectData?.ontology?.entity_types?.length || 0
  return { nodes, edges, types }
})

const formatDate = (dateStr) => {
  if (!dateStr) return '--:--:--'
  const d = new Date(dateStr)
  return d.toLocaleTimeString('en-US', { hour12: false }) + '.' + d.getMilliseconds()
}

// Auto-scroll logs
watch(() => props.systemLogs.length, () => {
  nextTick(() => {
    if (logContent.value) {
      logContent.value.scrollTop = logContent.value.scrollHeight
    }
  })
})
</script>

<style scoped>
.workbench-panel {
  height: 100%;
  background: var(--bg-canvas);
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.scroll-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.step-card {
  background: var(--bg-panel);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-sm), var(--edge-highlight);
  border: 1px solid var(--border-subtle);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  position: relative; /* anchors the ontology detail overlay */
}

.step-card.active {
  border-color: var(--border-accent);
  box-shadow: var(--shadow-accent);
}

.step-card.failed {
  border-color: var(--danger-border);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.step-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-num {
  font-family: var(--font-mono);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-disabled);
}

.step-card.active .step-num,
.step-card.completed .step-num,
.step-card.failed .step-num {
  color: var(--text-primary);
}

.step-title {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.5px;
  color: var(--text-primary);
}

.badge {
  font-size: 10px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  font-weight: 600;
  text-transform: uppercase;
}

.badge.success { background: var(--success-soft); color: var(--success); }
.badge.processing { background: var(--accent); color: var(--text-on-accent); }
.badge.accent { background: var(--accent); color: var(--text-on-accent); }
.badge.pending { background: var(--bg-inset); color: var(--text-muted); }
.badge.failed { background: var(--danger-soft); color: var(--danger); }

.api-note {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.description {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 16px;
}

/* Step 01 Tags */
.tags-container {
  margin-top: 12px;
  transition: opacity 0.3s;
}

.tags-container.dimmed {
    opacity: 0.3;
    pointer-events: none;
}

.tag-label {
  display: block;
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 8px;
  font-weight: 600;
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.entity-tag {
  background: var(--bg-raised);
  border: 1px solid var(--border-default);
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  transition: background 0.2s, border-color 0.2s;
}

.entity-tag.clickable {
    cursor: pointer;
}

.entity-tag.clickable:hover {
    background: var(--bg-overlay);
    border-color: var(--border-strong);
}

/* Ontology Detail Overlay */
.ontology-detail-overlay {
    position: absolute;
    top: 60px; /* clears the card header */
    left: 20px;
    right: 20px;
    bottom: 20px;
    background: var(--bg-overlay);
    z-index: 10;
    border: 1px solid var(--border-strong);
    box-shadow: var(--shadow-lg);
    border-radius: var(--radius-md);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

.detail-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-default);
    background: var(--bg-panel);
}

.detail-title-group {
    display: flex;
    align-items: center;
    gap: 8px;
}

.detail-type-badge {
    font-size: 9px;
    font-weight: 700;
    color: var(--text-on-accent);
    background: var(--accent);
    padding: 2px 6px;
    border-radius: var(--radius-xs);
    text-transform: uppercase;
}

.detail-name {
    font-size: 14px;
    font-weight: 700;
    font-family: var(--font-mono);
    color: var(--text-primary);
}

.close-btn {
    background: none;
    border: none;
    font-size: 18px;
    color: var(--text-muted);
    line-height: 1;
}

.close-btn:hover {
    color: var(--text-primary);
}

.detail-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 16px;
}

.detail-desc {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px dashed var(--border-default);
}

.detail-section {
    margin-bottom: 16px;
}

.section-label {
    display: block;
    font-size: 10px;
    font-weight: 600;
    color: var(--text-muted);
    margin-bottom: 8px;
}

.attr-list, .conn-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.attr-item {
    font-size: 11px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: baseline;
    padding: 4px;
    background: var(--bg-inset);
    border-radius: var(--radius-sm);
}

.attr-name {
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--text-primary);
}

.attr-type {
    color: var(--text-muted);
    font-size: 10px;
}

.attr-desc {
    color: var(--text-secondary);
    flex: 1;
    min-width: 150px;
}

.example-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.example-tag {
    font-size: 11px;
    background: var(--bg-inset);
    border: 1px solid var(--border-default);
    padding: 3px 8px;
    border-radius: var(--radius-pill);
    color: var(--text-secondary);
}

.conn-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    padding: 6px;
    background: var(--bg-inset);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
}

.conn-node {
    font-weight: 600;
    color: var(--text-primary);
}

.conn-arrow {
    color: var(--accent);
}

/* Step 02 Stats */
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  background: var(--bg-inset);
  padding: 16px;
  border-radius: var(--radius-md);
}

.stat-card {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.stat-label {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-top: 4px;
  display: block;
}

/* Step 03 Button */
.action-btn {
  width: 100%;
  background: var(--accent);
  color: var(--text-on-accent);
  border: none;
  padding: 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  transition: background 0.2s;
}

.action-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.action-btn:disabled {
  background: var(--bg-raised);
  color: var(--text-disabled);
}

/* Failed build */
.failure-panel {
  margin-top: 16px;
  padding: 14px;
  background: var(--danger-soft);
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-md);
}

.failure-message {
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--danger);
  word-break: break-word;
}

.failure-note {
  margin-bottom: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.failure-note.is-warning {
  color: var(--warning);
}

.failure-hint {
  margin-top: 6px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--text-muted);
  text-align: center;
}

/* Deliberately not shaped like the button above it. The rebuild throws away
   every episode the failed run committed, so it must not be reachable by
   reflex from the control that recovers them. */
.destructive-btn {
  display: block;
  width: 100%;
  margin-top: 12px;
  padding: 6px;
  background: none;
  border: none;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.destructive-btn:hover:not(:disabled) {
  color: var(--danger);
}

.destructive-btn:disabled {
  opacity: 0.55;
}

.progress-section {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--accent);
  margin-bottom: 12px;
}

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-soft);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* System Logs */
.system-logs {
  background: var(--term-bg);
  color: var(--term-fg);
  padding: 16px;
  font-family: var(--font-mono);
  border-top: 1px solid var(--term-rule);
  flex-shrink: 0;
}

.log-header {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid var(--term-rule);
  padding-bottom: 8px;
  margin-bottom: 8px;
  font-size: 10px;
  color: var(--term-dim);
}

.log-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 80px; /* about four lines */
  overflow-y: auto;
  padding-right: 4px;
}

.log-content::-webkit-scrollbar {
  width: 4px;
}

.log-content::-webkit-scrollbar-thumb {
  background: var(--term-rule);
  border-radius: var(--radius-xs);
}

.log-line {
  font-size: 11px;
  display: flex;
  gap: 12px;
  line-height: 1.5;
}

.log-time {
  color: var(--term-dim);
  min-width: 75px;
}

.log-msg {
  color: var(--term-fg);
  word-break: break-all;
}
</style>
