<template>
  <div class="setup-card" :class="cardClass">
    <div class="card-head">
      <div class="card-label">
        <span class="card-num">01</span>
        <span class="card-title">{{ $t('step2.simInstanceInit') }}</span>
      </div>
      <span class="card-badge" :class="phase > 0 ? 'badge--done' : 'badge--active'">
        {{ phase > 0 ? $t('common.completed') : $t('step2.initializing') }}
      </span>
    </div>

    <div class="card-body">
      <p class="api-route">POST /api/simulation/create</p>
      <p class="card-desc">{{ $t('step2.simInstanceDesc') }}</p>

      <div v-if="simulationId" class="id-grid">
        <div class="id-row">
          <span class="id-label">{{ $t('system.labelProject') }}</span>
          <span class="id-val">{{ projectData?.project_id || '—' }}</span>
        </div>
        <div class="id-row">
          <span class="id-label">{{ $t('system.labelGraph') }}</span>
          <span class="id-val">{{ projectData?.graph_id || '—' }}</span>
        </div>
        <div class="id-row">
          <span class="id-label">{{ $t('system.labelSimulation') }}</span>
          <span class="id-val highlight">{{ simulationId }}</span>
        </div>
        <div class="id-row" v-if="taskId">
          <span class="id-label">{{ $t('system.labelTask') }}</span>
          <span class="id-val">{{ taskId }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  phase:       { type: Number, required: true },
  simulationId:{ type: String, default: null },
  projectData: { type: Object, default: null },
  taskId:      { type: String, default: null },
})

const cardClass = computed(() => ({
  'card--active':    props.phase === 0,
  'card--completed': props.phase > 0,
}))
</script>

<style scoped>
.setup-card {
  background: #fff;
  border: 1px solid #EBEBEB;
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s;
}
.setup-card.card--active { border-color: #D0D0D0; }
.setup-card.card--completed { border-color: #E8E8E8; opacity: 0.85; }

/* Head */
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid #F0F0F0;
}
.card-label { display: flex; align-items: center; gap: 10px; }
.card-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: #CCCCCC;
}
.card-title {
  font-size: 13px;
  font-weight: 700;
  color: #1A1A1A;
}

/* Badge */
.card-badge {
  font-size: 10.5px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 20px;
}
.badge--done    { background: #F0FBF2; color: #2A7D3A; }
.badge--active  { background: #FFF3EE; color: #D44B00; }

/* Body */
.card-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }

.api-route {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #AAAAAA;
  margin: 0;
}

.card-desc {
  font-size: 12.5px;
  color: #555;
  margin: 0;
  line-height: 1.55;
}

/* ID grid */
.id-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #F8F8F8;
  border-radius: 7px;
  padding: 12px 14px;
}
.id-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.id-label {
  font-size: 10.5px;
  font-weight: 600;
  color: #AAAAAA;
  width: 60px;
  flex-shrink: 0;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.id-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #333;
  word-break: break-all;
}
.id-val.highlight { color: #1A1A1A; font-weight: 700; }
</style>
