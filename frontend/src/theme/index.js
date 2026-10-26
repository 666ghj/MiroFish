import { computed, ref, watch } from 'vue'

// The page theme: 'light', 'dark', or 'system' (follow the operating system, the default).
// The choice is remembered in localStorage and applied as data-theme="light|dark" on <html>;
// src/styles/theme.css holds the colors for each. index.html applies the saved theme before the
// first paint so the page does not flash light on reload.

const STORAGE_KEY = 'theme'
export const THEME_CHOICES = ['light', 'dark', 'system']

const readChoice = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return THEME_CHOICES.includes(saved) ? saved : 'system'
  } catch (e) {
    return 'system'
  }
}

const systemQuery = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-color-scheme: dark)')
  : null

const choice = ref(readChoice())
const systemDark = ref(systemQuery ? systemQuery.matches : false)

const resolvedTheme = computed(() => {
  if (choice.value === 'system') return systemDark.value ? 'dark' : 'light'
  return choice.value
})

const applyTheme = (theme) => {
  document.documentElement.dataset.theme = theme
}

export const setTheme = (next) => {
  if (!THEME_CHOICES.includes(next)) return
  choice.value = next
  try {
    if (next === 'system') {
      localStorage.removeItem(STORAGE_KEY)
    } else {
      localStorage.setItem(STORAGE_KEY, next)
    }
  } catch (e) {
    // private mode or blocked storage: the choice still applies until the page is closed
  }
}

export const initTheme = () => {
  if (systemQuery) {
    const onChange = (event) => { systemDark.value = event.matches }
    if (systemQuery.addEventListener) {
      systemQuery.addEventListener('change', onChange)
    } else if (systemQuery.addListener) {
      systemQuery.addListener(onChange)
    }
  }
  watch(resolvedTheme, applyTheme, { immediate: true })
}

export const useTheme = () => ({ choice, resolvedTheme, setTheme })
