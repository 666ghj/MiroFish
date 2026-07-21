<template>
  <div class="chat-root">
    <!-- Header -->
    <header class="chat-header">
      <div class="header-left">
        <div class="brand" @click="router.push('/')">MIROFISH</div>
      </div>
      <div class="header-center">
        <span class="header-title">Agent Chat</span>
        <span class="sim-badge">{{ simulationId }}</span>
      </div>
      <div class="header-right">
        <button class="back-btn" @click="router.back()">← Back</button>
      </div>
    </header>

    <div class="chat-body">
      <!-- Sidebar: Agent List -->
      <aside class="sidebar">
        <div class="sidebar-title">Agents</div>

        <div v-if="loadingAgents" class="loading-agents">
          <div class="spinner"></div>
          <span>Loading agents…</span>
        </div>

        <div v-else-if="agentError" class="agent-error">
          {{ agentError }}
          <button @click="loadAgents">Retry</button>
        </div>

        <div v-else class="agent-list">
          <div
            v-for="agent in agents"
            :key="agent.id"
            class="agent-card"
            :class="{ active: selectedAgent && selectedAgent.id === agent.id }"
            @click="selectAgent(agent)"
          >
            <div class="agent-avatar">{{ getInitial(agent.name) }}</div>
            <div class="agent-info">
              <div class="agent-name">{{ agent.name }}</div>
              <div class="agent-meta">ID: {{ agent.id }}</div>
            </div>
            <div v-if="unread[agent.id]" class="unread-dot"></div>
          </div>
        </div>

        <div class="platform-selector">
          <label>Platform</label>
          <select v-model="platform">
            <option value="">Both</option>
            <option value="reddit">Reddit</option>
            <option value="twitter">Twitter</option>
          </select>
        </div>
      </aside>

      <!-- Chat Panel -->
      <main class="chat-panel">
        <div v-if="!selectedAgent" class="empty-state">
          <div class="empty-icon">💬</div>
          <div class="empty-text">Select an agent from the left to start chatting</div>
        </div>

        <template v-else>
          <!-- Chat header -->
          <div class="chat-agent-header">
            <div class="agent-avatar large">{{ getInitial(selectedAgent.name) }}</div>
            <div>
              <div class="agent-name-lg">{{ selectedAgent.name }}</div>
              <div class="agent-id-sm">Agent #{{ selectedAgent.id }}</div>
            </div>
            <button class="clear-btn" @click="clearChat">Clear</button>
          </div>

          <!-- Messages -->
          <div class="messages" ref="messagesEl">
            <div v-if="currentMessages.length === 0" class="no-messages">
              No messages yet. Ask {{ selectedAgent.name }} anything!
            </div>
            <div
              v-for="(msg, i) in currentMessages"
              :key="i"
              class="message-row"
              :class="msg.role"
            >
              <div v-if="msg.role === 'agent'" class="msg-avatar">{{ getInitial(selectedAgent.name) }}</div>
              <div class="bubble">
                <div class="bubble-text">{{ msg.text }}</div>
                <div class="bubble-time">{{ msg.time }}</div>
              </div>
              <div v-if="msg.role === 'user'" class="msg-avatar user-avatar">You</div>
            </div>

            <!-- Typing indicator -->
            <div v-if="isWaiting" class="message-row agent">
              <div class="msg-avatar">{{ getInitial(selectedAgent.name) }}</div>
              <div class="bubble typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>

          <!-- Input -->
          <div class="input-area">
            <textarea
              v-model="inputText"
              ref="inputEl"
              class="chat-input"
              placeholder="Type your message…"
              rows="1"
              @keydown.enter.exact.prevent="sendMessage"
              @input="autoResize"
            ></textarea>
            <button
              class="send-btn"
              :disabled="isWaiting || !inputText.trim()"
              @click="sendMessage"
            >
              <span v-if="isWaiting" class="send-spinner"></span>
              <span v-else>Send ↑</span>
            </button>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSimulationProfilesRealtime, interviewAgent } from '../api/simulation'

const route = useRoute()
const router = useRouter()

const simulationId = computed(() => route.params.simulationId)

// Agent state
const agents = ref([])
const loadingAgents = ref(false)
const agentError = ref('')
const selectedAgent = ref(null)

// Chat state: keyed by agent id
const chatHistory = ref({})
const inputText = ref('')
const isWaiting = ref(false)
const platform = ref('')
const messagesEl = ref(null)
const inputEl = ref(null)
const unread = ref({})

const currentMessages = computed(() => {
  if (!selectedAgent.value) return []
  return chatHistory.value[selectedAgent.value.id] || []
})

function getInitial(name) {
  return name ? name.charAt(0).toUpperCase() : '?'
}

async function loadAgents() {
  loadingAgents.value = true
  agentError.value = ''
  try {
    const res = await getSimulationProfilesRealtime(simulationId.value, 'reddit')
    const profiles = res?.data?.profiles || res?.profiles || []
    agents.value = profiles.map(p => ({
      id: p.agent_id ?? p.id,
      name: p.name || p.agent_name || `Agent ${p.agent_id ?? p.id}`,
      profile: p
    }))
  } catch (e) {
    agentError.value = 'Failed to load agents: ' + (e.message || 'Unknown error')
  } finally {
    loadingAgents.value = false
  }
}

function selectAgent(agent) {
  selectedAgent.value = agent
  if (unread.value[agent.id]) {
    delete unread.value[agent.id]
  }
  nextTick(scrollToBottom)
}

function clearChat() {
  if (selectedAgent.value) {
    chatHistory.value[selectedAgent.value.id] = []
  }
}

function timestamp() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function pushMessage(agentId, role, text) {
  if (!chatHistory.value[agentId]) chatHistory.value[agentId] = []
  chatHistory.value[agentId].push({ role, text, time: timestamp() })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isWaiting.value || !selectedAgent.value) return

  const agent = selectedAgent.value
  inputText.value = ''
  resetInputHeight()

  pushMessage(agent.id, 'user', text)
  await nextTick(scrollToBottom)

  isWaiting.value = true
  try {
    const payload = {
      simulation_id: simulationId.value,
      agent_id: agent.id,
      prompt: text,
      timeout: 120
    }
    if (platform.value) payload.platform = platform.value

    const res = await interviewAgent(payload)
    const data = res?.data || res
    let reply = extractReply(data, platform.value)
    pushMessage(agent.id, 'agent', reply)
  } catch (e) {
    pushMessage(agent.id, 'agent', '⚠ ' + (e.message || 'Failed to get response'))
  } finally {
    isWaiting.value = false
    await nextTick(scrollToBottom)
  }
}

function extractReply(data, plt) {
  if (!data) return 'No response.'
  // Single platform mode
  if (data.response) return data.response
  // result field with response
  if (data.result?.response) return data.result.response
  // Dual-platform mode: result.platforms
  const platforms = data.result?.platforms || data.platforms
  if (platforms) {
    if (plt && platforms[plt]) return platforms[plt].response || JSON.stringify(platforms[plt])
    const first = Object.values(platforms)[0]
    return first?.response || JSON.stringify(first)
  }
  return JSON.stringify(data)
}

function scrollToBottom() {
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  }
}

function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function resetInputHeight() {
  if (inputEl.value) {
    inputEl.value.style.height = 'auto'
  }
}

watch(selectedAgent, () => nextTick(scrollToBottom))

onMounted(loadAgents)
</script>

<style scoped>
.chat-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #fff;
  font-family: 'JetBrains Mono', 'Space Grotesk', monospace;
}

/* Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  border-bottom: 2px solid #000;
  flex-shrink: 0;
}
.brand {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
  cursor: pointer;
}
.header-center {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-title {
  font-size: 15px;
  font-weight: 600;
}
.sim-badge {
  font-size: 11px;
  background: #000;
  color: #fff;
  padding: 2px 8px;
  border-radius: 3px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.back-btn {
  background: none;
  border: 1.5px solid #000;
  padding: 5px 14px;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s;
}
.back-btn:hover {
  background: #000;
  color: #fff;
}

/* Body */
.chat-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Sidebar */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  border-right: 2px solid #000;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-title {
  padding: 14px 18px 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  border-bottom: 1px solid #e0e0e0;
}
.loading-agents, .agent-error {
  padding: 20px 18px;
  font-size: 13px;
  color: #666;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.agent-error button {
  font-family: inherit;
  border: 1px solid #000;
  background: none;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
}
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid #e0e0e0;
  border-top-color: #000;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.agent-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}
.agent-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  position: relative;
  transition: background 0.12s;
}
.agent-card:hover { background: #f5f5f5; }
.agent-card.active { background: #000; color: #fff; }
.agent-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #e0e0e0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
  border: 1.5px solid #000;
}
.agent-card.active .agent-avatar { background: #fff; color: #000; }
.agent-info { flex: 1; min-width: 0; }
.agent-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.agent-meta { font-size: 11px; opacity: 0.6; }
.unread-dot {
  width: 8px; height: 8px;
  background: #ff4444;
  border-radius: 50%;
  flex-shrink: 0;
}

.platform-selector {
  padding: 12px 16px;
  border-top: 1px solid #e0e0e0;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.platform-selector select {
  font-family: inherit;
  font-size: 12px;
  border: 1.5px solid #000;
  padding: 4px 8px;
  background: #fff;
  cursor: pointer;
  flex: 1;
}

/* Chat Panel */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #aaa;
}
.empty-icon { font-size: 48px; }
.empty-text { font-size: 14px; }

.chat-agent-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1.5px solid #e0e0e0;
  flex-shrink: 0;
}
.agent-avatar.large {
  width: 40px;
  height: 40px;
  font-size: 16px;
}
.agent-name-lg { font-size: 15px; font-weight: 700; }
.agent-id-sm { font-size: 11px; color: #888; }
.clear-btn {
  margin-left: auto;
  font-family: inherit;
  font-size: 12px;
  border: 1.5px solid #ccc;
  background: none;
  padding: 4px 12px;
  cursor: pointer;
}
.clear-btn:hover { border-color: #000; }

/* Messages */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.no-messages {
  text-align: center;
  color: #bbb;
  font-size: 13px;
  margin-top: 40px;
}
.message-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  max-width: 75%;
}
.message-row.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.message-row.agent {
  align-self: flex-start;
}
.msg-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #e0e0e0;
  border: 1.5px solid #000;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.user-avatar { background: #000; color: #fff; }
.bubble {
  background: #f0f0f0;
  border: 1.5px solid #e0e0e0;
  border-radius: 4px 14px 14px 14px;
  padding: 10px 14px;
  max-width: 100%;
}
.message-row.user .bubble {
  background: #000;
  color: #fff;
  border-color: #000;
  border-radius: 14px 4px 14px 14px;
}
.bubble-text {
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble-time {
  font-size: 10px;
  opacity: 0.5;
  margin-top: 4px;
  text-align: right;
}

/* Typing indicator */
.bubble.typing {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 12px 16px;
}
.bubble.typing span {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #888;
  animation: bounce 1.2s infinite;
}
.bubble.typing span:nth-child(2) { animation-delay: 0.2s; }
.bubble.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.7); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

/* Input */
.input-area {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1.5px solid #e0e0e0;
  flex-shrink: 0;
}
.chat-input {
  flex: 1;
  font-family: inherit;
  font-size: 14px;
  border: 1.5px solid #000;
  padding: 10px 14px;
  resize: none;
  outline: none;
  line-height: 1.5;
  min-height: 42px;
  max-height: 160px;
  overflow-y: auto;
  transition: border-color 0.15s;
}
.chat-input:focus { border-color: #000; box-shadow: 2px 2px 0 #000; }
.send-btn {
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  background: #000;
  color: #fff;
  border: none;
  padding: 10px 18px;
  cursor: pointer;
  white-space: nowrap;
  height: 42px;
  transition: opacity 0.15s;
}
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.send-btn:not(:disabled):hover { opacity: 0.75; }
.send-spinner {
  display: inline-block;
  width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
</style>
