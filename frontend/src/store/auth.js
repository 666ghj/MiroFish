import { reactive, computed } from 'vue'

const AUTH_KEY = 'mirofish_token'
const USER_KEY = 'mirofish_user'

const state = reactive({
  token: localStorage.getItem(AUTH_KEY) || null,
  user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  get isAuthenticated() { return !!this.token }
})

export const isAdmin = computed(() => state.user?.role === 'admin')

export function setAuth(token, user) {
  state.token = token
  state.user = user
  localStorage.setItem(AUTH_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  state.token = null
  state.user = null
  localStorage.removeItem(AUTH_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getToken() {
  return state.token
}

// Compatibilitat enrere (LoginView usa setToken)
export function setToken(token) {
  setAuth(token, state.user)
}

export function clearToken() {
  clearAuth()
}

export default state
