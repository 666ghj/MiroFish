<template>
  <div class="home-container">
    <nav class="navbar">
      <div class="nav-brand">MIROFISH</div>
      <div class="nav-right">
        <router-link v-if="isAdmin" to="/admin/users" class="admin-link">
          {{ $t('home.admin') }}
        </router-link>
        <LanguageSwitcher />
        <span class="user-email">{{ authState.user?.email }}</span>
        <button class="logout-btn" @click="handleLogout" :title="$t('home.logout')">→</button>
      </div>
    </nav>

    <div class="content">
      <div class="header-row">
        <h2 class="section-title">{{ $t('home.myProjects') }}</h2>
        <button class="new-btn" @click="showNewModal = true">+ {{ $t('home.newProject') }}</button>
      </div>

      <div class="project-list" v-if="projects.length > 0">
        <div
          v-for="project in projects"
          :key="project.id"
          class="project-row"
          @click="openProject(project)"
        >
          <span class="status-dot" :class="statusClass(project.status)">■</span>
          <div class="project-info">
            <span class="project-name">{{ project.name }}</span>
            <span class="project-meta">{{ formatStatus(project.status) }} · {{ formatDate(project.created_at) }}</span>
          </div>
          <div class="project-actions" @click.stop>
            <button class="action-btn" @click="startRename(project)" :title="$t('home.rename')">✎</button>
            <button class="action-btn danger" @click="confirmDelete(project)" :title="$t('home.delete')">✕</button>
            <button class="arrow-btn" @click="openProject(project)">→</button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <span>{{ $t('home.noProjects') }}</span>
      </div>
    </div>

    <!-- Modal: Nou Projecte -->
    <div v-if="showNewModal" class="modal-overlay" @click.self="showNewModal = false">
      <div class="modal">
        <div class="modal-header">
          <span class="tag">NEW</span>
          <h3 class="modal-title">{{ $t('home.newProject') }}</h3>
        </div>

        <div class="console-section">
          <div class="console-header">
            <span class="console-label">{{ $t('home.realitySeed') }}</span>
            <span class="console-meta">{{ $t('home.supportedFormats') }}</span>
          </div>
          <div class="upload-zone"
               :class="{ 'drag-over': isDragOver, 'has-files': files.length > 0 }"
               @dragover.prevent="isDragOver = true"
               @dragleave.prevent="isDragOver = false"
               @drop.prevent="handleDrop"
               @click="fileInput?.click()">
            <input ref="fileInput" type="file" multiple accept=".pdf,.md,.txt"
                   @change="handleFileSelect" style="display:none" />
            <div v-if="files.length === 0" class="upload-placeholder">
              <div class="upload-icon">↑</div>
              <div class="upload-title">{{ $t('home.dragToUpload') }}</div>
              <div class="upload-hint">{{ $t('home.orBrowse') }}</div>
            </div>
            <div v-else class="file-list">
              <div v-for="(f, i) in files" :key="i" class="file-item">
                <span class="file-icon">📄</span>
                <span class="file-name">{{ f.name }}</span>
                <button @click.stop="files.splice(i, 1)" class="remove-btn">×</button>
              </div>
            </div>
          </div>
        </div>

        <div class="console-section">
          <div class="console-header">
            <span class="console-label">{{ $t('home.simulationPrompt') }}</span>
          </div>
          <div class="input-wrapper">
            <textarea v-model="requirement" class="code-input"
                      :placeholder="$t('home.promptPlaceholder')" rows="5"></textarea>
          </div>
        </div>

        <div class="modal-footer">
          <button class="cancel-btn" @click="showNewModal = false">{{ $t('common.cancel') }}</button>
          <button class="start-btn" @click="startProject" :disabled="!canStart">
            {{ $t('home.startEngine') }} →
          </button>
        </div>
      </div>
    </div>

    <!-- Modal: Rename -->
    <div v-if="renameProject" class="modal-overlay" @click.self="renameProject = null">
      <div class="modal modal-sm">
        <h3 class="modal-title">{{ $t('home.rename') }}</h3>
        <input v-model="renameValue" class="field-input" @keyup.enter="submitRename" />
        <div class="modal-footer">
          <button class="cancel-btn" @click="renameProject = null">{{ $t('common.cancel') }}</button>
          <button class="start-btn" @click="submitRename" :disabled="!renameValue.trim()">{{ $t('common.save') }}</button>
        </div>
      </div>
    </div>

    <!-- Modal: Confirmar Delete -->
    <div v-if="deleteTarget" class="modal-overlay" @click.self="deleteTarget = null">
      <div class="modal modal-sm">
        <h3 class="modal-title">{{ $t('home.confirmDelete') }}</h3>
        <p class="modal-desc">{{ deleteTarget.name }}</p>
        <div class="modal-footer">
          <button class="cancel-btn" @click="deleteTarget = null">{{ $t('common.cancel') }}</button>
          <button class="danger-btn" @click="submitDelete">{{ $t('home.delete') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import authState, { isAdmin, clearAuth } from '../store/auth'
import service from '../api/index'
import { setPendingUpload } from '../store/pendingUpload'

const router = useRouter()
const { t } = useI18n()

const projects = ref([])
const showNewModal = ref(false)
const files = ref([])
const requirement = ref('')
const isDragOver = ref(false)
const fileInput = ref(null)
const renameProject = ref(null)
const renameValue = ref('')
const deleteTarget = ref(null)

const canStart = computed(() => files.value.length > 0 && requirement.value.trim())

onMounted(loadProjects)

async function loadProjects() {
  try {
    const res = await service.get('/api/graph/project/list')
    projects.value = res.data || []
  } catch { /* silent */ }
}

function openProject(project) {
  router.push({ name: 'Process', params: { projectId: project.id } })
}

function handleFileSelect(e) {
  const valid = Array.from(e.target.files).filter(f =>
    ['pdf', 'md', 'txt'].includes(f.name.split('.').pop().toLowerCase())
  )
  files.value.push(...valid)
}

function handleDrop(e) {
  isDragOver.value = false
  const valid = Array.from(e.dataTransfer.files).filter(f =>
    ['pdf', 'md', 'txt'].includes(f.name.split('.').pop().toLowerCase())
  )
  files.value.push(...valid)
}

async function startProject() {
  if (!canStart.value) return
  setPendingUpload(files.value, requirement.value, false, null)
  showNewModal.value = false
  files.value = []
  requirement.value = ''
  router.push({ name: 'Process', params: { projectId: 'new' } })
}

function startRename(project) {
  renameProject.value = project
  renameValue.value = project.name
}

async function submitRename() {
  if (!renameValue.value.trim() || !renameProject.value) return
  try {
    await service.patch(`/api/graph/project/${renameProject.value.id}`, { name: renameValue.value.trim() })
    await loadProjects()
  } finally {
    renameProject.value = null
  }
}

function confirmDelete(project) {
  deleteTarget.value = project
}

async function submitDelete() {
  if (!deleteTarget.value) return
  try {
    await service.delete(`/api/graph/project/${deleteTarget.value.id}`)
    await loadProjects()
  } finally {
    deleteTarget.value = null
  }
}

function handleLogout() {
  service.post('/api/auth/logout').catch(() => {})
  clearAuth()
  router.push('/login')
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString()
}

function formatStatus(status) {
  const map = {
    created: t('common.pending'),
    ontology_generated: 'Ontologia',
    graph_building: t('common.processing'),
    graph_completed: t('common.ready'),
    failed: t('common.failed'),
  }
  return map[status] || status
}

function statusClass(status) {
  if (status === 'graph_completed') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'graph_building') return 'orange'
  return 'gray'
}
</script>

<style scoped>
.home-container { min-height: 100vh; background: #fff; font-family: 'Space Grotesk', system-ui, sans-serif; color: #000; }
.navbar { height: 60px; background: #000; color: #fff; display: flex; justify-content: space-between; align-items: center; padding: 0 40px; }
.nav-brand { font-family: 'JetBrains Mono', monospace; font-weight: 800; letter-spacing: 1px; font-size: 1.2rem; }
.nav-right { display: flex; align-items: center; gap: 16px; }
.admin-link { color: #ff4500; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; text-decoration: none; font-weight: 700; }
.admin-link:hover { opacity: 0.8; }
.user-email { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #aaa; }
.logout-btn { background: none; border: none; color: #fff; font-size: 1.1rem; cursor: pointer; padding: 4px 8px; transition: color 0.15s; }
.logout-btn:hover { color: #ff4500; }
.content { max-width: 900px; margin: 0 auto; padding: 48px 40px; }
.header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; }
.section-title { font-size: 1.4rem; font-weight: 500; margin: 0; }
.new-btn { background: #000; color: #fff; border: none; padding: 10px 20px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; cursor: pointer; transition: background 0.15s; }
.new-btn:hover { background: #ff4500; }
.project-list { border-top: 1px solid #e5e5e5; }
.project-row { display: flex; align-items: center; gap: 16px; padding: 16px 0; border-bottom: 1px solid #f0f0f0; cursor: pointer; transition: background 0.1s; }
.project-row:hover { background: #fafafa; }
.status-dot { font-size: 0.7rem; }
.status-dot.green { color: #22c55e; }
.status-dot.red { color: #ef4444; }
.status-dot.orange { color: #ff4500; }
.status-dot.gray { color: #aaa; }
.project-info { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.project-name { font-weight: 500; font-size: 1rem; }
.project-meta { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: #999; }
.project-actions { display: flex; align-items: center; gap: 8px; opacity: 0; transition: opacity 0.15s; }
.project-row:hover .project-actions { opacity: 1; }
.action-btn { background: none; border: 1px solid #e5e5e5; padding: 4px 8px; font-size: 0.85rem; cursor: pointer; transition: all 0.15s; }
.action-btn:hover { border-color: #000; }
.action-btn.danger:hover { border-color: #ef4444; color: #ef4444; }
.arrow-btn { background: #000; color: #fff; border: none; padding: 6px 12px; font-size: 0.9rem; cursor: pointer; }
.empty-state { padding: 48px 0; text-align: center; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; color: #999; border-top: 1px solid #e5e5e5; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; width: 100%; max-width: 560px; max-height: 90vh; overflow-y: auto; padding: 32px; }
.modal-sm { max-width: 400px; }
.modal-header { margin-bottom: 24px; }
.modal-title { font-size: 1.3rem; font-weight: 500; margin: 8px 0 0; }
.modal-desc { font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; color: #666; margin: 8px 0 0; }
.modal-footer { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
.cancel-btn { background: none; border: 1px solid #e5e5e5; padding: 10px 20px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; cursor: pointer; }
.cancel-btn:hover { border-color: #000; }
.start-btn { background: #000; color: #fff; border: none; padding: 10px 20px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; cursor: pointer; transition: background 0.15s; }
.start-btn:hover:not(:disabled) { background: #ff4500; }
.start-btn:disabled { background: #e5e5e5; color: #999; cursor: not-allowed; }
.danger-btn { background: #ef4444; color: #fff; border: none; padding: 10px 20px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; cursor: pointer; }
.danger-btn:hover { background: #dc2626; }
.tag { display: inline-block; background: #ff4500; color: #fff; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; letter-spacing: 1px; margin-bottom: 12px; }
.field-input { border: 1px solid #e5e5e5; background: #fafafa; padding: 12px 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; outline: none; width: 100%; box-sizing: border-box; margin-top: 8px; }
.console-section { padding: 0 0 16px 0; }
.console-header { display: flex; justify-content: space-between; margin-bottom: 10px; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: #666; }
.upload-zone { border: 1px dashed #ccc; height: 150px; overflow-y: auto; display: flex; align-items: center; justify-content: center; cursor: pointer; background: #fafafa; transition: all 0.2s; }
.upload-zone.has-files { align-items: flex-start; }
.upload-zone:hover, .upload-zone.drag-over { background: #f0f0f0; border-color: #999; }
.upload-placeholder { text-align: center; }
.upload-icon { width: 36px; height: 36px; border: 1px solid #ddd; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px; color: #999; }
.upload-title { font-weight: 500; font-size: 0.85rem; }
.upload-hint { font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: #999; }
.file-list { width: 100%; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.file-item { display: flex; align-items: center; background: #fff; padding: 6px 10px; border: 1px solid #eee; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; }
.file-name { flex: 1; margin: 0 8px; }
.remove-btn { background: none; border: none; cursor: pointer; font-size: 1rem; color: #999; }
.input-wrapper { border: 1px solid #ddd; background: #fafafa; }
.code-input { width: 100%; border: none; background: transparent; padding: 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; line-height: 1.6; resize: vertical; outline: none; box-sizing: border-box; }
</style>
