<template>
  <div class="history-page">
    <header class="topbar">
      <router-link to="/" class="brand">MIROFISH</router-link>
      <router-link to="/" class="back-link">返回首页 ↗</router-link>
    </header>

    <main>
      <section class="page-heading">
        <div><p class="eyebrow">ARCHIVE / 本地工作台</p><h1>历史记录</h1></div>
        <button type="button" class="refresh-button" :disabled="loading" @click="loadActive">{{ loading ? '刷新中…' : '刷新记录' }}</button>
      </section>

      <nav class="tabs" aria-label="历史记录类型">
        <button type="button" :class="{ active: activeTab === 'projects' }" @click="activeTab = 'projects'">项目 <span>{{ projects.length }}</span></button>
        <button type="button" :class="{ active: activeTab === 'tasks' }" @click="activeTab = 'tasks'">后台任务 <span>{{ tasks.length }}</span></button>
      </nav>

      <section v-if="activeTab === 'tasks'" class="filters" aria-label="任务状态筛选">
        <button v-for="filter in taskFilters" :key="filter.value || 'all'" type="button" :class="{ active: taskStatus === filter.value }" @click="taskStatus = filter.value">{{ filter.label }}</button>
      </section>

      <div v-if="error" class="error-banner" role="alert"><span>{{ error }}</span><button type="button" @click="loadActive">重试</button></div>
      <div v-if="loading && !hasLoaded" class="loading-state" aria-live="polite"><span></span>正在读取本地历史记录…</div>
      <template v-else>
        <HistoryProjectList v-if="activeTab === 'projects'" :projects="displayProjects" @open="openProject" />
        <HistoryTaskList v-else :tasks="tasks" @open-project="openProject" />
      </template>
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import HistoryProjectList from '../components/HistoryProjectList.vue'
import HistoryTaskList from '../components/HistoryTaskList.vue'
import { getHistoryProjects, getHistoryTasks } from '../api/history'

const router = useRouter()
const activeTab = ref('projects')
const taskStatus = ref('')
const projects = ref([])
const tasks = ref([])
const loading = ref(false)
const error = ref('')
const loadedTabs = ref(new Set())
const hasLoaded = computed(() => loadedTabs.value.has(activeTab.value))
const displayProjects = computed(() => projects.value.map(project => {
  const relatedTask = tasks.value.find(task => task.metadata?.project_id === project.project_id && task.metadata?.simulation_id)
  return { ...project, simulation_id: relatedTask?.metadata?.simulation_id || null }
}))
const taskFilters = [
  { label: '全部', value: '' }, { label: '运行中', value: 'processing' },
  { label: '已完成', value: 'completed' }, { label: '失败', value: 'failed' },
  { label: '已中断', value: 'interrupted' }
]

async function loadActive() {
  loading.value = true
  error.value = ''
  try {
    if (activeTab.value === 'projects') {
      const [projectResponse, taskResponse] = await Promise.all([
        getHistoryProjects(),
        getHistoryTasks()
      ])
      projects.value = projectResponse.data || []
      tasks.value = taskResponse.data || []
    } else {
      const response = await getHistoryTasks({ status: taskStatus.value || undefined })
      tasks.value = response.data || []
    }
    loadedTabs.value = new Set([...loadedTabs.value, activeTab.value])
  } catch (requestError) {
    error.value = requestError?.message || '历史记录加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function openProject(projectId) { router.push(`/process/${projectId}`) }
watch(activeTab, loadActive, { immediate: true })
watch(taskStatus, () => { if (activeTab.value === 'tasks') loadActive() })
</script>

<style scoped>
.history-page { min-height: 100vh; background: #f7f7f5; color: #111; --orange: #e85d18; }
.topbar { height: 72px; padding: 0 clamp(20px, 5vw, 72px); background: #fff; border-bottom: 1px solid #ddd; display: flex; align-items: center; justify-content: space-between; }
.brand { color: #111; font-size: 20px; font-weight: 800; letter-spacing: -.04em; text-decoration: none; }.back-link { color: #333; font-size: 13px; min-height: 44px; display: flex; align-items: center; }
main { width: min(1180px, calc(100% - 40px)); margin: 0 auto; padding: 64px 0 96px; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 48px; }.eyebrow { color: var(--orange); font-size: 12px; letter-spacing: .14em; margin-bottom: 12px; }.page-heading h1 { font-size: clamp(42px, 7vw, 82px); line-height: .95; letter-spacing: -.06em; }
.refresh-button { min-height: 44px; padding: 0 20px; border: 1px solid #111; background: transparent; cursor: pointer; }.refresh-button:hover:not(:disabled), .refresh-button:focus-visible { color: #fff; background: #111; outline: none; }.refresh-button:disabled { opacity: .45; cursor: wait; }
.tabs { display: flex; border-bottom: 1px solid #bbb; margin-bottom: 28px; }.tabs button { min-height: 52px; padding: 0 24px; border: 0; border-bottom: 3px solid transparent; background: transparent; cursor: pointer; font-size: 15px; }.tabs button.active { border-color: var(--orange); font-weight: 700; }.tabs span { margin-left: 6px; color: #888; font-variant-numeric: tabular-nums; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }.filters button { min-height: 40px; padding: 0 14px; border: 1px solid #ccc; background: #fff; cursor: pointer; }.filters button.active { color: #fff; background: #111; border-color: #111; }
.error-banner { margin-bottom: 24px; padding: 14px 16px; border: 1px solid #a53b3b; background: #fff4f4; display: flex; justify-content: space-between; align-items: center; gap: 16px; color: #7d2424; }.error-banner button { min-height: 40px; padding: 0 14px; border: 1px solid currentColor; background: transparent; cursor: pointer; }
.loading-state { min-height: 220px; border: 1px dashed #bbb; display: flex; align-items: center; justify-content: center; gap: 12px; color: #666; }.loading-state span { width: 12px; height: 12px; background: var(--orange); animation: pulse 1s ease-in-out infinite alternate; }
@keyframes pulse { to { opacity: .25; transform: scale(.75); } }
@media (max-width: 600px) { .topbar { height: 64px; }.page-heading { align-items: stretch; flex-direction: column; margin-bottom: 32px; }.refresh-button { width: 100%; }.tabs button { flex: 1; padding: 0 8px; }.history-page main { width: min(100% - 28px, 1180px); padding-top: 40px; } }
@media (prefers-reduced-motion: reduce) { .loading-state span { animation: none; } }
</style>
