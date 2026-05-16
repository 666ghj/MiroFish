<template>
  <div class="login-container">
    <nav class="navbar">
      <div class="nav-brand">MIROFISH</div>
    </nav>
    <main class="login-main">
      <div class="login-card">
        <div class="card-header">
          <span class="tag">AUTH</span>
          <h1 class="title">{{ $t('login.title') }}</h1>
          <p v-if="activated" class="success-msg">{{ $t('login.accountActivated') }}</p>
          <p v-else class="subtitle">{{ $t('login.subtitle') }}</p>
        </div>
        <form class="login-form" @submit.prevent="handleLogin">
          <div class="field">
            <label class="field-label" for="login-email">{{ $t('login.email') }}</label>
            <input id="login-email" v-model="form.email" type="email" class="field-input"
                   autocomplete="email" :disabled="loading" :placeholder="$t('login.emailPlaceholder')" />
          </div>
          <div class="field">
            <label class="field-label" for="login-password">{{ $t('login.password') }}</label>
            <input id="login-password" v-model="form.password" type="password" class="field-input"
                   autocomplete="current-password" :disabled="loading" :placeholder="$t('login.passwordPlaceholder')" />
          </div>
          <div v-if="error" class="error-msg" role="alert">{{ error }}</div>
          <button type="submit" class="submit-btn" :disabled="loading || !canSubmit">
            <span v-if="loading">{{ $t('login.loading') }}</span>
            <span v-else>{{ $t('login.submit') }} <span class="btn-arrow">→</span></span>
          </button>
          <router-link to="/forgot-password" class="forgot-link">{{ $t('login.forgotPassword') }}</router-link>
        </form>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import service from '../api/index'
import { setAuth } from '../store/auth'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()

const form = ref({ email: '', password: '' })
const loading = ref(false)
const error = ref('')
const activated = computed(() => route.query.activated === '1')
const canSubmit = computed(() => form.value.email.trim() !== '' && form.value.password !== '')

async function handleLogin() {
  if (!canSubmit.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const res = await service.post('/api/auth/login', {
      email: form.value.email,
      password: form.value.password
    })
    setAuth(res.token, res.user)
    router.push(route.query.redirect || '/')
  } catch {
    error.value = t('login.invalidCredentials')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container { min-height: 100vh; background: #fff; font-family: 'Space Grotesk', system-ui, sans-serif; color: #000; display: flex; flex-direction: column; }
.navbar { height: 60px; background: #000; color: #fff; display: flex; align-items: center; padding: 0 40px; }
.nav-brand { font-family: 'JetBrains Mono', monospace; font-weight: 800; letter-spacing: 1px; font-size: 1.2rem; }
.login-main { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px 20px; }
.login-card { width: 100%; max-width: 400px; border: 1px solid #e5e5e5; padding: 48px 40px; }
.card-header { margin-bottom: 32px; }
.tag { display: inline-block; background: #ff4500; color: #fff; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; letter-spacing: 1px; margin-bottom: 16px; }
.title { font-size: 1.8rem; font-weight: 500; margin-bottom: 8px; }
.subtitle { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #666; }
.login-form { display: flex; flex-direction: column; gap: 20px; }
.field { display: flex; flex-direction: column; gap: 8px; }
.field-label { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.field-input { border: 1px solid #e5e5e5; background: #fafafa; padding: 12px 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; outline: none; transition: border-color 0.15s; width: 100%; box-sizing: border-box; }
.field-input:focus { border-color: #000; background: #fff; }
.error-msg { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #ff4500; border-left: 3px solid #ff4500; padding-left: 12px; }
.success-msg { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #22c55e; border-left: 3px solid #22c55e; padding-left: 12px; }
.submit-btn { background: #000; color: #fff; border: none; padding: 14px 24px; font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.95rem; cursor: pointer; transition: background 0.15s; width: 100%; }
.submit-btn:hover:not(:disabled) { background: #ff4500; }
.submit-btn:disabled { background: #e5e5e5; color: #999; cursor: not-allowed; }
.btn-arrow { margin-left: 8px; }
.forgot-link { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #666; text-align: center; text-decoration: none; }
.forgot-link:hover { color: #ff4500; }
</style>
