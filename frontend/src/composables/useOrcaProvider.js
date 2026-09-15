import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getOrcaStatus,
  saveOrcaKey,
  clearOrcaKey,
  startOrcaConnect,
  exchangeOrcaCode,
  cancelOrcaConnect,
  getOrcaModels,
  setOrcaModel,
  setOrcaProvider,
  markOrcaReauth
} from '../api/orcarouter'

export function useOrcaProvider() {
  const { t } = useI18n()

  // ---- state -----------------------------------------------------------
  const status = ref({ configured: false, provider: 'default', source: null, key_preview: null })
  // ``provider`` is the *active* provider persisted on the server; ``selection``
  // is what the settings panel currently shows. They differ while the user has
  // opened OrcaRouter but has not stored a credential yet: both authentication
  // choices must be reachable before a key exists, otherwise the user could
  // never enter one.
  const provider = ref('default')
  const selection = ref('default')
  const apiKeyInput = ref('')
  const apiKeySaving = ref(false)
  const apiKeyMessage = ref('')

  const connectState = ref('idle') // idle | waiting_code | connecting | exchanging | done | denied | error
  const connectMessage = ref('')
  const connectError = ref('')
  const attemptId = ref('')
  const userCode = ref('')
  const authorizeUrl = ref('')

  const models = ref([])
  const modelsState = ref('idle') // idle | loading | ok | seed | empty | error
  const modelsMessage = ref('')
  const selectedModel = ref('')
  const catalogSource = ref(null) // live | seed
  const modelQuery = ref('')
  const modelPanelOpen = ref(false)

  // Monotonic generation guard for async login state. Every async response
  // must confirm it still belongs to the current generation before mutating
  // credentials or UI. A late URL or success from provider A must never
  // appear under provider B.
  let generation = 0

  // ---- derived ---------------------------------------------------------
  const isOrca = computed(() => selection.value === 'orcarouter')
  const canConnect = computed(() => connectState.value === 'idle' || connectState.value === 'done')
  const isBusy = computed(
    () => connectState.value === 'connecting' || connectState.value === 'exchanging' || apiKeySaving.value
  )
  // The model selector is bound to the capability-filtered list the server
  // returned for the current entry point; the search box only narrows that
  // list, it never accepts a free-form model id.
  const filteredModels = computed(() => {
    const query = modelQuery.value.trim().toLowerCase()
    if (!query) return models.value
    return models.value.filter((model) => model.id.toLowerCase().includes(query))
  })
  const selectedModelMeta = computed(
    () => models.value.find((model) => model.id === selectedModel.value) || null
  )

  // ---- provider switch -------------------------------------------------
  async function switchProvider(next) {
    if (next === selection.value) return
    connectError.value = ''
    // Show the OrcaRouter panel (both auth choices) even before a credential
    // exists. The provider is only activated on the server once one is stored.
    selection.value = next
    if (next === 'orcarouter' && !status.value.configured) {
      apiKeyMessage.value = t('orcarouter.apiKeyHint')
      return
    }
    await activate(next)
  }

  async function activate(next) {
    invalidateLogin('switching provider')
    try {
      const res = await setOrcaProvider(next)
      provider.value = res.provider
      status.value.provider = res.provider
      if (res.provider === 'orcarouter') await refreshModels()
    } catch (err) {
      connectError.value = err.message || t('common.error')
    }
  }

  // ---- API-key choice --------------------------------------------------
  async function saveApiKey() {
    const key = apiKeyInput.value.trim()
    if (!key) {
      apiKeyMessage.value = t('orcarouter.apiKeyHint')
      return
    }
    apiKeySaving.value = true
    apiKeyMessage.value = ''
    try {
      const res = await saveOrcaKey(key)
      status.value = res.status
      apiKeyInput.value = ''
      apiKeyMessage.value = t('orcarouter.apiKeySaved')
      if (provider.value !== 'orcarouter') await activate('orcarouter')
      else await refreshModels()
    } catch (err) {
      apiKeyMessage.value = err.message || t('orcarouter.apiKeyError')
    } finally {
      apiKeySaving.value = false
    }
  }

  async function removeKey() {
    invalidateLogin('removing key')
    try {
      const res = await clearOrcaKey()
      status.value = res.status
      models.value = []
      modelsState.value = 'idle'
      catalogSource.value = null
      selectedModel.value = ''
      closeModelPanel()
      if (provider.value === 'orcarouter') await activate('default')
    } catch (err) {
      connectError.value = err.message || t('common.error')
    }
  }

  // ---- PKCE choice (Flow B, out-of-band) ------------------------------
  async function startConnect() {
    if (!canConnect.value) return
    const myGen = ++generation
    connectState.value = 'connecting'
    connectMessage.value = t('orcarouter.connecting')
    connectError.value = ''
    try {
      const res = await startOrcaConnect()
      if (myGen !== generation) return // stale response; a newer login owns the UI now
      attemptId.value = res.attempt_id
      authorizeUrl.value = res.authorize_url
      connectState.value = 'waiting_code'
      connectMessage.value = t('orcarouter.enterCode')
      // Open the consent screen in a new tab.
      window.open(res.authorize_url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      if (myGen === generation) {
        connectState.value = 'error'
        connectError.value = err.message || t('orcarouter.exchangeFailed')
      }
    }
  }

  async function finishConnect() {
    const code = userCode.value.trim()
    if (!code || !attemptId.value) return
    const myGen = ++generation
    connectState.value = 'exchanging'
    connectError.value = ''
    try {
      const res = await exchangeOrcaCode(attemptId.value, code)
      if (myGen !== generation) return
      status.value = res.status
      connectState.value = 'done'
      connectMessage.value = t('orcarouter.success')
      userCode.value = ''
      attemptId.value = ''
      authorizeUrl.value = ''
      if (provider.value !== 'orcarouter') await activate('orcarouter')
      else await refreshModels()
    } catch (err) {
      if (myGen !== generation) return
      connectState.value = 'error'
      connectError.value = err.message || t('orcarouter.exchangeFailed')
    }
  }

  function cancelConnect() {
    const id = attemptId.value
    invalidateLogin('explicit cancel')
    if (id) {
      cancelOrcaConnect(id).catch(() => {})
    }
    connectState.value = 'idle'
    connectMessage.value = ''
    connectError.value = ''
    userCode.value = ''
    attemptId.value = ''
    authorizeUrl.value = ''
  }

  function invalidateLogin(reason) {
    generation += 1
    connectState.value = 'idle'
    connectMessage.value = ''
    connectError.value = ''
    if (reason === 'pagehide') {
      // Back-forward cache: issue server cancellation with keepalive because
      // the invalidated request's guarded finally may never run after restore.
      if (attemptId.value) {
        cancelOrcaConnect(attemptId.value).catch(() => {})
      }
    }
  }

  // ---- model discovery -------------------------------------------------
  async function refreshModels() {
    const myGen = generation
    modelsState.value = 'loading'
    modelsMessage.value = ''
    try {
      const res = await getOrcaModels('chat')
      if (myGen !== generation) return
      models.value = res.models || []
      catalogSource.value = res.source || null
      if (res.source === 'seed') {
        modelsState.value = 'seed'
        modelsMessage.value = res.message || t('orcarouter.modelSeed')
      } else if (models.value.length === 0) {
        modelsState.value = 'empty'
        modelsMessage.value = t('orcarouter.modelEmptyText')
      } else {
        modelsState.value = 'ok'
      }
      revalidateSelectedModel()
      if (modelsState.value !== 'ok') closeModelPanel()
    } catch (err) {
      if (myGen !== generation) return
      modelsState.value = 'error'
      modelsMessage.value = err.message || t('orcarouter.modelError')
      closeModelPanel()
    }
  }

  function revalidateSelectedModel() {
    const current = selectedModel.value
    if (!current) return
    const stillValid = models.value.some((m) => m.id === current)
    if (!stillValid) {
      selectedModel.value = ''
      modelsMessage.value = t('orcarouter.modelNotCompatible')
    }
  }

  async function pickModel(modelId) {
    // Only ids that came back from the filtered catalog can be selected.
    if (!models.value.some((m) => m.id === modelId)) return
    selectedModel.value = modelId
    closeModelPanel()
    try {
      await setOrcaModel(modelId)
    } catch (err) {
      modelsMessage.value = err.message || t('common.error')
    }
  }

  function openModelPanel() {
    if (modelsState.value === 'loading' || models.value.length === 0) return
    modelQuery.value = ''
    modelPanelOpen.value = true
  }

  function closeModelPanel() {
    modelPanelOpen.value = false
    modelQuery.value = ''
  }

  function toggleModelPanel() {
    if (modelPanelOpen.value) closeModelPanel()
    else openModelPanel()
  }

  // ---- reauth ----------------------------------------------------------
  async function handleRelay401() {
    try {
      const res = await markOrcaReauth()
      if (res && res.needs_reauth) {
        connectState.value = 'error'
        connectError.value = res.hint || t('orcarouter.reauthRequired')
      }
    } catch (err) {
      connectError.value = err.message || t('orcarouter.reauthRequired')
    }
  }

  // ---- lifecycle -------------------------------------------------------
  async function load() {
    const myGen = ++generation
    try {
      const res = await getOrcaStatus()
      if (myGen !== generation) return
      status.value = res
      provider.value = res.provider || 'default'
      selection.value = provider.value
      if (provider.value === 'orcarouter' && status.value.configured) {
        await refreshModels()
      }
    } catch (err) {
      if (myGen === generation) connectError.value = err.message || t('common.error')
    }
  }

  function onPageHide() {
    invalidateLogin('pagehide')
    closeModelPanel()
  }

  onMounted(() => {
    window.addEventListener('pagehide', onPageHide)
    load()
  })

  onBeforeUnmount(() => {
    window.removeEventListener('pagehide', onPageHide)
    invalidateLogin('unmount')
  })

  watch(isOrca, (now, prev) => {
    if (now !== prev && now) refreshModels()
  })

  return {
    status,
    provider,
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
    authorizeUrl,
    models,
    filteredModels,
    modelsState,
    modelsMessage,
    catalogSource,
    modelQuery,
    modelPanelOpen,
    selectedModel,
    selectedModelMeta,
    switchProvider,
    saveApiKey,
    removeKey,
    startConnect,
    finishConnect,
    cancelConnect,
    refreshModels,
    pickModel,
    openModelPanel,
    closeModelPanel,
    toggleModelPanel,
    handleRelay401
  }
}
