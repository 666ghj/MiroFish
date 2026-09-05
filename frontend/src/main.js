import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'

const app = createApp(App)

app.use(router)
app.use(i18n)

app.mount('#app')

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')
const heartbeatUrl = `${apiBase}/api/heartbeat`
const heartbeat = () => {
  fetch(heartbeatUrl, { method: 'POST', keepalive: true }).catch(() => {})
}
heartbeat()
setInterval(heartbeat, 10000)
