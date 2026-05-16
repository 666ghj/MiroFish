<template>
  <div class="auth-container">
    <nav class="navbar"><div class="nav-brand">MIROFISH</div></nav>
    <main class="auth-main">
      <div class="auth-card">
        <div class="card-header">
          <span class="tag">AUTH</span>
          <h1 class="title">{{ $t('setPassword.title') }}</h1>
          <p v-if="inviteData" class="subtitle">{{ inviteData.email }}</p>
        </div>
        <div v-if="tokenError" class="error-msg">{{ $t('setPassword.invalidToken') }}</div>
        <div v-else-if="done" class="success-msg">{{ $t('setPassword.done') }}</div>
        <form v-else-if="inviteData" class="auth-form" @submit.prevent="handleSubmit">
          <div class="field">
            <label class="field-label">{{ $t('setPassword.newPassword') }}</label>
            <input v-model="password" type="password" class="field-input" :disabled="loading" minlength="8" />
          </div>
          <div class="field">
            <label class="field-label">{{ $t('resetPassword.confirmPassword') }}</label>
            <input v-model="confirm" type="password" class="field-input" :disabled="loading" />
          </div>
          <div v-if="formError" class="error-msg">{{ formError }}</div>
          <button type="submit" class="submit-btn" :disabled="loading || !canSubmit">
            <span v-if="loading">{{ $t('common.loading') }}</span>
            <span v-else>{{ $t('setPassword.submit') }} →</span>
          </button>
        </form>
        <router-link v-if="done" to="/login?activated=1" class="back-link">{{ $t('resetPassword.goToLogin') }} →</router-link>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import service from '../api/index'

const props = defineProps({ token: String })
const { t } = useI18n()
const router = useRouter()

const inviteData = ref(null)
const password = ref('')
const confirm = ref('')
const loading = ref(false)
const tokenError = ref(false)
const formError = ref('')
const done = ref(false)

const canSubmit = computed(() => password.value.length >= 8 && password.value === confirm.value)

onMounted(async () => {
  try {
    const res = await service.get(`/api/auth/invitation/${props.token}`)
    inviteData.value = res.data
  } catch {
    tokenError.value = true
  }
})

async function handleSubmit() {
  if (!canSubmit.value) { formError.value = t('resetPassword.passwordMismatch'); return }
  loading.value = true; formError.value = ''
  try {
    await service.post('/api/auth/set-password', { token: props.token, password: password.value })
    done.value = true
    setTimeout(() => router.push('/login?activated=1'), 2000)
  } catch {
    formError.value = t('common.unknownError')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-container { min-height: 100vh; background: #fff; font-family: 'Space Grotesk', system-ui, sans-serif; color: #000; display: flex; flex-direction: column; }
.navbar { height: 60px; background: #000; color: #fff; display: flex; align-items: center; padding: 0 40px; }
.nav-brand { font-family: 'JetBrains Mono', monospace; font-weight: 800; letter-spacing: 1px; font-size: 1.2rem; }
.auth-main { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px 20px; }
.auth-card { width: 100%; max-width: 400px; border: 1px solid #e5e5e5; padding: 48px 40px; }
.card-header { margin-bottom: 32px; }
.tag { display: inline-block; background: #ff4500; color: #fff; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; letter-spacing: 1px; margin-bottom: 16px; }
.title { font-size: 1.8rem; font-weight: 500; margin-bottom: 8px; }
.subtitle { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #666; }
.auth-form { display: flex; flex-direction: column; gap: 20px; }
.field { display: flex; flex-direction: column; gap: 8px; }
.field-label { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
.field-input { border: 1px solid #e5e5e5; background: #fafafa; padding: 12px 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; outline: none; width: 100%; box-sizing: border-box; }
.field-input:focus { border-color: #000; background: #fff; }
.error-msg { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #ff4500; border-left: 3px solid #ff4500; padding-left: 12px; }
.success-msg { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #22c55e; border-left: 3px solid #22c55e; padding-left: 12px; }
.submit-btn { background: #000; color: #fff; border: none; padding: 14px 24px; font-family: 'JetBrains Mono', monospace; font-weight: 700; cursor: pointer; transition: background 0.15s; width: 100%; }
.submit-btn:hover:not(:disabled) { background: #ff4500; }
.submit-btn:disabled { background: #e5e5e5; color: #999; cursor: not-allowed; }
.back-link { display: block; margin-top: 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #000; text-decoration: none; text-align: center; }
.back-link:hover { color: #ff4500; }
</style>
