import { createI18n } from 'vue-i18n'
import en from '../../../locales/en.json'

// English is the only locale. The glob import and the runtime locale list are
// gone with the language switcher, so there is nothing left to select between
// and no stored preference to honour; index.html evicts the old one.
const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en }
})

export default i18n
