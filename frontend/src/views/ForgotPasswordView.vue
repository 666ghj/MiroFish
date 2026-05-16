<template>
  <div class="auth-container">
    <nav class="navbar"><div class="nav-brand">MIROFISH</div></nav>
    <main class="auth-main">
      <div class="auth-card">
        <div class="card-header">
          <span class="tag">AUTH</span>
          <h1 class="title">{{ $t('forgotPassword.title') }}</h1>
          <p class="subtitle">{{ $t('forgotPassword.subtitle') }}</p>
        </div>
        <div v-if="sent" class="success-msg">{{ $t('forgotPassword.sent') }}</div>
        <form v-else class="auth-form" @submit.prevent="handleSubmit">
          <div class="field">
            <label class="field-label">{{ $t('login.email') }}</label>
            <input v-model="email" type="email" class="field-input"
                   :disabled="loading" :placeholder="$t('login.emailPlaceholder')" />
          </div>
          <div v-if="error" class="error-msg">{{ error }}</div>
          <button type="submit" class="submit-btn" :disabled="loading || !email.trim()">
            <span v-if="loading">{{ $t('common.loading') }}</span>
            <span v-else>{{ $t('forgotPassword.submit') }} →</span>
          </button>
          <router-link to="/login" class="back-link">← {{ $t('common.back') }}</router-link>
        </form>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import service from '../api/index'

const { t } = useI18n()
const email = ref('')
const loading = ref(false)
const sent = ref(false)
const error = ref('')

async function handleSubmit() {
  loading.value = true; error.value = ''
  try {
    await service.post('/api/auth/forgot-password', { email: email.value })
    sent.value = true
  } catch {
    error.value = t('common.unknownError')
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
.back-link { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #666; text-decoration: none; text-align: center; }
.back-link:hover { color: #ff4500; }
</style>
