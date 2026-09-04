<template>
  <header class="app-nav">
    <BrandLockup />

    <nav class="app-nav-links" aria-label="Primary">
      <router-link
        v-for="link in navLinks"
        :key="link.path"
        :to="link.path"
        class="app-nav-link"
        :class="{ 'is-active': isActive(link) }"
        :aria-current="isActive(link) ? 'page' : undefined"
      >
        {{ link.label }}
      </router-link>
    </nav>

    <div id="nav-context" />
  </header>

  <main class="app-main">
    <slot />
  </main>

  <div id="app-modals" />
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BrandLockup from './BrandLockup.vue'

const route = useRoute()

// Linked by path rather than by name on purpose: /simulations and /reports are
// registered later in the migration, and router-link throws on an unresolvable
// named target while an unmatched path resolves to an empty route and renders
// as an inert link.
const navLinks = [
  { label: 'Projects', path: '/projects' },
  { label: 'Simulations', path: '/simulations' },
  { label: 'Reports', path: '/reports' }
]

const currentPath = computed(() => route.path)

// The active class is computed rather than left to .router-link-active because
// that class only appears once a matching route exists. Projects used to point
// at '/', which prefix-matches every route in the app and needed an exact-match
// case of its own; it points at the project list now, so all three links match
// the same way.
const isActive = (link) =>
  currentPath.value === link.path || currentPath.value.startsWith(`${link.path}/`)
</script>

<style scoped>
.app-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  height: var(--nav-h);
  padding: 0 24px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border-default);
}

.app-nav-links {
  display: flex;
  align-items: stretch;
  height: 100%;
  margin-left: 8px;
}

.app-nav-link {
  display: inline-flex;
  align-items: center;
  padding: 0 14px;
  border-bottom: 2px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.app-nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.app-nav-link:focus-visible {
  outline: none;
  box-shadow: var(--focus-shadow);
}

.app-nav-link.is-active {
  color: var(--text-primary);
  border-bottom-color: var(--accent);
}

.app-main {
  flex: 1;
  /* MANDATORY. Without it this flex child refuses to shrink below its content
     and the log wells and the d3 canvas push past the viewport. */
  min-height: 0;
  overflow: auto;
}

@media (max-width: 639px) {
  .app-nav {
    padding: 0 12px;
  }

  .app-nav-link {
    padding: 0 10px;
  }
}
</style>

<style>
/* The two teleport targets. These rules are deliberately unscoped: the content
   of both regions is teleported in from other components, which carry their
   own scope ids, so a scoped selector would never reach it. */

/* Right-hand region of the nav bar. Views teleport their step counter, status
   dot and view-mode switcher in here; it stays in the DOM when they do not. */
#nav-context {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-left: auto;
}

/* Full-viewport stacking layer for modals and toasts, so no view has to manage
   its own scrim depth. The layer is transparent to the pointer and every direct
   child takes the pointer back, which keeps an empty layer from swallowing
   clicks on the page underneath. */
#app-modals {
  position: fixed;
  inset: 0;
  z-index: 1000;
  pointer-events: none;
}

#app-modals > * {
  pointer-events: auto;
}
</style>
