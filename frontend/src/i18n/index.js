import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'
import { resolveLocale } from './locale'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const messages = {}
const availableLocales = []

for (const path in localeFiles) {
  const key = path.match(/\/([^/]+)\.json$/)[1]
  if (languages[key]) {
    messages[key] = localeFiles[path].default
    availableLocales.push({ key, label: languages[key].label })
  }
}

const savedLocale = resolveLocale(localStorage.getItem('locale'), Object.keys(messages)) || 'zh'

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'zh',
  messages
})

// Keep the browser tab, page description and language in sync with the UI.
watch(i18n.global.locale, (locale) => {
  document.documentElement.lang = locale
  document.title = i18n.global.t('meta.title')
  document.querySelector('meta[name="description"]')?.setAttribute('content', i18n.global.t('meta.description'))
}, { immediate: true })

export { availableLocales }
export default i18n
