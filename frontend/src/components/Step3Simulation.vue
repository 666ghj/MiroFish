<template>
  <div class="simulation-panel">
    <!-- Top Control Bar -->
    <div class="control-bar">
      <div class="status-group" v-if="phase >= 1">
        <!-- Twitter 平台进度 -->
        <div class="platform-status twitter" :class="{ active: runStatus.twitter_running, completed: runStatus.twitter_completed }">
          <div class="platform-header">
            <span class="platform-icon">𝕏</span>
            <span class="platform-name">Twitter</span>
            <span v-if="runStatus.twitter_completed" class="status-badge">✓</span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">R</span>
              <span class="stat-value mono">{{ runStatus.twitter_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || maxRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">T</span>
              <span class="stat-value mono">{{ runStatus.twitter_simulated_hours || 0 }}<span class="stat-unit">h</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">A</span>
              <span class="stat-value mono">{{ runStatus.twitter_actions_count || 0 }}</span>
            </span>
          </div>
        </div>
        
        <!-- Reddit 平台进度 -->
        <div class="platform-status reddit" :class="{ active: runStatus.reddit_running, completed: runStatus.reddit_completed }">
          <div class="platform-header">
            <span class="platform-icon">📮</span>
            <span class="platform-name">Reddit</span>
            <span v-if="runStatus.reddit_completed" class="status-badge">✓</span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">R</span>
              <span class="stat-value mono">{{ runStatus.reddit_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || maxRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">T</span>
              <span class="stat-value mono">{{ runStatus.reddit_simulated_hours || 0 }}<span class="stat-unit">h</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">A</span>
              <span class="stat-value mono">{{ runStatus.reddit_actions_count || 0 }}</span>
            </span>
          </div>
        </div>
      </div>
      
      <!-- Phase 0 时显示简单状态 -->
      <div class="status-group" v-else>
        <div class="status-item">
          <span class="label">ROUND</span>
          <span class="value mono">0<span class="total">/{{ maxRounds || '-' }}</span></span>
        </div>
        <div class="status-item">
          <span class="label">TIME</span>
          <span class="value mono">0<span class="unit">h</span></span>
        </div>
      </div>

      <div class="action-controls">
        <button 
          v-if="phase === 0"
          class="ctrl-btn start"
          :disabled="isStarting"
          @click="doStartSimulation"
        >
          <span v-if="isStarting" class="spinner-sm"></span>
          {{ isStarting ? 'INITIALIZING...' : 'START ENGINE' }}
        </button>
        
        <button 
          v-if="phase === 1"
          class="ctrl-btn stop"
          :disabled="isStopping"
          @click="handleStopSimulation"
        >
          {{ isStopping ? 'STOPPING...' : 'STOP SIMULATION' }}
        </button>

        <button 
          v-if="phase === 2"
          class="ctrl-btn next"
          @click="handleNextStep"
        >
          GENERATE REPORT ➝
        </button>
      </div>
    </div>

    <!-- Main Content: Dual Timeline or Start Screen -->
    <div class="main-content-area" ref="scrollContainer">
      <!-- Start Screen (Phase 0) -->
      <div v-if="phase === 0" class="start-screen">
        <div class="engine-status">
          <div class="engine-icon">⚡️</div>
          <h2>Simulation Engine Ready</h2>
          <p>Initialize the dual-platform parallel simulation environment.</p>
        </div>
        
        <div class="config-grid">
          <div class="config-card">
            <span class="label">SIMULATION ID</span>
            <span class="val mono">{{ simulationId }}</span>
          </div>
          <div class="config-card">
            <span class="label">TARGET ROUNDS</span>
            <span class="val">{{ maxRounds || 'AUTO' }}</span>
          </div>
          <div class="config-card">
            <span class="label">PLATFORMS</span>
            <span class="val">Twitter + Reddit</span>
          </div>
        </div>

        <div v-if="startError" class="error-banner">
          {{ startError }}
        </div>
      </div>

      <!-- Timeline Feed (Phase >= 1) -->
      <div v-else class="timeline-feed">
        <div class="timeline-axis"></div>
        
        <TransitionGroup name="timeline-item">
          <div 
            v-for="action in reversedActions" 
            :key="action.id || `${action.timestamp}-${action.agent_id}`" 
            class="timeline-item"
            :class="action.platform"
          >
            <div class="timeline-marker"></div>
            <div class="timeline-card">
              <div class="card-header">
                <div class="agent-info">
                  <div class="avatar-placeholder">{{ (action.agent_name || 'A')[0] }}</div>
                  <span class="agent-name">{{ action.agent_name }}</span>
                </div>
                <div class="action-badge" :class="getActionTypeClass(action.action_type)">
                  {{ getActionTypeLabel(action.action_type) }}
                </div>
              </div>
              
              <div class="card-body">
                <!-- Main Content -->
                <div v-if="action.action_args?.content" class="content-text">
                  {{ action.action_args.content }}
                </div>

                <!-- Quote / Repost Content -->
                <div v-if="action.action_args?.quote_content" class="quoted-block">
                  <div class="quote-author">
                    Replying to @{{ action.action_args.original_author_name || 'User' }}
                  </div>
                  <div class="quote-text">
                    {{ action.action_args.quote_content }}
                  </div>
                </div>

                <!-- Target Context (e.g. for Likes) -->
                <div v-if="action.action_type?.includes('LIKE') && action.action_args?.post_content" class="target-context">
                  <span class="context-label">Liked Post:</span>
                  "{{ truncateContent(action.action_args.post_content) }}"
                </div>
              </div>

              <div class="card-footer">
                <span class="time-tag">R{{ action.round_num }} • {{ formatActionTime(action.timestamp) }}</span>
                <span class="platform-tag">{{ action.platform === 'twitter' ? 'Twitter' : 'Reddit' }}</span>
              </div>
            </div>
          </div>
        </TransitionGroup>

        <div v-if="recentActions.length === 0" class="waiting-state">
          <div class="pulse-ring"></div>
          <span>Waiting for agent actions...</span>
        </div>
      </div>
    </div>

    <!-- Bottom Info / Logs -->
    <div class="system-logs">
      <div class="log-header">
        <span class="log-title">SIMULATION MONITOR</span>
        <span class="log-id">{{ simulationId || 'NO_SIMULATION' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div class="log-line" v-for="(log, idx) in systemLogs" :key="idx">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { 
  startSimulation, 
  stopSimulation,
  getRunStatus, 
  getRunStatusDetail
} from '../api/simulation'

const props = defineProps({
  simulationId: String,
  maxRounds: Number, // 从Step2传入的最大轮数
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

// State
const phase = ref(0) // 0: 未开始, 1: 运行中, 2: 已完成
const isStarting = ref(false)
const isStopping = ref(false)
const startError = ref(null)
const runStatus = ref({})
const recentActions = ref([])
const scrollContainer = ref(null)

// Computed
// Reverse actions to show newest at top
const reversedActions = computed(() => {
  return [...recentActions.value]
})

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

// 启动模拟
const doStartSimulation = async () => {
  if (!props.simulationId) {
    addLog('错误：缺少 simulationId')
    return
  }
  
  isStarting.value = true
  startError.value = null
  addLog('正在启动双平台并行模拟...')
  emit('update-status', 'processing')
  
  try {
    const params = {
      simulation_id: props.simulationId,
      platform: 'parallel',
      force: true  // 强制重新开始
    }
    
    if (props.maxRounds) {
      params.max_rounds = props.maxRounds
      addLog(`设置最大模拟轮数: ${props.maxRounds}`)
    }
    
    const res = await startSimulation(params)
    
    if (res.success && res.data) {
      if (res.data.force_restarted) {
        addLog('✓ 已清理旧的模拟日志，重新开始模拟')
      }
      addLog('✓ 模拟引擎启动成功')
      addLog(`  ├─ PID: ${res.data.process_pid || '-'}`)
      
      phase.value = 1
      runStatus.value = res.data
      
      startStatusPolling()
      startDetailPolling()
    } else {
      startError.value = res.error || '启动失败'
      addLog(`✗ 启动失败: ${res.error || '未知错误'}`)
      emit('update-status', 'error')
    }
  } catch (err) {
    startError.value = err.message
    addLog(`✗ 启动异常: ${err.message}`)
    emit('update-status', 'error')
  } finally {
    isStarting.value = false
  }
}

// 停止模拟
const handleStopSimulation = async () => {
  if (!props.simulationId) return
  
  isStopping.value = true
  addLog('正在停止模拟...')
  
  try {
    const res = await stopSimulation({ simulation_id: props.simulationId })
    
    if (res.success) {
      addLog('✓ 模拟已停止')
      phase.value = 2
      stopPolling()
      emit('update-status', 'completed')
    } else {
      addLog(`停止失败: ${res.error || '未知错误'}`)
    }
  } catch (err) {
    addLog(`停止异常: ${err.message}`)
  } finally {
    isStopping.value = false
  }
}

// 轮询状态
let statusTimer = null
let detailTimer = null

const startStatusPolling = () => {
  statusTimer = setInterval(fetchRunStatus, 2000)
}

const startDetailPolling = () => {
  detailTimer = setInterval(fetchRunStatusDetail, 3000)
}

const stopPolling = () => {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  if (detailTimer) {
    clearInterval(detailTimer)
    detailTimer = null
  }
}

// 追踪各平台的上一次轮次，用于检测变化并输出日志
const prevTwitterRound = ref(0)
const prevRedditRound = ref(0)

const fetchRunStatus = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getRunStatus(props.simulationId)
    
    if (res.success && res.data) {
      const data = res.data
      
      runStatus.value = data
      
      // 分别检测各平台的轮次变化并输出日志
      if (data.twitter_current_round > prevTwitterRound.value) {
        addLog(`[Twitter] R${data.twitter_current_round}/${data.total_rounds} | T:${data.twitter_simulated_hours || 0}h | A:${data.twitter_actions_count}`)
        prevTwitterRound.value = data.twitter_current_round
      }
      
      if (data.reddit_current_round > prevRedditRound.value) {
        addLog(`[Reddit] R${data.reddit_current_round}/${data.total_rounds} | T:${data.reddit_simulated_hours || 0}h | A:${data.reddit_actions_count}`)
        prevRedditRound.value = data.reddit_current_round
      }
      
      // 检测模拟是否已完成（通过 runner_status 或平台完成状态判断）
      const isCompleted = data.runner_status === 'completed' || data.runner_status === 'stopped'
      
      // 额外检查：如果后端还没来得及更新 runner_status，但平台已经报告完成
      // 通过检测 twitter_completed 和 reddit_completed 状态判断
      const platformsCompleted = checkPlatformsCompleted(data)
      
      if (isCompleted || platformsCompleted) {
        if (platformsCompleted && !isCompleted) {
          addLog('✓ 检测到所有平台模拟已结束')
        }
        addLog('✓ 模拟已完成')
        phase.value = 2
        stopPolling()
        emit('update-status', 'completed')
      }
    }
  } catch (err) {
    console.warn('获取运行状态失败:', err)
  }
}

// 检查所有启用的平台是否已完成
const checkPlatformsCompleted = (data) => {
  // 如果没有任何平台数据，返回 false
  if (!data) return false
  
  // 检查各平台的完成状态
  const twitterCompleted = data.twitter_completed === true
  const redditCompleted = data.reddit_completed === true
  
  // 如果至少有一个平台完成了，检查是否所有启用的平台都完成了
  // 通过 actions_count 判断平台是否被启用（如果 count > 0 或 running 曾为 true）
  const twitterEnabled = (data.twitter_actions_count > 0) || data.twitter_running || twitterCompleted
  const redditEnabled = (data.reddit_actions_count > 0) || data.reddit_running || redditCompleted
  
  // 如果没有任何平台被启用，返回 false
  if (!twitterEnabled && !redditEnabled) return false
  
  // 检查所有启用的平台是否都已完成
  if (twitterEnabled && !twitterCompleted) return false
  if (redditEnabled && !redditCompleted) return false
  
  return true
}

const fetchRunStatusDetail = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getRunStatusDetail(props.simulationId)
    
    if (res.success && res.data?.recent_actions) {
      // Keep only last 50 actions for performance
      recentActions.value = res.data.recent_actions.slice(0, 50)
    }
  } catch (err) {
    console.warn('获取详细状态失败:', err)
  }
}

// Helpers
const getActionTypeLabel = (type) => {
  const labels = {
    'CREATE_POST': 'POST',
    'REPOST': 'REPOST',
    'LIKE_POST': 'LIKE',
    'CREATE_COMMENT': 'COMMENT',
    'LIKE_COMMENT': 'LIKE',
    'DO_NOTHING': 'IDLE',
    'FOLLOW': 'FOLLOW',
    'SEARCH_POSTS': 'SEARCH',
    'QUOTE_POST': 'QUOTE'
  }
  return labels[type] || type || 'UNKNOWN'
}

const getActionTypeClass = (type) => {
  const classes = {
    'CREATE_POST': 'badge-post',
    'REPOST': 'badge-repost',
    'LIKE_POST': 'badge-like',
    'CREATE_COMMENT': 'badge-comment',
    'LIKE_COMMENT': 'badge-like',
    'QUOTE_POST': 'badge-quote'
  }
  return classes[type] || 'badge-default'
}

const truncateContent = (content) => {
  if (!content) return ''
  if (content.length > 100) return content.substring(0, 100) + '...'
  return content
}

const formatActionTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

const handleNextStep = () => {
  emit('next-step')
}

// Scroll log to bottom
const logContent = ref(null)
watch(() => props.systemLogs?.length, () => {
  nextTick(() => {
    if (logContent.value) {
      logContent.value.scrollTop = logContent.value.scrollHeight
    }
  })
})

onMounted(() => {
  addLog('Step3 模拟运行初始化')
  if (props.simulationId) {
    doStartSimulation()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.simulation-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #F0F2F5;
  font-family: 'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
  overflow: hidden;
}

/* --- Control Bar --- */
.control-bar {
  background: #FFF;
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #EAEAEA;
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
  z-index: 10;
  height: 64px;
}

.status-group {
  display: flex;
  gap: 16px;
}

.status-item {
  display: flex;
  flex-direction: column;
}

.status-item .label {
  font-size: 10px;
  color: #999;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.status-item .value {
  font-size: 16px;
  font-weight: 700;
  color: #333;
}

.status-item .total, .status-item .unit {
  font-size: 12px;
  color: #999;
  font-weight: 500;
}

/* 双平台进度卡片 */
.platform-status {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 14px;
  border-radius: 8px;
  background: #F5F5F5;
  opacity: 0.6;
  transition: all 0.3s;
  border-left: 3px solid transparent;
}

.platform-status.active {
  opacity: 1;
  background: #FFF;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.platform-status.twitter.active {
  border-left-color: #1DA1F2;
}

.platform-status.reddit.active {
  border-left-color: #FF5722;
}

.platform-status.completed {
  opacity: 1;
  background: #F1F8E9;
  border-left-color: #4CAF50;
}

.platform-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.platform-icon {
  font-size: 14px;
}

.platform-name {
  font-size: 11px;
  font-weight: 700;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.platform-status.twitter.active .platform-name { color: #1DA1F2; }
.platform-status.reddit.active .platform-name { color: #FF5722; }
.platform-status.completed .platform-name { color: #2E7D32; }

.platform-stats {
  display: flex;
  gap: 12px;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.stat-label {
  font-size: 9px;
  color: #999;
  font-weight: 600;
}

.stat-value {
  font-size: 13px;
  font-weight: 700;
  color: #333;
}

.stat-total, .stat-unit {
  font-size: 10px;
  color: #999;
  font-weight: 500;
}

.status-badge {
  font-size: 10px;
  color: #2E7D32;
  margin-left: 4px;
}

.ctrl-btn {
  padding: 8px 16px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 12px;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}

.ctrl-btn.start {
  background: #000;
  color: #FFF;
}

.ctrl-btn.stop {
  background: #FFEBEE;
  color: #C62828;
}

.ctrl-btn.next {
  background: #E8F5E9;
  color: #2E7D32;
}

.ctrl-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.ctrl-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* --- Main Content Area --- */
.main-content-area {
  flex: 1;
  overflow-y: auto;
  position: relative;
  background: #FAFAFA;
}

/* Start Screen */
.start-screen {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 40px;
}

.engine-status {
  text-align: center;
  margin-bottom: 40px;
}

.engine-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.engine-status h2 {
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 8px;
}

.engine-status p {
  color: #666;
  font-size: 14px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  width: 100%;
  max-width: 600px;
}

.config-card {
  background: #FFF;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #EAEAEA;
  text-align: center;
}

.config-card .label {
  display: block;
  font-size: 10px;
  color: #999;
  margin-bottom: 8px;
}

.config-card .val {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

/* --- Timeline Feed --- */
.timeline-feed {
  padding: 24px;
  position: relative;
  min-height: 100%;
}

.timeline-axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #E0E0E0;
  transform: translateX(-50%);
}

.timeline-item {
  display: flex;
  justify-content: center;
  margin-bottom: 24px;
  position: relative;
  width: 100%;
}

.timeline-marker {
  position: absolute;
  left: 50%;
  top: 20px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #FFF;
  border: 2px solid #999;
  transform: translateX(-50%);
  z-index: 2;
}

.timeline-item.twitter .timeline-marker { border-color: #1DA1F2; }
.timeline-item.reddit .timeline-marker { border-color: #FF5722; }

.timeline-card {
  width: 45%;
  background: #FFF;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  position: relative;
  border: 1px solid transparent;
  transition: all 0.3s;
}

/* Left side (Twitter) */
.timeline-item.twitter .timeline-card {
  margin-right: auto;
  margin-left: 20px; /* Gap from center */
  border-left: 4px solid #1DA1F2;
}

/* Right side (Reddit) */
.timeline-item.reddit .timeline-card {
  margin-left: auto;
  margin-right: 20px; /* Gap from center */
  border-left: 4px solid #FF5722;
}

.timeline-item.twitter {
  justify-content: flex-start;
  padding-right: 50%;
}

.timeline-item.reddit {
  justify-content: flex-end;
  padding-left: 50%;
}

/* Card Styles */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.agent-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.avatar-placeholder {
  width: 24px;
  height: 24px;
  background: #EEE;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #666;
}

.agent-name {
  font-size: 13px;
  font-weight: 700;
  color: #333;
}

.action-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}

.badge-post { background: #E3F2FD; color: #1565C0; }
.badge-quote { background: #F3E5F5; color: #7B1FA2; }
.badge-like { background: #FFEBEE; color: #C62828; }
.badge-repost { background: #E8F5E9; color: #2E7D32; }
.badge-comment { background: #FFF3E0; color: #E65100; }
.badge-default { background: #F5F5F5; color: #757575; }

.content-text {
  font-size: 13px;
  line-height: 1.5;
  color: #333;
  margin-bottom: 8px;
}

.quoted-block {
  background: #F9F9F9;
  border-left: 3px solid #DDD;
  padding: 8px 12px;
  border-radius: 0 4px 4px 0;
  margin-top: 8px;
}

.quote-author {
  font-size: 11px;
  color: #666;
  margin-bottom: 4px;
}

.quote-text {
  font-size: 12px;
  color: #555;
  font-style: italic;
}

.target-context {
  font-size: 11px;
  color: #666;
  background: #F5F5F5;
  padding: 6px;
  border-radius: 4px;
}

.card-footer {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: #999;
}

.time-tag { font-family: 'JetBrains Mono'; }

.waiting-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: #999;
}

.pulse-ring {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid #DDD;
  animation: ripple 1.5s infinite;
}

@keyframes ripple {
  0% { transform: scale(0.8); opacity: 1; }
  100% { transform: scale(2); opacity: 0; }
}

/* Transition Group */
.timeline-item-enter-active,
.timeline-item-leave-active {
  transition: all 0.5s ease;
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateY(-20px);
}

.timeline-item-leave-to {
  opacity: 0;
}

/* --- System Logs (unchanged) --- */
.system-logs {
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
  color: #888;
}

.log-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 120px;
  overflow-y: auto;
  padding-right: 4px;
}

.log-content::-webkit-scrollbar {
  width: 4px;
}

.log-content::-webkit-scrollbar-thumb {
  background: #333;
  border-radius: 2px;
}

.log-line {
  font-size: 11px;
  display: flex;
  gap: 12px;
  line-height: 1.5;
}

.log-time {
  color: #666;
  min-width: 75px;
}

.log-msg {
  color: #CCC;
  word-break: break-all;
}

.mono { font-family: 'JetBrains Mono', monospace; }
.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
