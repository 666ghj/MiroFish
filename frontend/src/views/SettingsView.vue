<template>
  <div class="settings-page">
    <div class="settings-card">
      <header class="head">
        <h1>配置 MiroFish</h1>
        <p class="sub">
          填写下方两项 Key 后即可开始使用。配置会保存在本机
          <code v-if="envFile">{{ envFile }}</code>
          ，重启程序也不会丢失。
        </p>
      </header>

      <div v-if="banner" :class="['banner', banner.type]">{{ banner.text }}</div>

      <section class="block">
        <h2>大模型（必填）</h2>
        <p class="hint">
          支持任意 OpenAI 兼容接口。常用组合：
          <span class="preset" @click="applyPreset('dashscope')">阿里百炼</span>
          <span class="preset" @click="applyPreset('openai')">OpenAI</span>
          <span class="preset" @click="applyPreset('deepseek')">DeepSeek</span>
        </p>
        <label>
          <span>API Key</span>
          <input v-model="form.LLM_API_KEY" type="password" placeholder="sk-..." autocomplete="off" />
        </label>
        <label>
          <span>接口地址 Base URL</span>
          <input v-model="form.LLM_BASE_URL" type="text" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
        </label>
        <label>
          <span>模型名称</span>
          <input v-model="form.LLM_MODEL_NAME" type="text" placeholder="qwen-plus" />
        </label>
      </section>

      <section class="block">
        <h2>Zep 记忆图谱（必填）</h2>
        <p class="hint">
          用于构建智能体记忆，<a href="https://app.getzep.com/" target="_blank" rel="noopener">app.getzep.com</a>
          免费额度即可满足常规使用。
        </p>
        <label>
          <span>ZEP_API_KEY</span>
          <input v-model="form.ZEP_API_KEY" type="password" placeholder="z_..." autocomplete="off" />
        </label>
      </section>

      <section class="block">
        <h2>高级（可选）</h2>
        <label>
          <span>默认模拟轮数</span>
          <input v-model="form.OASIS_DEFAULT_MAX_ROUNDS" type="number" min="1" max="200" placeholder="10" />
        </label>
      </section>

      <div class="actions">
        <button class="btn primary" :disabled="saving" @click="save">
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
        <button class="btn" :disabled="testing" @click="test">
          {{ testing ? '测试中...' : '测试连通性' }}
        </button>
        <button class="btn ghost" @click="goHome">返回首页</button>
      </div>

      <div v-if="update" class="update">
        发现新版本 <strong>{{ update.latest }}</strong>（当前 {{ update.current }}）
        <a v-if="update.url" :href="update.url" target="_blank" rel="noopener">前往下载</a>
      </div>

      <div v-if="testResults" class="results">
        <div v-for="(res, key) in testResults" :key="key" :class="['result', res.ok ? 'ok' : 'fail']">
          <strong>{{ key === 'llm' ? '大模型' : 'Zep' }}</strong>
          <span>{{ res.detail }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import service from '../api'

const router = useRouter()
const form = reactive({
  LLM_API_KEY: '',
  LLM_BASE_URL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  LLM_MODEL_NAME: 'qwen-plus',
  ZEP_API_KEY: '',
  OASIS_DEFAULT_MAX_ROUNDS: ''
})
const envFile = ref('')
const banner = ref(null)
const saving = ref(false)
const testing = ref(false)
const testResults = ref(null)
const update = ref(null)

const PRESETS = {
  dashscope: {
    LLM_BASE_URL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    LLM_MODEL_NAME: 'qwen-plus'
  },
  openai: {
    LLM_BASE_URL: 'https://api.openai.com/v1',
    LLM_MODEL_NAME: 'gpt-4o-mini'
  },
  deepseek: {
    LLM_BASE_URL: 'https://api.deepseek.com/v1',
    LLM_MODEL_NAME: 'deepseek-chat'
  }
}

function applyPreset(name) {
  Object.assign(form, PRESETS[name])
}

function flash(type, text) {
  banner.value = { type, text }
  setTimeout(() => {
    if (banner.value && banner.value.text === text) banner.value = null
  }, 6000)
}

async function load() {
  try {
    const res = await service.get('/api/desktop/config')
    const data = res.data || {}
    envFile.value = data.env_file || ''
    for (const key of Object.keys(form)) {
      const item = data[key]
      if (!item) continue
      // 已脱敏的 Key 不回填，避免误写入
      form[key] = item.value && item.value.includes('...') ? '' : item.value
    }
  } catch (err) {
    flash('error', '无法读取本地配置：' + (err.message || err))
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {}
    for (const [key, value] of Object.entries(form)) {
      if (value !== '' && value !== null && value !== undefined) payload[key] = value
    }
    await service.post('/api/desktop/config', payload)
    flash('ok', '已保存。新配置立即生效，重新开始一次分析即可使用。')
    await load()
  } catch (err) {
    flash('error', '保存失败：' + (err.message || err))
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  testResults.value = null
  try {
    const res = await service.post('/api/desktop/config/test', { ...form })
    testResults.value = res.data || {}
  } catch (err) {
    flash('error', '测试失败：' + (err.message || err))
  } finally {
    testing.value = false
  }
}

function goHome() {
  router.push('/')
}

async function checkUpdate() {
  try {
    const res = await service.get('/api/desktop/update-check')
    const data = res.data || {}
    if (data.update_available) update.value = data
  } catch (err) {
    // 离线或私有仓库时静默忽略
  }
}

onMounted(() => {
  load()
  checkUpdate()
})
</script>

<style scoped>
.settings-page {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  padding: 48px 20px 80px;
  background: radial-gradient(circle at 20% 0%, #16233d 0%, #0a0f1a 55%);
  box-sizing: border-box;
}

.settings-card {
  width: min(720px, 100%);
  background: rgba(17, 26, 43, 0.92);
  border: 1px solid rgba(120, 160, 220, 0.18);
  border-radius: 18px;
  padding: 32px 34px 38px;
  color: #e8eef8;
  box-shadow: 0 30px 70px rgba(0, 0, 0, 0.45);
}

.head h1 {
  margin: 0 0 8px;
  font-size: 26px;
  letter-spacing: 0.5px;
}

.sub {
  margin: 0 0 24px;
  color: #93a4bf;
  font-size: 14px;
  line-height: 1.7;
}

.sub code {
  background: rgba(255, 255, 255, 0.07);
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 12px;
}

.block {
  border-top: 1px solid rgba(120, 160, 220, 0.13);
  padding: 20px 0 4px;
}

.block h2 {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
  color: #cfe1ff;
}

.hint {
  margin: 0 0 14px;
  font-size: 13px;
  color: #8395b0;
  line-height: 1.6;
}

.hint a {
  color: #4cc9f0;
}

.preset {
  display: inline-block;
  margin-right: 8px;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(76, 201, 240, 0.12);
  color: #6cd8f8;
  cursor: pointer;
  font-size: 12px;
}

.preset:hover {
  background: rgba(76, 201, 240, 0.22);
}

label {
  display: block;
  margin-bottom: 14px;
}

label span {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: #9fb0c9;
}

input {
  width: 100%;
  box-sizing: border-box;
  padding: 11px 13px;
  border-radius: 10px;
  border: 1px solid rgba(120, 160, 220, 0.28);
  background: rgba(8, 14, 26, 0.85);
  color: #eaf2ff;
  font-size: 14px;
  outline: none;
}

input:focus {
  border-color: #4cc9f0;
  box-shadow: 0 0 0 3px rgba(76, 201, 240, 0.16);
}

.actions {
  display: flex;
  gap: 12px;
  margin-top: 26px;
  flex-wrap: wrap;
}

.btn {
  padding: 11px 20px;
  border-radius: 10px;
  border: 1px solid rgba(120, 160, 220, 0.3);
  background: rgba(255, 255, 255, 0.05);
  color: #dce7f7;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.btn:hover:not(:disabled) {
  border-color: #4cc9f0;
  color: #fff;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn.primary {
  background: linear-gradient(135deg, #22d3ee, #3b82f6);
  border: none;
  color: #04101f;
  font-weight: 700;
}

.btn.ghost {
  background: transparent;
  margin-left: auto;
}

.banner {
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 13px;
  margin-bottom: 18px;
  line-height: 1.6;
}

.banner.ok {
  background: rgba(52, 211, 153, 0.13);
  color: #79e8bd;
  border: 1px solid rgba(52, 211, 153, 0.35);
}

.banner.error {
  background: rgba(248, 113, 113, 0.12);
  color: #fca5a5;
  border: 1px solid rgba(248, 113, 113, 0.35);
}

.update {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 13px;
  background: rgba(76, 201, 240, 0.1);
  border: 1px solid rgba(76, 201, 240, 0.32);
  color: #a8e7fb;
}

.update a {
  margin-left: 8px;
  color: #4cc9f0;
}

.results {
  margin-top: 20px;
  display: grid;
  gap: 10px;
}

.result {
  display: flex;
  gap: 10px;
  font-size: 13px;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.6;
  word-break: break-word;
}

.result.ok {
  background: rgba(52, 211, 153, 0.1);
  color: #86efac;
}

.result.fail {
  background: rgba(248, 113, 113, 0.1);
  color: #fca5a5;
}
</style>
