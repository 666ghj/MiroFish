<template>
  <div class="report-panel">
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

      <!-- RIGHT PANEL: Workflow Timeline -->
      <div class="right-panel" ref="rightPanel">
        <div class="panel-header" :class="`panel-header--${activeStep.status}`" v-if="!isComplete">
          <span class="header-dot" v-if="activeStep.status === 'active'"></span>
          <span class="header-index mono">{{ activeStep.noLabel }}</span>
          <span class="header-title">{{ activeStep.title }}</span>
          <span class="header-meta mono" v-if="activeStep.meta">{{ activeStep.meta }}</span>
        </div>

        <!-- Workflow Overview (flat, status-based palette) -->
        <div class="workflow-overview" v-if="agentLogs.length > 0 || reportOutline">
          <div class="workflow-metrics">
            <div class="metric">
              <span class="metric-label">Sections</span>
              <span class="metric-value mono">{{ completedSections }}/{{ totalSections }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Elapsed</span>
              <span class="metric-value mono">{{ formatElapsedTime }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Tools</span>
              <span class="metric-value mono">{{ totalToolCalls }}</span>
            </div>
            <div class="metric metric-right">
              <span class="metric-pill" :class="`pill--${statusClass}`">{{ statusText }}</span>
            </div>
          </div>

          <div class="workflow-steps" v-if="workflowSteps.length > 0">
            <div
              v-for="(step, sidx) in workflowSteps"
              :key="step.key"
              class="wf-step"
              :class="`wf-step--${step.status}`"
            >
              <div class="wf-step-connector">
                <div class="wf-step-dot"></div>
                <div class="wf-step-line" v-if="sidx < workflowSteps.length - 1"></div>
              </div>

              <div class="wf-step-content">
                <div class="wf-step-title-row">
                  <span class="wf-step-index mono">{{ step.noLabel }}</span>
                  <span class="wf-step-title">{{ step.title }}</span>
                  <span class="wf-step-meta mono" v-if="step.meta">{{ step.meta }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="workflow-divider"></div>
        </div>

        <div class="workflow-timeline">
          <TransitionGroup name="timeline-item">
            <div 
              v-for="(log, idx) in displayLogs" 
              :key="log.timestamp + '-' + idx"
              class="timeline-item"
              :class="getTimelineItemClass(log, idx, displayLogs.length)"
            >
              <!-- Timeline Connector -->
              <div class="timeline-connector">
                <div class="connector-dot" :class="getConnectorClass(log, idx, displayLogs.length)"></div>
                <div class="connector-line" v-if="idx < displayLogs.length - 1"></div>
              </div>
              
              <!-- Timeline Content -->
              <div class="timeline-content">
                <div class="timeline-header">
                  <span class="action-label">{{ getActionLabel(log.action) }}</span>
                  <span class="action-time">{{ formatTime(log.timestamp) }}</span>
                </div>
                
                <!-- Action Body - Different for each type -->
                <div class="timeline-body" :class="{ 'collapsed': isLogCollapsed(log) }" @click="toggleLogExpand(log)">
                  
                  <!-- Report Start -->
                  <template v-if="log.action === 'report_start'">
                    <div class="info-row">
                      <span class="info-key">Simulation</span>
                      <span class="info-val mono">{{ log.details?.simulation_id }}</span>
                    </div>
                    <div class="info-row" v-if="log.details?.simulation_requirement">
                      <span class="info-key">Requirement</span>
                      <span class="info-val">{{ log.details.simulation_requirement }}</span>
                    </div>
                  </template>

                  <!-- Planning -->
                  <template v-if="log.action === 'planning_start'">
                    <div class="status-message planning">{{ log.details?.message }}</div>
                  </template>
                  <template v-if="log.action === 'planning_complete'">
                    <div class="status-message success">{{ log.details?.message }}</div>
                    <div class="outline-badge" v-if="log.details?.outline">
                      {{ log.details.outline.sections?.length || 0 }} sections planned
                    </div>
                  </template>

                  <!-- Section Start -->
                  <template v-if="log.action === 'section_start'">
                    <div class="section-tag">
                      <span class="tag-num">#{{ log.section_index }}</span>
                      <span class="tag-title">{{ log.section_title }}</span>
                    </div>
                  </template>
                  
                  <!-- Section/Subsection Content Generated (内容生成完成，但整个章节可能还没完成) -->
                  <template v-if="log.action === 'section_content' || log.action === 'subsection_content'">
                    <div class="section-tag content-ready" :class="{ 'is-subsection': log.action === 'subsection_content' }">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 20h9"></path>
                        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                      </svg>
                      <span class="tag-title">{{ log.section_title }}</span>
                      <span v-if="log.action === 'subsection_content'" class="tag-sub">(subsection)</span>
                    </div>
                  </template>
                  
                  <!-- Section Complete (完整章节生成完成，含所有子章节) -->
                  <template v-if="log.action === 'section_complete'">
                    <div class="section-tag completed">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                      </svg>
                      <span class="tag-title">{{ log.section_title }}</span>
                      <span v-if="log.details?.subsection_count > 0" class="tag-sub">(+{{ log.details.subsection_count }} subsections)</span>
                    </div>
                  </template>

                  <!-- Tool Call -->
                  <template v-if="log.action === 'tool_call'">
                    <div class="tool-badge" :class="'tool-' + getToolColor(log.details?.tool_name)">
                      <!-- Deep Insight - Lightbulb -->
                      <svg v-if="getToolIcon(log.details?.tool_name) === 'lightbulb'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.5V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.5A7 7 0 0 0 12 2z"></path>
                      </svg>
                      <!-- Panorama Search - Globe -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'globe'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                      </svg>
                      <!-- Agent Interview - Users -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'users'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"></path>
                      </svg>
                      <!-- Quick Search - Zap -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'zap'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                      </svg>
                      <!-- Graph Stats - Chart -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'chart'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="20" x2="18" y2="10"></line>
                        <line x1="12" y1="20" x2="12" y2="4"></line>
                        <line x1="6" y1="20" x2="6" y2="14"></line>
                      </svg>
                      <!-- Entity Query - Database -->
                      <svg v-else-if="getToolIcon(log.details?.tool_name) === 'database'" class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                      </svg>
                      <!-- Default - Tool -->
                      <svg v-else class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                      </svg>
                      {{ getToolDisplayName(log.details?.tool_name) }}
                    </div>
                    <div v-if="log.details?.parameters && expandedLogs.has(log.timestamp)" class="tool-params">
                      <pre>{{ formatParams(log.details.parameters) }}</pre>
                    </div>
                  </template>

                  <!-- Tool Result -->
                  <template v-if="log.action === 'tool_result'">
                    <div class="result-wrapper" :class="'result-' + log.details?.tool_name">
                      <!-- Hide result-meta for interview_agents as it's shown in the component header -->
                      <div v-if="log.details?.tool_name !== 'interview_agents'" class="result-meta">
                        <span class="result-tool">{{ getToolDisplayName(log.details?.tool_name) }}</span>
                        <span class="result-size">{{ formatResultSize(log.details?.result_length) }}</span>
                      </div>
                      
                      <!-- Structured Result Display -->
                      <div v-if="!showRawResult[log.timestamp]" class="result-structured">
                        <!-- Interview Agents - Special Display -->
                        <template v-if="log.details?.tool_name === 'interview_agents'">
                          <InterviewDisplay :result="parseInterview(log.details.result)" :result-length="log.details?.result_length" />
                        </template>
                        
                        <!-- Insight Forge -->
                        <template v-else-if="log.details?.tool_name === 'insight_forge'">
                          <InsightDisplay :result="parseInsightForge(log.details.result)" />
                        </template>
                        
                        <!-- Panorama Search -->
                        <template v-else-if="log.details?.tool_name === 'panorama_search'">
                          <PanoramaDisplay :result="parsePanorama(log.details.result)" />
                        </template>
                        
                        <!-- Quick Search -->
                        <template v-else-if="log.details?.tool_name === 'quick_search'">
                          <QuickSearchDisplay :result="parseQuickSearch(log.details.result)" />
                        </template>
                        
                        <!-- Default -->
                        <template v-else>
                          <pre class="raw-preview">{{ truncateText(log.details?.result, 300) }}</pre>
                        </template>
                      </div>
                      
                      <!-- Raw Result -->
                      <div v-else class="result-raw">
                        <pre>{{ log.details?.result }}</pre>
                      </div>
                    </div>
                  </template>

                  <!-- LLM Response -->
                  <template v-if="log.action === 'llm_response'">
                    <div class="llm-meta">
                      <span class="meta-tag">Iteration {{ log.details?.iteration }}</span>
                      <span class="meta-tag" :class="{ active: log.details?.has_tool_calls }">
                        Tools: {{ log.details?.has_tool_calls ? 'Yes' : 'No' }}
                      </span>
                      <span class="meta-tag" :class="{ active: log.details?.has_final_answer, 'final-answer': log.details?.has_final_answer }">
                        Final: {{ log.details?.has_final_answer ? 'Yes' : 'No' }}
                      </span>
                    </div>
                    <!-- 当是最终答案时，显示特殊提示 -->
                    <div v-if="log.details?.has_final_answer" class="final-answer-hint">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                      </svg>
                      <span>Section "{{ log.section_title }}" content generated</span>
                    </div>
                    <div v-if="expandedLogs.has(log.timestamp) && log.details?.response" class="llm-content">
                      <pre>{{ log.details.response }}</pre>
                    </div>
                  </template>

                  <!-- Report Complete -->
                  <template v-if="log.action === 'report_complete'">
                    <div class="complete-banner">
                      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                        <polyline points="22 4 12 14.01 9 11.01"></polyline>
                      </svg>
                      <span>Report Generation Complete</span>
                    </div>
                  </template>
                </div>

                <!-- Footer: Elapsed Time + Action Buttons -->
                <div class="timeline-footer" v-if="log.elapsed_seconds || (log.action === 'tool_call' && log.details?.parameters) || log.action === 'tool_result' || (log.action === 'llm_response' && log.details?.response)">
                  <span v-if="log.elapsed_seconds" class="elapsed-badge">+{{ log.elapsed_seconds.toFixed(1) }}s</span>
                  <span v-else class="elapsed-placeholder"></span>
                  
                  <div class="footer-actions">
                    <!-- Tool Call: Show/Hide Params -->
                    <button v-if="log.action === 'tool_call' && log.details?.parameters" class="action-btn" @click.stop="toggleLogExpand(log)">
                      {{ expandedLogs.has(log.timestamp) ? 'Hide Params' : 'Show Params' }}
                    </button>
                    
                    <!-- Tool Result: Raw/Structured View -->
                    <button v-if="log.action === 'tool_result'" class="action-btn" @click.stop="toggleRawResult(log.timestamp, $event)">
                      {{ showRawResult[log.timestamp] ? 'Structured View' : 'Raw Output' }}
                    </button>
                    
                    <!-- LLM Response: Show/Hide Response -->
                    <button v-if="log.action === 'llm_response' && log.details?.response" class="action-btn" @click.stop="toggleLogExpand(log)">
                      {{ expandedLogs.has(log.timestamp) ? 'Hide Response' : 'Show Response' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </TransitionGroup>

          <!-- Empty State -->
          <div v-if="agentLogs.length === 0 && !isComplete" class="workflow-empty">
            <div class="empty-pulse"></div>
            <span>Waiting for agent activity...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Console Logs -->
    <div class="console-logs">
      <div class="log-header">
        <span class="log-title">CONSOLE OUTPUT</span>
        <span class="log-id">{{ reportId || 'NO_REPORT' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div class="log-line" v-for="(log, idx) in consoleLogs" :key="idx">
          <span class="log-msg" :class="getLogLevelClass(log)">{{ log }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick, h, reactive } from 'vue'
import { getAgentLog, getConsoleLog } from '../api/report'

const props = defineProps({
  reportId: String,
  simulationId: String,
  systemLogs: Array
})

const emit = defineEmits(['add-log', 'update-status'])

// State
const agentLogs = ref([])
const consoleLogs = ref([])
const agentLogLine = ref(0)
const consoleLogLine = ref(0)
const reportOutline = ref(null)
const currentSectionIndex = ref(null)
const generatedSections = ref({})
const expandedContent = ref(new Set())
const expandedLogs = ref(new Set())
const collapsedSections = ref(new Set())
const isComplete = ref(false)
const startTime = ref(null)
const leftPanel = ref(null)
const rightPanel = ref(null)
const logContent = ref(null)
const showRawResult = reactive({})

// Toggle functions
const toggleRawResult = (timestamp, event) => {
  // 保存按钮相对于视口的位置
  const button = event?.target
  const buttonRect = button?.getBoundingClientRect()
  const buttonTopBeforeToggle = buttonRect?.top
  
  // 切换状态
  showRawResult[timestamp] = !showRawResult[timestamp]
  
  // 等待 DOM 更新后，调整滚动位置以保持按钮在相同位置
  if (button && buttonTopBeforeToggle !== undefined && rightPanel.value) {
    nextTick(() => {
      const newButtonRect = button.getBoundingClientRect()
      const buttonTopAfterToggle = newButtonRect.top
      const scrollDelta = buttonTopAfterToggle - buttonTopBeforeToggle
      
      // 调整滚动位置
      rightPanel.value.scrollTop += scrollDelta
    })
  }
}

const toggleSectionContent = (idx) => {
  if (!generatedSections.value[idx + 1]) return
  const newSet = new Set(expandedContent.value)
  if (newSet.has(idx)) {
    newSet.delete(idx)
  } else {
    newSet.add(idx)
  }
  expandedContent.value = newSet
}

const toggleSectionCollapse = (idx) => {
  // 只有已完成的章节才能折叠
  if (!generatedSections.value[idx + 1]) return
  const newSet = new Set(collapsedSections.value)
  if (newSet.has(idx)) {
    newSet.delete(idx)
  } else {
    newSet.add(idx)
  }
  collapsedSections.value = newSet
}

const toggleLogExpand = (log) => {
  const newSet = new Set(expandedLogs.value)
  if (newSet.has(log.timestamp)) {
    newSet.delete(log.timestamp)
  } else {
    newSet.add(log.timestamp)
  }
  expandedLogs.value = newSet
}

const isLogCollapsed = (log) => {
  if (['tool_call', 'tool_result', 'llm_response'].includes(log.action)) {
    return !expandedLogs.value.has(log.timestamp)
  }
  return false
}

// Tool configurations with display names and colors
const toolConfig = {
  'insight_forge': {
    name: 'Deep Insight',
    color: 'purple',
    icon: 'lightbulb' // 灯泡图标 - 代表洞察
  },
  'panorama_search': {
    name: 'Panorama Search',
    color: 'blue',
    icon: 'globe' // 地球图标 - 代表全景搜索
  },
  'interview_agents': {
    name: 'Agent Interview',
    color: 'green',
    icon: 'users' // 用户图标 - 代表对话
  },
  'quick_search': {
    name: 'Quick Search',
    color: 'orange',
    icon: 'zap' // 闪电图标 - 代表快速
  },
  'get_graph_statistics': {
    name: 'Graph Stats',
    color: 'cyan',
    icon: 'chart' // 图表图标 - 代表统计
  },
  'get_entities_by_type': {
    name: 'Entity Query',
    color: 'pink',
    icon: 'database' // 数据库图标 - 代表实体
  }
}

const getToolDisplayName = (toolName) => {
  return toolConfig[toolName]?.name || toolName
}

const getToolColor = (toolName) => {
  return toolConfig[toolName]?.color || 'gray'
}

const getToolIcon = (toolName) => {
  return toolConfig[toolName]?.icon || 'tool'
}

// Parse functions
const parseInsightForge = (text) => {
  const result = {
    query: '',
    stats: { facts: 0, entities: 0, relationships: 0 },
    subQueries: [],
    facts: [],
    entities: [],
    relations: []
  }
  
  try {
    const queryMatch = text.match(/原始问题:\s*(.+?)(?:\n|$)/)
    if (queryMatch) result.query = queryMatch[1].trim()
    
    const factMatch = text.match(/相关事实:\s*(\d+)/)
    const entityMatch = text.match(/涉及实体:\s*(\d+)/)
    const relMatch = text.match(/关系链:\s*(\d+)/)
    if (factMatch) result.stats.facts = parseInt(factMatch[1])
    if (entityMatch) result.stats.entities = parseInt(entityMatch[1])
    if (relMatch) result.stats.relationships = parseInt(relMatch[1])
    
    const subQSection = text.match(/### 分析的子问题\n([\s\S]*?)(?=###|\n\n###|$)/)
    if (subQSection) {
      const lines = subQSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.subQueries = lines.map(l => l.replace(/^\d+\.\s*/, '').trim())
    }
    
    const factsSection = text.match(/### 【关键事实】[\s\S]*?\n([\s\S]*?)(?=###|$)/)
    if (factsSection) {
      const lines = factsSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.facts = lines.map(l => {
        const match = l.match(/^\d+\.\s*"?(.+?)"?\s*$/)
        return match ? match[1].replace(/^"|"$/g, '') : l.replace(/^\d+\.\s*/, '').trim()
      }).slice(0, 10)
    }
    
    const entitySection = text.match(/### 【核心实体】\n([\s\S]*?)(?=###|$)/)
    if (entitySection) {
      const entityBlocks = entitySection[1].split(/\n- \*\*/).slice(1)
      result.entities = entityBlocks.map(block => {
        const nameMatch = block.match(/^(.+?)\*\*\s*\((.+?)\)/)
        return {
          name: nameMatch ? nameMatch[1].trim() : '',
          type: nameMatch ? nameMatch[2].trim() : ''
        }
      }).filter(e => e.name).slice(0, 8)
    }
    
    const relSection = text.match(/### 【关系链】\n([\s\S]*?)(?=###|$)/)
    if (relSection) {
      const lines = relSection[1].split('\n').filter(l => l.startsWith('-'))
      result.relations = lines.map(l => {
        const match = l.match(/^-\s*(.+?)\s*--\[(.+?)\]-->\s*(.+)$/)
        if (match) {
          return { source: match[1].trim(), relation: match[2].trim(), target: match[3].trim() }
        }
        return null
      }).filter(Boolean).slice(0, 6)
    }
  } catch (e) {
    console.warn('Parse insight_forge failed:', e)
  }
  
  return result
}

const parsePanorama = (text) => {
  const result = {
    query: '',
    stats: { nodes: 0, edges: 0, activeFacts: 0, historicalFacts: 0 },
    activeFacts: [],
    historicalFacts: [],
    entities: []
  }
  
  try {
    const queryMatch = text.match(/查询:\s*(.+?)(?:\n|$)/)
    if (queryMatch) result.query = queryMatch[1].trim()
    
    const nodesMatch = text.match(/总节点数:\s*(\d+)/)
    const edgesMatch = text.match(/总边数:\s*(\d+)/)
    const activeMatch = text.match(/当前有效事实:\s*(\d+)/)
    const histMatch = text.match(/历史\/过期事实:\s*(\d+)/)
    if (nodesMatch) result.stats.nodes = parseInt(nodesMatch[1])
    if (edgesMatch) result.stats.edges = parseInt(edgesMatch[1])
    if (activeMatch) result.stats.activeFacts = parseInt(activeMatch[1])
    if (histMatch) result.stats.historicalFacts = parseInt(histMatch[1])
    
    const activeSection = text.match(/### 【当前有效事实】[\s\S]*?\n([\s\S]*?)(?=###|$)/)
    if (activeSection) {
      const lines = activeSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.activeFacts = lines.map(l => l.replace(/^\d+\.\s*/, '').replace(/^"|"$/g, '').trim()).slice(0, 8)
    }
    
    const entitySection = text.match(/### 【涉及实体】\n([\s\S]*?)(?=###|$)/)
    if (entitySection) {
      const lines = entitySection[1].split('\n').filter(l => l.startsWith('-'))
      result.entities = lines.map(l => {
        const match = l.match(/^-\s*\*\*(.+?)\*\*\s*\((.+?)\)/)
        if (match) return { name: match[1].trim(), type: match[2].trim() }
        return null
      }).filter(Boolean).slice(0, 10)
    }
  } catch (e) {
    console.warn('Parse panorama failed:', e)
  }
  
  return result
}

const parseInterview = (text) => {
  const result = {
    topic: '',
    agentCount: '',
    successCount: 0,
    totalCount: 0,
    selectionReason: '',
    interviews: [],
    summary: ''
  }
  
  try {
    // 提取采访主题
    const topicMatch = text.match(/\*\*采访主题:\*\*\s*(.+?)(?:\n|$)/)
    if (topicMatch) result.topic = topicMatch[1].trim()
    
    // 提取采访人数（如 "5 / 9 位模拟Agent"）
    const countMatch = text.match(/\*\*采访人数:\*\*\s*(\d+)\s*\/\s*(\d+)/)
    if (countMatch) {
      result.successCount = parseInt(countMatch[1])
      result.totalCount = parseInt(countMatch[2])
      result.agentCount = `${countMatch[1]} / ${countMatch[2]}`
    }
    
    // 提取采访对象选择理由
    const reasonMatch = text.match(/### 采访对象选择理由\n([\s\S]*?)(?=\n---\n|\n### 采访实录)/)
    if (reasonMatch) {
      result.selectionReason = reasonMatch[1].trim()
    }
    
    // 提取每个采访记录
    const interviewBlocks = text.split(/#### 采访 #\d+:/).slice(1)
    
    interviewBlocks.forEach((block, index) => {
      const interview = {
        num: index + 1,
        title: '',
        name: '',
        role: '',
        bio: '',
        questions: [],
        twitterAnswer: '',
        redditAnswer: '',
        quotes: []
      }
      
      // 提取标题（如 "学生"、"教育从业者" 等）
      const titleMatch = block.match(/^(.+?)\n/)
      if (titleMatch) interview.title = titleMatch[1].trim()
      
      // 提取姓名和角色
      const nameRoleMatch = block.match(/\*\*(.+?)\*\*\s*\((.+?)\)/)
      if (nameRoleMatch) {
        interview.name = nameRoleMatch[1].trim()
        interview.role = nameRoleMatch[2].trim()
      }
      
      // 提取简介
      const bioMatch = block.match(/_简介:\s*([\s\S]*?)_\n/)
      if (bioMatch) {
        interview.bio = bioMatch[1].trim().replace(/\.\.\.$/, '...')
      }
      
      // 提取问题列表
      const qMatch = block.match(/\*\*Q:\*\*\s*([\s\S]*?)(?=\n\n\*\*A:\*\*|\*\*A:\*\*)/)
      if (qMatch) {
        const qText = qMatch[1].trim()
        // 按数字编号分割问题
        const questions = qText.split(/\n\d+\.\s+/).filter(q => q.trim())
        if (questions.length > 0) {
          // 如果第一个问题前面有"1."，需要特殊处理
          const firstQ = qText.match(/^1\.\s+(.+)/)
          if (firstQ) {
            interview.questions = [firstQ[1].trim(), ...questions.slice(1).map(q => q.trim())]
          } else {
            interview.questions = questions.map(q => q.trim())
          }
        }
      }
      
      // 提取回答 - 分Twitter和Reddit
      const answerMatch = block.match(/\*\*A:\*\*\s*([\s\S]*?)(?=\*\*关键引言|$)/)
      if (answerMatch) {
        const answerText = answerMatch[1].trim()
        
        // 分离Twitter和Reddit回答
        const twitterMatch = answerText.match(/【Twitter平台回答】\n?([\s\S]*?)(?=【Reddit平台回答】|$)/)
        const redditMatch = answerText.match(/【Reddit平台回答】\n?([\s\S]*?)$/)
        
        if (twitterMatch) {
          interview.twitterAnswer = twitterMatch[1].trim()
        }
        if (redditMatch) {
          interview.redditAnswer = redditMatch[1].trim()
        }
        
        // 如果只有一个平台的回答，将其作为主回答
        // 这样无论显示哪个平台都能有内容
        if (!twitterMatch && redditMatch) {
          // 只有 Reddit 回答，将其也设为 twitterAnswer 作为默认显示
          interview.twitterAnswer = interview.redditAnswer
        } else if (twitterMatch && !redditMatch) {
          // 只有 Twitter 回答，将其也设为 redditAnswer
          interview.redditAnswer = interview.twitterAnswer
        } else if (!twitterMatch && !redditMatch) {
          // 如果没有明确分平台，整体作为回答
          interview.twitterAnswer = answerText
        }
      }
      
      // 提取关键引言
      const quotesMatch = block.match(/\*\*关键引言:\*\*\n([\s\S]*?)(?=\n---|\n####|$)/)
      if (quotesMatch) {
        const quotesText = quotesMatch[1]
        const quoteMatches = quotesText.match(/> "([^"]+)"/g)
        if (quoteMatches) {
          interview.quotes = quoteMatches.map(q => q.replace(/^> "|"$/g, '').trim())
        }
      }
      
      if (interview.name || interview.title) {
        result.interviews.push(interview)
      }
    })
    
    // 提取采访摘要
    const summaryMatch = text.match(/### 采访摘要与核心观点\n([\s\S]*?)$/)
    if (summaryMatch) {
      result.summary = summaryMatch[1].trim()
    }
  } catch (e) {
    console.warn('Parse interview failed:', e)
  }
  
  return result
}

const parseQuickSearch = (text) => {
  const result = {
    query: '',
    count: 0,
    facts: []
  }
  
  try {
    const queryMatch = text.match(/搜索查询:\s*(.+?)(?:\n|$)/)
    if (queryMatch) result.query = queryMatch[1].trim()
    
    const countMatch = text.match(/找到\s*(\d+)\s*条/)
    if (countMatch) result.count = parseInt(countMatch[1])
    
    const factsSection = text.match(/### 相关事实:\n([\s\S]*)$/)
    if (factsSection) {
      const lines = factsSection[1].split('\n').filter(l => l.match(/^\d+\./))
      result.facts = lines.map(l => l.replace(/^\d+\.\s*/, '').trim()).slice(0, 10)
    }
  } catch (e) {
    console.warn('Parse quick_search failed:', e)
  }
  
  return result
}

// ========== Sub Components ==========

// Insight Display Component
const InsightDisplay = {
  props: ['result'],
  setup(props) {
    const expanded = ref(false)
    return () => h('div', { class: 'insight-display' }, [
      // Stats
      h('div', { class: 'stat-row' }, [
        h('div', { class: 'stat-box' }, [
          h('span', { class: 'stat-num' }, props.result.stats.facts),
          h('span', { class: 'stat-label' }, 'Facts')
        ]),
        h('div', { class: 'stat-box' }, [
          h('span', { class: 'stat-num' }, props.result.stats.entities),
          h('span', { class: 'stat-label' }, 'Entities')
        ]),
        h('div', { class: 'stat-box' }, [
          h('span', { class: 'stat-num' }, props.result.stats.relationships),
          h('span', { class: 'stat-label' }, 'Relations')
        ])
      ]),
      // Query
      props.result.query && h('div', { class: 'query-display' }, props.result.query),
      // Expandable content
      h('button', { 
        class: 'expand-details',
        onClick: () => { expanded.value = !expanded.value }
      }, expanded.value ? 'Hide Details' : `Show ${props.result.facts.length} Facts`),
      expanded.value && h('div', { class: 'detail-content' }, [
        props.result.facts.length > 0 && h('div', { class: 'facts-section' }, [
          h('div', { class: 'section-label' }, 'Key Facts'),
          ...props.result.facts.map((fact, i) => h('div', { class: 'fact-row', key: i }, [
            h('span', { class: 'fact-idx' }, i + 1),
            h('span', { class: 'fact-text' }, fact)
          ]))
        ]),
        props.result.entities.length > 0 && h('div', { class: 'entities-section' }, [
          h('div', { class: 'section-label' }, 'Core Entities'),
          h('div', { class: 'entity-chips' },
            props.result.entities.map((e, i) => h('span', { class: 'entity-chip', key: i }, [
              h('span', { class: 'chip-name' }, e.name),
              h('span', { class: 'chip-type' }, e.type)
            ]))
          )
        ]),
        props.result.relations.length > 0 && h('div', { class: 'relations-section' }, [
          h('div', { class: 'section-label' }, 'Relationships'),
          ...props.result.relations.map((r, i) => h('div', { class: 'relation-row', key: i }, [
            h('span', { class: 'rel-node' }, r.source),
            h('span', { class: 'rel-edge' }, r.relation),
            h('span', { class: 'rel-node' }, r.target)
          ]))
        ])
      ])
    ])
  }
}

// Panorama Display Component
const PanoramaDisplay = {
  props: ['result'],
  setup(props) {
    const expanded = ref(false)
    return () => h('div', { class: 'panorama-display' }, [
      h('div', { class: 'stat-row' }, [
        h('div', { class: 'stat-box' }, [
          h('span', { class: 'stat-num' }, props.result.stats.nodes),
          h('span', { class: 'stat-label' }, 'Nodes')
        ]),
        h('div', { class: 'stat-box' }, [
          h('span', { class: 'stat-num' }, props.result.stats.edges),
          h('span', { class: 'stat-label' }, 'Edges')
        ]),
        h('div', { class: 'stat-box highlight' }, [
          h('span', { class: 'stat-num' }, props.result.stats.activeFacts),
          h('span', { class: 'stat-label' }, 'Active')
        ]),
        h('div', { class: 'stat-box muted' }, [
          h('span', { class: 'stat-num' }, props.result.stats.historicalFacts),
          h('span', { class: 'stat-label' }, 'Historical')
        ])
      ]),
      props.result.query && h('div', { class: 'query-display' }, props.result.query),
      h('button', { 
        class: 'expand-details',
        onClick: () => { expanded.value = !expanded.value }
      }, expanded.value ? 'Hide Details' : `Show ${props.result.activeFacts.length} Active Facts`),
      expanded.value && h('div', { class: 'detail-content' }, [
        props.result.activeFacts.length > 0 && h('div', { class: 'facts-section' }, [
          h('div', { class: 'section-label' }, 'Active Facts'),
          ...props.result.activeFacts.map((fact, i) => h('div', { class: 'fact-row active', key: i }, [
            h('span', { class: 'fact-idx' }, i + 1),
            h('span', { class: 'fact-text' }, fact)
          ]))
        ]),
        props.result.entities.length > 0 && h('div', { class: 'entities-section' }, [
          h('div', { class: 'section-label' }, 'Related Entities'),
          h('div', { class: 'entity-chips' },
            props.result.entities.map((e, i) => h('span', { class: 'entity-chip', key: i }, [
              h('span', { class: 'chip-name' }, e.name),
              h('span', { class: 'chip-type' }, e.type)
            ]))
          )
        ])
      ])
    ])
  }
}

// Interview Display Component - Conversation Style (Q&A Format)
const InterviewDisplay = {
  props: ['result', 'resultLength'],
  setup(props) {
    // Format result size for display
    const formatSize = (length) => {
      if (!length) return ''
      if (length >= 1000) {
        return `${(length / 1000).toFixed(1)}k chars`
      }
      return `${length} chars`
    }
    
    // Clean quote text - remove leading list numbers to avoid double numbering
    const cleanQuoteText = (text) => {
      if (!text) return ''
      // Remove leading patterns like "1. ", "2. ", "1、", "（1）", "(1)" etc.
      return text.replace(/^\s*\d+[\.\、\)）]\s*/, '').trim()
    }
    
    const activeIndex = ref(0)
    const expandedAnswers = ref(new Set())
    // 为每个问题-回答对维护独立的平台选择状态
    const platformTabs = reactive({}) // { 'agentIdx-qIdx': 'twitter' | 'reddit' }
    
    // 获取某个问题的当前平台选择
    const getPlatformTab = (agentIdx, qIdx) => {
      const key = `${agentIdx}-${qIdx}`
      return platformTabs[key] || 'twitter'
    }
    
    // 设置某个问题的平台选择
    const setPlatformTab = (agentIdx, qIdx, platform) => {
      const key = `${agentIdx}-${qIdx}`
      platformTabs[key] = platform
    }
    
    const toggleAnswer = (key) => {
      const newSet = new Set(expandedAnswers.value)
      if (newSet.has(key)) {
        newSet.delete(key)
      } else {
        newSet.add(key)
      }
      expandedAnswers.value = newSet
    }
    
    const formatAnswer = (text, expanded) => {
      if (!text) return ''
      if (expanded || text.length <= 400) return text
      return text.substring(0, 400) + '...'
    }
    
    // 尝试按问题编号分割回答
    const splitAnswerByQuestions = (answerText, questionCount) => {
      if (!answerText || questionCount <= 0) return [answerText]
      
      // 更健壮的分割逻辑：查找所有 "数字." 格式的编号位置
      // 支持格式：
      // - "1.  \n内容" （数字+点+空格+换行+内容）
      // - "\n\n2.  \n内容" （换行+数字+点+空格+换行+内容）
      // 使用更宽松的匹配：开头或换行后的数字+点+空白
      const numberPattern = /(?:^|[\r\n]+)(\d+)\.\s+/g
      const matches = []
      let match
      
      while ((match = numberPattern.exec(answerText)) !== null) {
        matches.push({
          num: parseInt(match[1]),
          index: match.index,
          fullMatch: match[0]
        })
      }
      
      // 如果没有找到编号或只找到一个，返回整体
      if (matches.length <= 1) {
        // 尝试移除开头的编号（格式：1.  \n 或 1. ）
        const cleaned = answerText.replace(/^\d+\.\s+/, '').trim()
        return [cleaned || answerText]
      }
      
      // 按编号提取各部分
      const parts = []
      for (let i = 0; i < matches.length; i++) {
        const current = matches[i]
        const next = matches[i + 1]
        
        const startIdx = current.index + current.fullMatch.length
        const endIdx = next ? next.index : answerText.length
        
        let part = answerText.substring(startIdx, endIdx).trim()
        // 移除末尾可能的多余换行
        part = part.replace(/[\r\n]+$/, '').trim()
        parts.push(part)
      }
      
      // 如果分割成功且数量合理，返回分割结果
      if (parts.length > 0 && parts.some(p => p)) {
        return parts
      }
      
      return [answerText]
    }
    
    // 获取某个问题对应的回答
    const getAnswerForQuestion = (interview, qIdx, platform) => {
      const answer = platform === 'twitter' ? interview.twitterAnswer : (interview.redditAnswer || interview.twitterAnswer)
      if (!answer) return ''
      
      const questionCount = interview.questions?.length || 1
      const answers = splitAnswerByQuestions(answer, questionCount)
      
      // 如果只有一个回答部分，或者索引超出，返回完整回答
      if (answers.length === 1 || qIdx >= answers.length) {
        return qIdx === 0 ? answer : ''
      }
      
      return answers[qIdx] || ''
    }
    
    // 检查某个问题是否有双平台回答
    const hasMultiplePlatforms = (interview, qIdx) => {
      if (!interview.twitterAnswer || !interview.redditAnswer) return false
      const twitterAnswer = getAnswerForQuestion(interview, qIdx, 'twitter')
      const redditAnswer = getAnswerForQuestion(interview, qIdx, 'reddit')
      return twitterAnswer && redditAnswer && twitterAnswer !== redditAnswer
    }
    
    return () => h('div', { class: 'interview-display' }, [
      // Header Section
      h('div', { class: 'interview-header' }, [
        h('div', { class: 'header-main' }, [
          h('div', { class: 'header-title' }, 'Agent Interview'),
          h('div', { class: 'header-stats' }, [
            h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.successCount || props.result.interviews.length),
              h('span', { class: 'stat-label' }, 'Interviewed')
            ]),
            props.result.totalCount > 0 && h('span', { class: 'stat-divider' }, '/'),
            props.result.totalCount > 0 && h('span', { class: 'stat-item' }, [
              h('span', { class: 'stat-value' }, props.result.totalCount),
              h('span', { class: 'stat-label' }, 'Total')
            ]),
            props.resultLength && h('span', { class: 'stat-divider' }, '·'),
            props.resultLength && h('span', { class: 'stat-size' }, formatSize(props.resultLength))
          ])
        ]),
        props.result.topic && h('div', { class: 'header-topic' }, props.result.topic)
      ]),
      
      // Agent Selector Tabs
      props.result.interviews.length > 0 && h('div', { class: 'agent-tabs' }, 
        props.result.interviews.map((interview, i) => h('button', {
          class: ['agent-tab', { active: activeIndex.value === i }],
          key: i,
          onClick: () => { activeIndex.value = i }
        }, [
          h('span', { class: 'tab-avatar' }, interview.name ? interview.name.charAt(0) : (i + 1)),
          h('span', { class: 'tab-name' }, interview.title || interview.name || `Agent ${i + 1}`)
        ]))
      ),
      
      // Active Interview Detail
      props.result.interviews.length > 0 && h('div', { class: 'interview-detail' }, [
        // Agent Profile Card
        h('div', { class: 'agent-profile' }, [
          h('div', { class: 'profile-avatar' }, props.result.interviews[activeIndex.value]?.name?.charAt(0) || 'A'),
          h('div', { class: 'profile-info' }, [
            h('div', { class: 'profile-name' }, props.result.interviews[activeIndex.value]?.name || 'Agent'),
            h('div', { class: 'profile-role' }, props.result.interviews[activeIndex.value]?.role || ''),
            props.result.interviews[activeIndex.value]?.bio && h('div', { class: 'profile-bio' }, props.result.interviews[activeIndex.value].bio)
          ])
        ]),
        
        // Q&A Conversation Thread - 一问一答样式
        h('div', { class: 'qa-thread' }, 
          (props.result.interviews[activeIndex.value]?.questions?.length > 0 
            ? props.result.interviews[activeIndex.value].questions 
            : [props.result.interviews[activeIndex.value]?.question || 'No question available']
          ).map((question, qIdx) => {
            const interview = props.result.interviews[activeIndex.value]
            const currentPlatform = getPlatformTab(activeIndex.value, qIdx)
            const answerText = getAnswerForQuestion(interview, qIdx, currentPlatform)
            const hasDualPlatform = hasMultiplePlatforms(interview, qIdx)
            const expandKey = `${activeIndex.value}-${qIdx}`
            const isExpanded = expandedAnswers.value.has(expandKey)
            
            return h('div', { class: 'qa-pair', key: qIdx }, [
              // Question Block
              h('div', { class: 'qa-question' }, [
                h('div', { class: 'qa-badge q-badge' }, `Q${qIdx + 1}`),
                h('div', { class: 'qa-content' }, [
                  h('div', { class: 'qa-sender' }, 'Interviewer'),
                  h('div', { class: 'qa-text' }, question)
                ])
              ]),
              
              // Answer Block
              answerText && h('div', { class: 'qa-answer' }, [
                h('div', { class: 'qa-badge a-badge' }, `A${qIdx + 1}`),
                h('div', { class: 'qa-content' }, [
                  h('div', { class: 'qa-answer-header' }, [
                    h('div', { class: 'qa-sender' }, interview?.name || 'Agent'),
                    // 双平台切换按钮
                    hasDualPlatform && h('div', { class: 'platform-switch' }, [
                      h('button', {
                        class: ['platform-btn', { active: currentPlatform === 'twitter' }],
                        onClick: (e) => { e.stopPropagation(); setPlatformTab(activeIndex.value, qIdx, 'twitter') }
                      }, [
                        h('svg', { class: 'platform-icon', viewBox: '0 0 24 24', width: 12, height: 12, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
                          h('circle', { cx: '12', cy: '12', r: '10' }),
                          h('line', { x1: '2', y1: '12', x2: '22', y2: '12' }),
                          h('path', { d: 'M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z' })
                        ]),
                        h('span', {}, '世界1')
                      ]),
                      h('button', {
                        class: ['platform-btn', { active: currentPlatform === 'reddit' }],
                        onClick: (e) => { e.stopPropagation(); setPlatformTab(activeIndex.value, qIdx, 'reddit') }
                      }, [
                        h('svg', { class: 'platform-icon', viewBox: '0 0 24 24', width: 12, height: 12, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }, [
                          h('path', { d: 'M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z' })
                        ]),
                        h('span', {}, '世界2')
                      ])
                    ])
                  ]),
                  h('div', { 
                    class: 'qa-text answer-text',
                    innerHTML: formatAnswer(answerText, isExpanded)
                      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                      .replace(/\n/g, '<br>')
                  }),
                  // Expand/Collapse Button
                  answerText.length > 400 && h('button', {
                    class: 'expand-answer-btn',
                    onClick: () => toggleAnswer(expandKey)
                  }, isExpanded ? 'Show Less' : 'Show More')
                ])
              ])
            ])
          })
        ),
        
        // Key Quotes Section
        props.result.interviews[activeIndex.value]?.quotes?.length > 0 && h('div', { class: 'quotes-section' }, [
          h('div', { class: 'quotes-header' }, 'Key Quotes'),
          h('div', { class: 'quotes-list' },
            props.result.interviews[activeIndex.value].quotes.slice(0, 3).map((quote, qi) => {
              const cleanedQuote = cleanQuoteText(quote)
              const displayQuote = cleanedQuote.length > 200 ? cleanedQuote.substring(0, 200) + '...' : cleanedQuote
              return h('blockquote', { 
                key: qi, 
                class: 'quote-item',
                innerHTML: renderMarkdown(displayQuote)
              })
            })
          )
        ])
      ]),

      // Summary Section (Collapsible)
      props.result.summary && h('div', { class: 'summary-section' }, [
        h('div', { class: 'summary-header' }, 'Interview Summary'),
        h('div', { 
          class: 'summary-content',
          innerHTML: renderMarkdown(props.result.summary.length > 500 ? props.result.summary.substring(0, 500) + '...' : props.result.summary)
        })
      ])
    ])
  }
}

// Quick Search Display Component
const QuickSearchDisplay = {
  props: ['result'],
  setup(props) {
    const expanded = ref(false)
    return () => h('div', { class: 'quick-search-display' }, [
      h('div', { class: 'search-meta' }, [
        h('span', { class: 'search-query' }, props.result.query),
        h('span', { class: 'search-count' }, `${props.result.count} results`)
      ]),
      h('button', { 
        class: 'expand-details',
        onClick: () => { expanded.value = !expanded.value }
      }, expanded.value ? 'Hide Results' : 'Show Results'),
      expanded.value && props.result.facts.length > 0 && h('div', { class: 'search-results' },
        props.result.facts.map((fact, i) => h('div', { class: 'search-fact', key: i }, [
          h('span', { class: 'fact-idx' }, i + 1),
          h('span', { class: 'fact-text' }, fact)
        ]))
      )
    ])
  }
}

// Computed
const statusClass = computed(() => {
  if (isComplete.value) return 'completed'
  if (agentLogs.value.length > 0) return 'processing'
  return 'pending'
})

const statusText = computed(() => {
  if (isComplete.value) return 'Completed'
  if (agentLogs.value.length > 0) return 'Generating...'
  return 'Waiting'
})

const totalSections = computed(() => {
  return reportOutline.value?.sections?.length || 0
})

const completedSections = computed(() => {
  return Object.keys(generatedSections.value).length
})

const progressPercent = computed(() => {
  if (totalSections.value === 0) return 0
  return Math.round((completedSections.value / totalSections.value) * 100)
})

const totalToolCalls = computed(() => {
  return agentLogs.value.filter(l => l.action === 'tool_call').length
})

const formatElapsedTime = computed(() => {
  if (!startTime.value) return '0s'
  const lastLog = agentLogs.value[agentLogs.value.length - 1]
  const elapsed = lastLog?.elapsed_seconds || 0
  if (elapsed < 60) return `${Math.round(elapsed)}s`
  const mins = Math.floor(elapsed / 60)
  const secs = Math.round(elapsed % 60)
  return `${mins}m ${secs}s`
})

const displayLogs = computed(() => {
  return agentLogs.value
})

// Workflow steps overview (status-based, no nested cards)
const activeSectionIndex = computed(() => {
  if (isComplete.value) return null
  if (currentSectionIndex.value) return currentSectionIndex.value
  if (totalSections.value > 0 && completedSections.value < totalSections.value) return completedSections.value + 1
  return null
})

const isPlanningDone = computed(() => {
  return !!reportOutline.value?.sections?.length || agentLogs.value.some(l => l.action === 'planning_complete')
})

const isPlanningStarted = computed(() => {
  return agentLogs.value.some(l => l.action === 'planning_start' || l.action === 'report_start')
})

const isFinalizing = computed(() => {
  return !isComplete.value && isPlanningDone.value && totalSections.value > 0 && completedSections.value >= totalSections.value
})

// 当前活跃的步骤（用于顶部显示）
const activeStep = computed(() => {
  const steps = workflowSteps.value
  // 找到当前 active 的步骤
  const active = steps.find(s => s.status === 'active')
  if (active) return active
  
  // 如果没有 active，返回最后一个 done 的步骤
  const doneSteps = steps.filter(s => s.status === 'done')
  if (doneSteps.length > 0) return doneSteps[doneSteps.length - 1]
  
  // 否则返回第一个步骤
  return steps[0] || { noLabel: '--', title: '等待开始', status: 'todo', meta: '' }
})

const workflowSteps = computed(() => {
  const steps = []

  // Planning / Outline
  const planningStatus = isPlanningDone.value ? 'done' : (isPlanningStarted.value ? 'active' : 'todo')
  steps.push({
    key: 'planning',
    noLabel: 'PL',
    title: 'Planning / Outline',
    status: planningStatus,
    meta: planningStatus === 'active' ? 'IN PROGRESS' : ''
  })

  // Sections (if outline exists)
  const sections = reportOutline.value?.sections || []
  sections.forEach((section, i) => {
    const idx = i + 1
    const status = (isComplete.value || !!generatedSections.value[idx])
      ? 'done'
      : (activeSectionIndex.value === idx ? 'active' : 'todo')

    steps.push({
      key: `section-${idx}`,
      noLabel: String(idx).padStart(2, '0'),
      title: section.title,
      status,
      meta: status === 'active' ? 'IN PROGRESS' : ''
    })
  })

  // Complete
  const completeStatus = isComplete.value ? 'done' : (isFinalizing.value ? 'active' : 'todo')
  steps.push({
    key: 'complete',
    noLabel: 'OK',
    title: 'Complete',
    status: completeStatus,
    meta: completeStatus === 'active' ? 'FINALIZING' : ''
  })

  return steps
})

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

const isSectionCompleted = (sectionIndex) => {
  return !!generatedSections.value[sectionIndex]
}

// 从 section_index 获取主章节索引
// 后端编号方案：主章节 1,2,3... 子章节 101,102（第1章子章节1,2）
const getMainSectionIndex = (sectionIndex) => {
  if (sectionIndex >= 100) {
    return Math.floor(sectionIndex / 100)
  }
  return sectionIndex
}

// 判断是否是子章节
const isSubsection = (sectionIndex) => {
  return sectionIndex >= 100
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit' 
    })
  } catch {
    return ''
  }
}

const formatParams = (params) => {
  if (!params) return ''
  try {
    return JSON.stringify(params, null, 2)
  } catch {
    return String(params)
  }
}

const formatResultSize = (length) => {
  if (!length) return ''
  if (length < 1000) return `${length} chars`
  return `${(length / 1000).toFixed(1)}k chars`
}

const truncateText = (text, maxLen) => {
  if (!text) return ''
  if (text.length <= maxLen) return text
  return text.substring(0, maxLen) + '...'
}

const renderMarkdown = (content) => {
  if (!content) return ''
  
  // 去掉开头的二级标题（## xxx），因为章节标题已在外层显示
  let processedContent = content.replace(/^##\s+.+\n+/, '')
  
  // 处理代码块
  let html = processedContent.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  
  // 处理行内代码
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  
  // 处理标题
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')
  
  // 处理引用块
  html = html.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  
  // 处理无序列表
  html = html.replace(/^- (.+)$/gm, '<li class="md-li">$1</li>')
  html = html.replace(/(<li class="md-li">[\s\S]*?<\/li>)(\s*<li)/g, '$1$2')
  html = html.replace(/(<li class="md-li">.*<\/li>)+/g, '<ul class="md-ul">$&</ul>')
  
  // 处理有序列表
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="md-oli">$1</li>')
  html = html.replace(/(<li class="md-oli">.*<\/li>)+/g, '<ol class="md-ol">$&</ol>')
  
  // 处理粗体和斜体
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  
  // 处理分隔线
  html = html.replace(/^---$/gm, '<hr class="md-hr">')
  
  // 处理换行 - 空行变成段落分隔，单换行变成 <br>
  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  
  // 包装在段落中
  html = '<p class="md-p">' + html + '</p>'
  
  // 清理空段落
  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>)<\/p>/g, '$1')
  
  return html
}

const getTimelineItemClass = (log, idx, total) => {
  const isLatest = idx === total - 1 && !isComplete.value
  const isMilestone = log.action === 'section_complete' || log.action === 'report_complete'
  return {
    'node--active': isLatest,
    'node--done': !isLatest && isMilestone,
    'node--muted': !isLatest && !isMilestone,
    'node--tool': log.action === 'tool_call' || log.action === 'tool_result'
  }
}

const getConnectorClass = (log, idx, total) => {
  const isLatest = idx === total - 1 && !isComplete.value
  if (isLatest) return 'dot-active'
  if (log.action === 'section_complete' || log.action === 'report_complete') return 'dot-done'
  return 'dot-muted'
}

const getActionLabel = (action) => {
  const labels = {
    'report_start': 'Report Started',
    'planning_start': 'Planning',
    'planning_complete': 'Plan Complete',
    'section_start': 'Section Start',
    'section_content': 'Content Ready',
    'subsection_content': 'Subsection Ready',
    'section_complete': 'Section Done',
    'tool_call': 'Tool Call',
    'tool_result': 'Tool Result',
    'llm_response': 'LLM Response',
    'report_complete': 'Complete'
  }
  return labels[action] || action
}

const getLogLevelClass = (log) => {
  if (log.includes('ERROR') || log.includes('错误')) return 'error'
  if (log.includes('WARNING') || log.includes('警告')) return 'warning'
  // INFO 使用默认颜色，不标记为 success
  return ''
}

// Polling
let agentLogTimer = null
let consoleLogTimer = null

const fetchAgentLog = async () => {
  if (!props.reportId) return
  
  try {
    const res = await getAgentLog(props.reportId, agentLogLine.value)
    
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      
      if (newLogs.length > 0) {
        newLogs.forEach(log => {
          agentLogs.value.push(log)
          
          if (log.action === 'planning_complete' && log.details?.outline) {
            reportOutline.value = log.details.outline
          }
          
          if (log.action === 'section_start') {
            // 无论是主章节还是子章节开始，都映射到主章节索引
            // 后端编号：主章节 1,2,3... 子章节 101,102（第1章子章节1,2）
            const mainIndex = getMainSectionIndex(log.section_index)
            currentSectionIndex.value = mainIndex
          }
          
          // section_content / subsection_content - 表示内容生成完成（但整个章节可能还没完成）
          // 这里不更新 generatedSections，只记录进度
          if (log.action === 'section_content' || log.action === 'subsection_content') {
            // 子章节内容生成时，保持主章节的 loading 状态
            // 因为完整内容会在 section_complete 时一次性提供
          }
          
          // section_complete - 表示完整章节（含所有子章节）生成完成
          // details.content 包含合并后的完整内容
          // 注意：只有主章节 complete 时才更新内容，子章节 complete 不处理
          if (log.action === 'section_complete') {
            const mainIndex = getMainSectionIndex(log.section_index)
            // 只有主章节完成时（section_index < 100）才更新内容和清除 loading
            if (!isSubsection(log.section_index) && log.details?.content) {
              generatedSections.value[mainIndex] = log.details.content
              // 自动展开刚生成的章节
              expandedContent.value.add(mainIndex - 1)
              currentSectionIndex.value = null
            }
            // 子章节完成时不清除 currentSectionIndex，继续显示 loading
          }
          
          if (log.action === 'report_complete') {
            isComplete.value = true
            currentSectionIndex.value = null  // 确保清除 loading 状态
            emit('update-status', 'completed')
            stopPolling()
            // 任务完成后，滚动右侧面板到顶部
            nextTick(() => {
              if (rightPanel.value) {
                rightPanel.value.scrollTop = 0
              }
            })
          }
          
          if (log.action === 'report_start') {
            startTime.value = new Date(log.timestamp)
          }
        })
        
        agentLogLine.value = res.data.from_line + newLogs.length
        
        nextTick(() => {
          if (rightPanel.value) {
            rightPanel.value.scrollTop = rightPanel.value.scrollHeight
          }
        })
      }
    }
  } catch (err) {
    console.warn('Failed to fetch agent log:', err)
  }
}

// 提取最终答案内容 - 从 LLM response 中提取章节内容
const extractFinalContent = (response) => {
  if (!response) return null
  
  // 尝试提取 <final_answer> 标签内的内容
  const finalAnswerTagMatch = response.match(/<final_answer>([\s\S]*?)<\/final_answer>/)
  if (finalAnswerTagMatch) {
    return finalAnswerTagMatch[1].trim()
  }
  
  // 尝试找 Final Answer: 后面的内容（支持多种格式）
  // 格式1: Final Answer:\n\n内容
  // 格式2: Final Answer: 内容
  const finalAnswerMatch = response.match(/Final\s*Answer:\s*\n*([\s\S]*)$/i)
  if (finalAnswerMatch) {
    return finalAnswerMatch[1].trim()
  }
  
  // 尝试找 最终答案: 后面的内容
  const chineseFinalMatch = response.match(/最终答案[:：]\s*\n*([\s\S]*)$/i)
  if (chineseFinalMatch) {
    return chineseFinalMatch[1].trim()
  }
  
  // 如果以 ## 或 # 或 > 开头，可能是直接的 markdown 内容
  const trimmedResponse = response.trim()
  if (trimmedResponse.match(/^[#>]/)) {
    return trimmedResponse
  }
  
  // 如果内容较长且包含markdown格式，尝试移除思考过程后返回
  if (response.length > 300 && (response.includes('**') || response.includes('>'))) {
    // 移除 Thought: 开头的思考过程
    const thoughtMatch = response.match(/^Thought:[\s\S]*?(?=\n\n[^T]|\n\n$)/i)
    if (thoughtMatch) {
      const afterThought = response.substring(thoughtMatch[0].length).trim()
      if (afterThought.length > 100) {
        return afterThought
      }
    }
  }
  
  return null
}

const fetchConsoleLog = async () => {
  if (!props.reportId) return
  
  try {
    const res = await getConsoleLog(props.reportId, consoleLogLine.value)
    
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      
      if (newLogs.length > 0) {
        consoleLogs.value.push(...newLogs)
        consoleLogLine.value = res.data.from_line + newLogs.length
        
        nextTick(() => {
          if (logContent.value) {
            logContent.value.scrollTop = logContent.value.scrollHeight
          }
        })
      }
    }
  } catch (err) {
    console.warn('Failed to fetch console log:', err)
  }
}

const startPolling = () => {
  if (agentLogTimer || consoleLogTimer) return
  
  fetchAgentLog()
  fetchConsoleLog()
  
  agentLogTimer = setInterval(fetchAgentLog, 2000)
  consoleLogTimer = setInterval(fetchConsoleLog, 1500)
}

const stopPolling = () => {
  if (agentLogTimer) {
    clearInterval(agentLogTimer)
    agentLogTimer = null
  }
  if (consoleLogTimer) {
    clearInterval(consoleLogTimer)
    consoleLogTimer = null
  }
}

// Lifecycle
onMounted(() => {
  if (props.reportId) {
    addLog(`Report Agent initialized: ${props.reportId}`)
    startPolling()
  }
})

onUnmounted(() => {
  stopPolling()
})

watch(() => props.reportId, (newId) => {
  if (newId) {
    agentLogs.value = []
    consoleLogs.value = []
    agentLogLine.value = 0
    consoleLogLine.value = 0
    reportOutline.value = null
    currentSectionIndex.value = null
    generatedSections.value = {}
    expandedContent.value = new Set()
    expandedLogs.value = new Set()
    collapsedSections.value = new Set()
    isComplete.value = false
    startTime.value = null
    
    startPolling()
  }
}, { immediate: true })
</script>

<style scoped>
.report-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #F8F9FA;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  overflow: hidden;
}

/* Main Split Layout */
.main-split-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Panel Headers */
.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  background: #FFFFFF;
  border-bottom: 1px solid #E5E7EB;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  position: sticky;
  top: 0;
  z-index: 10;
}

.header-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #1F2937;
  box-shadow: 0 0 0 3px rgba(31, 41, 55, 0.15);
  margin-right: 10px;
  flex-shrink: 0;
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% {
    box-shadow: 0 0 0 3px rgba(31, 41, 55, 0.15);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(31, 41, 55, 0.1);
  }
}

.header-index {
  font-size: 12px;
  font-weight: 600;
  color: #9CA3AF;
  margin-right: 10px;
  flex-shrink: 0;
}

.header-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-transform: none;
  letter-spacing: 0;
}

.header-meta {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  color: #6B7280;
  flex-shrink: 0;
}

/* Panel header status variants */
.panel-header--active {
  background: #FAFAFA;
  border-color: #1F2937;
}

.panel-header--active .header-index {
  color: #1F2937;
}

.panel-header--active .header-title {
  color: #1F2937;
}

.panel-header--active .header-meta {
  color: #1F2937;
}

.panel-header--done {
  background: #F9FAFB;
}

.panel-header--done .header-index {
  color: #10B981;
}

.panel-header--todo .header-index,
.panel-header--todo .header-title {
  color: #9CA3AF;
}

/* Left Panel - Report Style */
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
  margin-bottom: 50px;
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
  color: #E5E7EB; /* Very light gray for number initially */
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
  font-family: 'Inter', -apple-system, sans-serif;
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

.cursor-blink {
  display: inline-block;
  width: 8px;
  height: 14px;
  background: #8B5CF6;
  opacity: 0.5;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0; }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Content Styles Override for this view */
.generated-content :deep(.md-h2) {
  font-family: 'Times New Roman', Times, serif;
  font-size: 18px;
  margin-top: 0;
}


/* Slide Content Transition */
.slide-content-enter-active {
  transition: opacity 0.3s ease-out;
}

.slide-content-leave-active {
  transition: opacity 0.2s ease-in;
}

.slide-content-enter-from,
.slide-content-leave-to {
  opacity: 0;
}

.slide-content-enter-to,
.slide-content-leave-from {
  opacity: 1;
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

/* Right Panel */
.right-panel {
  flex: 1;
  background: #FFFFFF;
  overflow-y: auto;
  display: flex;
  flex-direction: column;

  /* Functional palette (low saturation, status-based) */
  --wf-border: #E5E7EB;
  --wf-divider: #F3F4F6;

  --wf-active-bg: #FAFAFA;
  --wf-active-border: #1F2937;
  --wf-active-dot: #1F2937;
  --wf-active-text: #1F2937;

  --wf-done-bg: #F9FAFB;
  --wf-done-border: #E5E7EB;
  --wf-done-dot: #10B981;

  --wf-muted-dot: #D1D5DB;
  --wf-todo-text: #9CA3AF;
}

.right-panel::-webkit-scrollbar {
  width: 6px;
}

.right-panel::-webkit-scrollbar-track {
  background: transparent;
}

.right-panel::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
  transition: background 0.3s ease;
}

.right-panel:hover::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
}

.right-panel::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.25);
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

/* Workflow Overview */
.workflow-overview {
  padding: 16px 20px 0 20px;
}

.workflow-metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.metric {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}

.metric-right {
  margin-left: auto;
}

.metric-label {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-value {
  font-size: 12px;
  color: #374151;
}

.metric-pill {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--wf-border);
  background: #F9FAFB;
  color: #6B7280;
}

.metric-pill.pill--processing {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
  color: var(--wf-active-text);
}

.metric-pill.pill--completed {
  background: #ECFDF5;
  border-color: #A7F3D0;
  color: #065F46;
}

.metric-pill.pill--pending {
  background: transparent;
  border-style: dashed;
  color: #6B7280;
}

.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 10px;
}

.wf-step {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
}

.wf-step--active {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.wf-step--done {
  background: var(--wf-done-bg);
  border-color: var(--wf-done-border);
}

.wf-step--todo {
  background: transparent;
  border-color: var(--wf-border);
  border-style: dashed;
}

.wf-step-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 24px;
  flex-shrink: 0;
}

.wf-step-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--wf-muted-dot);
  border: 2px solid #FFFFFF;
  z-index: 1;
}

.wf-step-line {
  width: 2px;
  flex: 1;
  background: var(--wf-divider);
  margin-top: -2px;
}

.wf-step--active .wf-step-dot {
  background: var(--wf-active-dot);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.wf-step--done .wf-step-dot {
  background: var(--wf-done-dot);
}

.wf-step-title-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.wf-step-index {
  font-size: 11px;
  font-weight: 700;
  color: #9CA3AF;
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.wf-step-title {
  font-family: 'Times New Roman', Times, serif;
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  line-height: 1.35;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-step-meta {
  margin-left: auto;
  font-size: 10px;
  font-weight: 700;
  color: var(--wf-active-text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.wf-step--todo .wf-step-title,
.wf-step--todo .wf-step-index {
  color: var(--wf-todo-text);
}

.workflow-divider {
  height: 1px;
  background: var(--wf-divider);
  margin: 14px 0 0 0;
}

/* Workflow Timeline */
.workflow-timeline {
  padding: 14px 20px 24px;
  flex: 1;
}

.timeline-item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--wf-divider);
  border-radius: 8px;
  background: #FFFFFF;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.timeline-item:hover {
  background: #F9FAFB;
  border-color: var(--wf-border);
}

.timeline-item.node--active {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.timeline-item.node--active:hover {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.timeline-item.node--done {
  background: var(--wf-done-bg);
  border-color: var(--wf-done-border);
}

.timeline-item.node--done:hover {
  background: var(--wf-done-bg);
  border-color: var(--wf-done-border);
}

.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 24px;
  flex-shrink: 0;
}

.connector-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--wf-muted-dot);
  border: 2px solid #FFFFFF;
  z-index: 1;
}

.connector-line {
  width: 2px;
  flex: 1;
  background: var(--wf-divider);
  margin-top: -2px;
}

/* Connector dot: status only */
.dot-active {
  background: var(--wf-active-dot);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.dot-done {
  background: var(--wf-done-dot);
}

.dot-muted {
  background: var(--wf-muted-dot);
}

.timeline-content {
  min-width: 0;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  margin: 0;
  transition: none;
}

.timeline-content:hover {
  box-shadow: none;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.action-label {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.action-time {
  font-size: 11px;
  color: #9CA3AF;
  font-family: 'JetBrains Mono', monospace;
}

.timeline-body {
  font-size: 13px;
  color: #4B5563;
}

.timeline-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #F3F4F6;
}

.elapsed-placeholder {
  flex-shrink: 0;
}

.footer-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.elapsed-badge {
  font-size: 11px;
  color: #6B7280;
  background: #F3F4F6;
  padding: 2px 8px;
  border-radius: 10px;
  font-family: 'JetBrains Mono', monospace;
}

/* Timeline Body Elements */
.info-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}

.info-key {
  font-size: 11px;
  color: #9CA3AF;
  min-width: 80px;
}

.info-val {
  color: #374151;
}

.status-message {
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  border: 1px solid transparent;
}

.status-message.planning {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
  color: var(--wf-active-text);
}

.status-message.success {
  background: #ECFDF5;
  border-color: #A7F3D0;
  color: #065F46;
}

.outline-badge {
  display: inline-block;
  margin-top: 8px;
  padding: 4px 10px;
  background: #F9FAFB;
  color: #6B7280;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
}

.section-tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #F9FAFB;
  border: 1px solid var(--wf-border);
  border-radius: 6px;
}

.section-tag.content-ready {
  background: var(--wf-active-bg);
  border: 1px dashed var(--wf-active-border);
}

.section-tag.content-ready svg {
  color: var(--wf-active-dot);
}

.section-tag.content-ready.is-subsection {
  background: var(--wf-active-bg);
  border-color: var(--wf-active-border);
}

.section-tag.completed {
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
}

.section-tag.completed svg {
  color: #059669;
}

.tag-num {
  font-size: 11px;
  font-weight: 700;
  color: #6B7280;
}

.section-tag.completed .tag-num {
  color: #059669;
}

.tag-title {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
}

.tag-sub {
  font-size: 11px;
  color: #6B7280;
  margin-left: 4px;
}

.tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #F9FAFB;
  color: #374151;
  border: 1px solid var(--wf-border);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.2s ease;
}

.tool-icon {
  flex-shrink: 0;
}

/* Tool Colors - Purple (Deep Insight) */
.tool-badge.tool-purple {
  background: linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%);
  border-color: #C4B5FD;
  color: #6D28D9;
}
.tool-badge.tool-purple .tool-icon {
  stroke: #7C3AED;
}

/* Tool Colors - Blue (Panorama Search) */
.tool-badge.tool-blue {
  background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
  border-color: #93C5FD;
  color: #1D4ED8;
}
.tool-badge.tool-blue .tool-icon {
  stroke: #2563EB;
}

/* Tool Colors - Green (Agent Interview) */
.tool-badge.tool-green {
  background: linear-gradient(135deg, #F0FDF4 0%, #DCFCE7 100%);
  border-color: #86EFAC;
  color: #15803D;
}
.tool-badge.tool-green .tool-icon {
  stroke: #16A34A;
}

/* Tool Colors - Orange (Quick Search) */
.tool-badge.tool-orange {
  background: linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%);
  border-color: #FDBA74;
  color: #C2410C;
}
.tool-badge.tool-orange .tool-icon {
  stroke: #EA580C;
}

/* Tool Colors - Cyan (Graph Stats) */
.tool-badge.tool-cyan {
  background: linear-gradient(135deg, #ECFEFF 0%, #CFFAFE 100%);
  border-color: #67E8F9;
  color: #0E7490;
}
.tool-badge.tool-cyan .tool-icon {
  stroke: #0891B2;
}

/* Tool Colors - Pink (Entity Query) */
.tool-badge.tool-pink {
  background: linear-gradient(135deg, #FDF2F8 0%, #FCE7F3 100%);
  border-color: #F9A8D4;
  color: #BE185D;
}
.tool-badge.tool-pink .tool-icon {
  stroke: #DB2777;
}

/* Tool Colors - Gray (Default) */
.tool-badge.tool-gray {
  background: linear-gradient(135deg, #F9FAFB 0%, #F3F4F6 100%);
  border-color: #D1D5DB;
  color: #374151;
}
.tool-badge.tool-gray .tool-icon {
  stroke: #6B7280;
}

.tool-params {
  margin-top: 10px;
  background: transparent;
  border-radius: 0;
  padding: 10px 0 0 0;
  border-top: 1px dashed var(--wf-divider);
  overflow-x: auto;
}

.tool-params pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #4B5563;
  white-space: pre-wrap;
  word-break: break-all;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px;
}

/* Unified Action Buttons */
.action-btn {
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.action-btn:hover {
  background: #E5E7EB;
  color: #374151;
  border-color: #D1D5DB;
}

/* Result Wrapper */
.result-wrapper {
  background: transparent;
  border: none;
  border-top: 1px solid var(--wf-divider);
  border-radius: 0;
  padding: 12px 0 0 0;
}

.result-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.result-tool {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

.result-size {
  font-size: 10px;
  color: #6B7280;
  font-family: 'JetBrains Mono', monospace;
}

.result-raw {
  margin-top: 10px;
  max-height: 300px;
  overflow-y: auto;
}

.result-raw pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #374151;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  padding: 10px;
  border-radius: 6px;
}

.raw-preview {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #6B7280;
}

/* Legacy toggle-raw removed - using unified .action-btn */

/* LLM Response */
.llm-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 11px;
  padding: 3px 8px;
  background: #F3F4F6;
  color: #6B7280;
  border-radius: 4px;
}

.meta-tag.active {
  background: #DBEAFE;
  color: #1E40AF;
}

.meta-tag.final-answer {
  background: #D1FAE5;
  color: #059669;
  font-weight: 600;
}

.final-answer-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 10px 14px;
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  border-radius: 6px;
  color: #065F46;
  font-size: 12px;
  font-weight: 500;
}

.final-answer-hint svg {
  flex-shrink: 0;
}

.llm-content {
  margin-top: 10px;
  max-height: 200px;
  overflow-y: auto;
}

.llm-content pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #4B5563;
  background: #F3F4F6;
  padding: 10px;
  border-radius: 6px;
}

/* Complete Banner */
.complete-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  border-radius: 8px;
  color: #065F46;
  font-weight: 600;
  font-size: 14px;
}

/* Workflow Empty */
.workflow-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #9CA3AF;
  font-size: 13px;
}

.empty-pulse {
  width: 24px;
  height: 24px;
  background: #E5E7EB;
  border-radius: 50%;
  margin-bottom: 16px;
  animation: pulse-ring 1.5s infinite;
}

@keyframes pulse-ring {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.2); opacity: 0.5; }
}

/* Timeline Transitions */
.timeline-item-enter-active {
  transition: all 0.4s ease;
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

/* ========== Structured Result Display Components ========== */

/* Common Styles - using :deep() for dynamic components */
:deep(.stat-row) {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

:deep(.stat-box) {
  flex: 1;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px 8px;
  text-align: center;
}

:deep(.stat-box .stat-num) {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #111827;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.stat-box .stat-label) {
  display: block;
  font-size: 10px;
  color: #9CA3AF;
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

:deep(.stat-box.highlight) {
  background: #ECFDF5;
  border-color: #A7F3D0;
}

:deep(.stat-box.highlight .stat-num) {
  color: #059669;
}

:deep(.stat-box.muted) {
  background: #F9FAFB;
  border-color: #E5E7EB;
}

:deep(.stat-box.muted .stat-num) {
  color: #6B7280;
}

:deep(.query-display) {
  background: #F9FAFB;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  color: #374151;
  margin-bottom: 12px;
  border: 1px solid #E5E7EB;
  line-height: 1.5;
}

:deep(.expand-details) {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.expand-details:hover) {
  border-color: #D1D5DB;
  color: #374151;
}

:deep(.detail-content) {
  margin-top: 14px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  padding: 14px;
}

:deep(.section-label) {
  font-size: 11px;
  font-weight: 600;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #F3F4F6;
}

/* Facts Section */
:deep(.facts-section) {
  margin-bottom: 14px;
}

:deep(.fact-row) {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.fact-row:last-child) {
  border-bottom: none;
}

:deep(.fact-row.active) {
  background: #ECFDF5;
  margin: 0 -10px;
  padding: 8px 10px;
  border-radius: 6px;
  border-bottom: none;
}

:deep(.fact-idx) {
  min-width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #F3F4F6;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  color: #6B7280;
  flex-shrink: 0;
}

:deep(.fact-row.active .fact-idx) {
  background: #A7F3D0;
  color: #065F46;
}

:deep(.fact-text) {
  font-size: 12px;
  color: #4B5563;
  line-height: 1.6;
}

/* Entities Section */
:deep(.entities-section) {
  margin-bottom: 14px;
}

:deep(.entity-chips) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.entity-chip) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 6px 12px;
}

:deep(.chip-name) {
  font-size: 12px;
  font-weight: 500;
  color: #111827;
}

:deep(.chip-type) {
  font-size: 10px;
  color: #9CA3AF;
  background: #E5E7EB;
  padding: 1px 6px;
  border-radius: 3px;
}

/* Relations Section */
:deep(.relations-section) {
  margin-bottom: 14px;
}

:deep(.relation-row) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  flex-wrap: wrap;
  border-bottom: 1px solid #F3F4F6;
}

:deep(.relation-row:last-child) {
  border-bottom: none;
}

:deep(.rel-node) {
  font-size: 12px;
  font-weight: 500;
  color: #111827;
  background: #F3F4F6;
  padding: 4px 10px;
  border-radius: 4px;
}

:deep(.rel-edge) {
  font-size: 10px;
  font-weight: 600;
  color: #FFFFFF;
  background: #4F46E5;
  padding: 3px 10px;
  border-radius: 10px;
}

/* ========== Interview Display - Conversation Style ========== */
:deep(.interview-display) {
  padding: 0;
}

/* Header */
:deep(.interview-display .interview-header) {
  padding: 0;
  background: transparent;
  border-bottom: none;
  margin-bottom: 16px;
}

:deep(.interview-display .header-main) {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

:deep(.interview-display .header-title) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  letter-spacing: -0.01em;
}

:deep(.interview-display .header-stats) {
  display: flex;
  align-items: center;
  gap: 6px;
}

:deep(.interview-display .stat-item) {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

:deep(.interview-display .stat-value) {
  font-size: 14px;
  font-weight: 600;
  color: #4F46E5;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.interview-display .stat-label) {
  font-size: 11px;
  color: #9CA3AF;
  text-transform: lowercase;
}

:deep(.interview-display .stat-divider) {
  color: #D1D5DB;
  font-size: 12px;
}

:deep(.interview-display .stat-size) {
  font-size: 11px;
  color: #9CA3AF;
  font-family: 'JetBrains Mono', monospace;
}

:deep(.interview-display .header-topic) {
  margin-top: 4px;
  font-size: 12px;
  color: #6B7280;
  line-height: 1.5;
}

/* Agent Tabs - Card Style */
:deep(.interview-display .agent-tabs) {
  display: flex;
  gap: 8px;
  padding: 0 0 14px 0;
  background: transparent;
  border-bottom: 1px solid #F3F4F6;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: #E5E7EB transparent;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar) {
  height: 4px;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar-track) {
  background: transparent;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar-thumb) {
  background: #E5E7EB;
  border-radius: 2px;
}

:deep(.interview-display .agent-tabs::-webkit-scrollbar-thumb:hover) {
  background: #D1D5DB;
}

:deep(.interview-display .agent-tab) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

:deep(.interview-display .agent-tab:hover) {
  background: #F3F4F6;
  border-color: #D1D5DB;
  color: #374151;
}

:deep(.interview-display .agent-tab.active) {
  background: linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%);
  border-color: #A5B4FC;
  color: #4338CA;
  box-shadow: 0 1px 2px rgba(99, 102, 241, 0.1);
}

:deep(.interview-display .tab-avatar) {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  color: #6B7280;
  font-size: 10px;
  font-weight: 700;
  border-radius: 50%;
  flex-shrink: 0;
}

:deep(.interview-display .agent-tab:hover .tab-avatar) {
  background: #D1D5DB;
}

:deep(.interview-display .agent-tab.active .tab-avatar) {
  background: #6366F1;
  color: #FFFFFF;
}

:deep(.interview-display .tab-name) {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Interview Detail */
:deep(.interview-display .interview-detail) {
  padding: 12px 0;
  background: transparent;
}

/* Agent Profile - No card */
:deep(.interview-display .agent-profile) {
  display: flex;
  gap: 12px;
  padding: 0;
  background: transparent;
  border: none;
  margin-bottom: 16px;
}

:deep(.interview-display .profile-avatar) {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  color: #6B7280;
  font-size: 14px;
  font-weight: 600;
  border-radius: 50%;
  flex-shrink: 0;
}

:deep(.interview-display .profile-info) {
  flex: 1;
  min-width: 0;
}

:deep(.interview-display .profile-name) {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 2px;
}

:deep(.interview-display .profile-role) {
  font-size: 11px;
  color: #6B7280;
  margin-bottom: 4px;
}

:deep(.interview-display .profile-bio) {
  font-size: 11px;
  color: #9CA3AF;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Q&A Thread - Clean list */
:deep(.interview-display .qa-thread) {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

:deep(.interview-display .qa-pair) {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

:deep(.interview-display .qa-question),
:deep(.interview-display .qa-answer) {
  display: flex;
  gap: 12px;
}

:deep(.interview-display .qa-badge) {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  flex-shrink: 0;
}

:deep(.interview-display .q-badge) {
  background: transparent;
  color: #9CA3AF;
  border: 1px solid #E5E7EB;
}

:deep(.interview-display .a-badge) {
  background: #4F46E5;
  color: #FFFFFF;
  border: 1px solid #4F46E5;
}

:deep(.interview-display .qa-content) {
  flex: 1;
  min-width: 0;
}

:deep(.interview-display .qa-sender) {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

:deep(.interview-display .qa-text) {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}

:deep(.interview-display .qa-answer) {
  background: transparent;
  padding: 0;
  border: none;
  margin-top: 0;
}

:deep(.interview-display .qa-answer-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

/* Platform Switch */
:deep(.interview-display .platform-switch) {
  display: flex;
  gap: 2px;
  background: transparent;
  padding: 0;
  border-radius: 0;
}

:deep(.interview-display .platform-btn) {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #9CA3AF;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.interview-display .platform-btn:hover) {
  color: #6B7280;
}

:deep(.interview-display .platform-btn.active) {
  background: transparent;
  color: #4F46E5;
  border-color: #E5E7EB;
  box-shadow: none;
}

:deep(.interview-display .platform-icon) {
  flex-shrink: 0;
}

:deep(.interview-display .answer-text) {
  font-size: 13px;
  color: #111827;
  line-height: 1.6;
}

:deep(.interview-display .answer-text strong) {
  color: #111827;
  font-weight: 600;
}

:deep(.interview-display .expand-answer-btn) {
  display: inline-block;
  margin-top: 8px;
  padding: 0;
  background: transparent;
  border: none;
  border-bottom: 1px dotted #D1D5DB;
  border-radius: 0;
  font-size: 11px;
  font-weight: 500;
  color: #9CA3AF;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.interview-display .expand-answer-btn:hover) {
  background: transparent;
  color: #6B7280;
  border-bottom-style: solid;
}

/* Quotes Section - Clean list */
:deep(.interview-display .quotes-section) {
  background: transparent;
  border: none;
  border-top: 1px solid #F3F4F6;
  border-radius: 0;
  padding: 16px 0 0 0;
  margin-top: 16px;
}

:deep(.interview-display .quotes-header) {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 12px;
}

:deep(.interview-display .quotes-list) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

:deep(.interview-display .quote-item) {
  margin: 0;
  padding: 10px 12px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  font-size: 12px;
  font-style: italic;
  color: #4B5563;
  line-height: 1.5;
}

/* Summary Section */
:deep(.interview-display .summary-section) {
  margin-top: 20px;
  padding: 16px 0 0 0;
  background: transparent;
  border: none;
  border-top: 1px solid #F3F4F6;
  border-radius: 0;
}

:deep(.interview-display .summary-header) {
  font-size: 11px;
  font-weight: 600;
  color: #9CA3AF;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

:deep(.interview-display .summary-content) {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}

/* Markdown styles in summary */
:deep(.interview-display .summary-content h2),
:deep(.interview-display .summary-content h3),
:deep(.interview-display .summary-content h4),
:deep(.interview-display .summary-content h5) {
  margin: 12px 0 8px 0;
  font-weight: 600;
  color: #111827;
}

:deep(.interview-display .summary-content h2) {
  font-size: 15px;
}

:deep(.interview-display .summary-content h3) {
  font-size: 14px;
}

:deep(.interview-display .summary-content h4),
:deep(.interview-display .summary-content h5) {
  font-size: 13px;
}

:deep(.interview-display .summary-content p) {
  margin: 8px 0;
}

:deep(.interview-display .summary-content strong) {
  font-weight: 600;
  color: #111827;
}

:deep(.interview-display .summary-content em) {
  font-style: italic;
}

:deep(.interview-display .summary-content ul),
:deep(.interview-display .summary-content ol) {
  margin: 8px 0;
  padding-left: 20px;
}

:deep(.interview-display .summary-content li) {
  margin: 4px 0;
}

:deep(.interview-display .summary-content blockquote) {
  margin: 8px 0;
  padding-left: 12px;
  border-left: 3px solid #E5E7EB;
  color: #6B7280;
  font-style: italic;
}

/* Markdown styles in quotes */
:deep(.interview-display .quote-item strong) {
  font-weight: 600;
  color: #374151;
}

:deep(.interview-display .quote-item em) {
  font-style: italic;
}

/* Quick Search Display */
:deep(.quick-search-display) {
  padding: 4px 0;
}

:deep(.search-meta) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

:deep(.search-query) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 500;
  color: #111827;
}

:deep(.search-count) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  color: #059669;
  background: transparent;
  border: none;
  padding: 0;
}

:deep(.search-results) {
  margin-top: 12px;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px 12px;
}

:deep(.search-fact) {
  display: flex;
  gap: 10px;
  padding: 6px 0;
  border-bottom: none;
}

:deep(.search-fact:last-child) {
  border-bottom: none;
}

/* Console Logs - 与 Step3Simulation.vue 保持一致 */
.console-logs {
  background: #000;
  color: #DDD;
  padding: 16px;
  font-family: 'JetBrains Mono', monospace;
  border-top: 1px solid #222;
  flex-shrink: 0;
}

.log-header {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #333;
  padding-bottom: 8px;
  margin-bottom: 8px;
  font-size: 10px;
  color: #666;
}

.log-title {
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.log-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100px;
  overflow-y: auto;
  padding-right: 4px;
}

.log-content::-webkit-scrollbar { width: 4px; }
.log-content::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }

.log-line {
  font-size: 11px;
  line-height: 1.5;
}

.log-msg {
  color: #BBB;
  word-break: break-all;
}

.log-msg.error { color: #EF5350; }
.log-msg.warning { color: #FFA726; }
.log-msg.success { color: #66BB6A; }
</style>
