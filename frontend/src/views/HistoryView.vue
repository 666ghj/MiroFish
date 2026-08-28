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
        <HistoryProjectList v-if="activeTab === 'projects'" :projects="displayProjects" @open="openProject" @edit="editProject" @delete="requestProjectDelete" />
        <HistoryTaskList v-else :tasks="displayTasks" @open-project="openProject" @edit="editTask" @delete="requestTaskDelete" />
      </template>
    </main>

    <Teleport to="body">
      <div v-if="dialog" class="dialog-backdrop" @click.self="closeDialog">
        <section class="dialog" role="dialog" aria-modal="true" :aria-labelledby="dialog.type.startsWith('edit') ? 'edit-title' : 'delete-title'">
          <template v-if="dialog.type === 'edit-project'">
            <p class="dialog-eyebrow">EDIT PROJECT</p>
            <h2 id="edit-title">修改项目名称</h2>
            <label>项目名称<input v-model="dialog.name" maxlength="120" autofocus /></label>
          </template>
          <template v-else-if="dialog.type === 'edit-task'">
            <p class="dialog-eyebrow">EDIT TASK</p>
            <h2 id="edit-title">修改任务信息</h2>
            <label>任务显示名称<input v-model="dialog.name" maxlength="160" autofocus /></label>
            <label>备注<textarea v-model="dialog.note" maxlength="500" rows="4"></textarea></label>
          </template>
          <template v-else-if="dialog.type === 'delete-project'">
            <p class="dialog-eyebrow danger">DESTRUCTIVE ACTION</p>
            <h2 id="delete-title">彻底删除项目</h2>
            <p>将删除项目文件、图谱、模拟、报告和关联任务，操作不可恢复。</p>
            <label>输入项目名称以确认彻底删除<input v-model="deleteConfirmation" :placeholder="dialog.entity.name" autofocus /></label>
          </template>
          <template v-else>
            <p class="dialog-eyebrow danger">DELETE TASK</p>
            <h2 id="delete-title">删除任务记录</h2>
            <p>仅删除这条后台任务历史，不会删除关联项目。</p>
          </template>
          <p v-if="dialogError" class="dialog-error" role="alert">{{ dialogError }}</p>
          <footer>
            <button type="button" class="cancel-button" :disabled="mutationLoading" @click="closeDialog">取消</button>
            <button v-if="dialog.type.startsWith('edit')" type="button" class="primary-button" :disabled="mutationLoading || !dialog.name.trim()" @click="saveEdit">{{ mutationLoading ? '保存中…' : '保存' }}</button>
            <button v-else type="button" class="confirm-delete" :disabled="mutationLoading || (dialog.type === 'delete-project' && deleteConfirmation !== dialog.entity.name)" @click="confirmDelete">{{ mutationLoading ? '删除中…' : '确认删除' }}</button>
          </footer>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import HistoryProjectList from '../components/HistoryProjectList.vue'
import HistoryTaskList from '../components/HistoryTaskList.vue'
import {
  deleteHistoryProject,
  deleteHistoryTask,
  getHistoryProjects,
  getHistoryTasks,
  updateHistoryProject,
  updateHistoryTask
} from '../api/history'

const router = useRouter()
const activeTab = ref('projects')
const taskStatus = ref('')
const projects = ref([])
const tasks = ref([])
const loading = ref(false)
const error = ref('')
const dialog = ref(null)
const dialogError = ref('')
const deleteConfirmation = ref('')
const mutationLoading = ref(false)
const loadedTabs = ref(new Set())
const hasLoaded = computed(() => loadedTabs.value.has(activeTab.value))
const displayProjects = computed(() => projects.value.map(project => {
  const relatedTask = tasks.value.find(task => task.metadata?.project_id === project.project_id && task.metadata?.simulation_id)
  return { ...project, simulation_id: relatedTask?.metadata?.simulation_id || null }
}))
const displayTasks = computed(() => {
  const projectNames = new Map(projects.value.map(project => [project.project_id, project.name || '未命名项目']))
  return tasks.value.map(task => ({
    ...task,
    project_name: task.metadata?.project_id
      ? projectNames.get(task.metadata.project_id) || null
      : null
  }))
})
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
function editProject(project) {
  dialogError.value = ''
  dialog.value = { type: 'edit-project', entity: project, name: project.name || '', note: '' }
}
function editTask(task) {
  dialogError.value = ''
  dialog.value = { type: 'edit-task', entity: task, name: task.task_type || '', note: task.metadata?.note || '' }
}
function requestProjectDelete(project) {
  dialogError.value = ''
  deleteConfirmation.value = ''
  dialog.value = { type: 'delete-project', entity: project, name: '', note: '' }
}
function requestTaskDelete(task) {
  if (['pending', 'processing'].includes(task.status)) return
  dialogError.value = ''
  dialog.value = { type: 'delete-task', entity: task, name: '', note: '' }
}
function closeDialog() {
  if (mutationLoading.value) return
  dialog.value = null
  dialogError.value = ''
  deleteConfirmation.value = ''
}
async function saveEdit() {
  mutationLoading.value = true
  dialogError.value = ''
  try {
    if (dialog.value.type === 'edit-project') {
      await updateHistoryProject(dialog.value.entity.project_id, dialog.value.name.trim())
    } else {
      await updateHistoryTask(dialog.value.entity.task_id, dialog.value.name.trim(), dialog.value.note.trim())
    }
    dialog.value = null
    await loadActive()
  } catch (requestError) {
    dialogError.value = requestError?.message || '保存失败，请稍后重试。'
  } finally {
    mutationLoading.value = false
  }
}
async function confirmDelete() {
  mutationLoading.value = true
  dialogError.value = ''
  try {
    if (dialog.value.type === 'delete-project') {
      await deleteHistoryProject(dialog.value.entity.project_id)
    } else {
      await deleteHistoryTask(dialog.value.entity.task_id)
    }
    dialog.value = null
    await loadActive()
  } catch (requestError) {
    dialogError.value = requestError?.message || '删除失败，请稍后重试。'
  } finally {
    mutationLoading.value = false
  }
}
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
.dialog-backdrop { position: fixed; inset: 0; z-index: 1000; padding: 20px; display: grid; place-items: center; background: rgba(0, 0, 0, .58); }
.dialog { width: min(520px, 100%); max-height: calc(100vh - 40px); overflow-y: auto; padding: 28px; background: #fff; border: 1px solid #111; box-shadow: 12px 12px 0 rgba(0, 0, 0, .22); }.dialog-eyebrow { margin-bottom: 10px; color: #e85d18; font-size: 11px; letter-spacing: .16em; }.dialog-eyebrow.danger { color: #a53b3b; }.dialog h2 { margin-bottom: 14px; font-size: 28px; }.dialog > p:not(.dialog-eyebrow):not(.dialog-error) { color: #555; line-height: 1.6; }.dialog label { display: grid; gap: 8px; margin-top: 20px; color: #444; font-size: 13px; }.dialog input, .dialog textarea { width: 100%; border: 1px solid #aaa; border-radius: 0; padding: 11px 12px; background: #fff; color: #111; font: inherit; }.dialog input:focus, .dialog textarea:focus { border-color: #e85d18; outline: 2px solid rgba(232, 93, 24, .2); }.dialog-error { margin-top: 18px; padding: 10px 12px; border: 1px solid #a53b3b; background: #fff4f4; color: #7d2424; }.dialog footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 26px; }.dialog footer button { min-height: 44px; padding: 0 18px; cursor: pointer; }.dialog footer button:disabled { opacity: .42; cursor: not-allowed; }.cancel-button { border: 1px solid #aaa; background: #fff; }.primary-button { border: 1px solid #111; background: #111; color: #fff; }.confirm-delete { border: 1px solid #a53b3b; background: #a53b3b; color: #fff; }
@keyframes pulse { to { opacity: .25; transform: scale(.75); } }
@media (max-width: 600px) { .topbar { height: 64px; }.page-heading { align-items: stretch; flex-direction: column; margin-bottom: 32px; }.refresh-button { width: 100%; }.tabs button { flex: 1; padding: 0 8px; }.history-page main { width: min(100% - 28px, 1180px); padding-top: 40px; } }
@media (prefers-reduced-motion: reduce) { .loading-state span { animation: none; } }
</style>
