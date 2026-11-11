<template>
  <button class="theme-toggle" type="button" :title="label" :aria-label="label" @click="toggleTheme">
    {{ isDark ? '☀' : '☾' }}
  </button>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const isDark = ref(document.documentElement.dataset.theme === 'dark')
const label = computed(() => (isDark.value ? t('common.lightMode') : t('common.darkMode')))

const toggleTheme = () => {
  isDark.value = !isDark.value
  const theme = isDark.value ? 'dark' : 'light'
  document.documentElement.dataset.theme = theme
  localStorage.setItem('theme', theme)
}
</script>

<style scoped>
.theme-toggle {
  background: transparent;
  color: inherit;
  border: 1px solid #CCC;
  padding: 4px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  line-height: 1.2;
  cursor: pointer;
  transition: border-color 0.2s;
}

.theme-toggle:hover {
  border-color: #999;
}
</style>
