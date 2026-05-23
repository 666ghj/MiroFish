<template>
  <section class="step4b">
    <header>
      <h2>{{ t('interview.title') }}</h2>
      <p class="subtitle">{{ t('interview.subtitle') }}</p>
    </header>

    <div class="actions">
      <button :disabled="busy" @click="startPostRun">{{ t('interview.runAll') }}</button>
      <a :href="csvUrl" target="_blank" rel="noopener">{{ t('interview.downloadCsv') }}</a>
    </div>

    <nav class="tabs">
      <button v-for="tab in tabs" :key="tab.id"
              :class="{ active: active === tab.id }"
              @click="active = tab.id">
        {{ tab.label }}
      </button>
    </nav>

    <component :is="currentPanel" :sim-id="simId" :status="status" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import LongitudinalPanel from './interviews/LongitudinalPanel.vue'
import DiversityPanel from './interviews/DiversityPanel.vue'
import DelphiPanel from './interviews/DelphiPanel.vue'
import ScenarioPanel from './interviews/ScenarioPanel.vue'
import SynthesisPanel from './interviews/SynthesisPanel.vue'
import { startPost, getStatus, exportCsvUrl } from '../api/interview'

const props = defineProps({ simId: { type: String, required: true } })
const { t } = useI18n()
const tabs = [
  { id: 'longitudinal', label: t('interview.tab.longitudinal') },
  { id: 'diversity',    label: t('interview.tab.diversity') },
  { id: 'delphi',       label: t('interview.tab.delphi') },
  { id: 'scenario',     label: t('interview.tab.scenario') },
  { id: 'synthesis',    label: t('interview.tab.synthesis') },
]
const active = ref('longitudinal')
const status = ref({ status: 'idle' })
const busy = ref(false)
const csvUrl = computed(() => exportCsvUrl(props.simId))

const panels = {
  longitudinal: LongitudinalPanel, diversity: DiversityPanel,
  delphi: DelphiPanel, scenario: ScenarioPanel, synthesis: SynthesisPanel,
}
const currentPanel = computed(() => panels[active.value])

async function startPostRun() {
  busy.value = true
  try {
    const res = await startPost(props.simId)
    if (!res.success) throw new Error(res.error || 'failed to start')
    await poll(res.data.task_id)
  } finally { busy.value = false }
}

async function poll(taskId) {
  while (true) {
    const r = await getStatus(props.simId, taskId)
    status.value = r.data
    if (['completed', 'failed'].includes(r.data.status)) break
    await new Promise(resolve => setTimeout(resolve, 1500))
  }
}
</script>

<style scoped>
.step4b { padding: 1rem; }
.tabs { display: flex; gap: .5rem; margin: 1rem 0; }
.tabs button.active { font-weight: 700; border-bottom: 2px solid #333; }
.actions { display: flex; gap: 1rem; align-items: center; }
</style>
