import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { initTheme } from './theme'
import './styles/theme.css'

const app = createApp(App)

app.use(router)
app.use(i18n)

initTheme()

app.mount('#app')
