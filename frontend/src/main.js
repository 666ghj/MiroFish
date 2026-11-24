import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { BRAND } from './brand'
import { reveal } from './motion'

const app = createApp(App)

app.use(router)
app.use(i18n)
app.config.globalProperties.$brand = BRAND
app.directive('reveal', reveal)
document.title = BRAND.name

app.mount('#app')
