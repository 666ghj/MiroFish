import { createApp } from 'vue'

// Order matters. tokens.css defines the custom properties that base.css and
// every component style read, and both must be in the cascade before the first
// single-file-component style lands.
import './styles/tokens.css'
import './styles/base.css'

import App from './App.vue'
import router from './router'
import i18n from './i18n'

const app = createApp(App)

app.use(router)
app.use(i18n)

app.mount('#app')
