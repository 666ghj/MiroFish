<template>
  <router-view />
  <Analytics />
</template>

<script setup>
import { Analytics } from '@vercel/analytics/vue'

// Use Vue Router to manage pages
</script>

<style>
/* ── Design tokens ──────────────────────────────────────────── */
:root {
  /* Backgrounds */
  --bg-base:     #000000;
  --bg-surface:  #0a0a0a;
  --bg-card:     #101010;
  --bg-elevated: #171717;

  /* Borders */
  --border-subtle: #1c1c1c;
  --border-muted:  #2a2a2a;

  /* Text */
  --text-primary:   #ededed;
  --text-secondary: #a3a3a3;
  --text-tertiary:  #737373;

  /* Accent — blue */
  --accent:     #3b82f6;
  --accent-dim: rgba(59, 130, 246, 0.12);
  --accent-hover: #2563eb;

  /* Semantic */
  --green:  #4ade80;
  --amber:  #f59e0b;
  --red:    #f87171;

  /* Typography */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}

/* ── Global reset ───────────────────────────────────────────── */
*, *::before, *::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  background: var(--bg-base);
  color-scheme: dark;
}

::selection {
  background: rgba(59, 130, 246, 0.35);
  color: #fff;
}

#app {
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--text-primary);
  background-color: var(--bg-base);
}

/* Focus-visible for keyboard nav */
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Scrollbar — dark for simulation views, light for home */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #262626; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #404040; }
html { scrollbar-color: #262626 transparent; }

button { font-family: inherit; cursor: pointer; }
</style>
