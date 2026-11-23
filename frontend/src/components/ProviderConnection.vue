<template>
  <div class="provider-control">
    <button class="provider-trigger" type="button" @click="openPanel">
      <span class="provider-dot" :class="{ connected: provider?.chatgpt?.connected }"></span>
      {{ provider?.chatgpt?.connected ? 'ChatGPT conectado' : 'Proveedor de IA' }}
    </button>
    <div v-if="open" class="provider-backdrop" @click.self="closePanel">
      <section class="provider-panel" role="dialog" aria-modal="true" aria-label="Proveedor de IA">
        <button class="provider-close" type="button" aria-label="Cerrar" @click="closePanel">×</button>
        <p class="provider-kicker">MODELO DE MIROFISH</p>
        <h2>Conectar ChatGPT</h2>
        <p>Autoriza esta instalación local con tu cuenta de ChatGPT. Esta conexión no requiere Codex CLI ni una clave de OpenAI API.</p>
        <div class="provider-current"><span>Proveedor actual</span><strong>{{ provider?.chatgpt?.connected ? `ChatGPT · ${provider.chatgpt.model}` : provider?.configured_provider || 'Comprobando…' }}</strong></div>
        <p v-if="provider?.chatgpt?.email">Cuenta: {{ provider.chatgpt.email }}</p>
        <p v-if="error" class="provider-error" role="alert">{{ error }}</p>
        <button class="provider-action" type="button" :disabled="busy" data-oai-siwc-button @click="signIn">{{ busy ? 'Conectando…' : 'Continuar con ChatGPT' }}</button>
        <p v-if="waiting" class="provider-note">Completa la autorización en la ventana del navegador. Esta pantalla se actualizará al regresar.</p>
        <template v-if="provider?.chatgpt?.saved_account">
          <label for="chatgpt-model">Modelo disponible en tu cuenta</label>
          <select id="chatgpt-model" v-model="selectedModel" :disabled="busy" @focus="loadModels">
            <option v-for="item in models" :key="item.slug" :value="item.slug">{{ item.display_name }}</option>
          </select>
          <button class="provider-action" type="button" :disabled="busy || !selectedModel" @click="activate">{{ busy ? 'Comprobando…' : 'Usar ChatGPT en MiroFish' }}</button>
        </template>
        <button v-if="provider?.chatgpt?.connected" class="provider-action secondary" type="button" :disabled="busy" @click="disconnect">Volver a {{ provider.configured_provider }}</button>
        <p class="provider-note">Uso local de código abierto. El consumo comparte los límites de tu plan de ChatGPT. El cambio afecta a las tareas nuevas.</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { activateChatGPT, deactivateChatGPT, getChatGPTModels, getProviderStatus, startChatGPT } from '../api/provider'

const open = ref(false)
const busy = ref(false)
const waiting = ref(false)
const error = ref('')
const provider = ref(null)
const models = ref([])
const selectedModel = ref('')
let pollTimer = null

async function refresh() {
  try {
    provider.value = (await getProviderStatus()).data
    if (provider.value.chatgpt?.saved_account && !models.value.length) await loadModels()
  } catch (requestError) {
    error.value = requestError.message || 'No se pudo consultar el proveedor.'
  }
}
async function loadModels() {
  try {
    models.value = (await getChatGPTModels()).data
    if (!models.value.some(item => item.slug === selectedModel.value)) {
      selectedModel.value = models.value.find(item => item.slug === provider.value?.chatgpt?.model)?.slug || models.value.find(item => item.slug === 'gpt-6-luna')?.slug || models.value[0]?.slug || ''
    }
  } catch (requestError) {
    error.value = requestError.message || 'No se pudieron consultar los modelos.'
  }
}
async function openPanel() { open.value = true; await refresh() }
function closePanel() {
  open.value = false
  waiting.value = false
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}
async function signIn() {
  const popup = window.open('about:blank', '_blank')
  busy.value = true
  error.value = ''
  try {
    const previousAuthorization = provider.value?.chatgpt?.authorized_at
    const result = await startChatGPT(provider.value?.chatgpt?.account_key)
    if (popup) popup.location.href = result.data.url
    else window.location.href = result.data.url
    waiting.value = true
    const startedAt = Date.now()
    pollTimer = setInterval(async () => {
      await refresh()
      if (provider.value?.chatgpt?.authorized_at && provider.value.chatgpt.authorized_at !== previousAuthorization) {
        waiting.value = false
        clearInterval(pollTimer)
        pollTimer = null
      } else if (Date.now() - startedAt > 10 * 60 * 1000 || popup?.closed) {
        waiting.value = false
        error.value = 'La autorización no se completó. Inténtalo nuevamente.'
        clearInterval(pollTimer)
        pollTimer = null
      }
    }, 2000)
  } catch (requestError) {
    if (popup) popup.close()
    error.value = requestError.message || 'No se pudo iniciar la autorización.'
  } finally { busy.value = false }
}
async function activate() {
  busy.value = true
  error.value = ''
  try {
    provider.value = { ...provider.value, chatgpt: (await activateChatGPT(selectedModel.value)).data }
  } catch (requestError) {
    error.value = requestError.message || 'No se pudo activar ChatGPT.'
  } finally { busy.value = false }
}
async function disconnect() {
  busy.value = true
  error.value = ''
  try {
    provider.value = { ...provider.value, chatgpt: (await deactivateChatGPT()).data }
  } catch (requestError) {
    error.value = requestError.message || 'No se pudo restaurar el proveedor.'
  } finally { busy.value = false }
}
onMounted(refresh)
onBeforeUnmount(closePanel)
</script>

<style scoped>
.provider-control { position: fixed; right: 22px; bottom: 22px; z-index: 5000; }
.provider-trigger { display: flex; align-items: center; gap: 9px; padding: 12px 16px; border: 1px solid #111; border-radius: 4px; background: #111; color: white; font-size: 13px; font-weight: 700; cursor: pointer; box-shadow: 4px 4px 0 #f3a75c; }
.provider-dot { width: 8px; height: 8px; border-radius: 50%; background: #9ca3af; }
.provider-dot.connected { background: #6ee7a2; }
.provider-backdrop { position: fixed; inset: 0; display: grid; place-items: center; padding: 18px; background: rgba(0, 0, 0, .45); }
.provider-panel { position: relative; width: min(100%, 450px); padding: 26px; border: 2px solid #111; background: #fff; box-shadow: 8px 8px 0 #111; }
.provider-close { position: absolute; top: 10px; right: 14px; border: 0; background: none; font-size: 26px; cursor: pointer; }
.provider-kicker { margin-bottom: 7px; color: #b25913; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
h2 { margin-bottom: 12px; font-size: 23px; }
p { line-height: 1.55; font-size: 13px; }
.provider-current { display: flex; justify-content: space-between; gap: 12px; margin: 18px 0; padding: 12px; background: #f4f4f1; font-size: 13px; }
.provider-current strong { text-align: right; }
label { display: block; margin: 15px 0 5px; font-size: 12px; font-weight: 700; }
select { width: 100%; padding: 9px; margin-bottom: 10px; }
.provider-action { width: 100%; padding: 12px; margin-top: 8px; border: 1px solid #111; background: #111; color: #fff; font-weight: 700; cursor: pointer; }
.provider-action.secondary { background: #fff; color: #111; }
.provider-action:disabled { opacity: .45; cursor: not-allowed; }
.provider-error { margin: 12px 0; color: #a12620; font-size: 13px; }
.provider-note { margin-top: 14px; color: #555; }
@media (max-width: 600px) { .provider-control { right: 12px; bottom: 12px; } .provider-panel { padding: 22px; } }
</style>
