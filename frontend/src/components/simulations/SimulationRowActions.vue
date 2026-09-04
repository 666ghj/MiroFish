<template>
  <div class="row-actions">
    <div class="action-row">
      <!-- The primary action. Its label and its destination both follow from
           the status: 'Open' shows something that already exists, 'Continue'
           moves the simulation on to its next step. -->
      <router-link
        v-if="primary.route"
        class="primary-btn"
        :to="primary.route"
        :title="$t(`simulations.actions.${primary.hint}`)"
      >
        {{ $t(`simulations.actions.${primary.label}`) }}
      </router-link>

      <!-- Blocked instead of hidden, so a wedged simulation says what it needs
           rather than dead-ending on a button that does nothing. -->
      <button
        v-else
        type="button"
        class="primary-btn is-blocked"
        disabled
        :title="blockedHint"
      >
        {{ $t(`simulations.actions.${primary.label}`) }}
      </button>

      <div ref="menuRoot" class="menu-root">
        <button
          ref="trigger"
          type="button"
          class="menu-trigger"
          :aria-label="$t('simulations.actions.menuLabel', { name })"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click="toggleMenu"
          @keydown.down.prevent="openMenu"
        >
          <svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <circle cx="3.4" cy="8" r="1.4" fill="currentColor" />
            <circle cx="8" cy="8" r="1.4" fill="currentColor" />
            <circle cx="12.6" cy="8" r="1.4" fill="currentColor" />
          </svg>
        </button>

        <!-- The menu is teleported out of the table. The scrolling container the
             table lives in clips on both axes, so a dropdown left in place is cut
             off on the last few rows. -->
        <teleport to="#app-modals">
          <div
            v-if="menuOpen"
            ref="menu"
            class="menu"
            role="menu"
            :style="menuStyle"
            @keydown.esc.stop.prevent="closeMenu"
          >
            <button
              v-for="item in menuItems"
              :key="item.key"
              type="button"
              role="menuitem"
              class="menu-item"
              :class="{ 'is-danger': item.danger }"
              :disabled="!item.enabled"
              :title="item.enabled ? item.hint : item.disabledHint"
              @click="run(item)"
            >
              {{ $t(`simulations.actions.${item.key}`) }}
            </button>
          </div>
        </teleport>
      </div>
    </div>

    <p v-if="primary.blocked" class="blocked-hint">{{ blockedHint }}</p>

    <!-- A refused action says why. The handler can refuse an item the markup
         thought was clickable, and a click that closes the menu and then does
         nothing at all is indistinguishable from a broken build. -->
    <p v-if="refusedHint" class="blocked-hint" role="status" aria-live="polite">
      {{ refusedHint }}
    </p>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  primaryAction,
  restartBlockedBy,
  secondaryActions,
  RESTART_BLOCKED_LIVE
} from '../../utils/simulationFormat'

const props = defineProps({
  simulation: { type: Object, required: true },
  // The already-resolved display name, so the hints and the menu label read
  // the same as the row above them.
  name: { type: String, required: true }
})

const emit = defineEmits(['restart', 'stop', 'view-logs', 'delete'])

const { t } = useI18n()

// Copy that has no i18n key yet. locales/en.json is owned by another group, so
// these strings live here until keys exist for them; they are English-only,
// like the rest of the product.

// Restart on a live run is not a restart. The backend reaps the child and
// deletes the run state, the log, both action files and both databases before
// relaunching, so the run being watched is simply gone.
const RESTART_LIVE_HINT =
  'This simulation is still running. Stop it first - restarting a live run kills it ' +
  'and deletes everything it has produced.'

const RESTART_CREATED_HINT =
  'This simulation has not been prepared yet. Open it and finish setup first.'

// Shown when an item is refused and has nothing more specific to say. The
// status the row is in decides what is available, and it has already changed
// by the time this appears, so it points at the row rather than guessing.
const UNAVAILABLE_HINT =
  'That action is not available for this simulation in its current state.'

const menuOpen = ref(false)
const refusedHint = ref('')
const menuRoot = ref(null)
const menu = ref(null)
const trigger = ref(null)
const menuStyle = ref({})

const primary = computed(() => primaryAction(props.simulation))
const available = computed(() => secondaryActions(props.simulation))

// 'preparing' is not among these any more: the row opens into the setup view,
// which follows the preparation instead of dead-ending on a disabled button.
const blockedHint = computed(() => {
  if (primary.value.blocked === 'stale') return t('simulations.staleHint')
  return ''
})

// A disabled item explains itself rather than keeping the hint that describes
// what it would have done, which on a live row would read as a promise the
// item no longer keeps.
const restartHint = computed(() => {
  switch (restartBlockedBy(props.simulation)) {
    case RESTART_BLOCKED_LIVE:
      return RESTART_LIVE_HINT
    case null:
      return t('simulations.actions.restartHint')
    default:
      return RESTART_CREATED_HINT
  }
})

// `hint` is the tooltip; `disabledHint` is what a refusal says out loud. Only
// restart knows why it is unavailable, so the rest fall back to the generic
// line rather than repeating a description of what they would have done.
const menuItems = computed(() => [
  {
    key: 'restart',
    event: 'restart',
    enabled: available.value.restart,
    danger: false,
    hint: restartHint.value,
    disabledHint: restartHint.value
  },
  {
    key: 'stop',
    event: 'stop',
    enabled: available.value.stop,
    danger: false,
    hint: t('simulations.actions.stopHint'),
    disabledHint: UNAVAILABLE_HINT
  },
  {
    key: 'viewLogs',
    event: 'view-logs',
    enabled: available.value.logs,
    danger: false,
    hint: t('simulations.actions.viewLogsHint'),
    disabledHint: UNAVAILABLE_HINT
  },
  {
    key: 'delete',
    event: 'delete',
    enabled: available.value.delete,
    danger: true,
    hint: t('simulations.actions.deleteHint'),
    disabledHint: UNAVAILABLE_HINT
  }
])

const closeMenu = () => {
  menuOpen.value = false
  trigger.value?.focus()
}

// The menu is positioned against the viewport because it is teleported out of
// the table, and it flips above the trigger when the last rows leave no room
// below.
const positionMenu = () => {
  const anchor = trigger.value?.getBoundingClientRect()
  if (!anchor) return

  const height = menu.value?.offsetHeight || 0
  const flip = height > 0 && anchor.bottom + height + 8 > window.innerHeight

  menuStyle.value = {
    right: `${Math.max(8, window.innerWidth - anchor.right)}px`,
    ...(flip
      ? { bottom: `${window.innerHeight - anchor.top + 6}px` }
      : { top: `${anchor.bottom + 6}px` })
  }
}

const openMenu = async () => {
  // The previous refusal is spent once the menu is open again; leaving it up
  // would describe a state the row may have left.
  refusedHint.value = ''
  menuOpen.value = true
  await nextTick()
  positionMenu()
  await nextTick()
  menu.value?.querySelector('button:not(:disabled)')?.focus()
}

const toggleMenu = () => {
  if (menuOpen.value) {
    menuOpen.value = false
  } else {
    openMenu()
  }
}

// The guard lives here, not only on :disabled. Restart on a live run destroys
// the run, so state - not markup - decides whether the emit happens: a template
// regression, a stale menu whose row went live while it was open, or any
// programmatic call is refused the same way. A refusal still closes the menu
// and says why, so it never looks like a dead click.
const run = (item) => {
  if (!item?.enabled) {
    refusedHint.value = item?.disabledHint || UNAVAILABLE_HINT
    closeMenu()
    return
  }
  refusedHint.value = ''
  menuOpen.value = false
  emit(item.event, props.simulation)
}

// The menu is no longer a descendant of the trigger, so both have to be
// excluded here; closing on the pointerdown inside the menu would remove the
// item before its click could land.
const onDocumentPointerDown = (event) => {
  if (menuRoot.value?.contains(event.target)) return
  if (menu.value?.contains(event.target)) return
  menuOpen.value = false
}

// Anything that moves the trigger detaches the menu from it, and repositioning
// mid-gesture is worse than closing.
const onViewportChange = () => {
  menuOpen.value = false
}

watch(menuOpen, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerDown)
    window.addEventListener('scroll', onViewportChange, true)
    window.addEventListener('resize', onViewportChange)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    window.removeEventListener('scroll', onViewportChange, true)
    window.removeEventListener('resize', onViewportChange)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<style scoped>
.row-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.primary-btn {
  display: inline-flex;
  align-items: center;
  padding: 7px 16px;
  background: var(--accent);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--text-on-accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
  transition: background-color 0.15s ease;
}

.primary-btn:hover {
  background: var(--accent-hover);
  color: var(--text-on-accent);
}

.primary-btn.is-blocked {
  background: transparent;
  border-color: var(--border-strong);
  color: var(--text-disabled);
}

.blocked-hint {
  max-width: 260px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--warning);
  text-align: right;
}

.menu-root {
  position: relative;
}

.menu-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
}

.menu-trigger .icon {
  width: 16px;
  height: 16px;
}

.menu-trigger:hover,
.menu-trigger[aria-expanded='true'] {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.menu {
  position: fixed;
  z-index: 2;
  display: flex;
  flex-direction: column;
  min-width: 176px;
  padding: 6px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}

.menu-item {
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  white-space: nowrap;
}

/* Hover darkens rather than lightens. The menu sits on --bg-overlay, which is
   the lightest surface in the theme, and the usual pale hover wash pushed the
   danger item's 13px text to 3.98:1 - under AA. An opaque sunken row keeps it
   at 8.67:1 and the neutral items well above that, and it reads the same
   whatever is behind the teleported menu. */
.menu-item:not(:disabled):hover {
  background: var(--bg-sunken);
  color: var(--text-primary);
}

.menu-item.is-danger {
  color: var(--danger);
}

.menu-item.is-danger:not(:disabled):hover {
  background: var(--bg-sunken);
  color: var(--danger);
}

.menu-item:disabled {
  color: var(--text-disabled);
}
</style>
