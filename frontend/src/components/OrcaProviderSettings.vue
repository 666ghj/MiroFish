<template>
  <div ref="root" class="provider-settings">
    <!-- Navbar trigger: the settings panel would be far too tall to sit
         permanently inside a 60px navigation bar. -->
    <button
      id="orca-settings-trigger"
      type="button"
      class="ps-trigger"
      :class="{ 'is-open': panelOpen }"
      :aria-expanded="panelOpen ? 'true' : 'false'"
      @click="togglePanel"
    >
      <span class="ps-status" :class="statusClass"><span class="dot" /></span>
      {{ t('orcarouter.settingsTitle') }}
      <span class="ps-trigger-value">{{ statusText }}</span>
    </button>

    <div v-if="panelOpen" id="orca-settings-panel" class="ps-panel">
      <div class="ps-header">
        <span class="ps-title">{{ t('orcarouter.settingsTitle') }}</span>
        <span class="ps-status" :class="statusClass">
          <span class="dot" />
          {{ statusText }}
        </span>
      </div>

      <div class="ps-body">
        <!-- Provider selection -->
        <div class="ps-row">
          <label class="ps-label" for="orca-provider-select">{{ t('orcarouter.settingsTitle') }}</label>
          <select
            id="orca-provider-select"
            class="ps-select"
            :value="selection"
            :disabled="isBusy"
            @change="onProviderChange"
          >
            <option value="default">{{ t('orcarouter.providerDefault') }}</option>
            <option value="orcarouter">{{ t('orcarouter.providerOrca') }}</option>
          </select>
        </div>

        <!-- Authentication choice 1: paste an existing API key -->
        <div class="ps-row" v-if="isOrca">
          <label class="ps-label" for="orca-key-input">{{ t('orcarouter.apiKeyLabel') }}</label>
          <div class="ps-inline">
            <input
              id="orca-key-input"
              v-model="apiKeyInput"
              type="password"
              class="ps-input"
              :placeholder="t('orcarouter.apiKeyPlaceholder')"
              autocomplete="off"
              spellcheck="false"
              :disabled="isBusy"
            />
            <button
              id="orca-key-save"
              class="ps-btn"
              :disabled="isBusy || !apiKeyInput"
              @click="saveApiKey"
            >
              {{ t('orcarouter.apiKeySave') }}
            </button>
            <button
              v-if="status.configured"
              id="orca-key-clear"
              class="ps-btn ps-btn-danger"
              :disabled="isBusy"
              @click="removeKey"
            >
              {{ t('orcarouter.clearKey') }}
            </button>
          </div>
          <p class="ps-hint">{{ t('orcarouter.apiKeyHint') }}</p>
          <p v-if="apiKeyMessage" class="ps-message">{{ apiKeyMessage }}</p>
          <p v-if="status.configured && status.key_preview" id="orca-key-preview" class="ps-message ps-muted">
            {{ t('orcarouter.keyPreview') }}: {{ status.key_preview }}
          </p>
        </div>

        <!-- Authentication choice 2: OAuth 2.0 + PKCE (S256) -->
        <div class="ps-row" v-if="isOrca">
          <span class="ps-label">{{ t('orcarouter.authLabel') }}</span>
          <div class="ps-inline">
            <button
              id="orca-connect-btn"
              class="ps-btn ps-btn-orca"
              :disabled="isBusy || !canConnect"
              @click="startConnect"
            >
              {{ connectState === 'connecting' ? t('orcarouter.connecting') : t('orcarouter.connectButton') }}
            </button>
            <button
              v-if="connectState === 'waiting_code' || connectState === 'exchanging'"
              id="orca-connect-cancel"
              class="ps-btn"
              :disabled="isBusy"
              @click="cancelConnect"
            >
              {{ t('orcarouter.cancelButton') }}
            </button>
          </div>
          <p class="ps-hint">{{ t('orcarouter.authDesc') }}</p>

          <div v-if="connectState === 'waiting_code'" class="ps-code-box">
            <input
              id="orca-code-input"
              v-model="userCode"
              class="ps-input"
              :placeholder="t('orcarouter.codePlaceholder')"
              autocomplete="one-time-code"
              spellcheck="false"
              :disabled="isBusy"
            />
            <button
              id="orca-connect-finish"
              class="ps-btn ps-btn-orca"
              :disabled="isBusy || !userCode"
              @click="finishConnect"
            >
              {{ t('orcarouter.exchangeButton') }}
            </button>
          </div>

          <p v-if="connectMessage" class="ps-message ps-ok">{{ connectMessage }}</p>
          <p v-if="connectError" class="ps-message ps-error">{{ connectError }}</p>
          <p v-if="isOrca && status.configured && status.source" id="orca-auth-source" class="ps-message ps-muted">
            {{ status.source === 'pkce' ? t('orcarouter.authLabel') : t('orcarouter.apiKeyLabel') }} · {{ t('orcarouter.keyConfigured') }}
          </p>
        </div>

        <!-- Model selection: a selector bound to the capability-filtered catalog -->
        <div class="ps-row" v-if="isOrca && status.configured">
          <label class="ps-label" for="orca-model-trigger">{{ t('orcarouter.modelTitle') }}</label>
          <div class="ps-inline">
            <div ref="modelCombobox" class="ps-combobox">
              <button
                id="orca-model-trigger"
                ref="modelTrigger"
                type="button"
                class="ps-select ps-model-trigger"
                :class="{ 'is-open': modelPanelOpen }"
                :disabled="isBusy || modelsState === 'loading' || models.length === 0"
                :aria-expanded="modelPanelOpen ? 'true' : 'false'"
                aria-haspopup="listbox"
                @click="toggleModelPanel"
              >
                <span class="ps-model-value">
                  {{ selectedModel || (modelsState === 'loading' ? t('orcarouter.modelLoading') : t('orcarouter.modelPlaceholder')) }}
                </span>
                <span class="ps-model-caret" aria-hidden="true">▾</span>
              </button>

              <div
                v-if="modelPanelOpen"
                id="orca-model-panel"
                class="ps-model-panel"
                role="listbox"
              >
                <input
                  id="orca-model-search"
                  v-model="modelQuery"
                  class="ps-input ps-model-search"
                  type="text"
                  :placeholder="t('orcarouter.modelSearchPlaceholder')"
                  autocomplete="off"
                  spellcheck="false"
                />
                <ul class="ps-model-list">
                  <li
                    v-for="model in filteredModels"
                    :key="model.id"
                    class="orca-model-option"
                    role="option"
                    :data-model-id="model.id"
                    :aria-selected="model.id === selectedModel ? 'true' : 'false'"
                    @click="pickModel(model.id)"
                  >
                    <span class="ps-model-id">{{ model.id }}</span>
                    <span class="ps-model-meta">
                      <template v-if="model.context_window">
                        {{ formatContext(model.context_window) }}
                      </template>
                      <template v-if="model.input_modalities && model.input_modalities.length">
                        · {{ model.input_modalities.join('/') }}
                      </template>
                      <template v-if="model.reasoning_effort_levels && model.reasoning_effort_levels.length">
                        · {{ t('orcarouter.modelReasoning') }}
                      </template>
                    </span>
                  </li>
                  <li v-if="filteredModels.length === 0" class="ps-model-none">
                    {{ t('orcarouter.modelNoMatch') }}
                  </li>
                </ul>
              </div>
            </div>

            <button
              id="orca-model-refresh"
              class="ps-btn"
              :disabled="isBusy || modelsState === 'loading'"
              @click="refreshModels"
            >
              {{ t('orcarouter.modelRefresh') }}
            </button>
          </div>

          <p v-if="modelsState === 'seed'" class="ps-message ps-warn">{{ modelsMessage }}</p>
          <p v-else-if="modelsState === 'error'" class="ps-message ps-error">{{ modelsMessage }}</p>
          <p v-else-if="modelsState === 'empty'" class="ps-message ps-error">{{ modelsMessage }}</p>
          <p v-else-if="modelsMessage && modelsState === 'ok'" class="ps-message ps-muted">{{ modelsMessage }}</p>
          <p v-if="modelsState === 'ok'" id="orca-catalog-source" class="ps-message ps-muted">
            {{ t('orcarouter.modelLiveCount', { count: models.length }) }}
          </p>
        </div>

        <!-- Origins -->
        <div class="ps-row ps-origins" v-if="isOrca">
          <code>{{ t('orcarouter.authOrigin') }}</code>
          <code>{{ t('orcarouter.inferenceOrigin') }}</code>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useOrcaProvider } from '../composables/useOrcaProvider'

const { t } = useI18n()

const {
  status,
  selection,
  isOrca,
  apiKeyInput,
  apiKeySaving,
  apiKeyMessage,
  connectState,
  connectMessage,
  connectError,
  canConnect,
  isBusy,
  userCode,
  models,
  filteredModels,
  modelsState,
  modelsMessage,
  modelQuery,
  modelPanelOpen,
  selectedModel,
  switchProvider,
  saveApiKey,
  removeKey,
  startConnect,
  finishConnect,
  cancelConnect,
  refreshModels,
  pickModel,
  toggleModelPanel,
  closeModelPanel
} = useOrcaProvider()

const root = ref(null)
const modelCombobox = ref(null)
const modelTrigger = ref(null)
const panelOpen = ref(false)

const statusClass = computed(() => (status.value.configured ? 'ok' : 'muted'))

const statusText = computed(() =>
  status.value.configured ? t('orcarouter.keyConfigured') : t('orcarouter.keyNotConfigured')
)

function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (!panelOpen.value) closeModelPanel()
}

function closePanel() {
  panelOpen.value = false
  closeModelPanel()
}

function onProviderChange(event) {
  switchProvider(event.target.value)
}

function formatContext(value) {
  return value >= 1000 ? `${Math.round(value / 1000)}k` : String(value)
}

function onDocumentPointerDown(event) {
  const node = root.value
  if (!node || node.contains(event.target)) return
  closePanel()
}

function onKeydown(event) {
  if (event.key !== 'Escape') return
  if (modelPanelOpen.value) closeModelPanel()
  else if (panelOpen.value) closePanel()
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.provider-settings {
  position: relative;
  display: inline-block;
  font-size: 13px;
  color: #000;
}
.ps-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid #444;
  border-radius: 4px;
  background: transparent;
  color: #fff;
  cursor: pointer;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
}
.ps-trigger.is-open { border-color: #ff4500; }
.ps-trigger-value { color: #aaa; }
.ps-trigger .ps-status { gap: 6px; }
.ps-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.ps-status .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.ps-status.ok .dot { background: #22c55e; }
.ps-status.muted .dot { background: #999; }

/* The popover is right-aligned to its trigger and opaque so it stays readable
   above the marketing page behind it. */
.ps-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 80;
  width: 460px;
  max-height: calc(100vh - 96px);
  overflow-y: auto;
  border: 1px solid #d0d0d0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
  text-align: left;
}
.ps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #f0f0f0;
}
.ps-title {
  font-weight: 700;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  letter-spacing: 0.3px;
}
.ps-body { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
.ps-row { display: flex; flex-direction: column; gap: 6px; }
.ps-label { font-weight: 600; font-size: 12px; }
.ps-inline { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.ps-input {
  flex: 1;
  min-width: 180px;
  padding: 6px 10px;
  border: 1px solid #d0d0d0;
  border-radius: 4px;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
}
.ps-select {
  padding: 6px 10px;
  border: 1px solid #d0d0d0;
  border-radius: 4px;
  font-size: 12px;
  min-width: 220px;
  background: #fff;
}
.ps-btn {
  padding: 6px 12px;
  border: 1px solid #000;
  background: #000;
  color: #fff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.ps-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.ps-btn-danger { background: #fff; color: #c0392b; border-color: #c0392b; }
.ps-btn-orca { background: #ff4500; border-color: #ff4500; }
.ps-hint { color: #777; font-size: 12px; line-height: 1.5; margin: 0; }
.ps-message { font-size: 12px; margin: 0; }
.ps-ok { color: #15803d; }
.ps-error { color: #b91c1c; }
.ps-warn { color: #b45309; }
.ps-muted { color: #999; }
.ps-code-box { display: flex; gap: 8px; }
.ps-origins { display: flex; flex-direction: column; gap: 2px; }
.ps-origins code { font-size: 11px; color: #888; }

/* Model combobox: the option list is attached to its trigger (same right
   edge, full trigger width), scrolls internally and always draws an opaque
   background with a visible border. It stays in the flow so no ancestor
   scroll container can clip it. */
.ps-combobox {
  position: relative;
  flex: 1 1 240px;
  min-width: 0;
}
.ps-model-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
  text-align: left;
}
.ps-model-trigger:disabled { cursor: not-allowed; }
.ps-model-trigger.is-open { border-color: #ff4500; }
.ps-model-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}
.ps-model-caret { flex: none; color: #888; }
.ps-model-panel {
  margin-top: 4px;
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  background: #ffffff;
  border: 1px solid #d0d0d0;
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}
.ps-model-search { min-width: 0; width: 100%; flex: none; }
.ps-model-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.orca-model-option {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
}
.orca-model-option:hover { background: #f2f2f2; }
.orca-model-option[aria-selected='true'] { background: #ffe8e0; }
.ps-model-id { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ps-model-meta { flex: none; color: #888; font-size: 11px; }
.ps-model-none { padding: 6px 8px; color: #999; font-size: 12px; }
</style>
