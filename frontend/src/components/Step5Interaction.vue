<template>
  <div class="interaction-panel">
    <!-- Main Split Layout -->
    <div class="main-split-layout">
      <!-- LEFT PANEL: Report Style -->
      <div class="left-panel report-style" ref="leftPanel">
        <div v-if="reportOutline" class="report-content-wrapper">
          <!-- Report Header -->
          <div class="report-header-block">
            <div class="report-meta">
              <span class="report-tag">Prediction Report</span>
              <span class="report-id">ID: {{ reportId || 'REF-2024-X92' }}</span>
            </div>
            <h1 class="main-title">{{ reportOutline.title }}</h1>
            <p class="sub-title">{{ reportOutline.summary }}</p>
            <div class="header-divider"></div>
          </div>

          <!-- Sections List -->
          <div class="sections-list">
            <div 
              v-for="(section, idx) in reportOutline.sections" 
              :key="idx"
              class="report-section-item"
              :class="{ 
                'is-active': currentSectionIndex === idx + 1,
                'is-completed': isSectionCompleted(idx + 1),
                'is-pending': !isSectionCompleted(idx + 1) && currentSectionIndex !== idx + 1
              }"
            >
              <div class="section-header-row" @click="toggleSectionCollapse(idx)" :class="{ 'clickable': isSectionCompleted(idx + 1) }">
                <span class="section-number">{{ String(idx + 1).padStart(2, '0') }}</span>
                <h3 class="section-title">{{ section.title }}</h3>
                <svg 
                  v-if="isSectionCompleted(idx + 1)" 
                  class="collapse-icon" 
                  :class="{ 'is-collapsed': collapsedSections.has(idx) }"
                  viewBox="0 0 24 24" 
                  width="20" 
                  height="20" 
                  fill="none" 
                  stroke="currentColor" 
                  stroke-width="2"
                >
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </div>
              
              <div class="section-body" v-show="!collapsedSections.has(idx)">
                <!-- Completed Content -->
                <div v-if="generatedSections[idx + 1]" class="generated-content" v-html="renderMarkdown(generatedSections[idx + 1])"></div>
                
                <!-- Loading State -->
                <div v-else-if="currentSectionIndex === idx + 1" class="loading-state">
                  <div class="loading-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <circle cx="12" cy="12" r="10" stroke-width="4" stroke="#E5E7EB"></circle>
                      <path d="M12 2a10 10 0 0 1 10 10" stroke-width="4" stroke="#4B5563" stroke-linecap="round"></path>
                    </svg>
                  </div>
                  <span class="loading-text">正在生成{{ section.title }}...</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Waiting State -->
        <div v-if="!reportOutline" class="waiting-placeholder">
          <div class="waiting-animation">
            <div class="waiting-ring"></div>
            <div class="waiting-ring"></div>
            <div class="waiting-ring"></div>
          </div>
          <span class="waiting-text">Waiting for Report Agent...</span>
        </div>
      </div>

      <!-- RIGHT PANEL: Interaction Interface -->
      <div class="right-panel" ref="rightPanel">
        <!-- Unified Action Bar - Professional Design -->
        <div class="action-bar">
        <div class="action-bar-header">
          <svg class="action-bar-icon" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
          </svg>
          <div class="action-bar-text">
            <span class="action-bar-title">Interactive Tools</span>
            <span class="action-bar-subtitle mono">{{ profiles.length }} agents available</span>
          </div>
        </div>
          <div class="action-bar-tabs">
            <button 
              class="tab-pill"
              :class="{ active: activeTab === 'chat' && chatTarget === 'report_agent' }"
              @click="selectReportAgentChat"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
              </svg>
              <span>与Report Agent对话</span>
            </button>
            <div class="agent-dropdown" v-if="profiles.length > 0">
              <button 
                class="tab-pill agent-pill"
                :class="{ active: activeTab === 'chat' && chatTarget === 'agent' }"
                @click="toggleAgentDropdown"
              >
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                  <circle cx="12" cy="7" r="4"></circle>
                </svg>
                <span>{{ selectedAgent ? selectedAgent.username : '与世界中任意个体对话' }}</span>
                <svg class="dropdown-arrow" :class="{ open: showAgentDropdown }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </button>
              <div v-if="showAgentDropdown" class="dropdown-menu">
                <div class="dropdown-header">选择对话对象</div>
                <div 
                  v-for="(agent, idx) in profiles" 
                  :key="idx"
                  class="dropdown-item"
                  @click="selectAgent(agent, idx)"
                >
                  <div class="agent-avatar">{{ (agent.username || 'A')[0] }}</div>
                  <div class="agent-info">
                    <span class="agent-name">{{ agent.username }}</span>
                    <span class="agent-role">{{ agent.profession || '未知职业' }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="tab-divider"></div>
            <button 
              class="tab-pill survey-pill"
              :class="{ active: activeTab === 'survey' }"
              @click="selectSurveyTab"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 11l3 3L22 4"></path>
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
              </svg>
              <span>发送问卷调查到世界中</span>
            </button>
          </div>
        </div>

        <!-- Chat Mode -->
        <div v-if="activeTab === 'chat'" class="chat-container">

          <!-- Report Agent Tools Card -->
          <div v-if="chatTarget === 'report_agent'" class="report-agent-tools-card">
            <div class="tools-card-header">
              <div class="tools-card-avatar">R</div>
              <div class="tools-card-info">
                <div class="tools-card-name">Report Agent - Chat</div>
                <div class="tools-card-subtitle">报告生成智能体的快速对话版本，可调用 4 种专业工具，拥有MiroFish的完整记忆</div>
              </div>
              <button class="tools-card-toggle" @click="showToolsDetail = !showToolsDetail">
                <svg :class="{ 'is-expanded': showToolsDetail }" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </button>
            </div>
            <div v-if="showToolsDetail" class="tools-card-body">
              <div class="tools-grid">
                <div class="tool-item tool-purple">
                  <div class="tool-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.5V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.5A7 7 0 0 0 12 2z"></path>
                    </svg>
                  </div>
                  <div class="tool-content">
                    <div class="tool-name">InsightForge 深度归因</div>
                    <div class="tool-desc">对齐现实世界种子数据与模拟环境状态，结合Global/Local Memory机制，提供跨时空的深度归因分析</div>
                  </div>
                </div>
                <div class="tool-item tool-blue">
                  <div class="tool-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <circle cx="12" cy="12" r="10"></circle>
                      <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                    </svg>
                  </div>
                  <div class="tool-content">
                    <div class="tool-name">PanoramaSearch 全景追踪</div>
                    <div class="tool-desc">基于图结构的广度遍历算法，重构事件传播路径，捕获全量信息流动的拓扑结构</div>
                  </div>
                </div>
                <div class="tool-item tool-orange">
                  <div class="tool-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                    </svg>
                  </div>
                  <div class="tool-content">
                    <div class="tool-name">QuickSearch 快速检索</div>
                    <div class="tool-desc">基于 GraphRAG 的即时查询接口，优化索引效率，用于快速提取具体的节点属性与离散事实</div>
                  </div>
                </div>
                <div class="tool-item tool-green">
                  <div class="tool-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                      <circle cx="9" cy="7" r="4"></circle>
                      <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"></path>
                    </svg>
                  </div>
                  <div class="tool-content">
                    <div class="tool-name">InterviewSubAgent 虚拟访谈</div>
                    <div class="tool-desc">自主式访谈，能够并行与模拟世界中个体进行多轮对话，采集非结构化的观点数据与心理状态</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Agent Profile Card -->
          <div v-if="chatTarget === 'agent' && selectedAgent" class="agent-profile-card">
            <div class="profile-card-header">
              <div class="profile-card-avatar">{{ (selectedAgent.username || 'A')[0] }}</div>
              <div class="profile-card-info">
                <div class="profile-card-name">{{ selectedAgent.username }}</div>
                <div class="profile-card-meta">
                  <span v-if="selectedAgent.name" class="profile-card-handle">@{{ selectedAgent.name }}</span>
                  <span class="profile-card-profession">{{ selectedAgent.profession || '未知职业' }}</span>
                </div>
              </div>
              <button class="profile-card-toggle" @click="showFullProfile = !showFullProfile">
                <svg :class="{ 'is-expanded': showFullProfile }" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </button>
            </div>
            <div v-if="showFullProfile && selectedAgent.bio" class="profile-card-body">
              <div class="profile-card-bio">
                <div class="profile-card-label">简介</div>
                <p>{{ selectedAgent.bio }}</p>
              </div>
            </div>
          </div>

          <!-- Chat Messages -->
          <div class="chat-messages" ref="chatMessages">
            <div v-if="chatHistory.length === 0" class="chat-empty">
              <div class="empty-icon">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                </svg>
              </div>
              <p class="empty-text">
                {{ chatTarget === 'report_agent' ? '与 Report Agent 对话，深入了解报告内容' : '与模拟个体对话，了解他们的观点' }}
              </p>
            </div>
            <div 
              v-for="(msg, idx) in chatHistory" 
              :key="idx"
              class="chat-message"
              :class="msg.role"
            >
              <div class="message-avatar">
                <span v-if="msg.role === 'user'">U</span>
                <span v-else>{{ msg.role === 'assistant' && chatTarget === 'report_agent' ? 'R' : (selectedAgent?.username?.[0] || 'A') }}</span>
              </div>
              <div class="message-content">
                <div class="message-header">
                  <span class="sender-name">
                    {{ msg.role === 'user' ? 'You' : (chatTarget === 'report_agent' ? 'Report Agent' : (selectedAgent?.username || 'Agent')) }}
                  </span>
                  <span class="message-time">{{ formatTime(msg.timestamp) }}</span>
                </div>
                <div class="message-text" v-html="renderMarkdown(msg.content)"></div>
              </div>
            </div>
            <div v-if="isSending" class="chat-message assistant">
              <div class="message-avatar">
                <span>{{ chatTarget === 'report_agent' ? 'R' : (selectedAgent?.username?.[0] || 'A') }}</span>
              </div>
              <div class="message-content">
                <div class="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          </div>

          <!-- Chat Input -->
          <div class="chat-input-area">
            <textarea 
              v-model="chatInput"
              class="chat-input"
              placeholder="输入您的问题..."
              @keydown.enter.exact.prevent="sendMessage"
              :disabled="isSending || (!selectedAgent && chatTarget === 'agent')"
              rows="1"
              ref="chatInputRef"
            ></textarea>
            <button 
              class="send-btn"
              @click="sendMessage"
              :disabled="!chatInput.trim() || isSending || (!selectedAgent && chatTarget === 'agent')"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
        </div>

        <!-- Survey Mode -->
        <div v-if="activeTab === 'survey'" class="survey-container">
          <!-- Survey Setup -->
          <div class="survey-setup">
            <div class="setup-section">
              <div class="section-header">
                <span class="section-title">选择调查对象</span>
                <span class="selection-count">已选 {{ selectedAgents.size }} / {{ profiles.length }}</span>
              </div>
              <div class="agents-grid">
                <label 
                  v-for="(agent, idx) in profiles" 
                  :key="idx"
                  class="agent-checkbox"
                  :class="{ checked: selectedAgents.has(idx) }"
                >
                  <input 
                    type="checkbox" 
                    :checked="selectedAgents.has(idx)"
                    @change="toggleAgentSelection(idx)"
                  >
                  <div class="checkbox-avatar">{{ (agent.username || 'A')[0] }}</div>
                  <div class="checkbox-info">
                    <span class="checkbox-name">{{ agent.username }}</span>
                    <span class="checkbox-role">{{ agent.profession || '未知职业' }}</span>
                  </div>
                  <div class="checkbox-indicator">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="3">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                  </div>
                </label>
              </div>
              <div class="selection-actions">
                <button class="action-link" @click="selectAllAgents">全选</button>
                <span class="action-divider">|</span>
                <button class="action-link" @click="clearAgentSelection">清空</button>
              </div>
            </div>

            <div class="setup-section">
              <div class="section-header">
                <span class="section-title">问卷问题</span>
              </div>
              <textarea 
                v-model="surveyQuestion"
                class="survey-input"
                placeholder="输入您想问所有被选中对象的问题..."
                rows="3"
              ></textarea>
            </div>

            <button 
              class="survey-submit-btn"
              :disabled="selectedAgents.size === 0 || !surveyQuestion.trim() || isSurveying"
              @click="submitSurvey"
            >
              <span v-if="isSurveying" class="loading-spinner"></span>
              <span v-else>发送问卷</span>
            </button>
          </div>

          <!-- Survey Results -->
          <div v-if="surveyResults.length > 0" class="survey-results">
            <div class="results-header">
              <span class="results-title">调查结果</span>
              <span class="results-count">{{ surveyResults.length }} 条回复</span>
            </div>
            <div class="results-list">
              <div 
                v-for="(result, idx) in surveyResults" 
                :key="idx"
                class="result-card"
              >
                <div class="result-header">
                  <div class="result-avatar">{{ (result.agent_name || 'A')[0] }}</div>
                  <div class="result-info">
                    <span class="result-name">{{ result.agent_name }}</span>
                    <span class="result-role">{{ result.profession || '未知职业' }}</span>
                  </div>
                </div>
                <div class="result-question">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                  </svg>
                  <span>{{ result.question }}</span>
                </div>
                <div class="result-answer" v-html="renderMarkdown(result.answer)"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { chatWithReport, getReport, getAgentLog } from '../api/report'
import { interviewAgents, getSimulationProfilesRealtime } from '../api/simulation'

const props = defineProps({
  reportId: String,
  simulationId: String
})

const emit = defineEmits(['add-log', 'update-status'])

// State
const activeTab = ref('chat')
const chatTarget = ref('report_agent')
const showAgentDropdown = ref(false)
const selectedAgent = ref(null)
const selectedAgentIndex = ref(null)
const showFullProfile = ref(true)
const showToolsDetail = ref(true)

// Chat State
const chatInput = ref('')
const chatHistory = ref([])
const chatHistoryCache = ref({}) // 缓存所有对话记录: { 'report_agent': [], 'agent_0': [], 'agent_1': [], ... }
const isSending = ref(false)
const chatMessages = ref(null)
const chatInputRef = ref(null)

// Survey State
const selectedAgents = ref(new Set())
const surveyQuestion = ref('')
const surveyResults = ref([])
const isSurveying = ref(false)

// Report Data
const reportOutline = ref(null)
const generatedSections = ref({})
const collapsedSections = ref(new Set())
const currentSectionIndex = ref(null)
const profiles = ref([])

// Helper Methods
const isSectionCompleted = (sectionIndex) => {
  return !!generatedSections.value[sectionIndex]
}

// Refs
const leftPanel = ref(null)
const rightPanel = ref(null)

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

const toggleSectionCollapse = (idx) => {
  if (!generatedSections.value[idx + 1]) return
  const newSet = new Set(collapsedSections.value)
  if (newSet.has(idx)) {
    newSet.delete(idx)
  } else {
    newSet.add(idx)
  }
  collapsedSections.value = newSet
}

const selectChatTarget = (target) => {
  chatTarget.value = target
  if (target === 'report_agent') {
    showAgentDropdown.value = false
  }
}

// 保存当前对话记录到缓存
const saveChatHistory = () => {
  if (chatHistory.value.length === 0) return
  
  if (chatTarget.value === 'report_agent') {
    chatHistoryCache.value['report_agent'] = [...chatHistory.value]
  } else if (selectedAgentIndex.value !== null) {
    chatHistoryCache.value[`agent_${selectedAgentIndex.value}`] = [...chatHistory.value]
  }
}

const selectReportAgentChat = () => {
  // 保存当前对话记录
  saveChatHistory()
  
  activeTab.value = 'chat'
  chatTarget.value = 'report_agent'
  selectedAgent.value = null
  selectedAgentIndex.value = null
  showAgentDropdown.value = false
  
  // 恢复 Report Agent 的对话记录
  chatHistory.value = chatHistoryCache.value['report_agent'] || []
}

const selectSurveyTab = () => {
  activeTab.value = 'survey'
  selectedAgent.value = null
  selectedAgentIndex.value = null
  showAgentDropdown.value = false
}

const toggleAgentDropdown = () => {
  showAgentDropdown.value = !showAgentDropdown.value
  if (showAgentDropdown.value) {
    activeTab.value = 'chat'
    chatTarget.value = 'agent'
  }
}

const selectAgent = (agent, idx) => {
  // 保存当前对话记录
  saveChatHistory()
  
  selectedAgent.value = agent
  selectedAgentIndex.value = idx
  chatTarget.value = 'agent'
  showAgentDropdown.value = false
  
  // 恢复该 Agent 的对话记录
  chatHistory.value = chatHistoryCache.value[`agent_${idx}`] || []
  addLog(`选择对话对象: ${agent.username}`)
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit'
    })
  } catch {
    return ''
  }
}

const renderMarkdown = (content) => {
  if (!content) return ''
  
  let processedContent = content.replace(/^##\s+.+\n+/, '')
  let html = processedContent.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')
  html = html.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  
  // 处理列表 - 支持子列表
  html = html.replace(/^(\s*)- (.+)$/gm, (match, indent, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${text}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (match, indent, num, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${text}</li>`
  })
  
  // 包装无序列表
  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  // 包装有序列表
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')
  
  // 清理列表项之间的所有空白
  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  // 清理列表开始标签后的空白
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  // 清理列表结束标签前的空白
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')
  
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  html = html.replace(/^---$/gm, '<hr class="md-hr">')
  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = '<p class="md-p">' + html + '</p>'
  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>)<\/p>/g, '$1')
  // 清理列表前后的 <br> 标签
  html = html.replace(/<br>\s*(<ul|<ol)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>)\s*<br>/g, '$1')
  // 清理连续的 <br> 标签
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  // 清理列表后紧跟的段落开始标签前的 <br>
  html = html.replace(/(<\/ol>|<\/ul>)<br>(<p|<div)/g, '$1$2')
  
  return html
}

// Chat Methods
const sendMessage = async () => {
  if (!chatInput.value.trim() || isSending.value) return
  
  const message = chatInput.value.trim()
  chatInput.value = ''
  
  // Add user message
  chatHistory.value.push({
    role: 'user',
    content: message,
    timestamp: new Date().toISOString()
  })
  
  scrollToBottom()
  isSending.value = true
  
  try {
    if (chatTarget.value === 'report_agent') {
      await sendToReportAgent(message)
    } else {
      await sendToAgent(message)
    }
  } catch (err) {
    addLog(`发送失败: ${err.message}`)
    chatHistory.value.push({
      role: 'assistant',
      content: `抱歉，发生了错误: ${err.message}`,
      timestamp: new Date().toISOString()
    })
  } finally {
    isSending.value = false
    scrollToBottom()
    // 自动保存对话记录到缓存
    saveChatHistory()
  }
}

const sendToReportAgent = async (message) => {
  addLog(`向 Report Agent 发送: ${message.substring(0, 50)}...`)
  
  // Build chat history for API
  const historyForApi = chatHistory.value
    .filter(msg => msg.role !== 'user' || msg.content !== message)
    .slice(-10) // Keep last 10 messages
    .map(msg => ({
      role: msg.role,
      content: msg.content
    }))
  
  const res = await chatWithReport({
    simulation_id: props.simulationId,
    message: message,
    chat_history: historyForApi
  })
  
  if (res.success && res.data) {
    chatHistory.value.push({
      role: 'assistant',
      content: res.data.response || res.data.answer || '无响应',
      timestamp: new Date().toISOString()
    })
    addLog('Report Agent 已回复')
  } else {
    throw new Error(res.error || '请求失败')
  }
}

const sendToAgent = async (message) => {
  if (!selectedAgent.value || selectedAgentIndex.value === null) {
    throw new Error('请先选择一个模拟个体')
  }
  
  addLog(`向 ${selectedAgent.value.username} 发送: ${message.substring(0, 50)}...`)
  
  // Build prompt with chat history
  let prompt = message
  if (chatHistory.value.length > 1) {
    const historyContext = chatHistory.value
      .filter(msg => msg.content !== message)
      .slice(-6)
      .map(msg => `${msg.role === 'user' ? '提问者' : '你'}：${msg.content}`)
      .join('\n')
    prompt = `以下是我们之前的对话：\n${historyContext}\n\n现在我的新问题是：${message}`
  }
  
  const res = await interviewAgents({
    simulation_id: props.simulationId,
    interviews: [{
      agent_id: selectedAgentIndex.value,
      prompt: prompt
    }]
  })
  
  if (res.success && res.data) {
    // 正确的数据路径: res.data.result.results 是一个对象字典
    // 格式: {"twitter_0": {...}, "reddit_0": {...}} 或单平台 {"reddit_0": {...}}
    const resultData = res.data.result || res.data
    const resultsDict = resultData.results || resultData
    
    // 将对象字典转换为数组，优先获取 reddit 平台的回复
    let responseContent = null
    const agentId = selectedAgentIndex.value
    
    if (typeof resultsDict === 'object' && !Array.isArray(resultsDict)) {
      // 优先使用 reddit 平台回复，其次 twitter
      const redditKey = `reddit_${agentId}`
      const twitterKey = `twitter_${agentId}`
      const agentResult = resultsDict[redditKey] || resultsDict[twitterKey] || Object.values(resultsDict)[0]
      if (agentResult) {
        responseContent = agentResult.response || agentResult.answer
      }
    } else if (Array.isArray(resultsDict) && resultsDict.length > 0) {
      // 兼容数组格式
      responseContent = resultsDict[0].response || resultsDict[0].answer
    }
    
    if (responseContent) {
      chatHistory.value.push({
        role: 'assistant',
        content: responseContent,
        timestamp: new Date().toISOString()
      })
      addLog(`${selectedAgent.value.username} 已回复`)
    } else {
      throw new Error('无响应数据')
    }
  } else {
    throw new Error(res.error || '请求失败')
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (chatMessages.value) {
      chatMessages.value.scrollTop = chatMessages.value.scrollHeight
    }
  })
}

// Survey Methods
const toggleAgentSelection = (idx) => {
  const newSet = new Set(selectedAgents.value)
  if (newSet.has(idx)) {
    newSet.delete(idx)
  } else {
    newSet.add(idx)
  }
  selectedAgents.value = newSet
}

const selectAllAgents = () => {
  const newSet = new Set()
  profiles.value.forEach((_, idx) => newSet.add(idx))
  selectedAgents.value = newSet
}

const clearAgentSelection = () => {
  selectedAgents.value = new Set()
}

const submitSurvey = async () => {
  if (selectedAgents.value.size === 0 || !surveyQuestion.value.trim()) return
  
  isSurveying.value = true
  addLog(`发送问卷给 ${selectedAgents.value.size} 个对象...`)
  
  try {
    const interviews = Array.from(selectedAgents.value).map(idx => ({
      agent_id: idx,
      prompt: surveyQuestion.value.trim()
    }))
    
    const res = await interviewAgents({
      simulation_id: props.simulationId,
      interviews: interviews
    })
    
    if (res.success && res.data) {
      // 正确的数据路径: res.data.result.results 是一个对象字典
      // 格式: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
      const resultData = res.data.result || res.data
      const resultsDict = resultData.results || resultData
      
      // 将对象字典转换为数组格式
      const surveyResultsList = []
      
      for (const interview of interviews) {
        const agentIdx = interview.agent_id
        const agent = profiles.value[agentIdx]
        
        // 优先使用 reddit 平台回复，其次 twitter
        let responseContent = '无响应'
        
        if (typeof resultsDict === 'object' && !Array.isArray(resultsDict)) {
          const redditKey = `reddit_${agentIdx}`
          const twitterKey = `twitter_${agentIdx}`
          const agentResult = resultsDict[redditKey] || resultsDict[twitterKey]
          if (agentResult) {
            responseContent = agentResult.response || agentResult.answer || '无响应'
          }
        } else if (Array.isArray(resultsDict)) {
          // 兼容数组格式
          const matchedResult = resultsDict.find(r => r.agent_id === agentIdx)
          if (matchedResult) {
            responseContent = matchedResult.response || matchedResult.answer || '无响应'
          }
        }
        
        surveyResultsList.push({
          agent_id: agentIdx,
          agent_name: agent?.username || `Agent ${agentIdx}`,
          profession: agent?.profession,
          question: surveyQuestion.value.trim(),
          answer: responseContent
        })
      }
      
      surveyResults.value = surveyResultsList
      addLog(`收到 ${surveyResults.value.length} 条回复`)
    } else {
      throw new Error(res.error || '请求失败')
    }
  } catch (err) {
    addLog(`问卷发送失败: ${err.message}`)
  } finally {
    isSurveying.value = false
  }
}

// Load Report Data
const loadReportData = async () => {
  if (!props.reportId) return
  
  try {
    addLog(`加载报告数据: ${props.reportId}`)
    
    // Get report info
    const reportRes = await getReport(props.reportId)
    if (reportRes.success && reportRes.data) {
      // Load agent logs to get report outline and sections
      await loadAgentLogs()
    }
  } catch (err) {
    addLog(`加载报告失败: ${err.message}`)
  }
}

const loadAgentLogs = async () => {
  if (!props.reportId) return
  
  try {
    const res = await getAgentLog(props.reportId, 0)
    if (res.success && res.data) {
      const logs = res.data.logs || []
      
      logs.forEach(log => {
        if (log.action === 'planning_complete' && log.details?.outline) {
          reportOutline.value = log.details.outline
        }
        
        if (log.action === 'section_complete' && log.section_index < 100 && log.details?.content) {
          generatedSections.value[log.section_index] = log.details.content
        }
      })
      
      addLog('报告数据加载完成')
    }
  } catch (err) {
    addLog(`加载报告日志失败: ${err.message}`)
  }
}

const loadProfiles = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getSimulationProfilesRealtime(props.simulationId, 'reddit')
    if (res.success && res.data) {
      profiles.value = res.data.profiles || []
      addLog(`加载了 ${profiles.value.length} 个模拟个体`)
    }
  } catch (err) {
    addLog(`加载模拟个体失败: ${err.message}`)
  }
}

// Click outside to close dropdown
const handleClickOutside = (e) => {
  const dropdown = document.querySelector('.agent-dropdown')
  if (dropdown && !dropdown.contains(e.target)) {
    showAgentDropdown.value = false
  }
}

// Lifecycle
onMounted(() => {
  addLog('Step5 深度互动初始化')
  loadReportData()
  loadProfiles()
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

watch(() => props.reportId, (newId) => {
  if (newId) {
    loadReportData()
  }
}, { immediate: true })

watch(() => props.simulationId, (newId) => {
  if (newId) {
    loadProfiles()
  }
}, { immediate: true })
</script>

<style scoped>
.interaction-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #F8F9FA;
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  overflow: hidden;
}

/* Utility Classes */
.mono {
  font-family: 'JetBrains Mono', 'SF Mono', 'Monaco', 'Consolas', monospace;
}

/* Main Split Layout */
.main-split-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Left Panel - Report Style (与 Step4Report.vue 完全一致) */
.left-panel.report-style {
  width: 45%;
  min-width: 450px;
  background: #FFFFFF;
  border-right: 1px solid #E5E7EB;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 30px 50px 60px 50px;
}

.left-panel::-webkit-scrollbar {
  width: 6px;
}

.left-panel::-webkit-scrollbar-track {
  background: transparent;
}

.left-panel::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
  transition: background 0.3s ease;
}

.left-panel:hover::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
}

.left-panel::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.25);
}

/* Report Header */
.report-content-wrapper {
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

.report-header-block {
  margin-bottom: 30px;
}

.report-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.report-tag {
  background: #000000;
  color: #FFFFFF;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 8px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.report-id {
  font-size: 11px;
  color: #9CA3AF;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.main-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 36px;
  font-weight: 700;
  color: #111827;
  line-height: 1.2;
  margin: 0 0 16px 0;
  letter-spacing: -0.02em;
}

.sub-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 16px;
  color: #6B7280;
  font-style: italic;
  line-height: 1.6;
  margin: 0 0 30px 0;
  font-weight: 400;
}

.header-divider {
  height: 1px;
  background: #E5E7EB;
  width: 100%;
}

/* Sections List */
.sections-list {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.report-section-item {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  transition: background-color 0.2s ease;
  padding: 8px 12px;
  margin: -8px -12px;
  border-radius: 8px;
}

.section-header-row.clickable {
  cursor: pointer;
}

.section-header-row.clickable:hover {
  background-color: #F9FAFB;
}

.collapse-icon {
  margin-left: auto;
  color: #9CA3AF;
  transition: transform 0.3s ease;
  flex-shrink: 0;
  align-self: center;
}

.collapse-icon.is-collapsed {
  transform: rotate(-90deg);
}

.section-number {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  color: #E5E7EB;
  font-weight: 500;
  transition: color 0.3s ease;
}

.section-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 24px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  transition: color 0.3s ease;
}

/* States */
.report-section-item.is-pending .section-number {
  color: #E5E7EB;
}
.report-section-item.is-pending .section-title {
  color: #D1D5DB;
}

.report-section-item.is-active .section-number,
.report-section-item.is-completed .section-number {
  color: #9CA3AF;
}

.report-section-item.is-active .section-title,
.report-section-item.is-completed .section-title {
  color: #111827;
}

.section-body {
  padding-left: 28px;
  overflow: hidden;
}

/* Generated Content */
.generated-content {
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.8;
  color: #374151;
}

.generated-content :deep(p) {
  margin-bottom: 1em;
}

.generated-content :deep(.md-h2),
.generated-content :deep(.md-h3),
.generated-content :deep(.md-h4) {
  font-family: 'Times New Roman', Times, serif;
  color: #111827;
  margin-top: 1.5em;
  margin-bottom: 0.8em;
  font-weight: 700;
}

.generated-content :deep(.md-h2) { font-size: 20px; border-bottom: 1px solid #F3F4F6; padding-bottom: 8px; }
.generated-content :deep(.md-h3) { font-size: 18px; }
.generated-content :deep(.md-h4) { font-size: 16px; }

.generated-content :deep(.md-ul),
.generated-content :deep(.md-ol) {
  padding-left: 20px;
  margin-bottom: 1em;
}

.generated-content :deep(.md-li) {
  margin-bottom: 0.5em;
}

.generated-content :deep(.md-quote) {
  border-left: 3px solid #E5E7EB;
  padding-left: 16px;
  margin: 1.5em 0;
  color: #6B7280;
  font-style: italic;
  font-family: 'Times New Roman', Times, serif;
}

.generated-content :deep(.code-block) {
  background: #F9FAFB;
  padding: 12px;
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  overflow-x: auto;
  margin: 1em 0;
  border: 1px solid #E5E7EB;
}

.generated-content :deep(strong) {
  font-weight: 600;
  color: #111827;
}

/* Loading State */
.loading-state {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #6B7280;
  font-size: 14px;
  margin-top: 4px;
}

.loading-icon {
  width: 18px;
  height: 18px;
  animation: spin 1s linear infinite;
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-text {
  font-family: 'Times New Roman', Times, serif;
  font-size: 15px;
  color: #4B5563;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Content Styles Override */
.generated-content :deep(.md-h2) {
  font-family: 'Times New Roman', Times, serif;
  font-size: 18px;
  margin-top: 0;
}

/* Waiting Placeholder */
.waiting-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 40px;
  color: #9CA3AF;
}

.waiting-animation {
  position: relative;
  width: 48px;
  height: 48px;
}

.waiting-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  border: 2px solid #E5E7EB;
  border-radius: 50%;
  animation: ripple 2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.waiting-ring:nth-child(2) {
  animation-delay: 0.4s;
}

.waiting-ring:nth-child(3) {
  animation-delay: 0.8s;
}

@keyframes ripple {
  0% { transform: scale(0.5); opacity: 1; }
  100% { transform: scale(2); opacity: 0; }
}

.waiting-text {
  font-size: 14px;
}

/* Right Panel - Interaction */
.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #FFFFFF;
  overflow: hidden;
}

/* Action Bar - Professional Design */
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #E5E7EB;
  background: linear-gradient(180deg, #FFFFFF 0%, #FAFBFC 100%);
  gap: 16px;
}

.action-bar-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 160px;
}

.action-bar-icon {
  color: #1F2937;
  flex-shrink: 0;
}

.action-bar-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.action-bar-title {
  font-size: 13px;
  font-weight: 600;
  color: #1F2937;
  letter-spacing: -0.01em;
}

.action-bar-subtitle {
  font-size: 11px;
  color: #9CA3AF;
}

.action-bar-subtitle.mono {
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
}

.action-bar-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  justify-content: flex-end;
}

.tab-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 500;
  color: #6B7280;
  background: #F3F4F6;
  border: 1px solid transparent;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.tab-pill:hover {
  background: #E5E7EB;
  color: #374151;
}

.tab-pill.active {
  background: #1F2937;
  color: #FFFFFF;
  box-shadow: 0 2px 8px rgba(31, 41, 55, 0.15);
}

.tab-pill svg {
  flex-shrink: 0;
  opacity: 0.7;
}

.tab-pill.active svg {
  opacity: 1;
}

.tab-divider {
  width: 1px;
  height: 24px;
  background: #E5E7EB;
  margin: 0 6px;
}

.agent-pill {
  width: 200px;
  justify-content: space-between;
}

.agent-pill span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.survey-pill {
  background: #ECFDF5;
  color: #047857;
}

.survey-pill:hover {
  background: #D1FAE5;
  color: #065F46;
}

.survey-pill.active {
  background: #047857;
  color: #FFFFFF;
  box-shadow: 0 2px 8px rgba(4, 120, 87, 0.2);
}

/* Interaction Header */
.interaction-header {
  padding: 16px 24px;
  border-bottom: 1px solid #E5E7EB;
  background: #FAFAFA;
}

.tab-switcher {
  display: flex;
  gap: 8px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
  color: #6B7280;
  background: transparent;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  background: #F9FAFB;
  border-color: #D1D5DB;
}

.tab-btn.active {
  background: #1F2937;
  color: #FFFFFF;
  border-color: #1F2937;
}

.tab-btn svg {
  flex-shrink: 0;
}

/* Chat Container */
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Report Agent Tools Card */
.report-agent-tools-card {
  border-bottom: 1px solid #E5E7EB;
  background: linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%);
}

.tools-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
}

.tools-card-avatar {
  width: 44px;
  height: 44px;
  min-width: 44px;
  min-height: 44px;
  background: linear-gradient(135deg, #1F2937 0%, #374151 100%);
  color: #FFFFFF;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(31, 41, 55, 0.2);
}

.tools-card-info {
  flex: 1;
  min-width: 0;
}

.tools-card-name {
  font-size: 15px;
  font-weight: 600;
  color: #1F2937;
  margin-bottom: 2px;
}

.tools-card-subtitle {
  font-size: 12px;
  color: #6B7280;
}

.tools-card-toggle {
  width: 28px;
  height: 28px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6B7280;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.tools-card-toggle:hover {
  background: #F9FAFB;
  border-color: #D1D5DB;
}

.tools-card-toggle svg {
  transition: transform 0.3s ease;
}

.tools-card-toggle svg.is-expanded {
  transform: rotate(180deg);
}

.tools-card-body {
  padding: 0 20px 16px 20px;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.tool-item {
  display: flex;
  gap: 10px;
  padding: 12px;
  background: #FFFFFF;
  border-radius: 10px;
  border: 1px solid #E5E7EB;
  transition: all 0.2s ease;
}

.tool-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.tool-icon-wrapper {
  width: 32px;
  height: 32px;
  min-width: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.tool-purple .tool-icon-wrapper {
  background: rgba(139, 92, 246, 0.1);
  color: #8B5CF6;
}

.tool-blue .tool-icon-wrapper {
  background: rgba(59, 130, 246, 0.1);
  color: #3B82F6;
}

.tool-orange .tool-icon-wrapper {
  background: rgba(249, 115, 22, 0.1);
  color: #F97316;
}

.tool-green .tool-icon-wrapper {
  background: rgba(34, 197, 94, 0.1);
  color: #22C55E;
}

.tool-content {
  flex: 1;
  min-width: 0;
}

.tool-name {
  font-size: 12px;
  font-weight: 600;
  color: #1F2937;
  margin-bottom: 4px;
}

.tool-desc {
  font-size: 11px;
  color: #6B7280;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Agent Profile Card */
.agent-profile-card {
  border-bottom: 1px solid #E5E7EB;
  background: linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%);
}

.profile-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
}

.profile-card-avatar {
  width: 44px;
  height: 44px;
  min-width: 44px;
  min-height: 44px;
  background: linear-gradient(135deg, #1F2937 0%, #374151 100%);
  color: #FFFFFF;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(31, 41, 55, 0.2);
}

.profile-card-info {
  flex: 1;
  min-width: 0;
}

.profile-card-name {
  font-size: 15px;
  font-weight: 600;
  color: #1F2937;
  margin-bottom: 2px;
}

.profile-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6B7280;
}

.profile-card-handle {
  color: #9CA3AF;
}

.profile-card-profession {
  padding: 2px 8px;
  background: #E5E7EB;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.profile-card-toggle {
  width: 28px;
  height: 28px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6B7280;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.profile-card-toggle:hover {
  background: #F9FAFB;
  border-color: #D1D5DB;
}

.profile-card-toggle svg {
  transition: transform 0.3s ease;
}

.profile-card-toggle svg.is-expanded {
  transform: rotate(180deg);
}

.profile-card-body {
  padding: 0 20px 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.profile-card-label {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.profile-card-bio {
  background: #FFFFFF;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid #E5E7EB;
}

.profile-card-bio p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #4B5563;
}

/* Target Selector */
.target-selector {
  padding: 16px 24px;
  border-bottom: 1px solid #E5E7EB;
}

.selector-label {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 10px;
}

.selector-options {
  display: flex;
  gap: 12px;
}

.target-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.target-option:hover {
  border-color: #D1D5DB;
}

.target-option.active {
  background: #1F2937;
  color: #FFFFFF;
  border-color: #1F2937;
}

/* Agent Dropdown */
.agent-dropdown {
  position: relative;
}

.dropdown-arrow {
  margin-left: 4px;
  transition: transform 0.2s ease;
  opacity: 0.6;
}

.dropdown-arrow.open {
  transform: rotate(180deg);
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  min-width: 240px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.12), 0 4px 12px rgba(0, 0, 0, 0.06);
  max-height: 320px;
  overflow-y: auto;
  z-index: 100;
}

.dropdown-header {
  padding: 12px 16px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #F3F4F6;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
  border-left: 3px solid transparent;
}

.dropdown-item:hover {
  background: #F9FAFB;
  border-left-color: #1F2937;
}

.dropdown-item:first-of-type {
  margin-top: 4px;
}

.dropdown-item:last-child {
  margin-bottom: 4px;
}

.agent-avatar {
  width: 32px;
  height: 32px;
  min-width: 32px;
  min-height: 32px;
  background: linear-gradient(135deg, #1F2937 0%, #374151 100%);
  color: #FFFFFF;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
  box-shadow: 0 2px 4px rgba(31, 41, 55, 0.1);
}

.agent-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: #1F2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-role {
  font-size: 11px;
  color: #9CA3AF;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Chat Messages */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #9CA3AF;
}

.empty-icon {
  opacity: 0.3;
}

.empty-text {
  font-size: 14px;
  text-align: center;
  max-width: 280px;
  line-height: 1.6;
}

.chat-message {
  display: flex;
  gap: 12px;
}

.chat-message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  min-width: 36px;
  min-height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.chat-message.user .message-avatar {
  background: #1F2937;
  color: #FFFFFF;
}

.chat-message.assistant .message-avatar {
  background: #F3F4F6;
  color: #374151;
}

.message-content {
  max-width: 70%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.chat-message.user .message-content {
  align-items: flex-end;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-message.user .message-header {
  flex-direction: row-reverse;
}

.sender-name {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

.message-time {
  font-size: 11px;
  color: #9CA3AF;
}

.message-text {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
}

.chat-message.user .message-text {
  background: #1F2937;
  color: #FFFFFF;
  border-bottom-right-radius: 4px;
}

.chat-message.assistant .message-text {
  background: #F3F4F6;
  color: #374151;
  border-bottom-left-radius: 4px;
}

.message-text :deep(.md-p) {
  margin: 0;
}

.message-text :deep(.md-p:last-child) {
  margin-bottom: 0;
}

/* 修复有序列表编号 - 使用 CSS 计数器让多个 ol 连续编号 */
.message-text {
  counter-reset: list-counter;
}

.message-text :deep(.md-ol) {
  list-style: none;
  padding-left: 0;
  margin: 8px 0;
}

.message-text :deep(.md-oli) {
  counter-increment: list-counter;
  display: flex;
  gap: 8px;
  margin: 4px 0;
}

.message-text :deep(.md-oli)::before {
  content: counter(list-counter) ".";
  font-weight: 600;
  color: #374151;
  min-width: 20px;
  flex-shrink: 0;
}

/* 无序列表样式 */
.message-text :deep(.md-ul) {
  padding-left: 20px;
  margin: 8px 0;
}

.message-text :deep(.md-li) {
  margin: 4px 0;
}

/* Typing Indicator */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 10px 14px;
  background: #F3F4F6;
  border-radius: 12px;
  border-bottom-left-radius: 4px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #9CA3AF;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

/* Chat Input */
.chat-input-area {
  padding: 16px 24px;
  border-top: 1px solid #E5E7EB;
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
  padding: 12px 16px;
  font-size: 14px;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  resize: none;
  font-family: inherit;
  line-height: 1.5;
  transition: border-color 0.2s ease;
}

.chat-input:focus {
  outline: none;
  border-color: #1F2937;
}

.chat-input:disabled {
  background: #F9FAFB;
  cursor: not-allowed;
}

.send-btn {
  width: 44px;
  height: 44px;
  background: #1F2937;
  color: #FFFFFF;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  background: #374151;
}

.send-btn:disabled {
  background: #E5E7EB;
  color: #9CA3AF;
  cursor: not-allowed;
}

/* Survey Container */
.survey-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.survey-setup {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 24px;
  border-bottom: 1px solid #E5E7EB;
  overflow: hidden;
}

.setup-section {
  margin-bottom: 24px;
}

.setup-section:first-child {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.setup-section:last-child {
  margin-bottom: 0;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.setup-section .section-header .section-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.selection-count {
  font-size: 12px;
  color: #9CA3AF;
}

/* Agents Grid */
.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  flex: 1;
  overflow-y: auto;
  padding: 4px;
  align-content: start;
}

.agent-checkbox {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.agent-checkbox:hover {
  border-color: #D1D5DB;
}

.agent-checkbox.checked {
  background: #F0FDF4;
  border-color: #10B981;
}

.agent-checkbox input {
  display: none;
}

.checkbox-avatar {
  width: 28px;
  height: 28px;
  min-width: 28px;
  min-height: 28px;
  background: #E5E7EB;
  color: #374151;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.agent-checkbox.checked .checkbox-avatar {
  background: #10B981;
  color: #FFFFFF;
}

.checkbox-info {
  flex: 1;
  min-width: 0;
}

.checkbox-name {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #1F2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.checkbox-role {
  display: block;
  font-size: 10px;
  color: #9CA3AF;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.checkbox-indicator {
  width: 20px;
  height: 20px;
  border: 2px solid #E5E7EB;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.agent-checkbox.checked .checkbox-indicator {
  background: #10B981;
  border-color: #10B981;
  color: #FFFFFF;
}

.checkbox-indicator svg {
  opacity: 0;
  transform: scale(0.5);
  transition: all 0.2s ease;
}

.agent-checkbox.checked .checkbox-indicator svg {
  opacity: 1;
  transform: scale(1);
}

.selection-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.action-link {
  font-size: 12px;
  color: #6B7280;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
}

.action-link:hover {
  color: #1F2937;
  text-decoration: underline;
}

.action-divider {
  color: #E5E7EB;
}

/* Survey Input */
.survey-input {
  width: 100%;
  padding: 14px 16px;
  font-size: 14px;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  resize: none;
  font-family: inherit;
  line-height: 1.5;
  transition: border-color 0.2s ease;
}

.survey-input:focus {
  outline: none;
  border-color: #1F2937;
}

.survey-submit-btn {
  width: 100%;
  padding: 14px 24px;
  font-size: 14px;
  font-weight: 600;
  color: #FFFFFF;
  background: #1F2937;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 20px;
}

.survey-submit-btn:hover:not(:disabled) {
  background: #374151;
}

.survey-submit-btn:disabled {
  background: #E5E7EB;
  color: #9CA3AF;
  cursor: not-allowed;
}

.loading-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #FFFFFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Survey Results */
.survey-results {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.results-title {
  font-size: 14px;
  font-weight: 600;
  color: #1F2937;
}

.results-count {
  font-size: 12px;
  color: #9CA3AF;
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.result-card {
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
  padding: 20px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.result-avatar {
  width: 36px;
  height: 36px;
  min-width: 36px;
  min-height: 36px;
  background: #1F2937;
  color: #FFFFFF;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.result-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.result-name {
  font-size: 14px;
  font-weight: 600;
  color: #1F2937;
}

.result-role {
  font-size: 12px;
  color: #9CA3AF;
}

.result-question {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  background: #FFFFFF;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #6B7280;
}

.result-question svg {
  flex-shrink: 0;
  margin-top: 2px;
}

.result-answer {
  font-size: 14px;
  line-height: 1.7;
  color: #374151;
}

/* Markdown Styles */
:deep(.md-p) {
  margin: 0 0 12px 0;
}

:deep(.md-h2) {
  font-size: 20px;
  font-weight: 700;
  color: #1F2937;
  margin: 24px 0 12px 0;
}

:deep(.md-h3) {
  font-size: 16px;
  font-weight: 600;
  color: #374151;
  margin: 20px 0 10px 0;
}

:deep(.md-h4) {
  font-size: 14px;
  font-weight: 600;
  color: #4B5563;
  margin: 16px 0 8px 0;
}

:deep(.md-h5) {
  font-size: 13px;
  font-weight: 600;
  color: #6B7280;
  margin: 12px 0 6px 0;
}

:deep(.md-ul), :deep(.md-ol) {
  margin: 12px 0;
  padding-left: 24px;
}

:deep(.md-li), :deep(.md-oli) {
  margin: 6px 0;
}

/* 聊天/问卷区域的引用样式 */
.chat-messages :deep(.md-quote),
.result-answer :deep(.md-quote) {
  margin: 12px 0;
  padding: 12px 16px;
  background: #F9FAFB;
  border-left: 3px solid #1F2937;
  color: #4B5563;
}

:deep(.code-block) {
  margin: 12px 0;
  padding: 12px 16px;
  background: #1F2937;
  border-radius: 6px;
  overflow-x: auto;
}

:deep(.code-block code) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: #E5E7EB;
}

:deep(.inline-code) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  background: #F3F4F6;
  padding: 2px 6px;
  border-radius: 4px;
  color: #1F2937;
}

:deep(.md-hr) {
  border: none;
  border-top: 1px solid #E5E7EB;
  margin: 24px 0;
}
</style>
