import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const messages = {}
const availableLocales = []
const enabledLocales = new Set(['en'])

for (const path in localeFiles) {
  const key = path.match(/\/([^/]+)\.json$/)[1]
  if (languages[key] && enabledLocales.has(key)) {
    messages[key] = localeFiles[path].default
    availableLocales.push({ key, label: languages[key].label })
  }
}

const rawSavedLocale = localStorage.getItem('locale')
const supportedLocaleKeys = Object.keys(messages)
const savedLocale = rawSavedLocale && rawSavedLocale !== 'zh' && supportedLocaleKeys.includes(rawSavedLocale)
  ? rawSavedLocale
  : (supportedLocaleKeys.includes('en') ? 'en' : availableLocales[0]?.key || 'en')

if (rawSavedLocale !== savedLocale) {
  localStorage.setItem('locale', savedLocale)
}

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'en',
  messages
})

export { availableLocales }
export default i18n
