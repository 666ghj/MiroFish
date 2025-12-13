<template>
  <div class="report-panel">
    <!-- Main Split Layout -->
    <div class="main-split-layout">
      <!-- LEFT PANEL: Progress & Content -->
      <div class="left-panel" ref="leftPanel">
        <div class="panel-header">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 11l3 3L22 4"></path>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
          </svg>
          <span>Report Progress</span>
        </div>

        <!-- Outline Overview -->
        <div v-if="reportOutline" class="outline-overview">
          <h2 class="report-title">{{ reportOutline.title }}</h2>
          <p class="report-summary">{{ reportOutline.summary }}</p>
          
          <!-- Progress Bar -->
          <div class="progress-wrapper">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
            </div>
            <span class="progress-text">{{ progressPercent }}%</span>
          </div>
        </div>

        <!-- Sections List with Content -->
        <div class="sections-container" v-if="reportOutline">
          <div 
            v-for="(section, idx) in reportOutline.sections" 
            :key="idx"
            class="section-card"
            :class="{ 
              'completed': isSectionCompleted(idx + 1),
              'current': currentSectionIndex === idx + 1,
              'pending': !isSectionCompleted(idx + 1) && currentSectionIndex !== idx + 1
            }"
          >
            <div class="section-card-header" @click="toggleSectionContent(idx)">
              <div class="section-indicator">
                <svg v-if="isSectionCompleted(idx + 1)" class="check-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="3">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <div v-else-if="currentSectionIndex === idx + 1" class="generating-spinner"></div>
                <span v-else class="section-number">{{ idx + 1 }}</span>
              </div>
              <span class="section-name">{{ section.title }}</span>
              <span v-if="generatedSections[idx + 1]" class="expand-btn">
                {{ expandedContent.has(idx) ? '−' : '+' }}
              </span>
            </div>
            
            <!-- Section Content Preview -->
            <Transition name="slide-content">
              <div v-if="expandedContent.has(idx) && generatedSections[idx + 1]" class="section-content">
                <div class="content-body" v-html="renderMarkdown(generatedSections[idx + 1])"></div>
              </div>
            </Transition>
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
        <div class="panel-header">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          <span>Agent Workflow</span>
          <span class="log-count" v-if="agentLogs.length > 0">{{ agentLogs.length }}</span>
        </div>

        <div class="workflow-timeline">
          <TransitionGroup name="timeline-item">
            <div 
              v-for="(log, idx) in displayLogs" 
              :key="log.timestamp + '-' + idx"
              class="timeline-item"
              :class="getTimelineItemClass(log)"
            >
              <!-- Timeline Connector -->
              <div class="timeline-connector">
                <div class="connector-dot" :class="getConnectorClass(log)"></div>
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
                    <div class="tool-badge">
                      <svg class="tool-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                      </svg>
                      {{ getToolDisplayName(log.details?.tool_name) }}
                    </div>
                    <div v-if="log.details?.parameters && expandedLogs.has(log.timestamp)" class="tool-params">
                      <pre>{{ formatParams(log.details.parameters) }}</pre>
                    </div>
                    <button v-if="log.details?.parameters" class="expand-toggle" @click.stop="toggleLogExpand(log)">
                      {{ expandedLogs.has(log.timestamp) ? 'Hide Params' : 'Show Params' }}
                    </button>
                  </template>

                  <!-- Tool Result -->
                  <template v-if="log.action === 'tool_result'">
                    <div class="result-wrapper" :class="'result-' + log.details?.tool_name">
                      <div class="result-meta">
                        <span class="result-tool">{{ getToolDisplayName(log.details?.tool_name) }}</span>
                        <span class="result-size">{{ formatResultSize(log.details?.result_length) }}</span>
                      </div>
                      
                      <!-- Structured Result Display -->
                      <div v-if="!showRawResult[log.timestamp]" class="result-structured">
                        <!-- Interview Agents - Special Display -->
                        <template v-if="log.details?.tool_name === 'interview_agents'">
                          <InterviewDisplay :result="parseInterview(log.details.result)" />
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
                      
                      <button class="toggle-raw" @click.stop="toggleRawResult(log.timestamp)">
                        {{ showRawResult[log.timestamp] ? 'Structured View' : 'Raw Output' }}
                      </button>
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
                    <button v-if="log.details?.response" class="expand-toggle" @click.stop="toggleLogExpand(log)">
                      {{ expandedLogs.has(log.timestamp) ? 'Hide Response' : 'Show Response' }}
                    </button>
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

                <!-- Elapsed Time -->
                <div class="timeline-footer" v-if="log.elapsed_seconds">
                  <span class="elapsed-badge">+{{ log.elapsed_seconds.toFixed(1) }}s</span>
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
const isComplete = ref(false)
const startTime = ref(null)
const leftPanel = ref(null)
const rightPanel = ref(null)
const logContent = ref(null)
const showRawResult = reactive({})

// Toggle functions
const toggleRawResult = (timestamp) => {
  showRawResult[timestamp] = !showRawResult[timestamp]
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

// Tool display names (without emojis)
const getToolDisplayName = (toolName) => {
  const names = {
    'insight_forge': 'Deep Insight',
    'panorama_search': 'Panorama Search',
    'interview_agents': 'Agent Interview',
    'quick_search': 'Quick Search',
    'get_graph_statistics': 'Graph Stats',
    'get_entities_by_type': 'Entity Query'
  }
  return names[toolName] || toolName
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
    interviews: [],
    summary: ''
  }
  
  try {
    const topicMatch = text.match(/\*\*采访主题:\*\*\s*(.+?)(?:\n|$)/)
    if (topicMatch) result.topic = topicMatch[1].trim()
    
    const countMatch = text.match(/\*\*采访人数:\*\*\s*(.+?)(?:\n|$)/)
    if (countMatch) result.agentCount = countMatch[1].trim()
    
    // Extract interview records
    const interviewMatches = text.matchAll(/#### 采访 #(\d+):\s*(.+?)\n\*\*(.+?)\*\*\s*\((.+?)\)\n_简介:\s*(.+?)_\n\n\*\*Q:\*\*\s*([\s\S]*?)\n\n\*\*A:\*\*\s*([\s\S]*?)(?=\*\*关键引言|\n---|\n####|$)/g)
    
    for (const match of interviewMatches) {
      const interview = {
        num: match[1],
        title: match[2].trim(),
        name: match[3].trim(),
        role: match[4].trim(),
        bio: match[5].trim(),
        question: match[6].trim(),
        answer: match[7].trim(),
        quotes: []
      }
      
      // Extract key quotes
      const quoteSection = text.match(new RegExp(`#### 采访 #${match[1]}[\\s\\S]*?\\*\\*关键引言:\\*\\*\\n([\\s\\S]*?)(?=\\n---)`))
      if (quoteSection) {
        const quotes = quoteSection[1].match(/> "(.+?)"/g)
        if (quotes) {
          interview.quotes = quotes.map(q => q.replace(/^> "|"$/g, '')).slice(0, 2)
        }
      }
      
      result.interviews.push(interview)
    }
    
    const summarySection = text.match(/### 采访摘要与核心观点\n([\s\S]*?)$/)
    if (summarySection) {
      result.summary = summarySection[1].trim().substring(0, 400)
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

// Interview Display Component - Beautiful Interview Style
const InterviewDisplay = {
  props: ['result'],
  setup(props) {
    const activeIndex = ref(0)
    return () => h('div', { class: 'interview-display' }, [
      // Header
      h('div', { class: 'interview-header' }, [
        h('div', { class: 'interview-topic' }, props.result.topic || 'Agent Interview'),
        h('div', { class: 'interview-meta' }, props.result.agentCount)
      ]),
      // Interview Cards
      props.result.interviews.length > 0 && h('div', { class: 'interview-carousel' }, 
        props.result.interviews.map((interview, i) => h('div', { 
          class: ['interview-card', { active: activeIndex.value === i }],
          key: i,
          onClick: () => { activeIndex.value = i }
        }, [
          // Interviewee Info
          h('div', { class: 'interviewee' }, [
            h('div', { class: 'avatar' }, interview.name.charAt(0)),
            h('div', { class: 'info' }, [
              h('span', { class: 'name' }, interview.name),
              h('span', { class: 'role' }, interview.role)
            ]),
            h('span', { class: 'interview-idx' }, `#${interview.num}`)
          ]),
          // Bio
          interview.bio && h('div', { class: 'bio' }, interview.bio.length > 80 ? interview.bio.substring(0, 80) + '...' : interview.bio),
          // Q&A Section
          activeIndex.value === i && h('div', { class: 'qa-section' }, [
            h('div', { class: 'question' }, [
              h('div', { class: 'q-label' }, 'Q'),
              h('div', { class: 'q-text' }, interview.question.length > 200 ? interview.question.substring(0, 200) + '...' : interview.question)
            ]),
            h('div', { class: 'answer' }, [
              h('div', { class: 'a-label' }, 'A'),
              h('div', { class: 'a-text' }, interview.answer.length > 400 ? interview.answer.substring(0, 400) + '...' : interview.answer)
            ]),
            // Key Quotes
            interview.quotes.length > 0 && h('div', { class: 'quotes' },
              interview.quotes.map((q, qi) => h('blockquote', { class: 'quote', key: qi }, `"${q.length > 100 ? q.substring(0, 100) + '...' : q}"`))
            )
          ])
        ]))
      ),
      // Navigation dots
      props.result.interviews.length > 1 && h('div', { class: 'carousel-dots' },
        props.result.interviews.map((_, i) => h('span', {
          class: ['dot', { active: activeIndex.value === i }],
          key: i,
          onClick: () => { activeIndex.value = i }
        }))
      ),
      // Summary
      props.result.summary && h('div', { class: 'interview-summary' }, [
        h('div', { class: 'summary-label' }, 'Summary'),
        h('div', { class: 'summary-text' }, props.result.summary)
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

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

const isSectionCompleted = (sectionIndex) => {
  return !!generatedSections.value[sectionIndex]
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
  
  // 处理代码块
  let html = content.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  
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

const getTimelineItemClass = (log) => {
  return {
    'is-tool': log.action === 'tool_call' || log.action === 'tool_result',
    'is-section': log.action === 'section_start' || log.action === 'section_complete' || log.action === 'section_content' || log.action === 'subsection_content',
    'is-complete': log.action === 'report_complete',
    'is-planning': log.action === 'planning_start' || log.action === 'planning_complete'
  }
}

const getConnectorClass = (log) => {
  const classes = {
    'report_start': 'dot-start',
    'planning_start': 'dot-planning',
    'planning_complete': 'dot-planning',
    'section_start': 'dot-section',
    'section_content': 'dot-section-content',
    'subsection_content': 'dot-subsection-content',
    'section_complete': 'dot-section-done',
    'tool_call': 'dot-tool',
    'tool_result': 'dot-result',
    'llm_response': 'dot-llm',
    'report_complete': 'dot-complete'
  }
  return classes[log.action] || 'dot-default'
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
            currentSectionIndex.value = log.section_index
          }
          
          // section_content / subsection_content - 表示内容生成完成（但整个章节可能还没完成）
          // 这里不更新 generatedSections，只记录进度
          if (log.action === 'section_content' || log.action === 'subsection_content') {
            // 可以用于显示进度，但不更新左侧面板的内容
            // 因为完整内容会在 section_complete 时一次性提供
          }
          
          // section_complete - 表示完整章节（含所有子章节）生成完成
          // details.content 包含合并后的完整内容
          if (log.action === 'section_complete') {
            if (log.details?.content) {
              generatedSections.value[log.section_index] = log.details.content
              // 自动展开刚生成的章节
              expandedContent.value.add(log.section_index - 1)
            }
            currentSectionIndex.value = null
          }
          
          if (log.action === 'report_complete') {
            isComplete.value = true
            emit('update-status', 'completed')
            stopPolling()
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

.panel-header svg {
  color: #6366F1;
}

.log-count {
  margin-left: auto;
  background: #EEF2FF;
  color: #4F46E5;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
}

/* Left Panel */
.left-panel {
  width: 45%;
  min-width: 350px;
  background: #FFFFFF;
  border-right: 1px solid #E5E7EB;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.outline-overview {
  padding: 20px;
  border-bottom: 1px solid #F3F4F6;
}

.report-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 8px;
  line-height: 1.4;
}

.report-summary {
  font-size: 13px;
  color: #6B7280;
  line-height: 1.6;
  margin: 0 0 16px;
}

.progress-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: #E5E7EB;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4F46E5 0%, #7C3AED 100%);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 12px;
  font-weight: 600;
  color: #4F46E5;
  min-width: 36px;
  text-align: right;
}

/* Section Cards */
.sections-container {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-card {
  background: #FAFAFA;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.2s ease;
}

.section-card:hover {
  border-color: #D1D5DB;
}

.section-card.current {
  border-color: #F59E0B;
  background: #FFFBEB;
}

.section-card.completed {
  border-color: #10B981;
  background: #ECFDF5;
}

.section-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  cursor: pointer;
}

.section-indicator {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #E5E7EB;
  flex-shrink: 0;
}

.section-card.completed .section-indicator {
  background: #10B981;
}

.section-card.current .section-indicator {
  background: #F59E0B;
}

.check-icon {
  color: #FFFFFF;
}

.generating-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #FFFFFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.section-number {
  font-size: 12px;
  font-weight: 600;
  color: #6B7280;
}

.section-name {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}

.expand-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #6B7280;
  transition: all 0.2s;
}

.section-card.completed .expand-btn {
  background: #D1FAE5;
  color: #059669;
}

.section-card:hover .expand-btn {
  background: #D1D5DB;
}

.section-card.completed:hover .expand-btn {
  background: #A7F3D0;
}

.section-content {
  border-top: 1px solid #E5E7EB;
  padding: 20px;
  background: #FFFFFF;
  max-height: 500px;
  overflow-y: auto;
}

.section-content::-webkit-scrollbar {
  width: 6px;
}

.section-content::-webkit-scrollbar-track {
  background: #F3F4F6;
  border-radius: 3px;
}

.section-content::-webkit-scrollbar-thumb {
  background: #D1D5DB;
  border-radius: 3px;
}

.section-content::-webkit-scrollbar-thumb:hover {
  background: #9CA3AF;
}

.content-body {
  font-size: 13px;
  line-height: 1.7;
  color: #4B5563;
}

.content-body :deep(.md-h2) {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  margin: 20px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #E5E7EB;
}

.content-body :deep(.md-h3) {
  font-size: 16px;
  font-weight: 600;
  color: #1F2937;
  margin: 16px 0 10px;
}

.content-body :deep(.md-h4) {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin: 14px 0 8px;
}

.content-body :deep(.md-h5) {
  font-size: 13px;
  font-weight: 600;
  color: #4B5563;
  margin: 12px 0 6px;
}

.content-body :deep(.md-p) {
  margin: 10px 0;
}

.content-body :deep(.md-quote) {
  margin: 12px 0;
  padding: 10px 16px;
  border-left: 3px solid #6366F1;
  background: #F3F4F6;
  color: #4B5563;
  font-style: italic;
}

.content-body :deep(.md-ul),
.content-body :deep(.md-ol) {
  margin: 10px 0;
  padding-left: 24px;
}

.content-body :deep(.md-li),
.content-body :deep(.md-oli) {
  margin: 6px 0;
  line-height: 1.6;
}

.content-body :deep(.md-hr) {
  border: none;
  border-top: 1px solid #E5E7EB;
  margin: 16px 0;
}

.content-body :deep(.code-block) {
  background: #1F2937;
  color: #E5E7EB;
  padding: 12px 16px;
  border-radius: 6px;
  overflow-x: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  margin: 12px 0;
}

.content-body :deep(.inline-code) {
  background: #F3F4F6;
  color: #DC2626;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.content-body :deep(strong) {
  color: #111827;
  font-weight: 600;
}

.content-body :deep(em) {
  color: #4B5563;
}

/* Slide Content Transition */
.slide-content-enter-active {
  transition: all 0.4s ease-out;
  overflow: hidden;
}

.slide-content-leave-active {
  transition: all 0.3s ease-in;
  overflow: hidden;
}

.slide-content-enter-from {
  max-height: 0;
  opacity: 0;
  padding: 0 20px;
}

.slide-content-enter-to {
  max-height: 500px;
  opacity: 1;
}

.slide-content-leave-from {
  max-height: 500px;
  opacity: 1;
}

.slide-content-leave-to {
  max-height: 0;
  opacity: 0;
  padding: 0 20px;
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
  background: #F8F9FA;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

/* Workflow Timeline */
.workflow-timeline {
  padding: 20px;
  flex: 1;
}

.timeline-item {
  display: flex;
  gap: 16px;
  margin-bottom: 4px;
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
  background: #D1D5DB;
  border: 2px solid #F8F9FA;
  z-index: 1;
}

.connector-line {
  width: 2px;
  flex: 1;
  background: #E5E7EB;
  margin-top: -2px;
}

/* Dot colors */
.dot-start { background: #3B82F6; }
.dot-planning { background: #F59E0B; }
.dot-section { background: #10B981; }
.dot-section-content { background: #34D399; }
.dot-subsection-content { background: #6EE7B7; }
.dot-section-done { background: #059669; box-shadow: 0 0 0 2px rgba(5, 150, 105, 0.2); }
.dot-tool { background: #8B5CF6; }
.dot-result { background: #EC4899; }
.dot-llm { background: #06B6D4; }
.dot-complete { background: #10B981; box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2); }

.timeline-content {
  flex: 1;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  transition: all 0.2s ease;
}

.timeline-content:hover {
  border-color: #D1D5DB;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
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
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #F3F4F6;
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
}

.status-message.planning {
  background: #FEF3C7;
  color: #92400E;
}

.status-message.success {
  background: #D1FAE5;
  color: #065F46;
}

.outline-badge {
  display: inline-block;
  margin-top: 8px;
  padding: 4px 10px;
  background: #EEF2FF;
  color: #4338CA;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
}

.section-tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #EEF2FF;
  border-radius: 6px;
}

.section-tag.content-ready {
  background: #ECFDF5;
  border: 1px dashed #34D399;
}

.section-tag.content-ready svg {
  color: #34D399;
}

.section-tag.content-ready.is-subsection {
  background: #F0FDF4;
  border-color: #6EE7B7;
}

.section-tag.completed {
  background: #D1FAE5;
  border: 1px solid #059669;
}

.section-tag.completed svg {
  color: #059669;
}

.tag-num {
  font-size: 11px;
  font-weight: 700;
  color: #4F46E5;
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
  background: #F3E8FF;
  color: #7C3AED;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.tool-icon {
  flex-shrink: 0;
}

.tool-params {
  margin-top: 10px;
  background: #F9FAFB;
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
}

.tool-params pre {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #4B5563;
  white-space: pre-wrap;
  word-break: break-all;
}

.expand-toggle {
  margin-top: 8px;
  background: transparent;
  border: none;
  color: #6366F1;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
}

.expand-toggle:hover {
  text-decoration: underline;
}

/* Result Wrapper */
.result-wrapper {
  background: #F9FAFB;
  border-radius: 8px;
  padding: 12px;
}

.result-wrapper.result-insight_forge {
  background: linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%);
}

.result-wrapper.result-panorama_search {
  background: linear-gradient(135deg, #DBEAFE 0%, #BFDBFE 100%);
}

.result-wrapper.result-interview_agents {
  background: linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 100%);
}

.result-wrapper.result-quick_search {
  background: linear-gradient(135deg, #D1FAE5 0%, #A7F3D0 100%);
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
  background: rgba(255,255,255,0.5);
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

.toggle-raw {
  margin-top: 10px;
  background: rgba(255,255,255,0.7);
  border: none;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #6B7280;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-raw:hover {
  background: rgba(255,255,255,0.9);
  color: #374151;
}

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
  background: linear-gradient(135deg, #D1FAE5 0%, #A7F3D0 100%);
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
  background: linear-gradient(135deg, #D1FAE5 0%, #A7F3D0 100%);
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

/* Common Styles */
.stat-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.stat-box {
  flex: 1;
  background: rgba(255,255,255,0.8);
  border-radius: 6px;
  padding: 8px;
  text-align: center;
}

.stat-box .stat-num {
  display: block;
  font-size: 18px;
  font-weight: 700;
  color: #374151;
  font-family: 'JetBrains Mono', monospace;
}

.stat-box .stat-label {
  display: block;
  font-size: 10px;
  color: #6B7280;
  margin-top: 2px;
}

.stat-box.highlight {
  background: rgba(16, 185, 129, 0.2);
}

.stat-box.highlight .stat-num {
  color: #059669;
}

.stat-box.muted {
  background: rgba(107, 114, 128, 0.1);
}

.stat-box.muted .stat-num {
  color: #6B7280;
}

.query-display {
  background: rgba(255,255,255,0.6);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: #4B5563;
  margin-bottom: 10px;
  border-left: 3px solid #6366F1;
}

.expand-details {
  background: rgba(255,255,255,0.7);
  border: 1px solid rgba(0,0,0,0.1);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: #4B5563;
  cursor: pointer;
  transition: all 0.2s;
}

.expand-details:hover {
  background: rgba(255,255,255,0.9);
}

.detail-content {
  margin-top: 12px;
  background: rgba(255,255,255,0.5);
  border-radius: 8px;
  padding: 12px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

/* Facts Section */
.facts-section {
  margin-bottom: 12px;
}

.fact-row {
  display: flex;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(0,0,0,0.05);
}

.fact-row:last-child {
  border-bottom: none;
}

.fact-row.active {
  background: rgba(16, 185, 129, 0.1);
  margin: 0 -8px;
  padding: 6px 8px;
  border-radius: 4px;
}

.fact-idx {
  min-width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E5E7EB;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  color: #6B7280;
  flex-shrink: 0;
}

.fact-text {
  font-size: 12px;
  color: #4B5563;
  line-height: 1.5;
}

/* Entities Section */
.entities-section {
  margin-bottom: 12px;
}

.entity-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.entity-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(255,255,255,0.8);
  border: 1px solid rgba(0,0,0,0.1);
  border-radius: 20px;
  padding: 4px 10px;
}

.chip-name {
  font-size: 11px;
  font-weight: 500;
  color: #374151;
}

.chip-type {
  font-size: 9px;
  color: #9CA3AF;
}

/* Relations Section */
.relations-section {
  margin-bottom: 12px;
}

.relation-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  flex-wrap: wrap;
}

.rel-node {
  font-size: 11px;
  font-weight: 500;
  color: #374151;
  background: #E5E7EB;
  padding: 2px 8px;
  border-radius: 4px;
}

.rel-edge {
  font-size: 10px;
  color: #FFFFFF;
  background: #6366F1;
  padding: 2px 8px;
  border-radius: 12px;
}

/* Interview Display */
.interview-display {
  padding: 4px 0;
}

.interview-header {
  margin-bottom: 12px;
}

.interview-topic {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 4px;
}

.interview-meta {
  font-size: 11px;
  color: #6B7280;
}

.interview-carousel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.interview-card {
  background: rgba(255,255,255,0.9);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 10px;
  padding: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.interview-card:hover {
  border-color: rgba(139, 92, 246, 0.3);
}

.interview-card.active {
  border-color: #8B5CF6;
  box-shadow: 0 2px 12px rgba(139, 92, 246, 0.15);
}

.interviewee {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.avatar {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #8B5CF6 0%, #A78BFA 100%);
  color: #FFFFFF;
  font-size: 14px;
  font-weight: 700;
  border-radius: 50%;
}

.interviewee .info {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.interviewee .name {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.interviewee .role {
  font-size: 11px;
  color: #6B7280;
}

.interview-idx {
  font-size: 11px;
  font-weight: 600;
  color: #8B5CF6;
  background: #F3E8FF;
  padding: 2px 8px;
  border-radius: 10px;
}

.bio {
  font-size: 11px;
  color: #6B7280;
  font-style: italic;
  margin-bottom: 10px;
  padding: 8px;
  background: rgba(0,0,0,0.03);
  border-radius: 6px;
}

.qa-section {
  border-top: 1px solid rgba(0,0,0,0.08);
  padding-top: 12px;
  margin-top: 4px;
}

.question, .answer {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.q-label, .a-label {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.q-label {
  background: #EEF2FF;
  color: #4F46E5;
}

.a-label {
  background: #D1FAE5;
  color: #059669;
}

.q-text, .a-text {
  font-size: 12px;
  color: #4B5563;
  line-height: 1.6;
}

.q-text {
  font-weight: 500;
}

.quotes {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(0,0,0,0.1);
}

.quote {
  font-size: 11px;
  color: #6B7280;
  font-style: italic;
  padding: 6px 12px;
  margin: 4px 0;
  border-left: 2px solid #A78BFA;
  background: rgba(167, 139, 250, 0.08);
}

.carousel-dots {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-top: 12px;
}

.carousel-dots .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(0,0,0,0.15);
  cursor: pointer;
  transition: all 0.2s;
}

.carousel-dots .dot.active {
  background: #8B5CF6;
  width: 20px;
  border-radius: 4px;
}

.interview-summary {
  margin-top: 12px;
  padding: 12px;
  background: rgba(255,255,255,0.6);
  border-radius: 8px;
}

.summary-label {
  font-size: 11px;
  font-weight: 600;
  color: #6B7280;
  margin-bottom: 6px;
}

.summary-text {
  font-size: 12px;
  color: #4B5563;
  line-height: 1.6;
}

/* Quick Search Display */
.quick-search-display {
  padding: 4px 0;
}

.search-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.search-query {
  font-size: 12px;
  font-weight: 500;
  color: #374151;
}

.search-count {
  font-size: 10px;
  color: #059669;
  background: rgba(16, 185, 129, 0.15);
  padding: 2px 8px;
  border-radius: 10px;
}

.search-results {
  margin-top: 10px;
  background: rgba(255,255,255,0.5);
  border-radius: 6px;
  padding: 8px;
}

.search-fact {
  display: flex;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(0,0,0,0.05);
}

.search-fact:last-child {
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
  height: 120px;
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
