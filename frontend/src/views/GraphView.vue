<template>
  <div class="graph-redirect">
    <div class="loader">
      <div class="spinner" />
      <h2>Loading graph…</h2>
      <p v-if="graphId">graph_id: <code>{{ graphId }}</code></p>
      <p v-if="error" class="err">{{ error }}</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const router = useRouter()
const graphId = ref(route.params.id)
const error = ref('')

onMounted(async () => {
  try {
    // Look up the project that owns this graph_id by scanning the project list
    // Note: must use /api/... prefix since baseURL is empty
    const res = await axios.get('/api/graph/project/list', { params: { limit: 200 } })
    if (!res.data?.success) throw new Error(res.data?.error || 'project list failed')
    const projects = res.data.data || []
    const match = projects.find(p => p.graph_id === graphId.value)
    if (!match) {
      error.value = `No project found for graph_id "${graphId.value}". The graph may not exist or has been deleted.`
      return
    }
    // Redirect to the project page, which has the full graph visualization
    await router.replace({ name: 'Process', params: { projectId: match.project_id } })
  } catch (e) {
    error.value = e.message || String(e)
  }
})
</script>

<style scoped>
.graph-redirect {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, #0e1116 0%, #1a1f2b 100%);
  color: #cbd5e1;
  font-family: 'Inter', system-ui, sans-serif;
}
.loader {
  text-align: center;
  max-width: 480px;
  padding: 2rem;
}
.spinner {
  width: 48px;
  height: 48px;
  border: 3px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  margin: 0 auto 1.5rem;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
h2 { font-size: 1.5rem; margin: 0 0 0.75rem; color: #f1f5f9; font-weight: 600; }
p  { font-size: 0.9rem; color: #94a3b8; margin: 0.25rem 0; }
code { background: rgba(99, 102, 241, 0.15); padding: 0.15em 0.4em; border-radius: 4px; color: #c7d2fe; font-size: 0.85em; }
.err { color: #fca5a5; }
</style>
