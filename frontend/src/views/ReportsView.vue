<template>
  <div class="reports-view">
    <header class="app-header">
      <div class="brand" @click="router.push('/')">MIROFISH</div>
      <div class="header-right">
        <button class="text-btn" @click="router.push('/')">{{ $t('reportsPage.back') }}</button>
      </div>
    </header>

    <main class="content">
      <div class="page-head">
        <div>
          <h1>{{ $t('reportsPage.title') }}</h1>
          <p class="subtitle">{{ $t('reportsPage.subtitle') }}</p>
        </div>
        <span v-if="!loading && !error" class="count-pill">{{ $t('reportsPage.count', { n: filtered.length }) }}</span>
      </div>

      <div class="toolbar">
        <input
          v-model="query"
          class="search"
          type="text"
          :placeholder="$t('reportsPage.search')"
        />
        <div class="filters">
          <button
            v-for="f in statusFilters"
            :key="f"
            class="chip"
            :class="{ active: statusFilter === f }"
            @click="statusFilter = f"
          >
            {{ f === 'all' ? $t('reportsPage.all') : $t(`common.${f}`) }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="state">{{ $t('common.loading') }}</div>
      <div v-else-if="error" class="state error">
        {{ error }}
        <button class="text-btn" @click="load">{{ $t('common.retry') }}</button>
      </div>
      <div v-else-if="!reports.length" class="state">{{ $t('reportsPage.empty') }}</div>
      <div v-else-if="!filtered.length" class="state">{{ $t('reportsPage.noMatch') }}</div>

      <ul v-else class="report-list">
        <li
          v-for="r in filtered"
          :key="r.report_id"
          class="report-card"
          @click="openReport(r)"
        >
          <div class="card-top">
            <span class="status" :class="r.status">{{ statusLabel(r.status) }}</span>
            <span class="date mono">{{ formatDate(r.created_at) }}</span>
          </div>
          <h2 class="card-title">{{ r.outline?.title || r.report_id }}</h2>
          <p v-if="r.outline?.summary" class="card-summary">{{ r.outline.summary }}</p>
          <p v-else-if="r.simulation_requirement" class="card-summary">{{ r.simulation_requirement }}</p>
          <div class="card-foot">
            <span class="meta mono">
              {{ r.simulation_id }}
              <template v-if="r.outline?.sections?.length">
                · {{ r.outline.sections.length }} {{ $t('reportsPage.sections') }}
              </template>
            </span>
            <span class="actions">
              <button
                class="text-btn"
                :class="{ on: panel[r.report_id] === 'seed' }"
                @click.stop="togglePanel(r, 'seed')"
              >{{ $t('reportsPage.realitySeed') }}</button>
              <button
                class="text-btn"
                :class="{ on: panel[r.report_id] === 'prompt' }"
                @click.stop="togglePanel(r, 'prompt')"
              >{{ $t('reportsPage.simulationPrompt') }}</button>
              <button class="text-btn" @click.stop="openReport(r)">{{ $t('reportsPage.open') }}</button>
              <button
                v-if="r.status === 'completed'"
                class="text-btn"
                @click.stop="openInterview(r)"
              >{{ $t('reportsPage.interact') }}</button>
              <span v-if="r.status === 'completed'" class="dl" @click.stop>
                <button class="text-btn" @click="toggleMenu(r.report_id)">{{ $t('reportsPage.download') }} ▾</button>
                <span v-if="menuOpen === r.report_id" class="dl-menu">
                  <a :href="downloadUrl(r, 'md')" @click="menuOpen = null">{{ $t('reportsPage.downloadMd') }}</a>
                  <a :href="downloadUrl(r, 'pdf')" @click="menuOpen = null">{{ $t('reportsPage.downloadPdf') }}</a>
                </span>
              </span>
            </span>
          </div>

          <div v-if="panel[r.report_id]" class="detail" @click.stop>
            <div v-if="ctxLoading[r.report_id]" class="detail-note">{{ $t('reportsPage.loadingContext') }}</div>
            <div v-else-if="ctxError[r.report_id]" class="detail-note error">{{ ctxError[r.report_id] }}</div>
            <template v-else-if="ctx[r.report_id]">
              <template v-if="panel[r.report_id] === 'seed'">
                <div class="detail-label">01 / {{ $t('reportsPage.realitySeed') }}</div>
                <div v-if="!ctx[r.report_id].seed_text && !ctx[r.report_id].seed_files.length" class="detail-note">
                  {{ $t('reportsPage.noSeed') }}
                </div>
                <template v-else>
                  <ul v-if="ctx[r.report_id].seed_files.length" class="file-list">
                    <li v-for="f in ctx[r.report_id].seed_files" :key="f.filename">
                      {{ f.filename }}<span v-if="f.size" class="mono dim"> · {{ formatSize(f.size) }}</span>
                    </li>
                  </ul>
                  <pre v-if="ctx[r.report_id].seed_text" class="detail-text">{{ ctx[r.report_id].seed_text }}</pre>
                </template>
              </template>
              <template v-else>
                <div class="detail-label">>_ 02 / {{ $t('reportsPage.simulationPrompt') }}</div>
                <pre v-if="ctx[r.report_id].simulation_prompt" class="detail-text">{{ ctx[r.report_id].simulation_prompt }}</pre>
                <div v-else class="detail-note">{{ $t('reportsPage.noPrompt') }}</div>
              </template>
            </template>
          </div>
        </li>
      </ul>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listReports, getReportContext } from '../api/report'

const router = useRouter()
const { t, locale } = useI18n()

const reports = ref([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const statusFilter = ref('all')
const statusFilters = ['all', 'completed', 'processing', 'failed']

const panel = ref({})       // report_id -> 'seed' | 'prompt'
const ctx = ref({})         // report_id -> context payload (cached)
const ctxLoading = ref({})
const ctxError = ref({})
const menuOpen = ref(null)

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return reports.value.filter(r => {
    if (statusFilter.value !== 'all' && statusKey(r.status) !== statusFilter.value) return false
    if (!q) return true
    return [r.outline?.title, r.outline?.summary, r.simulation_requirement, r.simulation_id, r.report_id]
      .some(v => v && v.toLowerCase().includes(q))
  })
})

// Backend statuses: pending/planning/generating/completed/failed
const statusKey = (status) => {
  if (status === 'completed' || status === 'failed') return status
  return 'processing'
}

const statusLabel = (status) => t(`common.${statusKey(status)}`)

const formatDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

const downloadUrl = (r, format) => `${API_BASE}/api/report/${r.report_id}/download?format=${format}`

const toggleMenu = (id) => {
  menuOpen.value = menuOpen.value === id ? null : id
}

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const togglePanel = async (r, which) => {
  const id = r.report_id
  if (panel.value[id] === which) {
    panel.value = { ...panel.value, [id]: null }
    return
  }
  panel.value = { ...panel.value, [id]: which }
  if (ctx.value[id]) return
  ctxLoading.value = { ...ctxLoading.value, [id]: true }
  ctxError.value = { ...ctxError.value, [id]: '' }
  try {
    const res = await getReportContext(id)
    ctx.value = { ...ctx.value, [id]: res.data }
  } catch (err) {
    ctxError.value = { ...ctxError.value, [id]: `${t('reportsPage.contextFailed')}: ${err.message}` }
  } finally {
    ctxLoading.value = { ...ctxLoading.value, [id]: false }
  }
}

const openReport = (r) => router.push({ name: 'Report', params: { reportId: r.report_id } })
const openInterview = (r) => router.push({ name: 'Interaction', params: { reportId: r.report_id } })

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listReports({ limit: 200 })
    const data = res.data || []
    reports.value = [...data].sort(
      (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)
    )
  } catch (err) {
    error.value = `${t('reportsPage.loadFailed')}: ${err.message}`
  } finally {
    loading.value = false
  }
}

const closeMenu = () => { menuOpen.value = null }

onMounted(() => {
  load()
  document.addEventListener('click', closeMenu)
})
onBeforeUnmount(() => document.removeEventListener('click', closeMenu))
</script>

<style scoped>
.reports-view {
  min-height: 100vh;
  background: #fff;
  color: #000;
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
}

.app-header {
  height: 60px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #eaeaea;
}

.brand {
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}

.content {
  max-width: 960px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 24px;
}

h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
}

.subtitle {
  margin: 6px 0 0;
  color: #666;
  font-size: 13px;
}

.count-pill {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #f4f4f4;
  color: #444;
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

.search {
  flex: 1;
  min-width: 220px;
  padding: 10px 12px;
  border: 1px solid #ddd;
  font-family: inherit;
  font-size: 13px;
  outline: none;
}

.search:focus {
  border-color: #000;
}

.filters {
  display: flex;
  gap: 6px;
}

.chip {
  padding: 8px 12px;
  border: 1px solid #ddd;
  background: #fff;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.chip.active {
  background: #000;
  border-color: #000;
  color: #fff;
}

.state {
  padding: 60px 0;
  text-align: center;
  color: #777;
  font-size: 13px;
}

.state.error {
  color: #c0392b;
}

.report-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.report-card {
  border: 1px solid #e5e5e5;
  padding: 20px 22px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.report-card:hover {
  border-color: #000;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.status {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid #ccc;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status.completed {
  color: #1e8449;
  border-color: #1e8449;
}

.status.failed {
  color: #c0392b;
  border-color: #c0392b;
}

.status.pending,
.status.planning,
.status.generating {
  color: #b9770e;
  border-color: #b9770e;
}

.date,
.meta {
  font-size: 11px;
  color: #888;
}

.card-title {
  margin: 0 0 8px;
  font-size: 17px;
  line-height: 1.4;
  font-weight: 700;
}

.card-summary {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.6;
  color: #444;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.actions {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.text-btn {
  background: none;
  border: none;
  padding: 0;
  font-family: inherit;
  font-size: 12px;
  color: #000;
  text-decoration: underline;
  cursor: pointer;
}

.text-btn:hover {
  color: #666;
}

.text-btn.on {
  font-weight: 700;
}

.dl {
  position: relative;
}

.dl-menu {
  position: absolute;
  right: 0;
  top: 100%;
  margin-top: 6px;
  z-index: 5;
  min-width: 150px;
  background: #fff;
  border: 1px solid #000;
  display: flex;
  flex-direction: column;
}

.dl-menu a {
  padding: 8px 12px;
  font-size: 12px;
  color: #000;
  text-decoration: none;
  white-space: nowrap;
}

.dl-menu a:hover {
  background: #f4f4f4;
}

.detail {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed #ddd;
  cursor: default;
}

.detail-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #666;
  margin-bottom: 10px;
}

.detail-note {
  font-size: 12px;
  color: #888;
}

.detail-note.error {
  color: #c0392b;
}

.detail-text {
  margin: 0;
  padding: 12px 14px;
  max-height: 320px;
  overflow: auto;
  background: #fafafa;
  border: 1px solid #eee;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.file-list {
  list-style: none;
  margin: 0 0 10px;
  padding: 0;
  font-size: 12px;
}

.file-list li {
  padding: 3px 0;
}

.dim {
  color: #888;
}
</style>
