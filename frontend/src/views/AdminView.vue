<template>
  <div class="admin-container">
    <nav class="navbar">
      <div class="nav-brand">MIROFISH</div>
      <div class="nav-right">
        <router-link to="/" class="back-link">← {{ $t('common.back') }}</router-link>
        <LanguageSwitcher />
      </div>
    </nav>

    <div class="content">
      <div class="tabs">
        <router-link to="/admin/users"      class="tab" :class="{ active: tab === 'users' }">
          {{ $t('admin.users') }}
        </router-link>
        <router-link to="/admin/config"     class="tab" :class="{ active: tab === 'config' }">
          {{ $t('admin.config') }}
        </router-link>
        <router-link to="/admin/executions" class="tab" :class="{ active: tab === 'executions' }">
          {{ $t('admin.executions') }}
        </router-link>
      </div>

      <!-- Tab: Usuaris -->
      <div v-if="tab === 'users'" class="tab-content">
        <div class="tab-header">
          <h2 class="section-title">{{ $t('admin.users') }}</h2>
          <button class="new-btn" @click="showInviteForm = !showInviteForm">
            + {{ $t('admin.inviteUser') }}
          </button>
        </div>

        <div v-if="showInviteForm" class="invite-form">
          <div class="form-row">
            <input v-model="invite.name" class="field-input" :placeholder="$t('admin.name')" />
            <input v-model="invite.email" type="email" class="field-input" :placeholder="$t('admin.email')" />
            <select v-model="invite.role" class="field-select">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <button class="start-btn" @click="submitInvite" :disabled="!invite.email || !invite.name">
              {{ $t('admin.send') }} →
            </button>
          </div>
          <div v-if="inviteSuccess" class="success-msg">{{ $t('admin.inviteSent') }}</div>
          <div v-if="inviteError" class="error-msg">{{ inviteError }}</div>
        </div>

        <table class="data-table" v-if="users.length">
          <thead>
            <tr>
              <th>{{ $t('admin.email') }}</th>
              <th>{{ $t('admin.name') }}</th>
              <th>{{ $t('admin.role') }}</th>
              <th>{{ $t('admin.status') }}</th>
              <th>{{ $t('admin.created') }}</th>
              <th>{{ $t('admin.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td class="mono">{{ user.email }}</td>
              <td>{{ user.name }}</td>
              <td>
                <select class="role-select" :value="user.role" @change="changeRole(user, $event.target.value)">
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td><span class="status-badge" :class="user.status">{{ user.status }}</span></td>
              <td class="mono">{{ formatDate(user.created_at) }}</td>
              <td class="actions-cell">
                <button v-if="user.status === 'pending'" class="action-btn" @click="reinvite(user)" :title="$t('admin.reinvite')">✉</button>
                <button v-if="user.status !== 'disabled'" class="action-btn danger" @click="disableUser(user)" :title="$t('admin.disable')">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty-state">{{ $t('admin.noUsers') }}</div>
      </div>

      <!-- Tab: Configuració -->
      <div v-if="tab === 'config'" class="tab-content">
        <div class="tab-header">
          <h2 class="section-title">{{ $t('admin.config') }}</h2>
          <button class="start-btn" @click="saveConfig">{{ $t('common.save') }}</button>
        </div>
        <div v-if="configEntries.length" class="config-form">
          <div v-for="entry in configEntries" :key="entry.key" class="config-row">
            <label class="config-label">
              <span class="config-key mono">{{ entry.key }}</span>
              <span class="config-desc">{{ entry.label }}</span>
            </label>
            <input
              v-model="configValues[entry.key]"
              :type="entry.is_secret ? 'password' : 'text'"
              class="field-input"
              :placeholder="entry.is_secret ? '●●●●' : entry.value"
            />
          </div>
        </div>
        <div v-else class="empty-state">{{ $t('admin.noConfig') }}</div>
        <div v-if="configSaved" class="success-msg">{{ $t('admin.configSaved') }}</div>
      </div>

      <!-- Tab: Historial -->
      <div v-if="tab === 'executions'" class="tab-content">
        <div class="tab-header">
          <h2 class="section-title">{{ $t('admin.executions') }}</h2>
        </div>
        <table class="data-table" v-if="executions.length">
          <thead>
            <tr>
              <th>{{ $t('admin.user') }}</th>
              <th>{{ $t('admin.project') }}</th>
              <th>{{ $t('admin.platform') }}</th>
              <th>{{ $t('admin.status') }}</th>
              <th>{{ $t('admin.rounds') }}</th>
              <th>{{ $t('admin.created') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ex in executions" :key="ex.simulation_id">
              <td class="mono">{{ ex.user_email || '—' }}</td>
              <td>{{ ex.project_name }}</td>
              <td class="mono">{{ ex.platform }}</td>
              <td><span class="status-badge" :class="ex.status">{{ ex.status }}</span></td>
              <td class="mono">{{ ex.rounds_completed }}/{{ ex.rounds_total || '?' }}</td>
              <td class="mono">{{ formatDate(ex.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty-state">{{ $t('admin.noExecutions') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import service from '../api/index'

const props = defineProps({ tab: { type: String, default: 'users' } })
const { t } = useI18n()

const users = ref([])
const showInviteForm = ref(false)
const invite = ref({ name: '', email: '', role: 'user' })
const inviteSuccess = ref(false)
const inviteError = ref('')

const configEntries = ref([])
const configValues = ref({})
const configSaved = ref(false)

const executions = ref([])

onMounted(loadTab)
watch(() => props.tab, loadTab)

async function loadTab() {
  if (props.tab === 'users') await loadUsers()
  if (props.tab === 'config') await loadConfig()
  if (props.tab === 'executions') await loadExecutions()
}

async function loadUsers() {
  try {
    const res = await service.get('/api/users/')
    users.value = res.data || []
  } catch { /* silent */ }
}

async function loadConfig() {
  try {
    const res = await service.get('/api/admin/config')
    configEntries.value = res.data || []
    configValues.value = Object.fromEntries(
      configEntries.value.filter(e => !e.is_secret).map(e => [e.key, e.value])
    )
  } catch { /* silent */ }
}

async function loadExecutions() {
  try {
    const res = await service.get('/api/admin/executions')
    executions.value = res.data || []
  } catch { /* silent */ }
}

async function submitInvite() {
  inviteSuccess.value = false; inviteError.value = ''
  try {
    await service.post('/api/users/', invite.value)
    inviteSuccess.value = true
    invite.value = { name: '', email: '', role: 'user' }
    await loadUsers()
  } catch (e) {
    inviteError.value = e.response?.data?.error || t('common.unknownError')
  }
}

async function changeRole(user, newRole) {
  await service.patch(`/api/users/${user.id}`, { role: newRole })
  await loadUsers()
}

async function disableUser(user) {
  await service.delete(`/api/users/${user.id}`)
  await loadUsers()
}

async function reinvite(user) {
  await service.post(`/api/users/${user.id}/reinvite`)
}

async function saveConfig() {
  const payload = {}
  for (const [k, v] of Object.entries(configValues.value)) {
    if (v !== '' && !configEntries.value.find(e => e.key === k)?.is_secret) {
      payload[k] = v
    }
  }
  await service.patch('/api/admin/config', payload)
  configSaved.value = true
  setTimeout(() => { configSaved.value = false }, 2000)
}

function formatDate(iso) {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}
</script>

<style scoped>
.admin-container { min-height: 100vh; background: #fff; font-family: 'Space Grotesk', system-ui, sans-serif; color: #000; }
.navbar { height: 60px; background: #000; color: #fff; display: flex; justify-content: space-between; align-items: center; padding: 0 40px; }
.nav-brand { font-family: 'JetBrains Mono', monospace; font-weight: 800; letter-spacing: 1px; font-size: 1.2rem; }
.nav-right { display: flex; align-items: center; gap: 16px; }
.back-link { color: #aaa; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; text-decoration: none; }
.back-link:hover { color: #fff; }
.content { max-width: 1100px; margin: 0 auto; padding: 40px; }
.tabs { display: flex; gap: 0; border-bottom: 1px solid #e5e5e5; margin-bottom: 32px; }
.tab { padding: 12px 24px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; text-decoration: none; color: #666; border-bottom: 2px solid transparent; transition: all 0.15s; }
.tab:hover { color: #000; }
.tab.active { color: #000; border-bottom-color: #ff4500; }
.tab-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.section-title { font-size: 1.2rem; font-weight: 500; margin: 0; }
.new-btn, .start-btn { background: #000; color: #fff; border: none; padding: 8px 18px; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: background 0.15s; }
.new-btn:hover, .start-btn:hover:not(:disabled) { background: #ff4500; }
.start-btn:disabled { background: #e5e5e5; color: #999; cursor: not-allowed; }
.invite-form { border: 1px solid #e5e5e5; padding: 20px; margin-bottom: 24px; background: #fafafa; }
.form-row { display: flex; gap: 12px; flex-wrap: wrap; }
.field-input { border: 1px solid #e5e5e5; background: #fff; padding: 8px 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; outline: none; flex: 1; min-width: 160px; }
.field-input:focus { border-color: #000; }
.field-select { border: 1px solid #e5e5e5; background: #fff; padding: 8px 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; cursor: pointer; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.data-table th { font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #666; padding: 10px 12px; text-align: left; border-bottom: 1px solid #e5e5e5; }
.data-table td { padding: 12px; border-bottom: 1px solid #f0f0f0; }
.mono { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; }
.status-badge { display: inline-block; font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; }
.status-badge.active { background: #dcfce7; color: #166534; }
.status-badge.pending { background: #fef9c3; color: #854d0e; }
.status-badge.disabled { background: #f1f5f9; color: #64748b; }
.status-badge.completed { background: #dcfce7; color: #166534; }
.status-badge.failed { background: #fee2e2; color: #991b1b; }
.role-select { border: 1px solid #e5e5e5; background: #fff; padding: 4px 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; cursor: pointer; }
.actions-cell { display: flex; gap: 6px; }
.action-btn { background: none; border: 1px solid #e5e5e5; padding: 4px 8px; font-size: 0.85rem; cursor: pointer; }
.action-btn:hover { border-color: #000; }
.action-btn.danger:hover { border-color: #ef4444; color: #ef4444; }
.config-form { display: flex; flex-direction: column; gap: 16px; }
.config-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: center; padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
.config-label { display: flex; flex-direction: column; gap: 2px; }
.config-key { font-size: 0.8rem; color: #000; }
.config-desc { font-size: 0.8rem; color: #666; }
.empty-state { padding: 48px 0; text-align: center; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #999; }
.success-msg { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #22c55e; border-left: 3px solid #22c55e; padding-left: 10px; margin-top: 8px; }
.error-msg { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #ff4500; border-left: 3px solid #ff4500; padding-left: 10px; margin-top: 8px; }
</style>
