<template>
  <router-view v-slot="{ Component, route }">
    <transition name="page" mode="out-in">
      <component :is="Component" :key="route.path" />
    </transition>
  </router-view>
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

  /* Accent - blue */
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

  /* Motion: one easing, three durations. Small distances, no bounce. */
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --dur-1: 120ms;   /* hover, press, color */
  --dur-2: 220ms;   /* enter, popovers, drawers */
  --dur-3: 420ms;   /* page and section reveals */
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

/* Scrollbar - dark for simulation views, light for home */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #262626; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #404040; }
html { scrollbar-color: #262626 transparent; }

button { font-family: inherit; cursor: pointer; }

/* ── Motion ─────────────────────────────────────────────────── */
/* Interactive feedback: every button and link eases its colors and presses in slightly */
button, a, [role="button"] {
  transition: color var(--dur-1) ease, background-color var(--dur-1) ease,
              border-color var(--dur-1) ease, box-shadow var(--dur-1) ease,
              opacity var(--dur-1) ease, transform var(--dur-1) var(--ease-out);
}
button:not(:disabled):active, [role="button"]:active { transform: scale(0.97); }

/* Page change: quick fade with a 6px rise */
.page-enter-active { transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out); }
.page-leave-active { transition: opacity var(--dur-1) ease; }
.page-enter-from { opacity: 0; transform: translateY(6px); }
.page-leave-to { opacity: 0; }

/* v-reveal (see motion.js) */
.reveal { opacity: 0; transform: translateY(8px); transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out); }
.reveal.is-in { opacity: 1; transform: none; }
.reveal--stagger { opacity: 1; transform: none; }
.reveal--stagger > * { opacity: 0; transform: translateY(8px);
  transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out);
  transition-delay: calc(var(--i, 0) * 60ms); }
.reveal--stagger.is-in > * { opacity: 1; transform: none; }

/* Shared enter animation for things that appear in place */
@keyframes rise-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes pop-in { from { opacity: 0; transform: translateY(4px) scale(0.98); } to { opacity: 1; transform: none; } }

/* Respect the OS setting everywhere, including older component animations */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important; transition-delay: 0ms !important; scroll-behavior: auto !important;
  }
  .reveal, .reveal--stagger > * { opacity: 1 !important; transform: none !important; }
}
</style>
