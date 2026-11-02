<template>
  <div class="theme-switcher" ref="switcherRef" @keydown.esc="open = false">
    <button
      class="switcher-trigger"
      :title="$t('theme.label')"
      :aria-label="$t('theme.label')"
      aria-haspopup="listbox"
      :aria-expanded="open"
      @click="open = !open"
    >
      <svg class="theme-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <template v-if="choice === 'dark'">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </template>
        <template v-else-if="choice === 'light'">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </template>
        <template v-else>
          <rect x="3" y="4" width="18" height="12" rx="1" />
          <path d="M8 20h8M12 16v4" />
        </template>
      </svg>
      <span class="caret">{{ open ? '▲' : '▼' }}</span>
    </button>
    <ul v-if="open" class="switcher-dropdown" role="listbox" :aria-label="$t('theme.label')">
      <li
        v-for="item in THEME_CHOICES"
        :key="item"
        class="switcher-option"
        :class="{ active: item === choice }"
        role="option"
        :aria-selected="item === choice"
        @click="select(item)"
      >
        {{ $t(`theme.${item}`) }}
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { THEME_CHOICES, setTheme, useTheme } from '@/theme/index.js'

const { choice } = useTheme()
const open = ref(false)
const switcherRef = ref(null)

const select = (item) => {
  setTheme(item)
  open.value = false
}

const onClickOutside = (e) => {
  if (switcherRef.value && !switcherRef.value.contains(e.target)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onClickOutside))
onUnmounted(() => document.removeEventListener('click', onClickOutside))
</script>

<style scoped>
.theme-switcher {
  position: relative;
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
}

.switcher-trigger {
  background: transparent;
  color: var(--c-333333);
  border: 1px solid var(--c-cccccc);
  padding: 5px 9px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: border-color 0.2s, opacity 0.2s;
}

.switcher-trigger:hover {
  border-color: var(--c-999999);
}

.theme-icon {
  flex-shrink: 0;
}

.caret {
  font-size: 0.6rem;
}

.switcher-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: var(--c-ffffff);
  border: 1px solid var(--c-dddddd);
  list-style: none;
  padding: 4px 0;
  min-width: 100px;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.switcher-option {
  padding: 6px 12px;
  font-size: 0.8rem;
  color: var(--c-333333);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}

.switcher-option:hover {
  background: var(--c-f0f0f0);
}

.switcher-option.active {
  color: var(--orange, var(--c-ff4500));
}
</style>
