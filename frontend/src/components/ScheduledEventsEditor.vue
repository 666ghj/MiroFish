<template>
  <div class="events-editor">
    <div class="editor-header">
      <span class="box-label">
        {{ $t('step2.scheduledEvents.title') }}
        <span class="count-badge">{{ events.length }}</span>
      </span>
    </div>
    <p class="editor-desc">{{ $t('step2.scheduledEvents.desc') }}</p>

    <p v-if="isLegacy" class="legacy-note">{{ $t('step2.scheduledEvents.legacyNote') }}</p>

    <template v-else>
      <div v-if="events.length === 0" class="empty-state">
        {{ $t('step2.scheduledEvents.empty') }}
      </div>

      <div v-for="(event, idx) in events" :key="event.key" class="event-row" :class="{ disabled: !event.enabled }">
        <div class="event-fields">
          <label class="field hour-field">
            <span class="field-label">{{ $t('step2.scheduledEvents.hour') }}</span>
            <input
              type="number"
              class="input mono"
              min="0"
              :max="maxHour"
              step="1"
              v-model.number="event.at_sim_hour"
              @input="markDirty"
            />
          </label>
          <label class="field poster-field">
            <span class="field-label">{{ $t('step2.scheduledEvents.poster') }}</span>
            <select class="input" v-model.number="event.poster_agent_id" @change="markDirty">
              <option v-for="agent in agents" :key="agent.agent_id" :value="agent.agent_id">
                Agent {{ agent.agent_id }} · {{ agent.entity_name }} ({{ agent.entity_type }})
              </option>
            </select>
          </label>
          <label class="field enabled-field">
            <span class="field-label">{{ $t('step2.scheduledEvents.enabled') }}</span>
            <input type="checkbox" v-model="event.enabled" @change="markDirty" />
          </label>
          <button type="button" class="icon-btn" :title="$t('step2.scheduledEvents.remove')" @click="removeEvent(idx)">×</button>
        </div>
        <textarea
          class="input content-input"
          rows="2"
          :placeholder="$t('step2.scheduledEvents.contentPlaceholder')"
          v-model="event.content"
          @input="markDirty"
        ></textarea>
        <span v-if="event.source === 'llm_suggested'" class="source-tag">{{ $t('step2.scheduledEvents.fromSuggestion') }}</span>
      </div>

      <div class="editor-actions">
        <button type="button" class="btn secondary" @click="addEvent" :disabled="!agents.length || saving">
          + {{ $t('step2.scheduledEvents.add') }}
        </button>
        <button type="button" class="btn primary" @click="save" :disabled="saving || !dirty">
          {{ saving ? $t('step2.scheduledEvents.saving') : $t('step2.scheduledEvents.save') }}
        </button>
        <span v-if="savedAt && !dirty" class="saved-note">{{ $t('step2.scheduledEvents.saved') }}</span>
      </div>

      <ul v-if="errors.length" class="error-list">
        <li v-for="message in errors" :key="message">{{ message }}</li>
      </ul>

      <div v-if="availableSuggestions.length" class="suggestions">
        <span class="field-label">{{ $t('step2.scheduledEvents.suggested') }}</span>
        <p class="editor-desc">{{ $t('step2.scheduledEvents.suggestedDesc') }}</p>
        <div v-for="suggestion in availableSuggestions" :key="suggestion.id" class="suggestion-row">
          <span class="suggestion-hour mono">T+{{ suggestion.at_sim_hour }}h</span>
          <span class="suggestion-text">{{ suggestion.content }}</span>
          <button type="button" class="btn secondary small" @click="useSuggestion(suggestion)">
            {{ $t('step2.scheduledEvents.useSuggestion') }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { putScheduledEvents } from '../api/simulation'

const props = defineProps({
  simulationId: String,
  config: Object
})

const emit = defineEmits(['add-log', 'saved'])
const { t } = useI18n()

let nextKey = 1
const withKey = (event) => ({ ...event, key: nextKey++ })

const events = ref([])
const dirty = ref(false)
const saving = ref(false)
const savedAt = ref(null)
const errors = ref([])

const agents = computed(() => props.config?.agent_configs || [])
const maxHour = computed(() => Math.max(0, (props.config?.time_config?.total_simulation_hours || 1) - 1))
const isLegacy = computed(() => (props.config?.behavior_version || 1) < 2)

const loadFromConfig = () => {
  events.value = (props.config?.event_config?.scheduled_events || []).map(withKey)
  dirty.value = false
}

// Re-seed from the config when the simulation (or its prepared config) changes,
// but never overwrite the user's unsaved edits.
watch(() => props.config?.event_config?.scheduled_events, () => {
  if (!dirty.value) loadFromConfig()
}, { immediate: true })

const usedSuggestionIds = ref(new Set())
const availableSuggestions = computed(() =>
  (props.config?.event_config?.suggested_events || []).filter(s => !usedSuggestionIds.value.has(s.id))
)

const markDirty = () => {
  dirty.value = true
  errors.value = []
}

const defaultPosterId = () => {
  const sorted = [...agents.value].sort((a, b) => (b.influence_weight || 0) - (a.influence_weight || 0))
  return sorted.length ? sorted[0].agent_id : 0
}

const addEvent = () => {
  const last = events.value[events.value.length - 1]
  events.value.push(withKey({
    at_sim_hour: Math.min(maxHour.value, last ? Number(last.at_sim_hour) + 6 : 12),
    poster_agent_id: defaultPosterId(),
    content: '',
    source: 'user',
    enabled: true
  }))
  markDirty()
}

const removeEvent = (idx) => {
  events.value.splice(idx, 1)
  markDirty()
}

const useSuggestion = (suggestion) => {
  events.value.push(withKey({
    at_sim_hour: suggestion.at_sim_hour,
    poster_agent_id: suggestion.poster_agent_id ?? defaultPosterId(),
    poster_type: suggestion.poster_type,
    content: suggestion.content,
    source: 'llm_suggested',
    enabled: true
  }))
  usedSuggestionIds.value = new Set([...usedSuggestionIds.value, suggestion.id])
  markDirty()
}

const save = async () => {
  saving.value = true
  errors.value = []
  try {
    const payload = events.value.map(({ key, ...event }) => event)
    const res = await putScheduledEvents(props.simulationId, payload)
    events.value = (res.data?.scheduled_events || []).map(withKey)
    dirty.value = false
    savedAt.value = Date.now()
    emit('add-log', t('log.scheduledEventsSaved', { count: events.value.length }))
    emit('saved', res.data?.scheduled_events || [])
  } catch (err) {
    const details = err.response?.data?.errors
    errors.value = Array.isArray(details) && details.length ? details : [err.message]
    emit('add-log', t('log.scheduledEventsSaveFailed', { error: err.message }))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.events-editor {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--c-e5e5e5);
}

.box-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c-666666);
}

.count-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: var(--c-f0f0f0);
  border-radius: 10px;
  padding: 1px 8px;
  color: var(--c-333333);
}

.editor-desc {
  margin: 6px 0 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--c-888888);
}

.legacy-note {
  font-size: 12px;
  color: var(--c-aa6666);
  background: var(--c-fff6f3);
  border: 1px solid var(--c-f5d8cf);
  border-radius: 6px;
  padding: 8px 10px;
}

.empty-state {
  font-size: 12px;
  color: var(--c-999999);
  padding: 10px 0;
}

.event-row {
  position: relative;
  border: 1px solid var(--c-e5e5e5);
  border-radius: 6px;
  background: var(--c-ffffff);
  padding: 10px;
  margin-bottom: 10px;
}

.event-row.disabled {
  opacity: 0.6;
}

.event-fields {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-bottom: 8px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hour-field { width: 84px; }
.poster-field { flex: 1; min-width: 0; }
.enabled-field { align-items: center; }

.field-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--c-999999);
}

.input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--c-dddddd);
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 12px;
  font-family: inherit;
  background: var(--c-fafafa);
}

.input:focus {
  outline: none;
  border-color: var(--c-ff5722);
  background: var(--c-ffffff);
}

.mono { font-family: 'JetBrains Mono', monospace; }

.content-input {
  resize: vertical;
  line-height: 1.5;
}

.icon-btn {
  border: none;
  background: transparent;
  color: var(--c-aaaaaa);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  padding: 4px 6px;
}

.icon-btn:hover { color: var(--c-e53935); }

.source-tag {
  display: inline-block;
  margin-top: 6px;
  font-size: 10px;
  color: var(--c-888888);
  background: var(--c-f4f4f4);
  border-radius: 3px;
  padding: 1px 6px;
}

.editor-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.btn {
  border-radius: 4px;
  border: 1px solid var(--c-dddddd);
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
  background: var(--c-ffffff);
}

.btn.small { padding: 3px 8px; font-size: 11px; }
.btn.primary { background: var(--c-000000); color: var(--c-ffffff); border-color: var(--c-000000); }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }

.saved-note {
  font-size: 12px;
  color: var(--c-2e7d32);
}

.error-list {
  margin: 10px 0 0;
  padding: 8px 10px 8px 26px;
  font-size: 12px;
  color: var(--c-c62828);
  background: var(--c-fff5f5);
  border: 1px solid var(--c-f3cfcf);
  border-radius: 6px;
}

.suggestions {
  margin-top: 16px;
}

.suggestion-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--c-f0f0f0);
  font-size: 12px;
}

.suggestion-hour {
  color: var(--c-888888);
  white-space: nowrap;
}

.suggestion-text {
  flex: 1;
  color: var(--c-444444);
  line-height: 1.45;
}
</style>
