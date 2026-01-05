<template>
  <div class="settings-view">
    <header class="header">
      <div class="brand" @click="router.push('/')">MIROFISH</div>
      <div class="actions">
        <button class="btn" @click="refresh" :disabled="loading">{{ loading ? 'Loading…' : 'Refresh' }}</button>
        <button class="btn" @click="router.push('/history')">History</button>
      </div>
    </header>

    <main class="content">
      <div v-if="error" class="error">{{ error }}</div>

      <section class="panel">
        <div class="panel-title">LLM Settings</div>
        <div class="panel-sub">
          <span v-if="config.source_path" class="mono">source: {{ config.source_path }}</span>
          <span v-if="config.updated_at" class="mono">updated: {{ config.updated_at }}</span>
        </div>

        <div class="form">
          <div class="field">
            <div class="label">Base URL</div>
            <input v-model="form.base_url" class="input mono" placeholder="https://proxy.example.com:3333 (auto /v1)" />
          </div>

          <div class="field">
            <div class="label">API Key</div>
            <div class="flex-row">
              <input
                v-model="form.api_key"
                class="input mono"
                type="password"
                placeholder="Leave blank to keep current"
              />
              <button class="btn danger" @click="clearApiKey" :disabled="loading">Clear</button>
            </div>
            <div class="hint" v-if="config.api_key_set">
              Current: ****{{ config.api_key_last4 }}
            </div>
          </div>

          <div class="field">
            <div class="label">Selected Models (max 10, ordered)</div>
            <div class="selected">
              <div v-if="selectedModels.length === 0" class="hint">No models selected. Fetch models or type one manually.</div>
              <div v-for="(m, idx) in selectedModels" :key="m" class="selected-row">
                <div class="mono truncate">{{ m }}</div>
                <div class="right">
                  <button class="link" @click="moveUp(idx)" :disabled="idx === 0">Up</button>
                  <button class="link" @click="moveDown(idx)" :disabled="idx === selectedModels.length - 1">Down</button>
                  <button class="link danger" @click="removeSelected(m)">Remove</button>
                </div>
              </div>
            </div>
          </div>

          <div class="field">
            <div class="label">Add Model (manual)</div>
            <div class="flex-row">
              <input v-model="manualModel" class="input mono" placeholder="e.g. gpt-4o-mini" />
              <button class="btn" @click="addManualModel" :disabled="loading || !manualModel.trim()">Add</button>
            </div>
          </div>

          <div class="flex-row actions-row">
            <button class="btn primary" @click="save" :disabled="loading">Save</button>
            <button class="btn" @click="fetchModels" :disabled="loading">Fetch Models</button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">Available Models</div>
        <div class="panel-sub">{{ availableModels.length }} items</div>

        <div class="field">
          <input v-model="modelFilter" class="input mono" placeholder="Filter…" />
        </div>

        <div class="table">
          <div class="row row-2 head">
            <div>Use</div>
            <div>Model</div>
          </div>
          <div v-for="m in filteredModels" :key="m" class="row row-2">
            <div>
              <input
                type="checkbox"
                :checked="selectedModels.includes(m)"
                @change="toggleModel(m)"
                :disabled="!selectedModels.includes(m) && selectedModels.length >= 10"
              />
            </div>
            <div class="mono truncate">{{ m }}</div>
          </div>
          <div v-if="availableModels.length === 0" class="empty">No models loaded. Click “Fetch Models”.</div>
        </div>
      </section>

      <!-- Model Routing Section -->
      <section class="panel">
        <div class="panel-title">模型路由配置</div>
        <div class="panel-sub">
          <span>为不同任务阶段配置最优模型</span>
        </div>

        <!-- Preset Buttons -->
        <div class="preset-buttons">
          <button
            v-for="(preset, key) in presets"
            :key="key"
            class="btn preset-btn"
            :class="{ active: isPresetActive(key) }"
            @click="applyPreset(key)"
            :disabled="loading"
          >
            {{ preset.label }}
            <span class="preset-desc">{{ preset.description }}</span>
          </button>
        </div>

        <!-- Stage Configuration -->
        <div class="routing-grid">
          <div v-for="(stage, stageId) in stages" :key="stageId" class="stage-card">
            <div class="stage-header">
              <div class="stage-label">{{ stage.label }}</div>
              <div class="stage-tip">{{ stage.tip }}</div>
            </div>
            <div class="stage-desc">{{ stage.description }}</div>

            <div class="stage-select">
              <select
                v-model="routingForm[stageId]"
                class="input"
                @change="checkWarning(stageId)"
              >
                <option value="">（使用默认模型）</option>
                <option
                  v-for="m in allModelsForRouting"
                  :key="m"
                  :value="m"
                  :class="{ recommended: isRecommended(stageId, m) }"
                >
                  {{ m }}{{ isRecommended(stageId, m) ? ' ✅' : '' }}
                </option>
              </select>
            </div>

            <!-- Warning -->
            <div v-if="routingWarnings[stageId]" class="stage-warning" :class="routingWarnings[stageId].level">
              ⚠️ {{ routingWarnings[stageId].message }}
            </div>
          </div>
        </div>

        <div class="flex-row actions-row">
          <button class="btn primary" @click="saveRouting" :disabled="loading">保存路由配置</button>
          <button class="btn" @click="resetRouting" :disabled="loading">重置</button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">Usage (aggregated)</div>
        <div class="panel-sub">
          <span class="mono">requests: {{ usage.total_requests || 0 }}</span>
          <span class="mono">errors: {{ usage.total_errors || 0 }}</span>
        </div>

        <div class="tables-grid">
          <div class="table">
            <div class="row row-4 head">
              <div>Model</div>
              <div class="right">Req</div>
              <div class="right">Err</div>
              <div class="right">Total</div>
            </div>
            <div v-for="(v, k) in usage.totals_by_model || {}" :key="k" class="row row-4">
              <div class="mono truncate">{{ k }}</div>
              <div class="right mono">{{ v.requests }}</div>
              <div class="right mono">{{ v.errors }}</div>
              <div class="right mono">{{ v.total_tokens }}</div>
            </div>
          </div>

          <div class="table">
            <div class="row row-4 head">
              <div>Stage</div>
              <div class="right">Req</div>
              <div class="right">Err</div>
              <div class="right">Total</div>
            </div>
            <div v-for="(v, k) in usage.totals_by_stage || {}" :key="k" class="row row-4">
              <div class="mono truncate">{{ k }}</div>
              <div class="right mono">{{ v.requests }}</div>
              <div class="right mono">{{ v.errors }}</div>
              <div class="right mono">{{ v.total_tokens }}</div>
            </div>
          </div>
        </div>

        <div v-if="usage.paths && usage.paths.length" class="hint">
          logs:
          <span class="mono">{{ usage.paths.length }}</span>
          files
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getLlmConfig, getLlmUsage, listLlmModels, saveLlmConfig, getLlmStages, getLlmPresets, setLlmRouting } from '../api/llm'

const router = useRouter()

const loading = ref(false)
const error = ref('')

const config = ref({
  base_url: '',
  models: [],
  model_routing: {},
  api_key_set: false,
  api_key_last4: '',
  updated_at: '',
  source_path: ''
})

const usage = ref({})

const form = ref({
  base_url: '',
  api_key: ''
})
const manualModel = ref('')
const modelFilter = ref('')

// Model Routing
const stages = ref({})
const presets = ref({})
const routingForm = reactive({})
const routingWarnings = reactive({})

const selectedModels = computed(() => config.value.models || [])

const availableModels = ref([])
const filteredModels = computed(() => {
  const q = modelFilter.value.trim().toLowerCase()
  if (!q) return availableModels.value
  return availableModels.value.filter((m) => String(m).toLowerCase().includes(q))
})

// 合并 availableModels 和 selectedModels 用于路由选择
const allModelsForRouting = computed(() => {
  const set = new Set([...availableModels.value, ...selectedModels.value])
  return Array.from(set).sort()
})

// 检查模型是否为该 stage 的推荐模型
const isRecommended = (stageId, model) => {
  const stage = stages.value[stageId]
  if (!stage || !stage.recommended) return false
  return stage.recommended.includes(model)
}

// 检查是否应该显示警告
const checkWarning = (stageId) => {
  const model = routingForm[stageId]
  if (!model) {
    delete routingWarnings[stageId]
    return
  }

  const stage = stages.value[stageId]
  if (!stage || !stage.warnings) {
    delete routingWarnings[stageId]
    return
  }

  for (const warning of stage.warnings) {
    try {
      const regex = new RegExp(warning.pattern)
      if (regex.test(model)) {
        routingWarnings[stageId] = { message: warning.message, level: warning.level }
        return
      }
    } catch (e) {
      // Invalid regex, skip
    }
  }
  delete routingWarnings[stageId]
}

// 检查当前配置是否匹配某个预设
const isPresetActive = (presetKey) => {
  const preset = presets.value[presetKey]
  if (!preset || !preset.routing) return false
  for (const [stage, model] of Object.entries(preset.routing)) {
    if (routingForm[stage] !== model) return false
  }
  return true
}

// 应用预设
const applyPreset = (presetKey) => {
  const preset = presets.value[presetKey]
  if (!preset || !preset.routing) return
  for (const [stage, model] of Object.entries(preset.routing)) {
    routingForm[stage] = model
    checkWarning(stage)
  }
}

// 重置路由配置到当前已保存的状态
const resetRouting = () => {
  const current = config.value.model_routing || {}
  for (const stageId of Object.keys(stages.value)) {
    routingForm[stageId] = current[stageId] || ''
    delete routingWarnings[stageId]
  }
}

// 保存路由配置
const saveRouting = async () => {
  loading.value = true
  error.value = ''
  try {
    const routing = {}
    for (const [stage, model] of Object.entries(routingForm)) {
      if (model) routing[stage] = model
    }
    const res = await setLlmRouting({ routing })
    config.value = res.data || config.value
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const refresh = async () => {
  loading.value = true
  error.value = ''
  try {
    const cRes = await getLlmConfig()
    config.value = cRes.data || {}
    form.value.base_url = config.value.base_url || ''
    form.value.api_key = ''

    const uRes = await getLlmUsage(200000)
    usage.value = uRes.data || {}

    // 加载 stages 和 presets
    try {
      const stagesRes = await getLlmStages()
      stages.value = (stagesRes.data && stagesRes.data.stages) || {}
    } catch (e) {
      console.warn('Failed to load stages:', e)
    }

    try {
      const presetsRes = await getLlmPresets()
      presets.value = (presetsRes.data && presetsRes.data.presets) || {}
    } catch (e) {
      console.warn('Failed to load presets:', e)
    }

    // 初始化路由表单
    resetRouting()
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const save = async () => {
  loading.value = true
  error.value = ''
  try {
    const payload = {
      base_url: form.value.base_url,
      models: selectedModels.value
    }

    const key = form.value.api_key.trim()
    if (key) payload.api_key = key

    const res = await saveLlmConfig(payload)
    config.value = res.data || config.value
    form.value.api_key = ''
    await refresh()
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const clearApiKey = async () => {
  const confirmed = window.confirm('Clear saved API key? (You can still use .env env var if configured)')
  if (!confirmed) return
  loading.value = true
  error.value = ''
  try {
    const res = await saveLlmConfig({ clear_api_key: true })
    config.value = res.data || config.value
    form.value.api_key = ''
    await refresh()
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const fetchModels = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await listLlmModels()
    availableModels.value = (res.data && res.data.models) || []
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

const toggleModel = async (model) => {
  const m = String(model)
  const current = [...selectedModels.value]
  const idx = current.indexOf(m)
  if (idx >= 0) current.splice(idx, 1)
  else {
    if (current.length >= 10) return
    current.push(m)
  }
  config.value = { ...config.value, models: current }
}

const addManualModel = async () => {
  const m = manualModel.value.trim()
  if (!m) return
  if (selectedModels.value.includes(m)) return
  if (selectedModels.value.length >= 10) return
  config.value = { ...config.value, models: [...selectedModels.value, m] }
  manualModel.value = ''
}

const removeSelected = (m) => {
  config.value = { ...config.value, models: selectedModels.value.filter((x) => x !== m) }
}

const moveUp = (idx) => {
  if (idx <= 0) return
  const next = [...selectedModels.value]
  const tmp = next[idx - 1]
  next[idx - 1] = next[idx]
  next[idx] = tmp
  config.value = { ...config.value, models: next }
}

const moveDown = (idx) => {
  const next = [...selectedModels.value]
  if (idx < 0 || idx >= next.length - 1) return
  const tmp = next[idx + 1]
  next[idx + 1] = next[idx]
  next[idx] = tmp
  config.value = { ...config.value, models: next }
}

onMounted(async () => {
  await refresh()
})
</script>

<style scoped>
.settings-view {
  min-height: 100vh;
  background: #ffffff;
  color: #000;
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid #000;
}

.brand {
  font-weight: 800;
  letter-spacing: 0.08em;
  cursor: pointer;
}

.actions {
  display: flex;
  gap: 10px;
}

.btn {
  border: 1px solid #000;
  background: #fff;
  padding: 8px 12px;
  cursor: pointer;
}

.btn.primary {
  background: #000;
  color: #fff;
}

.btn.danger {
  border-color: #c00;
  color: #c00;
}

.content {
  padding: 18px 24px 48px;
  display: grid;
  gap: 16px;
}

.panel {
  border: 1px solid #000;
  padding: 14px;
}

.panel-title {
  font-weight: 700;
  margin-bottom: 6px;
}

.panel-sub {
  display: flex;
  gap: 12px;
  color: #333;
  font-size: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.error {
  border: 1px solid #c00;
  color: #c00;
  padding: 10px;
  white-space: pre-wrap;
}

.form {
  display: grid;
  gap: 12px;
}

.field .label {
  font-size: 12px;
  margin-bottom: 6px;
  color: #333;
}

.flex-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.actions-row {
  justify-content: flex-end;
}

.input {
  width: 100%;
  border: 1px solid #000;
  padding: 8px 10px;
}

.mono {
  font-family: inherit;
}

.hint {
  font-size: 12px;
  color: #555;
  margin-top: 6px;
}

.table {
  border-top: 1px solid #000;
}

.row.head {
  font-weight: 700;
  border-bottom: 1px solid #000;
  padding: 8px 0;
  display: grid;
  gap: 10px;
}

.row {
  padding: 8px 0;
  display: grid;
  gap: 10px;
  border-bottom: 1px solid #eee;
}

.row.row-2 {
  grid-template-columns: 80px 1fr;
}

.row.row-4 {
  grid-template-columns: 1fr 70px 70px 90px;
}

.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.right {
  text-align: right;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.link {
  background: transparent;
  border: none;
  cursor: pointer;
  text-decoration: underline;
  padding: 0;
}

.link.danger {
  color: #c00;
}

.empty {
  padding: 10px 0;
  color: #666;
}

.selected {
  border: 1px solid #eee;
  padding: 8px;
}

.selected-row {
  display: grid;
  grid-template-columns: 1fr 180px;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid #f1f1f1;
}

.tables-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* Model Routing Styles */
.preset-buttons {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.preset-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 10px 14px;
  min-width: 140px;
}

.preset-btn.active {
  background: #000;
  color: #fff;
}

.preset-desc {
  font-size: 11px;
  color: #666;
  margin-top: 4px;
}

.preset-btn.active .preset-desc {
  color: #ccc;
}

.routing-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.stage-card {
  border: 1px solid #ddd;
  padding: 12px;
  background: #fafafa;
}

.stage-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 6px;
}

.stage-label {
  font-weight: 600;
  font-size: 14px;
}

.stage-tip {
  font-size: 11px;
  color: #888;
  max-width: 60%;
  text-align: right;
}

.stage-desc {
  font-size: 12px;
  color: #555;
  margin-bottom: 10px;
  line-height: 1.4;
}

.stage-select select {
  width: 100%;
  padding: 8px;
  border: 1px solid #000;
  background: #fff;
  font-family: inherit;
}

.stage-select option.recommended {
  font-weight: 600;
}

.stage-warning {
  margin-top: 8px;
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 2px;
}

.stage-warning.warning {
  background: #fff3cd;
  color: #856404;
  border: 1px solid #ffc107;
}

.stage-warning.error {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

@media (max-width: 900px) {
  .tables-grid {
    grid-template-columns: 1fr;
  }

  .routing-grid {
    grid-template-columns: 1fr;
  }
}
</style>
