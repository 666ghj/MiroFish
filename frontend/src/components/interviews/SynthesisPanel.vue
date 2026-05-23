<template>
  <div class="panel">
    <h3>Synthesis</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <pre v-else class="report">{{ report }}</pre>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { getSynthesis } from '../../api/interview'

const props = defineProps({ simId: String, status: Object })
const loading = ref(true); const error = ref(null); const report = ref('')

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    // service interceptor returns the envelope {success, data, error} directly
    const r = await getSynthesis(props.simId)
    if (!r.success) { error.value = r.error; return }
    report.value = r.data.report_markdown
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}
</script>

<style scoped>
.panel { padding: .5rem; }
.report { white-space: pre-wrap; font-family: ui-monospace, monospace; line-height: 1.4; }
</style>
