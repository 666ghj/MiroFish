<template>
  <button type="button" ref="trigger" class="settings-trigger" @click="openSettings">{{ $t('aiSettings.open') }}</button>
  <Teleport to="body">
    <div v-if="open" class="settings-overlay" @keydown.esc="closeSettings" @keydown.tab="trapFocus">
      <section role="dialog" aria-modal="true" aria-labelledby="ai-settings-title" class="settings-dialog">
        <div class="settings-heading">
          <h2 id="ai-settings-title">{{ $t('aiSettings.open') }}</h2>
          <button type="button" :disabled="saving" :aria-label="$t('aiSettings.close')" @click="closeSettings">×</button>
        </div>
        <p>{{ $t('aiSettings.description') }}</p>
        <p v-if="error" role="alert" class="settings-error">{{ error }}</p>
        <p v-if="saved" role="status" class="settings-success">{{ $t('aiSettings.saved') }}</p>
        <form v-if="loaded" @submit.prevent="save">
          <label for="ai-provider">{{ $t('aiSettings.provider') }}</label>
          <select id="ai-provider" v-model="selectedProvider" :disabled="saving" @change="selectProvider">
            <option v-for="provider in aiProviders" :key="provider.id" :value="provider.id">{{ provider.label || $t('aiSettings.customProvider') }}</option>
          </select>
          <label for="llm-base-url">{{ $t('aiSettings.baseUrl') }}</label>
          <input id="llm-base-url" v-model="form.llm_base_url" type="url" required :disabled="saving" @input="selectedProvider = detectProvider(form.llm_base_url)" />
          <label for="llm-model-name">{{ $t('aiSettings.model') }}</label>
          <input id="llm-model-name" v-model="form.llm_model_name" type="text" required :disabled="saving" />
          <label for="llm-api-key">{{ $t('aiSettings.llmKey') }} <span v-if="status.llm_configured">({{ $t('aiSettings.configured') }})</span></label>
          <input id="llm-api-key" v-model="form.llm_api_key" type="password" autocomplete="off" :required="!status.llm_configured || form.llm_base_url !== status.llm_base_url" :disabled="saving" :placeholder="status.llm_configured ? $t('aiSettings.keepKey') : ''" />
          <label for="zep-api-key">{{ $t('aiSettings.zepKey') }} <span v-if="status.zep_configured">({{ $t('aiSettings.configured') }})</span></label>
          <input id="zep-api-key" v-model="form.zep_api_key" type="password" autocomplete="off" :required="!status.zep_configured" :disabled="saving" :placeholder="status.zep_configured ? $t('aiSettings.keepKey') : ''" />
          <p class="settings-hint"><a href="https://app.getzep.com/" target="_blank" rel="noopener noreferrer">{{ $t('aiSettings.getZep') }}</a></p>
          <p class="settings-hint">{{ $t('aiSettings.storage') }}</p>
          <button type="submit" class="save-settings" :disabled="saving">{{ $t(saving ? 'aiSettings.saving' : 'aiSettings.save') }}</button>
        </form>
        <p v-else-if="!error">{{ $t('aiSettings.loading') }}</p>
        <button v-if="error && !loaded" type="button" @click="openSettings">{{ $t('aiSettings.retry') }}</button>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, reactive, ref } from 'vue'
import { getAISettings, saveAISettings } from '../api/settings'
import { aiProviders, detectProvider } from '../config/aiProviders'

const selectedProvider = ref('custom')
const trigger = ref(null)
const open = ref(false)
const loaded = ref(false)
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const status = ref({})
const form = reactive({ llm_base_url: '', llm_model_name: '', llm_api_key: '', zep_api_key: '' })
let setupToken = ''
let requestVersion = 0

async function openSettings() {
  const version = ++requestVersion
  open.value = true
  loaded.value = false
  saved.value = false
  error.value = ''
  form.llm_api_key = ''
  form.zep_api_key = ''
  try {
    const response = await getAISettings()
    if (!open.value || version !== requestVersion) return
    status.value = response.data
    setupToken = response.data.setup_token
    form.llm_base_url = response.data.llm_base_url
    form.llm_model_name = response.data.llm_model_name
    selectedProvider.value = detectProvider(form.llm_base_url)
    loaded.value = true
    await nextTick()
    document.getElementById('llm-base-url')?.focus()
  } catch (err) {
    if (open.value && version === requestVersion) error.value = err.message
  }
}

function selectProvider() {
  const provider = aiProviders.find(item => item.id === selectedProvider.value)
  if (!provider?.baseUrl) return
  form.llm_base_url = provider.baseUrl
  form.llm_model_name = provider.model
  form.llm_api_key = ''
}

function closeSettings() {
  if (saving.value) return
  requestVersion++
  form.llm_api_key = ''
  form.zep_api_key = ''
  setupToken = ''
  open.value = false
  trigger.value?.focus()
}

function trapFocus(event) {
  const controls = Array.from(event.currentTarget.querySelectorAll('button, input, select, a[href]')).filter(element => !element.disabled)
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

async function save() {
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const response = await saveAISettings({ ...form }, setupToken)
    status.value = response.data
    form.llm_api_key = ''
    form.zep_api_key = ''
    saved.value = true
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.settings-trigger { padding: 6px 12px; border: 1px solid #ccc; background: white; cursor: pointer; font: inherit; font-size: 12px; }
.settings-overlay { position: fixed; inset: 0; z-index: 1000; background: #0008; display: flex; align-items: center; justify-content: center; padding: 20px; }
.settings-dialog { box-sizing: border-box; background: white; color: #222; padding: 24px; border-radius: 8px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; font: 14px/1.5 system-ui, sans-serif; }
.settings-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { margin: 0; font-size: 22px; }
.settings-heading button { border: 0; background: white; font-size: 24px; cursor: pointer; }
form { display: grid; gap: 8px; }
label { margin-top: 6px; }
label span, .settings-hint { color: #666; font-size: 12px; }
input, select { box-sizing: border-box; width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; font: inherit; }
.save-settings { padding: 12px; background: #222; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 8px; }
button:disabled { opacity: .5; cursor: default; }
.settings-error { color: #b42318; }
.settings-success { color: #126b35; }
a { color: #b33300; }
</style>
