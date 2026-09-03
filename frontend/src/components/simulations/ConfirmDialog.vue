<template>
  <teleport to="#app-modals">
    <div
      v-if="open"
      class="confirm-scrim"
      @click.self="cancel"
    >
      <div
        ref="dialog"
        class="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="bodyId"
        @keydown.esc.stop="cancel"
        @keydown.tab="trapFocus"
      >
        <h2 :id="titleId" class="confirm-title">{{ title }}</h2>
        <p :id="bodyId" class="confirm-body">{{ body }}</p>

        <div class="confirm-actions">
          <button
            ref="cancelButton"
            type="button"
            class="btn btn-quiet"
            :disabled="busy"
            @click="cancel"
          >
            {{ $t('common.cancel') }}
          </button>
          <button
            ref="confirmButton"
            type="button"
            class="btn"
            :class="tone === 'danger' ? 'btn-danger' : 'btn-accent'"
            :disabled="busy"
            @click="confirm"
          >
            {{ busy ? $t('common.loading') : confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  body: { type: String, default: '' },
  confirmLabel: { type: String, default: '' },
  // 'danger' for anything that destroys data, 'accent' for the rest.
  tone: { type: String, default: 'danger' },
  // Keeps the dialog up, and both buttons inert, while the request is in
  // flight. The caller closes it once the request settles.
  busy: { type: Boolean, default: false }
})

const emit = defineEmits(['confirm', 'cancel'])

const dialog = ref(null)
const cancelButton = ref(null)
const confirmButton = ref(null)

const uid = Math.random().toString(36).slice(2, 8)
const titleId = `confirm-title-${uid}`
const bodyId = `confirm-body-${uid}`

const confirm = () => {
  if (!props.busy) emit('confirm')
}

const cancel = () => {
  if (!props.busy) emit('cancel')
}

// Two focusable controls, so the trap is just a wrap between them. Cancel is
// focused first: the dialog only ever guards a destructive action, and the
// safe choice should be the one a stray Return key picks.
const trapFocus = (event) => {
  const first = cancelButton.value
  const last = confirmButton.value
  if (!first || !last) return

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    await nextTick()
    cancelButton.value?.focus()
  },
  { immediate: true }
)
</script>

<style scoped>
.confirm-scrim {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg-scrim);
}

.confirm-dialog {
  width: 100%;
  max-width: 460px;
  padding: 24px;
  background: var(--bg-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg), var(--edge-highlight);
}

.confirm-title {
  margin-bottom: 10px;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
}

.confirm-body {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
}

.btn {
  padding: 9px 18px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.btn:disabled {
  opacity: 0.6;
}

.btn-quiet {
  background: transparent;
  border-color: var(--border-strong);
  color: var(--text-secondary);
}

.btn-quiet:not(:disabled):hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.btn-accent {
  background: var(--accent);
  color: var(--text-on-accent);
}

.btn-accent:not(:disabled):hover {
  background: var(--accent-hover);
}

.btn-danger {
  background: var(--danger-soft);
  border-color: var(--danger-border);
  color: var(--danger);
}

.btn-danger:not(:disabled):hover {
  background: var(--danger);
  color: var(--text-inverse);
}
</style>
