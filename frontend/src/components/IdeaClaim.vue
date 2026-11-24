<template>
  <div class="claim" :class="[`claim--${status}`, { 'claim--changed': changed, 'claim--empty': empty }]">
    <div class="claim-top">
      <span v-if="label" class="claim-label">{{ label }}</span>
      <span class="chip" :class="`chip--${status}`" :title="chipTitle">
        <svg viewBox="0 0 12 12" aria-hidden="true"><path :d="CHIP_ICON[status]" /></svg>
        {{ chipText }}
      </span>
      <span v-if="changed" class="updated">Updated</span>
      <span class="spacer"></span>
      <button
        v-if="!empty || editable"
        type="button"
        class="icon-btn"
        :aria-label="editing ? 'Cancel editing' : `Edit ${label || 'this item'}`"
        @click="toggleEdit"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11 2.5l2.5 2.5L6 12.5H3.5V10z" /></svg>
      </button>
      <button
        v-if="!empty"
        type="button"
        class="icon-btn"
        :class="{ on: claim.locked }"
        :aria-pressed="!!claim.locked"
        :aria-label="claim.locked ? 'Unlock: let the AI update this' : 'Lock: stop the AI changing this'"
        :title="claim.locked ? 'Locked: the AI will not change this' : 'Lock this so the AI will not change it'"
        @click="$emit('lock', path, !claim.locked)"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
          <path :d="claim.locked ? 'M5.5 7V5a2.5 2.5 0 0 1 5 0v2' : 'M5.5 7V5a2.5 2.5 0 0 1 4.9-.7'" />
        </svg>
      </button>
    </div>

    <form v-if="editing" class="edit" @submit.prevent="save">
      <textarea
        ref="input"
        v-model="draft"
        rows="2"
        maxlength="400"
        :aria-label="`Edit ${label || 'item'}`"
        @keydown.enter.exact.prevent="save"
        @keydown.esc="editing = false"
      ></textarea>
      <div class="edit-actions">
        <button type="submit" class="btn-mini btn-mini--primary">Save</button>
        <button type="button" class="btn-mini" @click="editing = false">Cancel</button>
      </div>
    </form>
    <p v-else class="claim-text">{{ empty ? placeholder : claim.text }}</p>

    <div v-if="!editing && sourceList.length" class="claim-sources">
      <a v-for="s in sourceList" :key="s.id" :href="s.url" target="_blank" rel="noopener" class="src-link">
        {{ s.host }}
      </a>
    </div>
    <p v-if="!editing && claim.previous && claim.previous.text && changed" class="claim-prev">
      Was: {{ claim.previous.text }}
    </p>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'

const props = defineProps({
  claim: { type: Object, required: true },
  path: { type: String, required: true },
  label: { type: String, default: '' },
  sources: { type: Object, default: () => ({}) },
  changed: { type: Boolean, default: false },
  placeholder: { type: String, default: 'Not known yet' },
  editable: { type: Boolean, default: true },
})
const emit = defineEmits(['edit', 'lock'])

const CHIP_ICON = {
  founder_stated: 'M2.5 6.5l2.2 2.2L9.5 3.8',
  ai_inference: 'M6 2.5v.01M6 5v4.5',
  evidence: 'M4.5 7.5l-1 1a2 2 0 0 1-2.8-2.8l2-2a2 2 0 0 1 2.8 0M7.5 4.5l1-1a2 2 0 0 1 2.8 2.8l-2 2a2 2 0 0 1-2.8 0',
  contradiction: 'M6 2.5v4M6 9v.01',
  unknown: 'M3 6h6',
}

const status = computed(() => (props.claim.text ? props.claim.status : 'unknown') || 'unknown')
const empty = computed(() => !props.claim.text)
const chipText = computed(() => ({
  founder_stated: 'You said',
  ai_inference: 'AI guess',
  evidence: `Evidence · ${(props.claim.source_ids || []).length}`,
  contradiction: 'Contradiction',
  unknown: 'Open gap',
}[status.value]))
const chipTitle = computed(() => ({
  founder_stated: props.claim.specific ? 'You said this, with specific detail' : 'You said this',
  ai_inference: 'The AI inferred this. Edit it if it is wrong.',
  evidence: 'Backed by the linked sources',
  contradiction: 'This conflicts with something you said earlier',
  unknown: 'Not covered yet',
}[status.value]))

const sourceList = computed(() => (props.claim.source_ids || [])
  .map(id => props.sources[id] && { id, url: props.sources[id].url, host: host(props.sources[id].url) })
  .filter(Boolean))

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch (_) { return 'source' }
}

const editing = ref(false)
const draft = ref('')
const input = ref(null)

function toggleEdit() {
  editing.value = !editing.value
  if (editing.value) {
    draft.value = props.claim.text || ''
    nextTick(() => input.value?.focus())
  }
}

function save() {
  emit('edit', props.path, draft.value.trim())
  editing.value = false
}
</script>

<style scoped>
.claim {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: background 0.6s ease, border-color 0.6s ease;
}
.claim--changed { background: rgba(59, 130, 246, 0.08); border-color: rgba(59, 130, 246, 0.35); }
.claim-top { display: flex; align-items: center; gap: 8px; min-height: 22px; }
.claim-label { font-size: 11px; font-weight: 600; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }
.spacer { flex: 1; }

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 7px 2px 5px;
  border-radius: 999px;
  border: 1px solid #2e2e2e;
  color: var(--text-secondary);
  white-space: nowrap;
}
.chip svg { width: 11px; height: 11px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
.chip--founder_stated { color: #e5e5e5; border-color: #3a3a3a; }
.chip--ai_inference { color: #a3a3a3; border-style: dashed; }
.chip--evidence { color: #86efac; border-color: rgba(74, 222, 128, 0.35); background: rgba(74, 222, 128, 0.08); }
.chip--contradiction { color: #fcd34d; border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.08); }
.chip--unknown { color: #737373; border-style: dashed; }

.updated {
  font-size: 10px;
  font-weight: 600;
  color: #93c5fd;
}

.icon-btn {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #6b6b6b;
  opacity: 0.6;
  transition: opacity 0.15s, color 0.15s, background 0.15s;
}
.claim:hover .icon-btn, .icon-btn:focus-visible, .icon-btn.on { opacity: 1; }
.icon-btn:hover { color: var(--text-primary); background: #1a1a1a; }
.icon-btn.on { color: #93c5fd; }
.icon-btn svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; }

.claim-text { margin-top: 4px; font-size: 13.5px; line-height: 1.55; color: var(--text-primary); }
.claim--empty .claim-text { color: #5a5a5a; font-style: italic; }
.claim--ai_inference .claim-text { color: #c4c4c4; }
.claim-prev { margin-top: 4px; font-size: 11.5px; color: var(--text-tertiary); text-decoration: line-through; }

.claim-sources { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.src-link {
  font-size: 11px;
  color: #93c5fd;
  text-decoration: none;
  padding: 1px 7px;
  border-radius: 4px;
  background: rgba(59, 130, 246, 0.1);
}
.src-link:hover { text-decoration: underline; }

.edit { margin-top: 6px; display: flex; flex-direction: column; gap: 6px; }
.edit textarea {
  width: 100%;
  resize: vertical;
  font: inherit;
  font-size: 13.5px;
  color: var(--text-primary);
  background: #0d0d0d;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 8px 10px;
}
.edit textarea:focus { outline: none; border-color: var(--accent); }
.edit-actions { display: flex; gap: 6px; }
.btn-mini {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #333;
  background: transparent;
  color: var(--text-secondary);
}
.btn-mini--primary { background: var(--accent); border-color: var(--accent); color: #fff; }

@media (prefers-reduced-motion: reduce) {
  .claim { transition: none; }
}
</style>
