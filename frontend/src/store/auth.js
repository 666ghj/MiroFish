import { reactive } from 'vue'

const AUTH_KEY = 'mirofish_token'

const state = reactive({
  token: localStorage.getItem(AUTH_KEY) || null,
  isAuthenticated: !!localStorage.getItem(AUTH_KEY)
})

export function setToken(token) {
  state.token = token
  state.isAuthenticated = true
  localStorage.setItem(AUTH_KEY, token)
}

export function clearToken() {
  state.token = null
  state.isAuthenticated = false
  localStorage.removeItem(AUTH_KEY)
}

export function getToken() {
  return state.token
}

export default state
