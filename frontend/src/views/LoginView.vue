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
          <p class="subtitle">{{ $t('login.subtitle') }}</p>
        </div>

        <form class="login-form" @submit.prevent="handleLogin">
          <div class="field">
            <label class="field-label" for="login-username">{{ $t('login.username') }}</label>
            <input
              id="login-username"
              v-model="form.username"
              type="text"
              class="field-input"
              autocomplete="username"
              :disabled="loading"
              :placeholder="$t('login.usernamePlaceholder')"
            />
          </div>

          <div class="field">
            <label class="field-label" for="login-password">{{ $t('login.password') }}</label>
            <input
              id="login-password"
              v-model="form.password"
              type="password"
              class="field-input"
              autocomplete="current-password"
              :disabled="loading"
              :placeholder="$t('login.passwordPlaceholder')"
            />
          </div>

          <div v-if="error" class="error-msg" role="alert">
            {{ error }}
          </div>

          <button
            type="submit"
            class="submit-btn"
            :disabled="loading || !canSubmit"
          >
            <span v-if="loading">{{ $t('login.loading') }}</span>
            <span v-else>{{ $t('login.submit') }} <span class="btn-arrow" aria-hidden="true">→</span></span>
          </button>
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
import { setToken } from '../store/auth'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()

const form = ref({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

const canSubmit = computed(
  () => form.value.username.trim() !== '' && form.value.password !== ''
)

async function handleLogin() {
  if (!canSubmit.value || loading.value) return
  loading.value = true
  error.value = ''

  try {
    const res = await service.post('/api/auth/login', {
      username: form.value.username,
      password: form.value.password
    })
    setToken(res.token)
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch {
    error.value = t('login.invalidCredentials')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  background: #ffffff;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000000;
  display: flex;
  flex-direction: column;
}

.navbar {
  height: 60px;
  background: #000000;
  color: #ffffff;
  display: flex;
  align-items: center;
  padding: 0 40px;
  flex-shrink: 0;
}

.nav-brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  letter-spacing: 1px;
  font-size: 1.2rem;
}

.login-main {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  border: 1px solid #e5e5e5;
  padding: 48px 40px;
}

.card-header {
  margin-bottom: 40px;
}

.tag {
  display: inline-block;
  background: #ff4500;
  color: #ffffff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  letter-spacing: 1px;
  margin-bottom: 16px;
}

.title {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 1.8rem;
  font-weight: 500;
  margin-bottom: 8px;
  color: #000000;
}

.subtitle {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  color: #666666;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 700;
  color: #000000;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.field-input {
  border: 1px solid #e5e5e5;
  background: #fafafa;
  padding: 12px 16px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  color: #000000;
  outline: none;
  transition: border-color 0.15s;
  width: 100%;
  box-sizing: border-box;
}

.field-input:focus {
  border-color: #000000;
  background: #ffffff;
}

.field-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-msg {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  color: #ff4500;
  border-left: 3px solid #ff4500;
  padding-left: 12px;
}

.submit-btn {
  background: #000000;
  color: #ffffff;
  border: none;
  padding: 14px 24px;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  font-size: 0.95rem;
  cursor: pointer;
  transition: background 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
}

.submit-btn:hover:not(:disabled) {
  background: #ff4500;
}

.submit-btn:disabled {
  background: #e5e5e5;
  color: #999999;
  cursor: not-allowed;
}

.btn-arrow {
  font-size: 1rem;
}
</style>
