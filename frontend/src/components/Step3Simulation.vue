<template>
  <div class="simulation-panel">
    <RecoveryBanner :retry-key="`${simulationId}:run`" :auto-retry="!stopRequested" :completed="canGenerateReport" :error="startError" :busy="isStarting || recovering" :label="$t(connectionError ? 'recovery.reconnect' : 'recovery.restart')" :hint="connectionError ? '' : $t('recovery.restartHint')" @retry="recoverSimulation" />
    <RecoveryBanner :retry-key="`${simulationId}:report`" :error="reportError" :busy="isGeneratingReport" @retry="handleNextStep" />
    <RecoveryBanner :retry-key="`${simulationId}:stop`" :error="stopError" :busy="isStopping" :completed="runStatus.runner_status === 'stopped' && canGenerateReport" :label="$t('step3.retryStop')" @retry="handleStopSimulation" />
    <RecoveryBanner :retry-key="`${simulationId}:effort-config`" :error="configError" :busy="loadingConfig" :completed="!!fullRounds && !configError" @retry="loadEffortConfig" />
    <section v-if="phase === 0 && !stopRequested" class="effort-selector" aria-labelledby="effort-title">
      <h3 id="effort-title">{{ $t('step3.effortTitle') }}</h3>
      <p>{{ $t('step3.effortDescription') }}</p>
      <fieldset :disabled="isStarting || restoring || loadingConfig">
        <legend class="sr-only">{{ $t('step3.effortTitle') }}</legend>
        <label v-for="effort in simulationEfforts" :key="effort" class="effort-card" :class="{ selected: selectedEffort === effort }">
          <input type="radio" name="simulation-effort" :value="effort" :checked="selectedEffort === effort" @change="selectEffort(effort)">
          <strong>{{ $t(`step3.effort_${effort}`) }}</strong>
          <span>{{ fullRounds ? $t('step3.effortRounds', { rounds: roundsForEffort(fullRounds, effort) }) : $t('step3.loadingPlan') }}</span>
          <small>{{ $t(`step3.effort_${effort}Description`) }}</small>
        </label>
      </fieldset>
      <button class="action-btn primary" :disabled="isStarting || restoring || !fullRounds || !!startError" @click="doStartSimulation()">
        {{ $t(isStarting ? 'step3.startingSimulation' : 'step3.startSimulation') }}
      </button>
    </section>
    <p v-if="stopRequested && !canGenerateReport && !stopError" class="run-notice" role="status">{{ $t('step3.stoppingNotice') }}</p>
    <p v-if="runStatus.runner_status === 'stopped'" class="run-notice" role="status">{{ $t('step3.stoppedNotice') }}</p>
    <div v-if="showStopConfirmation" class="stop-overlay" @click.self="cancelStop">
      <section class="stop-dialog" ref="stopDialog" role="dialog" aria-modal="true" aria-labelledby="stop-title" aria-describedby="stop-warning" @keydown="handleDialogKeydown">
        <h3 id="stop-title">{{ $t('step3.stopTitle') }}</h3>
        <p id="stop-warning">{{ $t('step3.stopWarning') }}</p>
        <div class="action-controls">
          <button class="action-btn secondary" autofocus @click="cancelStop">{{ $t('step3.keepRunning') }}</button>
          <button class="action-btn primary" @click="confirmStop">{{ $t('step3.confirmStop') }}</button>
        </div>
      </section>
    </div>
    <!-- Top Control Bar -->
    <div class="control-bar">
      <div class="status-group">
        <!-- Twitter 平台进度 -->
        <div class="platform-status twitter" :class="{ active: runStatus.twitter_running, completed: runStatus.twitter_completed }">
          <div class="platform-header">
            <svg class="platform-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
            </svg>
            <span class="platform-name">Info Plaza</span>
            <span v-if="runStatus.twitter_completed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ runStatus.twitter_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || selectedRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">TIME</span>
              <span class="stat-value mono">{{ twitterElapsedTime }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ runStatus.twitter_actions_count || 0 }}</span>
            </span>
          </div>
          <!-- 可用动作提示 -->
          <div class="actions-tooltip">
            <div class="tooltip-title">Available Actions</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">POST</span>
              <span class="tooltip-action">LIKE</span>
              <span class="tooltip-action">REPOST</span>
              <span class="tooltip-action">QUOTE</span>
              <span class="tooltip-action">FOLLOW</span>
              <span class="tooltip-action">IDLE</span>
            </div>
          </div>
        </div>
        
        <!-- Reddit 平台进度 -->
        <div class="platform-status reddit" :class="{ active: runStatus.reddit_running, completed: runStatus.reddit_completed }">
          <div class="platform-header">
            <svg class="platform-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
            </svg>
            <span class="platform-name">Topic Community</span>
            <span v-if="runStatus.reddit_completed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ runStatus.reddit_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || selectedRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">TIME</span>
              <span class="stat-value mono">{{ redditElapsedTime }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ runStatus.reddit_actions_count || 0 }}</span>
            </span>
          </div>
          <!-- 可用动作提示 -->
          <div class="actions-tooltip">
            <div class="tooltip-title">Available Actions</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">POST</span>
              <span class="tooltip-action">COMMENT</span>
              <span class="tooltip-action">LIKE</span>
              <span class="tooltip-action">DISLIKE</span>
              <span class="tooltip-action">SEARCH</span>
              <span class="tooltip-action">TREND</span>
              <span class="tooltip-action">FOLLOW</span>
              <span class="tooltip-action">MUTE</span>
              <span class="tooltip-action">REFRESH</span>
              <span class="tooltip-action">IDLE</span>
            </div>
          </div>
        </div>
      </div>

      <div class="action-controls">
        <button v-if="canStop" class="action-btn secondary" @click="requestStop">{{ $t('step3.stopSimulation') }}</button>
        <button 
          class="action-btn primary"
          :disabled="!canGenerateReport || isGeneratingReport"
          @click="handleNextStep"
        >
          <span v-if="isGeneratingReport" class="loading-spinner-small"></span>
          {{ isGeneratingReport ? $t('step3.generatingReportBtn') : $t(runStatus.runner_status === 'stopped' ? 'step3.generatePartialReport' : 'step3.startGenerateReportBtn') }}
          <span v-if="!isGeneratingReport" class="arrow-icon">→</span>
        </button>
      </div>
    </div>

    <!-- Main Content: Dual Timeline -->
    <div class="main-content-area" ref="scrollContainer">
      <!-- Timeline Header -->
      <div class="timeline-header" v-if="allActions.length > 0">
        <div class="timeline-stats">
          <span class="total-count">TOTAL EVENTS: <span class="mono">{{ allActions.length }}</span></span>
          <span class="platform-breakdown">
            <span class="breakdown-item twitter">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
              <span class="mono">{{ twitterActionsCount }}</span>
            </span>
            <span class="breakdown-divider">/</span>
            <span class="breakdown-item reddit">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
              <span class="mono">{{ redditActionsCount }}</span>
            </span>
          </span>
        </div>
      </div>
      
      <!-- Timeline Feed -->
      <div class="timeline-feed">
        <div class="timeline-axis"></div>
        
        <TransitionGroup name="timeline-item">
          <div 
            v-for="action in chronologicalActions" 
            :key="action._uniqueId || action.id || `${action.timestamp}-${action.agent_id}`" 
            class="timeline-item"
            :class="action.platform"
          >
            <div class="timeline-marker">
              <div class="marker-dot"></div>
            </div>
            
            <div class="timeline-card">
              <div class="card-header">
                <div class="agent-info">
                  <div class="avatar-placeholder">{{ (action.agent_name || 'A')[0] }}</div>
                  <span class="agent-name">{{ action.agent_name }}</span>
                </div>
                
                <div class="header-meta">
                  <div class="platform-indicator">
                    <svg v-if="action.platform === 'twitter'" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
                    <svg v-else viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                  </div>
                  <div class="action-badge" :class="getActionTypeClass(action.action_type)">
                    {{ getActionTypeLabel(action.action_type) }}
                  </div>
                </div>
              </div>
              
              <div class="card-body">
                <!-- CREATE_POST: 发布帖子 -->
                <div v-if="action.action_type === 'CREATE_POST' && action.action_args?.content" class="content-text main-text">
                  {{ action.action_args.content }}
                </div>

                <!-- QUOTE_POST: 引用帖子 -->
                <template v-if="action.action_type === 'QUOTE_POST'">
                  <div v-if="action.action_args?.quote_content" class="content-text">
                    {{ action.action_args.quote_content }}
                  </div>
                  <div v-if="action.action_args?.original_content" class="quoted-block">
                    <div class="quote-header">
                      <svg class="icon-small" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                      <span class="quote-label">@{{ action.action_args.original_author_name || 'User' }}</span>
                    </div>
                    <div class="quote-text">
                      {{ truncateContent(action.action_args.original_content, 150) }}
                    </div>
                  </div>
                </template>

                <!-- REPOST: 转发帖子 -->
                <template v-if="action.action_type === 'REPOST'">
                  <div class="repost-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"></polyline><path d="M3 11V9a4 4 0 0 1 4-4h14"></path><polyline points="7 23 3 19 7 15"></polyline><path d="M21 13v2a4 4 0 0 1-4 4H3"></path></svg>
                    <span class="repost-label">Reposted from @{{ action.action_args?.original_author_name || 'User' }}</span>
                  </div>
                  <div v-if="action.action_args?.original_content" class="repost-content">
                    {{ truncateContent(action.action_args.original_content, 200) }}
                  </div>
                </template>

                <!-- LIKE_POST: 点赞帖子 -->
                <template v-if="action.action_type === 'LIKE_POST'">
                  <div class="like-info">
                    <svg class="icon-small filled" viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                    <span class="like-label">Liked @{{ action.action_args?.post_author_name || 'User' }}'s post</span>
                  </div>
                  <div v-if="action.action_args?.post_content" class="liked-content">
                    "{{ truncateContent(action.action_args.post_content, 120) }}"
                  </div>
                </template>

                <!-- CREATE_COMMENT: 发表评论 -->
                <template v-if="action.action_type === 'CREATE_COMMENT'">
                  <div v-if="action.action_args?.content" class="content-text">
                    {{ action.action_args.content }}
                  </div>
                  <div v-if="action.action_args?.post_id" class="comment-context">
                    <svg class="icon-small" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                    <span>Reply to post #{{ action.action_args.post_id }}</span>
                  </div>
                </template>

                <!-- SEARCH_POSTS: 搜索帖子 -->
                <template v-if="action.action_type === 'SEARCH_POSTS'">
                  <div class="search-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    <span class="search-label">Search Query:</span>
                    <span class="search-query">"{{ action.action_args?.query || '' }}"</span>
                  </div>
                </template>

                <!-- FOLLOW: 关注用户 -->
                <template v-if="action.action_type === 'FOLLOW'">
                  <div class="follow-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg>
                    <span class="follow-label">Followed @{{ action.action_args?.target_user || action.action_args?.user_id || 'User' }}</span>
                  </div>
                </template>

                <!-- UPVOTE / DOWNVOTE -->
                <template v-if="action.action_type === 'UPVOTE_POST' || action.action_type === 'DOWNVOTE_POST'">
                  <div class="vote-info">
                    <svg v-if="action.action_type === 'UPVOTE_POST'" class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    <svg v-else class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    <span class="vote-label">{{ action.action_type === 'UPVOTE_POST' ? 'Upvoted' : 'Downvoted' }} Post</span>
                  </div>
                  <div v-if="action.action_args?.post_content" class="voted-content">
                    "{{ truncateContent(action.action_args.post_content, 120) }}"
                  </div>
                </template>

                <!-- DO_NOTHING: 无操作（静默） -->
                <template v-if="action.action_type === 'DO_NOTHING'">
                  <div class="idle-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    <span class="idle-label">Action Skipped</span>
                  </div>
                </template>

                <!-- 通用回退：未知类型或有 content 但未被上述处理 -->
                <div v-if="!['CREATE_POST', 'QUOTE_POST', 'REPOST', 'LIKE_POST', 'CREATE_COMMENT', 'SEARCH_POSTS', 'FOLLOW', 'UPVOTE_POST', 'DOWNVOTE_POST', 'DO_NOTHING'].includes(action.action_type) && action.action_args?.content" class="content-text">
                  {{ action.action_args.content }}
                </div>
              </div>

              <div class="card-footer">
                <span class="time-tag">R{{ action.round_num }} • {{ formatActionTime(action.timestamp) }}</span>
                <!-- Platform tag removed as it is in header now -->
              </div>
            </div>
          </div>
        </TransitionGroup>

        <div v-if="allActions.length === 0" class="waiting-state">
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
import RecoveryBanner from './RecoveryBanner.vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  startSimulation,
  stopSimulation,
  getRunStatus,
  getRunStatusDetail,
  getSimulationConfig
} from '../api/simulation'
import { generateReport } from '../api/report'
import { simulationEfforts, normalizeSimulationEffort, plannedSimulationRounds, roundsForEffort } from '../utils/simulationEffort'

const { t } = useI18n()

const props = defineProps({
  simulationId: String,
  minutesPerRound: {
    type: Number,
    default: 30 // 默认每轮30分钟
  },
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const router = useRouter()

// State
const isGeneratingReport = ref(false)
const phase = ref(0) // 0: 未开始, 1: 运行中, 2: 已完成
const isStarting = ref(false)
const startRequested = ref(false)
const isStopping = ref(false)
const loadingFinalActivity = ref(false)
const startError = ref(null)
const connectionError = ref(false)
const reportError = ref('')
const runStatus = ref({})
const restoring = ref(true)
const simulationConfig = ref(null)
const loadingConfig = ref(false)
const configError = ref('')
const stopError = ref('')
const showStopConfirmation = ref(false)
const stopDialog = ref(null)
let stopTrigger = null
const effortStorageKey = `simulation:${props.simulationId}:effort`
const stopStorageKey = `simulation:${props.simulationId}:stop-requested`
const readStored = key => { try { return localStorage.getItem(key) } catch { return null } }
const saveStored = (key, value) => { try { localStorage.setItem(key, value) } catch { /* Browser storage is optional. */ } }
const selectedEffort = ref(normalizeSimulationEffort(readStored(effortStorageKey)))
const stopRequested = ref(readStored(stopStorageKey) === 'true')
const fullRounds = computed(() => plannedSimulationRounds(simulationConfig.value))
const selectedRounds = computed(() => roundsForEffort(fullRounds.value, selectedEffort.value))
const canStop = computed(() => !stopRequested.value && (isStarting.value || ['starting', 'running', 'paused'].includes(runStatus.value.runner_status)))
const canGenerateReport = computed(() => ['completed', 'stopped'].includes(runStatus.value.runner_status) && !startError.value && !stopError.value && !isStopping.value && !loadingFinalActivity.value)
const selectEffort = effort => {
  selectedEffort.value = normalizeSimulationEffort(effort)
  saveStored(effortStorageKey, selectedEffort.value)
}
const loadEffortConfig = async () => {
  if (loadingConfig.value) return
  loadingConfig.value = true
  configError.value = ''
  try {
    const response = await getSimulationConfig(props.simulationId)
    if (!response.success || !plannedSimulationRounds(response.data)) throw new Error(response.error || t('step3.invalidPlan'))
    simulationConfig.value = response.data
  } catch (error) { configError.value = error.message }
  finally { loadingConfig.value = false }
}
let runGeneration = 0
const allActions = ref([]) // 所有动作（增量累积）
const actionIds = ref(new Set()) // 用于去重的动作ID集合
const scrollContainer = ref(null)

// Computed
// 按时间顺序显示动作（最新的在最后面，即底部）
const chronologicalActions = computed(() => {
  return allActions.value
})

// 各平台动作计数
const twitterActionsCount = computed(() => {
  return allActions.value.filter(a => a.platform === 'twitter').length
})

const redditActionsCount = computed(() => {
  return allActions.value.filter(a => a.platform === 'reddit').length
})

// 格式化模拟流逝时间（根据轮次和每轮分钟数计算）
const formatElapsedTime = (currentRound) => {
  if (!currentRound || currentRound <= 0) return '0h 0m'
  const totalMinutes = currentRound * props.minutesPerRound
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours}h ${minutes}m`
}

// Twitter平台的模拟流逝时间
const twitterElapsedTime = computed(() => {
  return formatElapsedTime(runStatus.value.twitter_current_round || 0)
})

// Reddit平台的模拟流逝时间
const redditElapsedTime = computed(() => {
  return formatElapsedTime(runStatus.value.reddit_current_round || 0)
})

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

// 重置所有状态（用于重新启动模拟）
const resetAllState = () => {
  phase.value = 0
  runStatus.value = {}
  allActions.value = []
  actionIds.value = new Set()
  prevTwitterRound.value = 0
  prevRedditRound.value = 0
  startError.value = null
  isStarting.value = false
  isStopping.value = false
  stopPolling()  // 停止之前可能存在的轮询
}

// 启动模拟
const doStartSimulation = async (force = false) => {
  if (isStarting.value || stopRequested.value) return
  if (!props.simulationId) {
    addLog(t('log.errorMissingSimId'))
    return
  }

  if (!fullRounds.value) await loadEffortConfig()
  if (!fullRounds.value) return
  runGeneration += 1
  stopPolling()
  
  isStarting.value = true
  startRequested.value = true
  startError.value = null
  addLog(t('log.startingDualSim'))
  emit('update-status', 'processing')
  
  try {
    const params = {
      simulation_id: props.simulationId,
      platform: 'parallel',
      simulation_effort: selectedEffort.value,
      force,  // Only an explicit recovery restarts a failed run.
      enable_graph_memory_update: true  // 开启动态图谱更新
    }
    
    addLog(t('log.graphMemoryUpdateEnabled'))
    
    const res = await startSimulation(params)
    
    if (stopRequested.value) return
    if (res.success && res.data) {
      startRequested.value = false
      if (res.data.force_restarted) {
        allActions.value = []
        actionIds.value = new Set()
      }
      addLog(t('log.engineStarted'))
      addLog(`  ├─ PID: ${res.data.process_pid || '-'}`)
      
      phase.value = 1
      runStatus.value = res.data
      
      startStatusPolling()
      startDetailPolling()
    } else {
      startError.value = res.error || t('common.unknownError')
      addLog(t('log.startFailed', { error: res.error || t('common.unknownError') }))
      emit('update-status', 'error')
    }
  } catch (err) {
    connectionError.value = !err.response
    startError.value = err.message
    addLog(t('log.startException', { error: err.message }))
    emit('update-status', 'error')
  } finally {
    isStarting.value = false
    if (stopRequested.value) await handleStopSimulation()
  }
}

// Confirmation changes only local intent until the user explicitly accepts.
const requestStop = event => {
  if (!canStop.value) return
  stopTrigger = event?.currentTarget
  showStopConfirmation.value = true
  nextTick(() => stopDialog.value?.querySelector('button')?.focus())
}
const cancelStop = () => {
  showStopConfirmation.value = false
  stopTrigger?.focus()
}
const handleDialogKeydown = event => {
  if (event.key === 'Escape') { event.preventDefault(); cancelStop() }
  if (event.key !== 'Tab') return
  const buttons = stopDialog.value?.querySelectorAll('button')
  if (!buttons?.length) return
  if (event.shiftKey && event.target === buttons[0]) { event.preventDefault(); buttons[buttons.length - 1].focus() }
  else if (!event.shiftKey && event.target === buttons[buttons.length - 1]) { event.preventDefault(); buttons[0].focus() }
}
const confirmStop = async () => {
  if (!showStopConfirmation.value || stopRequested.value) return
  showStopConfirmation.value = false
  stopRequested.value = true
  saveStored(stopStorageKey, 'true')
  runGeneration += 1
  startError.value = null
  stopPolling()
  if (!isStarting.value) await handleStopSimulation()
}

const handleStopSimulation = async () => {
  if (!props.simulationId || isStopping.value) return
  stopRequested.value = true
  saveStored(stopStorageKey, 'true')
  isStopping.value = true
  stopError.value = ''
  startError.value = null
  phase.value = 1
  runGeneration += 1
  stopPolling()
  try {
    if (['completed', 'stopped'].includes(runStatus.value.runner_status)) {
      phase.value = 2
      await fetchRunStatusDetail()
      return
    }
    const res = await stopSimulation({ simulation_id: props.simulationId, wait: false })
    if (!res.success) throw new Error(res.error || t('common.unknownError'))
    runStatus.value = { ...runStatus.value, ...res.data }
    if (res.data?.runner_status === 'failed') throw new Error(res.data.error || t('log.simFailed'))
    if (res.data?.runner_status === 'stopped' || res.data?.runner_status === 'completed') {
      phase.value = 2
      emit('update-status', 'completed')
      await fetchRunStatusDetail()
    } else {
      runStatus.value.runner_status = 'stopping'
      startStatusPolling()
      startDetailPolling()
    }
  } catch (error) {
    stopError.value = error.message
    emit('update-status', 'error')
  } finally { isStopping.value = false }
}

// 轮询状态
let statusTimer = null
let detailTimer = null

const startStatusPolling = () => {
  if (statusTimer) clearInterval(statusTimer)
  statusTimer = setInterval(fetchRunStatus, 2000)
}

const startDetailPolling = () => {
  if (detailTimer) clearInterval(detailTimer)
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
  if (!props.simulationId || loadingFinalActivity.value) return
  
  const generation = runGeneration
  try {
    const res = await getRunStatus(props.simulationId)
    if (generation !== runGeneration) return
    
    if (res.success && res.data) {
      const data = res.data
      
      runStatus.value = data
      if (data.runner_status !== 'idle' && data.simulation_effort) selectEffort(data.simulation_effort)
      if (data.stop_requested || ['stopping', 'stopped'].includes(data.runner_status)) {
        stopRequested.value = true
        saveStored(stopStorageKey, 'true')
      }
      
      // 分别检测各平台的轮次变化并输出日志
      if (data.twitter_current_round > prevTwitterRound.value) {
        addLog(`[Plaza] R${data.twitter_current_round}/${data.total_rounds} | T:${data.twitter_simulated_hours || 0}h | A:${data.twitter_actions_count}`)
        prevTwitterRound.value = data.twitter_current_round
      }
      
      if (data.reddit_current_round > prevRedditRound.value) {
        addLog(`[Community] R${data.reddit_current_round}/${data.total_rounds} | T:${data.reddit_simulated_hours || 0}h | A:${data.reddit_actions_count}`)
        prevRedditRound.value = data.reddit_current_round
      }
      
      // 检测模拟是否已完成（通过 runner_status 或平台完成状态判断）
      const isCompleted = data.runner_status === 'completed' || data.runner_status === 'stopped'
      const isFailed = data.runner_status === 'failed'
      
      // runner_status is authoritative because the backend only publishes a
      // terminal state after the Zep ingestion barrier has completed.
      if (isFailed) {
        connectionError.value = false
        if (stopRequested.value) stopError.value = data.error || t('log.simFailed')
        else startError.value = data.error || t('log.simFailed')
        addLog(t('log.simFailed') + (data.error ? `: ${data.error}` : ''))
        phase.value = 2
        stopPolling()
        emit('update-status', 'error')
      } else if (isCompleted) {
        startError.value = null
        stopError.value = ''
        loadingFinalActivity.value = true
        stopPolling()
        try {
          // Status and detail use separate polling intervals. Fetch once after
          // the terminal barrier so the last saved actions cannot be missed.
          await fetchRunStatusDetail()
          if (generation !== runGeneration) return
          if (!startError.value && !stopError.value) {
            addLog(t('log.simCompleted'))
            phase.value = 2
            emit('update-status', 'completed')
          } else emit('update-status', 'error')
        } finally { loadingFinalActivity.value = false }
      } else if (data.runner_status !== 'idle') {
        phase.value = 1
      }
      return data
    } else { throw new Error(res.error || t('common.unknownError')) }
  } catch (err) {
    if (generation !== runGeneration) return
    stopPolling()
    connectionError.value = true
    if (stopRequested.value) stopError.value = err.message
    else startError.value = err.message
    emit('update-status', 'error')
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
  
  const generation = runGeneration
  try {
    const res = await getRunStatusDetail(props.simulationId)
    if (generation !== runGeneration) return
    
    if (res.success && res.data) {
      // 使用 all_actions 获取完整的动作列表
      const serverActions = res.data.all_actions || []
      
      // 增量添加新动作（去重）
      let newActionsAdded = 0
      serverActions.forEach(action => {
        // 生成唯一ID
        const actionId = action.id || `${action.timestamp}-${action.platform}-${action.agent_id}-${action.action_type}`
        
        if (!actionIds.value.has(actionId)) {
          actionIds.value.add(actionId)
          allActions.value.push({
            ...action,
            _uniqueId: actionId
          })
          newActionsAdded++
        }
      })
      
      // New activity remains available without moving the user's scroll position.
    } else { throw new Error(res.error || t('common.unknownError')) }
  } catch (err) {
    if (generation !== runGeneration) return
    stopPolling()
    connectionError.value = true
    if (stopRequested.value) stopError.value = err.message
    else startError.value = err.message
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
    'QUOTE_POST': 'QUOTE',
    'UPVOTE_POST': 'UPVOTE',
    'DOWNVOTE_POST': 'DOWNVOTE'
  }
  return labels[type] || type || 'UNKNOWN'
}

const getActionTypeClass = (type) => {
  const classes = {
    'CREATE_POST': 'badge-post',
    'REPOST': 'badge-action',
    'LIKE_POST': 'badge-action',
    'CREATE_COMMENT': 'badge-comment',
    'LIKE_COMMENT': 'badge-action',
    'QUOTE_POST': 'badge-post',
    'FOLLOW': 'badge-meta',
    'SEARCH_POSTS': 'badge-meta',
    'UPVOTE_POST': 'badge-action',
    'DOWNVOTE_POST': 'badge-action',
    'DO_NOTHING': 'badge-idle'
  }
  return classes[type] || 'badge-default'
}

const truncateContent = (content, maxLength = 100) => {
  if (!content) return ''
  if (content.length > maxLength) return content.substring(0, maxLength) + '...'
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

const handleNextStep = async () => {
  if (!canGenerateReport.value) return
  if (!props.simulationId) {
    addLog(t('log.errorMissingSimId'))
    return
  }

  if (isGeneratingReport.value) {
    addLog(t('log.reportRequestSent'))
    return
  }
  
  reportError.value = ''
  isGeneratingReport.value = true
  addLog(t('log.startingReportGen'))
  
  try {
    const res = await generateReport({
      simulation_id: props.simulationId
    })
    
    if (res.success && res.data) {
      const reportId = res.data.report_id
      addLog(t('log.reportGenTaskStarted', { reportId }))
      
      // 跳转到报告页面
      router.push({ name: 'Report', params: { reportId } })
    } else {
      reportError.value = res.error || t('common.unknownError')
      addLog(t('log.reportGenFailed', { error: res.error || t('common.unknownError') }))
      isGeneratingReport.value = false
    }
  } catch (err) {
    reportError.value = err.message
    addLog(t('log.reportGenException', { error: err.message }))
    isGeneratingReport.value = false
  }
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

const restoreSimulation = async () => {
  restoring.value = true
  startError.value = null
  connectionError.value = false
  try {
    const data = await fetchRunStatus()
    if (!data) return
    if (!['completed', 'stopped'].includes(data.runner_status)) await fetchRunStatusDetail()
    if (startError.value || stopError.value) return
    if (stopRequested.value && !['stopping', 'stopped', 'completed'].includes(data.runner_status)) {
      await handleStopSimulation()
      return
    }
    if (data.runner_status === 'idle') {
      phase.value = 0
      emit('update-status', 'idle')
      await loadEffortConfig()
    } else if (!['completed', 'stopped', 'failed'].includes(data.runner_status)) {
      phase.value = 1
      emit('update-status', 'processing')
      startStatusPolling()
      startDetailPolling()
    }
  } finally { restoring.value = false }
}

const recovering = ref(false)
const recoverSimulation = async () => {
  if (stopRequested.value) return handleStopSimulation()
  if (recovering.value || isStarting.value) return
  recovering.value = true
  try {
    if (connectionError.value) {
      const retryRequestedStart = startRequested.value
      await restoreSimulation()
      if (retryRequestedStart && runStatus.value.runner_status === 'idle' && !startError.value && !stopError.value && !configError.value) {
        await doStartSimulation(false)
      }
    } else await doStartSimulation(true)
  } finally { recovering.value = false }
}

onMounted(() => {
  addLog(t('log.step3Init'))
  if (props.simulationId) {
    restoreSimulation()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.effort-selector { padding: 20px 24px; border-bottom: 1px solid #e5e7eb; background: #fafafa; flex-shrink: 0; }
.effort-selector h3, .stop-dialog h3 { margin: 0 0 8px; font-size: 16px; }
.effort-selector p, .stop-dialog p { margin: 0 0 16px; color: #555; font-size: 13px; line-height: 1.6; }
.effort-selector fieldset { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 0; border: 0; margin: 0 0 16px; }
.effort-card { display: flex; flex-direction: column; gap: 7px; padding: 12px; border: 1px solid #d9dde3; border-radius: 8px; background: white; cursor: pointer; font-size: 12px; }
.effort-card.selected { border: 2px solid #111; padding: 11px; }
.effort-card input { align-self: flex-start; accent-color: #111; }
.effort-card small { color: #666; line-height: 1.4; }
.effort-card:focus-within { outline: 2px solid #526ff0; outline-offset: 2px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
.run-notice { margin: 0; padding: 12px 24px; background: #fff7e6; color: #725322; font-size: 13px; line-height: 1.5; flex-shrink: 0; }
.stop-overlay { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(0,0,0,.45); }
.stop-dialog { max-width: 460px; border-radius: 12px; background: white; padding: 24px; box-shadow: 0 16px 56px rgba(0,0,0,.2); }
.action-controls { display: flex; flex-wrap: wrap; gap: 8px; }
.stop-dialog .action-controls { display: flex; flex-wrap: wrap; gap: 12px; justify-content: flex-end; }
@media (max-width: 600px) { .effort-selector { padding: 12px; } .effort-selector fieldset { gap: 6px; } .effort-card { padding: 8px; } .effort-card.selected { padding: 7px; } }

.simulation-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #FFFFFF;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
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
  z-index: 10;
  height: 64px;
}

.status-group {
  display: flex;
  gap: 12px;
}

/* Platform Status Cards */
.platform-status {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 4px;
  background: #FAFAFA;
  border: 1px solid #EAEAEA;
  opacity: 0.7;
  transition: all 0.3s;
  min-width: 140px;
  position: relative;
  cursor: pointer;
}

.platform-status.active {
  opacity: 1;
  border-color: #333;
  background: #FFF;
}

.platform-status.completed {
  opacity: 1;
  border-color: #1A936F;
  background: #F2FAF6;
}

/* Actions Tooltip */
.actions-tooltip {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-top: 8px;
  padding: 10px 14px;
  background: #000;
  color: #FFF;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  z-index: 100;
  min-width: 180px;
  pointer-events: none;
}

.actions-tooltip::before {
  content: '';
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-bottom: 6px solid #000;
}

.platform-status:hover .actions-tooltip {
  opacity: 1;
  visibility: visible;
}

.tooltip-title {
  font-size: 10px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}

.tooltip-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tooltip-action {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
  color: #FFF;
  letter-spacing: 0.03em;
}

.platform-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
}

.platform-name {
  font-size: 11px;
  font-weight: 700;
  color: #000;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.platform-status.twitter .platform-icon { color: #000; }
.platform-status.reddit .platform-icon { color: #000; }

.platform-stats {
  display: flex;
  gap: 10px;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 3px;
}

.stat-label {
  font-size: 8px;
  color: #999;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-value {
  font-size: 11px;
  font-weight: 600;
  color: #333;
}

.stat-total, .stat-unit {
  font-size: 9px;
  color: #999;
  font-weight: 400;
}

.status-badge {
  margin-left: auto;
  color: #1A936F;
  display: flex;
  align-items: center;
}

/* Action Button */
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.action-btn.primary {
  background: #000;
  color: #FFF;
}

.action-btn.primary:hover:not(:disabled) {
  background: #333;
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* --- Main Content Area --- */
.main-content-area {
  flex: 1;
  overflow-y: auto;
  position: relative;
  background: #FFF;
}

/* Timeline Header */
.timeline-header {
  position: sticky;
  top: 0;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(8px);
  padding: 12px 24px;
  border-bottom: 1px solid #EAEAEA;
  z-index: 5;
  display: flex;
  justify-content: center;
}

.timeline-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11px;
  color: #666;
  background: #F5F5F5;
  padding: 4px 12px;
  border-radius: 20px;
}

.total-count {
  font-weight: 600;
  color: #333;
}

.platform-breakdown {
  display: flex;
  align-items: center;
  gap: 8px;
}

.breakdown-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.breakdown-divider { color: #DDD; }
.breakdown-item.twitter { color: #000; }
.breakdown-item.reddit { color: #000; }

/* --- Timeline Feed --- */
.timeline-feed {
  padding: 24px 0;
  position: relative;
  min-height: 100%;
  max-width: 900px;
  margin: 0 auto;
}

.timeline-axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: #EAEAEA; /* Cleaner line */
  transform: translateX(-50%);
}

.timeline-item {
  display: flex;
  justify-content: center;
  margin-bottom: 32px;
  position: relative;
  width: 100%;
}

.timeline-marker {
  position: absolute;
  left: 50%;
  top: 24px;
  width: 10px;
  height: 10px;
  background: #FFF;
  border: 1px solid #CCC;
  border-radius: 50%;
  transform: translateX(-50%);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
}

.marker-dot {
  width: 4px;
  height: 4px;
  background: #CCC;
  border-radius: 50%;
}

.timeline-item.twitter .marker-dot { background: #000; }
.timeline-item.reddit .marker-dot { background: #000; }
.timeline-item.twitter .timeline-marker { border-color: #000; }
.timeline-item.reddit .timeline-marker { border-color: #000; }

/* Card Layout */
.timeline-card {
  width: calc(100% - 48px);
  background: #FFF;
  border-radius: 2px;
  padding: 16px 20px;
  border: 1px solid #EAEAEA;
  box-shadow: 0 2px 10px rgba(0,0,0,0.02);
  position: relative;
  transition: all 0.2s;
}

.timeline-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  border-color: #DDD;
}

/* Left side (Twitter) */
.timeline-item.twitter {
  justify-content: flex-start;
  padding-right: 50%;
}
.timeline-item.twitter .timeline-card {
  margin-left: auto;
  margin-right: 32px; /* Gap from axis */
}

/* Right side (Reddit) */
.timeline-item.reddit {
  justify-content: flex-end;
  padding-left: 50%;
}
.timeline-item.reddit .timeline-card {
  margin-right: auto;
  margin-left: 32px; /* Gap from axis */
}

/* Card Content Styles */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F5F5F5;
}

.agent-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar-placeholder {
  width: 24px;
  height: 24px;
  background: #000;
  color: #FFF;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: #000;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.platform-indicator {
  color: #999;
  display: flex;
  align-items: center;
}

.action-badge {
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 2px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border: 1px solid transparent;
}

/* Monochromatic Badges */
.badge-post { background: #F0F0F0; color: #333; border-color: #E0E0E0; }
.badge-comment { background: #F0F0F0; color: #666; border-color: #E0E0E0; }
.badge-action { background: #FFF; color: #666; border: 1px solid #E0E0E0; }
.badge-meta { background: #FAFAFA; color: #999; border: 1px dashed #DDD; }
.badge-idle { opacity: 0.5; }

.content-text {
  font-size: 13px;
  line-height: 1.6;
  color: #333;
  margin-bottom: 10px;
}

.content-text.main-text {
  font-size: 14px;
  color: #000;
}

/* Info Blocks (Quote, Repost, etc) */
.quoted-block, .repost-content {
  background: #F9F9F9;
  border: 1px solid #EEE;
  padding: 10px 12px;
  border-radius: 2px;
  margin-top: 8px;
  font-size: 12px;
  color: #555;
}

.quote-header, .repost-info, .like-info, .search-info, .follow-info, .vote-info, .idle-info, .comment-context {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 11px;
  color: #666;
}

.icon-small {
  color: #999;
}
.icon-small.filled {
  color: #999; /* Keep icons neutral unless highlighted */
}

.search-query {
  font-family: 'JetBrains Mono', monospace;
  background: #F0F0F0;
  padding: 0 4px;
  border-radius: 2px;
}

.card-footer {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
  font-size: 10px;
  color: #BBB;
  font-family: 'JetBrains Mono', monospace;
}

/* Waiting State */
.waiting-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: #CCC;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.pulse-ring {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid #EAEAEA;
  animation: ripple 2s infinite;
}

@keyframes ripple {
  0% { transform: scale(0.8); opacity: 1; border-color: #CCC; }
  100% { transform: scale(2.5); opacity: 0; border-color: #EAEAEA; }
}

/* Animation */
.timeline-item-enter-active,
.timeline-item-leave-active {
  transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.timeline-item-leave-to {
  opacity: 0;
}

/* Logs */
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
  color: #666;
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
  display: flex;
  gap: 12px;
  line-height: 1.5;
}

.log-time { color: #555; min-width: 75px; }
.log-msg { color: #BBB; word-break: break-all; }
.mono { font-family: 'JetBrains Mono', monospace; }

/* Loading spinner for button */
.loading-spinner-small {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-right: 6px;
}
</style>
