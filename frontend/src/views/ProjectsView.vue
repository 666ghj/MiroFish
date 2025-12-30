<template>
  <div class="projects-page">
    <nav class="navbar">
      <div class="nav-brand" @click="goHome">MIROFISH</div>

      <div class="nav-center">
        <div class="title">历史项目</div>
        <div class="subtitle">默认只显示“已生成报告/可交互”的项目，点击可直接进入交互页</div>
      </div>

      <div class="nav-actions">
        <button class="btn" @click="refresh" :disabled="loading">刷新</button>
        <button class="btn primary" @click="goHome">新建项目</button>
      </div>
    </nav>

    <main class="content">
      <div class="toolbar">
        <div class="search">
          <input
            v-model="query"
            class="search-input"
            placeholder="搜索项目名称 / 项目ID / 图谱ID / 模拟ID / 报告ID"
            :disabled="loading"
          />
          <button class="btn" @click="clearQuery" :disabled="!query">清空</button>
        </div>
        <div class="filter">
          <select v-model="filterMode" class="select" :disabled="loading">
            <option value="interactive">仅显示可交互（报告已生成）</option>
            <option value="env">仅显示环境已就绪</option>
            <option value="all">显示全部</option>
          </select>
        </div>
        <div class="meta">
          <span v-if="loading">加载中...</span>
          <span v-else>共 {{ filteredProjects.length }} 个</span>
        </div>
      </div>

      <div v-if="error" class="error-box">
        <div class="error-title">加载失败</div>
        <div class="error-msg">{{ error }}</div>
        <button class="btn primary" @click="refresh">重试</button>
      </div>

      <div v-else-if="!loading && filteredProjects.length === 0" class="empty-box">
        <div class="empty-title">暂无历史项目</div>
        <div class="empty-msg">去首页上传文件创建一个新项目。</div>
        <button class="btn primary" @click="goHome">去首页</button>
      </div>

      <div v-else class="list">
        <div class="list-header">
          <div class="col name">项目</div>
          <div class="col status">交互</div>
          <div class="col ids">ID</div>
          <div class="col time">更新时间</div>
          <div class="col action">操作</div>
        </div>

        <button
          v-for="p in filteredProjects"
          :key="p.project_id"
          class="row"
          type="button"
          @click="p.latest_completed_report?.report_id ? openInteraction(p.latest_completed_report.report_id) : (p.latest_report?.report_id ? openReport(p.latest_report.report_id) : (p.latest_ready_simulation?.simulation_id ? openEnv(p.latest_ready_simulation.simulation_id) : openProject(p.project_id)))"
        >
          <div class="col name">
            <div class="name-main">{{ p.name || 'Unnamed Project' }}</div>
            <div class="name-sub" v-if="p.simulation_requirement">
              {{ p.simulation_requirement }}
            </div>
          </div>
          <div class="col status">
            <span class="status-pill" :class="reportStatusClass(p.latest_completed_report?.report_status || p.latest_report?.report_status)">
              {{ reportStatusText(p.latest_completed_report?.report_status || p.latest_report?.report_status) }}
            </span>
          </div>
          <div class="col ids">
            <div class="mono">{{ p.project_id }}</div>
            <div class="mono muted" v-if="p.graph_id">graph: {{ p.graph_id }}</div>
            <div class="mono muted" v-if="p.latest_ready_simulation?.simulation_id">
              sim: {{ p.latest_ready_simulation.simulation_id }}
            </div>
            <div class="mono muted" v-if="p.latest_completed_report?.report_id || p.latest_report?.report_id">
              report: {{ p.latest_completed_report?.report_id || p.latest_report?.report_id }}
            </div>
          </div>
          <div class="col time">
            {{ formatTime(p.latest_completed_report?.updated_at || p.latest_report?.updated_at || p.latest_ready_simulation?.updated_at || p.updated_at || p.created_at) }}
          </div>
          <div class="col action">
            <div class="actions" @click.stop>
              <button
                v-if="p.latest_completed_report?.report_id"
                class="mini-btn primary"
                type="button"
                @click="openInteraction(p.latest_completed_report.report_id)"
              >
                交互 →
              </button>
              <button
                v-if="p.latest_completed_report?.report_id || p.latest_report?.report_id"
                class="mini-btn"
                type="button"
                @click="openReport(p.latest_completed_report?.report_id || p.latest_report?.report_id)"
              >
                报告 →
              </button>
              <button
                v-if="p.latest_ready_simulation?.simulation_id"
                class="mini-btn"
                type="button"
                @click="openEnv(p.latest_ready_simulation.simulation_id)"
              >
                环境 →
              </button>
              <button class="mini-btn" type="button" @click="openProject(p.project_id)">项目 →</button>
            </div>
          </div>
        </button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listProjects } from '../api/graph'
import { listSimulations } from '../api/simulation'
import { checkReportStatus } from '../api/report'

const router = useRouter()

const loading = ref(false)
const error = ref('')
const projects = ref([])
const query = ref('')
const filterMode = ref('interactive')

const ENV_READY_STATUSES = new Set(['ready', 'running', 'paused', 'stopped', 'completed'])

const goHome = () => router.push({ name: 'Home' })

const refresh = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listProjects(200)
    const baseProjects = res?.data || []

    let allSimulations = []
    try {
      const simsRes = await listSimulations()
      allSimulations = Array.isArray(simsRes?.data) ? simsRes.data : []
    } catch {
      allSimulations = []
    }

    const latestReadyByProjectId = new Map()
    for (const sim of allSimulations) {
      if (!ENV_READY_STATUSES.has(sim?.status)) continue
      const projectId = sim?.project_id
      if (!projectId) continue

      const ts = Date.parse(sim?.updated_at || sim?.created_at || '') || 0
      const existing = latestReadyByProjectId.get(projectId)
      const existingTs = Date.parse(existing?.updated_at || existing?.created_at || '') || 0
      if (!existing || ts >= existingTs) {
        latestReadyByProjectId.set(projectId, sim)
      }
    }

    const simsByProjectId = new Map()
    for (const sim of allSimulations) {
      if (!ENV_READY_STATUSES.has(sim?.status)) continue
      if (!sim?.project_id || !sim?.simulation_id) continue
      if (!simsByProjectId.has(sim.project_id)) simsByProjectId.set(sim.project_id, [])
      simsByProjectId.get(sim.project_id).push(sim)
    }

    for (const [projectId, sims] of simsByProjectId.entries()) {
      sims.sort((a, b) => {
        const at = Date.parse(a?.updated_at || a?.created_at || '') || 0
        const bt = Date.parse(b?.updated_at || b?.created_at || '') || 0
        return bt - at
      })
      simsByProjectId.set(projectId, sims)
    }

    const latestReportByProjectId = new Map()
    const latestCompletedReportByProjectId = new Map()
    await Promise.all(
      baseProjects.map(async p => {
        const sims = simsByProjectId.get(p.project_id) || []
        let latestAnyReport = null
        for (const sim of sims) {
          try {
            const r = await checkReportStatus(sim.simulation_id)

            if (r?.success && r?.data?.has_report && r?.data?.report_id && !latestAnyReport) {
              latestAnyReport = {
                report_id: r.data.report_id,
                simulation_id: sim.simulation_id,
                report_status: r.data.report_status,
                interview_unlocked: !!r.data.interview_unlocked,
                updated_at: sim.updated_at || sim.created_at || null
              }
            }

            if (r?.success && r?.data?.interview_unlocked && r?.data?.report_id) {
              const completed = {
                report_id: r.data.report_id,
                simulation_id: sim.simulation_id,
                report_status: r.data.report_status,
                interview_unlocked: true,
                updated_at: sim.updated_at || sim.created_at || null
              }
              latestCompletedReportByProjectId.set(p.project_id, completed)
              if (!latestAnyReport) latestAnyReport = completed
              break
            }
          } catch {
            // ignore
          }
        }

        if (latestAnyReport) {
          latestReportByProjectId.set(p.project_id, latestAnyReport)
        }
      })
    )

    projects.value = baseProjects.map(p => {
      const latestReady = latestReadyByProjectId.get(p.project_id) || null
      const latestReport = latestCompletedReportByProjectId.get(p.project_id) || null
      const latestAny = latestReportByProjectId.get(p.project_id) || null
      return {
        ...p,
        latest_ready_simulation: latestReady
          ? {
              simulation_id: latestReady.simulation_id,
              status: latestReady.status,
              updated_at: latestReady.updated_at || latestReady.created_at || null
            }
          : null,
        latest_report: latestAny,
        latest_completed_report: latestReport
      }
    })
  } catch (e) {
    error.value = e?.message || 'Unknown error'
  } finally {
    loading.value = false
  }
}

const clearQuery = () => {
  query.value = ''
}

const filteredProjects = computed(() => {
  const q = query.value.trim().toLowerCase()
  let base = projects.value

  if (filterMode.value === 'env') base = base.filter(p => p?.latest_ready_simulation?.simulation_id)
  if (filterMode.value === 'interactive') base = base.filter(p => p?.latest_completed_report?.report_id)

  if (!q) return base

  return base.filter(p => {
    const haystack = [
      p?.name,
      p?.project_id,
      p?.graph_id,
      p?.simulation_requirement,
      p?.latest_ready_simulation?.simulation_id,
      p?.latest_completed_report?.report_id
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return haystack.includes(q)
  })
})

const openProject = (projectId) => {
  if (!projectId) return
  router.push({ name: 'Process', params: { projectId } })
}

const openEnv = (simulationId) => {
  if (!simulationId) return
  router.push({ name: 'Simulation', params: { simulationId } })
}

const openReport = (reportId) => {
  if (!reportId) return
  router.push({ name: 'Report', params: { reportId } })
}

const openInteraction = (reportId) => {
  if (!reportId) return
  router.push({ name: 'Interaction', params: { reportId } })
}

const envStatusText = (status) => {
  switch (status) {
    case 'ready':
      return '已就绪'
    case 'running':
      return '模拟中'
    case 'paused':
      return '已暂停'
    case 'stopped':
      return '已停止'
    case 'completed':
      return '已完成'
    default:
      return status ? `状态: ${status}` : '未准备'
  }
}

const envStatusClass = (status) => {
  switch (status) {
    case 'ready':
    case 'completed':
      return 'ok'
    case 'running':
      return 'running'
    case 'paused':
    case 'stopped':
      return 'neutral'
    case 'failed':
      return 'bad'
    default:
      return 'neutral'
  }
}

const reportStatusText = (status) => {
  if (!status) return '未生成'
  if (status === 'completed') return '已解锁'
  if (status === 'generating') return '生成中'
  if (status === 'failed') return '失败'
  return status
}

const reportStatusClass = (status) => {
  if (status === 'completed') return 'ok'
  if (status === 'generating') return 'running'
  if (status === 'failed') return 'bad'
  return 'neutral'
}

const formatTime = (isoString) => {
  if (!isoString) return '-'
  const dt = new Date(isoString)
  if (Number.isNaN(dt.getTime())) return isoString

  return dt.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.projects-page {
  min-height: 100vh;
  background: #fff;
  color: #000;
}

.navbar {
  height: 60px;
  background: #000;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  gap: 16px;
}

.nav-brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  letter-spacing: 1px;
  font-size: 1.1rem;
  cursor: pointer;
}

.nav-center {
  flex: 1;
  min-width: 0;
}

.title {
  font-weight: 700;
  font-size: 1rem;
}

.subtitle {
  margin-top: 2px;
  font-size: 0.8rem;
  opacity: 0.75;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn {
  height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: transparent;
  color: #fff;
  cursor: pointer;
  font-size: 0.9rem;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn.primary {
  background: #ff4500;
  border-color: #ff4500;
}

.content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 28px 24px 40px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.search {
  display: flex;
  gap: 10px;
  flex: 1;
}

.filter {
  display: flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
  color: #333;
  font-size: 0.9rem;
}

.select {
  height: 38px;
  border: 1px solid #e5e5e5;
  border-radius: 10px;
  padding: 0 10px;
  background: #fff;
  outline: none;
  font-size: 0.92rem;
}

.search-input {
  flex: 1;
  height: 38px;
  border: 1px solid #e5e5e5;
  border-radius: 10px;
  padding: 0 12px;
  font-size: 0.95rem;
  outline: none;
}

.meta {
  white-space: nowrap;
  color: #666;
  font-size: 0.9rem;
}

.error-box,
.empty-box {
  border: 1px solid #e5e5e5;
  border-radius: 14px;
  padding: 18px;
  background: #fafafa;
}

.error-title,
.empty-title {
  font-weight: 700;
  margin-bottom: 6px;
}

.error-msg,
.empty-msg {
  color: #666;
  margin-bottom: 14px;
}

.error-box .btn,
.empty-box .btn {
  border-color: #000;
  color: #000;
}

.error-box .btn.primary,
.empty-box .btn.primary {
  border-color: #ff4500;
  color: #fff;
}

.list {
  border: 1px solid #e5e5e5;
  border-radius: 14px;
  overflow: hidden;
}

.list-header {
  display: grid;
  grid-template-columns: 2fr 0.7fr 1.6fr 1fr 1.2fr;
  gap: 12px;
  padding: 12px 14px;
  background: #f7f7f7;
  font-weight: 700;
  font-size: 0.85rem;
  color: #333;
}

.row {
  width: 100%;
  text-align: left;
  display: grid;
  grid-template-columns: 2fr 0.7fr 1.6fr 1fr 1.2fr;
  gap: 12px;
  padding: 14px;
  border: none;
  background: #fff;
  cursor: pointer;
  border-top: 1px solid #eee;
}

.row:hover {
  background: #fafafa;
}

.col {
  min-width: 0;
}

.name-main {
  font-weight: 700;
}

.name-sub {
  margin-top: 4px;
  color: #666;
  font-size: 0.85rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
}

.mono.muted {
  color: #666;
  margin-top: 4px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 0.82rem;
  border: 1px solid #ddd;
  background: #fff;
}

.status-pill.ok {
  border-color: rgba(0, 160, 90, 0.35);
  color: #008a4b;
  background: rgba(0, 160, 90, 0.08);
}

.status-pill.running {
  border-color: rgba(255, 69, 0, 0.35);
  color: #ff4500;
  background: rgba(255, 69, 0, 0.08);
}

.status-pill.bad {
  border-color: rgba(220, 0, 0, 0.35);
  color: #c40000;
  background: rgba(220, 0, 0, 0.08);
}

.status-pill.neutral {
  color: #333;
  background: #f6f6f6;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.mini-btn {
  height: 30px;
  padding: 0 10px;
  border-radius: 10px;
  border: 1px solid #e5e5e5;
  background: #fff;
  color: #000;
  cursor: pointer;
  font-size: 0.85rem;
}

.mini-btn.primary {
  border-color: #ff4500;
  background: rgba(255, 69, 0, 0.08);
  color: #ff4500;
}

@media (max-width: 900px) {
  .list-header,
  .row {
    grid-template-columns: 2fr 1fr;
    grid-template-areas:
      "name status"
      "ids time";
  }

  .col.name {
    grid-area: name;
  }
  .col.status {
    grid-area: status;
  }
  .col.ids {
    grid-area: ids;
  }
  .col.time {
    grid-area: time;
  }
  .col.action {
    display: none;
  }

  .subtitle {
    display: none;
  }
}
</style>
