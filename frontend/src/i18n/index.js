import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'

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

// Default to English for production, can be overridden by VITE_DEFAULT_LOCALE
const defaultLocale = import.meta.env.VITE_DEFAULT_LOCALE || 'en'
const savedLocale = localStorage.getItem('locale') || defaultLocale

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: defaultLocale,
  messages
})

export { availableLocales }
export default i18n
