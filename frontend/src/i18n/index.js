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

// A language link also updates an existing browser preference.
const pageUrl = new URL(window.location.href)
const requestedLocale = pageUrl.searchParams.get('lang')
if (Object.hasOwn(messages, requestedLocale)) {
  localStorage.setItem('locale', requestedLocale)
  pageUrl.searchParams.delete('lang')
  window.history.replaceState(window.history.state, '', pageUrl)
}
const savedLocale = localStorage.getItem('locale')

const i18n = createI18n({
  legacy: false,
  locale: Object.hasOwn(messages, savedLocale) ? savedLocale : 'en',
  fallbackLocale: 'en',
  messages
})

export { availableLocales }
export default i18n
