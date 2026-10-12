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
          <div v-if="r.stats" class="chips">
            <span class="stat-chip"><b>{{ r.stats.agents }}</b> {{ $t('reportsPage.agents') }} / {{ $t('reportsPage.personas') }}</span>
            <span v-for="p in r.stats.platforms" :key="p.key" class="stat-chip platform">
              {{ platformLabel(p.key) }} · <b>{{ p.actions }}</b> {{ $t('reportsPage.actions') }}
            </span>
            <span class="stat-chip"><b>{{ r.stats.rounds }}</b>/{{ r.stats.total_rounds }} {{ $t('reportsPage.rounds') }}</span>
            <span v-if="r.stats.model" class="stat-chip mono">{{ r.stats.model }}</span>
          </div>
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
                :class="{ on: panel[r.report_id] === 'stats' }"
                @click.stop="togglePanel(r, 'stats')"
              >{{ $t('reportsPage.simStats') }}</button>
              <button
                class="text-btn"
                :class="{ on: panel[r.report_id] === 'quotes' }"
                @click.stop="togglePanel(r, 'quotes')"
              >{{ $t('reportsPage.keyQuotes') }}</button>
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
              <template v-if="panel[r.report_id] === 'stats'">
                <div class="detail-label">{{ $t('reportsPage.simStats') }}</div>
                <div v-if="!ctx[r.report_id].stats" class="detail-note">{{ $t('reportsPage.noStats') }}</div>
                <template v-else>
                  <div class="kpis">
                    <div class="kpi"><span class="kpi-v">{{ ctx[r.report_id].stats.agents }}</span><span class="kpi-l">{{ $t('reportsPage.agents') }}</span></div>
                    <div class="kpi"><span class="kpi-v">{{ ctx[r.report_id].stats.active_agents }}</span><span class="kpi-l">{{ $t('reportsPage.active') }}</span></div>
                    <div class="kpi"><span class="kpi-v">{{ ctx[r.report_id].stats.total_actions }}</span><span class="kpi-l">{{ $t('reportsPage.actions') }}</span></div>
                    <div class="kpi"><span class="kpi-v">{{ ctx[r.report_id].stats.rounds }}</span><span class="kpi-l">{{ $t('reportsPage.rounds') }}</span></div>
                    <div v-if="ctx[r.report_id].stats.simulated_hours != null" class="kpi"><span class="kpi-v">{{ ctx[r.report_id].stats.simulated_hours }}</span><span class="kpi-l">{{ $t('reportsPage.hours') }}</span></div>
                    <div v-if="ctx[r.report_id].stats.duration_seconds != null" class="kpi"><span class="kpi-v">{{ formatDuration(ctx[r.report_id].stats.duration_seconds) }}</span><span class="kpi-l">{{ $t('reportsPage.duration') }}</span></div>
                  </div>

                  <div v-if="ctx[r.report_id].stats.timeline.length" class="stat-block">
                    <div class="stat-title">{{ $t('reportsPage.activityByRound') }}</div>
                    <svg class="chart" :viewBox="`0 0 ${CHART_W} ${CHART_H}`" preserveAspectRatio="none">
                      <line v-for="g in chartGrid(ctx[r.report_id].stats.timeline)" :key="g.y" :x1="PAD_L" :x2="CHART_W - PAD_R" :y1="g.y" :y2="g.y" class="grid" />
                      <text v-for="g in chartGrid(ctx[r.report_id].stats.timeline)" :key="'t' + g.y" :x="PAD_L - 6" :y="g.y + 3" class="axis" text-anchor="end">{{ g.label }}</text>
                      <polyline
                        v-for="(p, i) in ctx[r.report_id].stats.platforms"
                        :key="p.key"
                        :points="chartPoints(ctx[r.report_id].stats.timeline, p.key)"
                        fill="none"
                        :stroke="SERIES_COLORS[i % SERIES_COLORS.length]"
                        stroke-width="2"
                        stroke-linejoin="round"
                        vector-effect="non-scaling-stroke"
                      />
                      <text
                        v-for="x in chartXLabels(ctx[r.report_id].stats.timeline)"
                        :key="'x' + x.round"
                        :x="x.x" :y="CHART_H - 4" class="axis" text-anchor="middle"
                      >{{ x.round }}</text>
                    </svg>
                    <div class="legend">
                      <span v-for="(p, i) in ctx[r.report_id].stats.platforms" :key="p.key" class="legend-item">
                        <i :style="{ background: SERIES_COLORS[i % SERIES_COLORS.length] }"></i>{{ platformLabel(p.key) }}
                      </span>
                      <span class="dim">· {{ $t('reportsPage.round') }}</span>
                    </div>
                  </div>

                  <div v-for="p in ctx[r.report_id].stats.platforms" :key="p.key" class="stat-block">
                    <div class="stat-title">{{ platformLabel(p.key) }}
                      <span class="dim mono">· {{ p.active_agents }} {{ $t('reportsPage.active') }} · {{ p.actions }} {{ $t('reportsPage.actions') }}</span>
                    </div>
                    <div v-for="a in p.action_types" :key="a.type" class="bar-row">
                      <span class="bar-label mono">{{ a.type }}</span>
                      <span class="bar-track"><span class="bar-fill" :style="{ width: barWidth(a.count, p.action_types) }"></span></span>
                      <span class="bar-num mono">{{ a.count }}</span>
                    </div>
                  </div>

                  <div class="stat-block">
                    <div class="stat-title">{{ $t('reportsPage.entityTypes') }}</div>
                    <div v-for="e in ctx[r.report_id].stats.entity_types" :key="e.type" class="bar-row">
                      <span class="bar-label mono">{{ e.type }}</span>
                      <span class="bar-track"><span class="bar-fill" :style="{ width: barWidth(e.count, ctx[r.report_id].stats.entity_types) }"></span></span>
                      <span class="bar-num mono">{{ e.count }}</span>
                    </div>
                  </div>

                  <div v-if="ctx[r.report_id].stats.top_agents.length" class="stat-block">
                    <div class="stat-title">{{ $t('reportsPage.topAgents') }}</div>
                    <div v-for="a in ctx[r.report_id].stats.top_agents" :key="a.agent_id" class="top-row">
                      <span>{{ a.name }} <span class="dim mono">{{ a.type }}</span></span>
                      <span class="mono">{{ a.actions }}</span>
                    </div>
                  </div>

                  <div v-if="ctx[r.report_id].stats.model" class="detail-note">
                    {{ $t('reportsPage.model') }}: <span class="mono">{{ ctx[r.report_id].stats.model }}</span>
                  </div>
                </template>
              </template>
              <template v-else-if="panel[r.report_id] === 'quotes'">
                <div class="detail-label">{{ $t('reportsPage.keyQuotes') }}</div>
                <div v-if="!ctx[r.report_id].stats?.quotes?.length" class="detail-note">{{ $t('reportsPage.noQuotes') }}</div>
                <template v-else>
                  <div v-for="group in quoteGroups(ctx[r.report_id].stats.quotes)" :key="group.kind" class="stat-block">
                    <div class="stat-title">{{ group.kind === 'post' ? $t('reportsPage.topPosts') : $t('reportsPage.topComments') }}</div>
                    <blockquote v-for="(q, i) in group.items" :key="i" class="quote">
                      <p>{{ q.content }}</p>
                      <footer>
                        <b>{{ q.author }}</b>
                        <span v-if="q.author_type" class="dim mono"> · {{ q.author_type }}</span>
                        <span class="dim mono"> · {{ platformLabel(q.platform) }}</span>
                        <span v-if="q.round" class="dim mono"> · {{ $t('reportsPage.round') }} {{ q.round }}</span>
                        <span class="quote-score mono">♥ {{ q.likes }}<template v-if="q.shares"> · ⇄ {{ q.shares }}</template></span>
                      </footer>
                    </blockquote>
                  </div>
                </template>
              </template>
              <template v-else-if="panel[r.report_id] === 'seed'">
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

const CHART_W = 600
const CHART_H = 150
const PAD_L = 28
const PAD_R = 8
const PAD_T = 8
const PAD_B = 18
const SERIES_COLORS = ['#000000', '#ff4500', '#2e86de']

const chartMax = (timeline) => {
  let max = 1
  for (const row of timeline) {
    for (const k of Object.keys(row)) if (k !== 'round') max = Math.max(max, row[k])
  }
  return max
}

const chartX = (i, n) => PAD_L + (n <= 1 ? 0 : (i / (n - 1)) * (CHART_W - PAD_L - PAD_R))
const chartY = (v, max) => PAD_T + (1 - v / max) * (CHART_H - PAD_T - PAD_B)

const chartPoints = (timeline, key) => {
  const max = chartMax(timeline)
  return timeline.map((row, i) => `${chartX(i, timeline.length)},${chartY(row[key] || 0, max)}`).join(' ')
}

const chartGrid = (timeline) => {
  const max = chartMax(timeline)
  return [0, 0.5, 1].map(f => ({ y: chartY(max * f, max), label: Math.round(max * f) }))
}

const chartXLabels = (timeline) => {
  const step = Math.max(1, Math.ceil(timeline.length / 10))
  return timeline
    .map((row, i) => ({ round: row.round, x: chartX(i, timeline.length) }))
    .filter((_, i) => i % step === 0 || i === timeline.length - 1)
}

const quoteGroups = (quotes) =>
  ['post', 'comment']
    .map(kind => ({ kind, items: quotes.filter(q => q.kind === kind) }))
    .filter(g => g.items.length)

const platformLabel = (key) => t(`reportsPage.${key}`)

const barWidth = (count, rows) => {
  const max = Math.max(...rows.map(r => r.count), 1)
  return `${Math.max((count / max) * 100, 2)}%`
}

const formatDuration = (sec) => {
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  return m < 60 ? `${m}m ${sec % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

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

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 14px;
}

.stat-chip {
  font-size: 11px;
  padding: 3px 9px;
  background: #f4f4f4;
  color: #333;
}

.stat-chip.platform {
  background: #000;
  color: #fff;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.kpi {
  border: 1px solid #eee;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kpi-v {
  font-size: 20px;
  font-weight: 700;
}

.kpi-l {
  font-size: 11px;
  color: #777;
}

.stat-block {
  margin-bottom: 18px;
}

.stat-title {
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 8px;
}

.bar-row {
  display: grid;
  grid-template-columns: 170px 1fr 40px;
  align-items: center;
  gap: 10px;
  padding: 2px 0;
  font-size: 11px;
}

.bar-track {
  height: 8px;
  background: #f0f0f0;
}

.bar-fill {
  display: block;
  height: 100%;
  background: #000;
}

.bar-num {
  text-align: right;
}

.chart {
  width: 100%;
  height: 150px;
  display: block;
}

.chart .grid {
  stroke: #eee;
  stroke-width: 1;
}

.chart .axis {
  font-size: 9px;
  fill: #888;
  font-family: inherit;
}

.legend {
  display: flex;
  gap: 14px;
  font-size: 11px;
  margin-top: 6px;
  align-items: center;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-item i {
  width: 10px;
  height: 10px;
  display: inline-block;
}

.quote {
  margin: 0 0 12px;
  padding: 10px 14px;
  border-left: 3px solid #000;
  background: #fafafa;
}

.quote p {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.quote footer {
  font-size: 11px;
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  align-items: baseline;
}

.quote-score {
  margin-left: auto;
  color: #444;
}

.top-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 3px 0;
  border-bottom: 1px solid #f2f2f2;
}
</style>
