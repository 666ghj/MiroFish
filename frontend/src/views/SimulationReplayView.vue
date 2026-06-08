<template>
  <div class="replay-view">
    <!-- ========== Header bar ========== -->
    <header class="replay-header">
      <div class="header-left">
        <button class="back-btn" @click="goBack">←</button>
        <div class="title-block">
          <div class="title-main">Foresight's Sandbox</div>
          <div class="title-sub">
            <span v-if="currentAction">
              Foresight is {{ isSimLive ? 'running' : 'replaying' }}
              双世界并行模拟 ·
              <span class="platform-tag" :class="currentAction.platform">
                {{ currentAction.platform === 'twitter' ? 'Twitter' : 'Reddit' }}
              </span>
              event ·
              <span class="sub-detail">Round {{ currentRoundNumber }}/{{ maxRound }}</span>
              ·
              <span class="sub-detail">Day {{ currentRound?.simulated_day ?? '-' }}
                {{ String(currentRound?.simulated_hour ?? 0).padStart(2, '0') }}:00</span>
            </span>
            <span v-else-if="loading">loading replay data…</span>
            <span v-else>no actions yet</span>
          </div>
        </div>
      </div>
      <div class="header-right">
        <div class="theme-toggle-slot" id="theme-toggle-anchor"></div>
        <button class="icon-btn" @click="toggleAnalyst" :title="analystMode ? '切换沉浸视图' : '切换分析视图'">
          {{ analystMode ? '◫' : '▦' }}
        </button>
        <button class="icon-btn" @click="reload" title="刷新数据">↻</button>
      </div>
    </header>

    <!-- ========== Loading / Error ========== -->
    <div v-if="loading" class="screen-state">
      <div class="state-text">加载回放数据…</div>
    </div>
    <div v-else-if="loadError" class="screen-state">
      <div class="state-text error">加载失败：{{ loadError }}</div>
      <button class="primary-btn" @click="reload">重试</button>
    </div>

    <!-- ========== Main Stage (Cinematic Mode) ========== -->
    <main v-else-if="replayData && !analystMode" class="stage-wrap">
      <div class="stage">
        <!-- 平台框（类似浏览器/reddit 外壳） -->
        <div class="platform-frame" :class="currentAction?.platform || 'reddit'">
          <div class="platform-frame-head">
            <span class="dot red"></span>
            <span class="dot yellow"></span>
            <span class="dot green"></span>
            <span class="platform-url mono">
              <template v-if="currentAction?.platform === 'twitter'">x.com/{{ currentAction.agent_name }}</template>
              <template v-else-if="currentAction?.platform === 'reddit'">reddit.com/r/foresight/u/{{ currentAction.agent_name }}</template>
              <template v-else>foresight://sandbox/idle</template>
            </span>
          </div>

          <!-- 内容区 -->
          <div class="platform-frame-body">
            <!-- 有动作时显示帖子卡片 -->
            <div v-if="currentAction" class="post-card">
              <!-- 平台头部：reddit 子版 或 twitter 推文顶栏 -->
              <div v-if="currentAction.platform === 'reddit'" class="reddit-subreddit-bar">
                r/foresight · posted by u/{{ currentAction.agent_name }}
                · {{ formatTime(currentAction.timestamp) }}
              </div>
              <div v-else class="twitter-top-bar">
                <div class="avatar" :style="avatarGradient(currentAction.agent_id)">{{ agentInitial(currentAction.agent_name) }}</div>
                <div class="tw-names">
                  <div class="tw-display">{{ currentAction.agent_name }}</div>
                  <div class="tw-handle mono">@{{ getAgentUsername(currentAction.agent_id) }} · {{ formatTime(currentAction.timestamp) }}</div>
                </div>
              </div>

              <!-- 动作类型 badge -->
              <div class="action-type-badge" :class="currentAction.action_type.toLowerCase()">
                {{ formatActionType(currentAction.action_type) }}
              </div>

              <!-- 内容 -->
              <div class="post-content" v-if="currentAction.action_args?.content">
                {{ currentAction.action_args.content }}
              </div>
              <div class="post-content empty" v-else-if="currentAction.action_type === 'DO_NOTHING'">
                <em>（该 Agent 本轮未产生动作）</em>
              </div>
              <div class="post-content" v-else>
                {{ JSON.stringify(currentAction.action_args) }}
              </div>

              <!-- 底部互动栏 -->
              <div v-if="currentAction.platform === 'reddit'" class="reddit-actions">
                <span class="reddit-btn">▲ 0</span>
                <span class="reddit-btn">💬 {{ (currentRound?.stats?.by_type?.CREATE_COMMENT) || 0 }}</span>
                <span class="reddit-btn">⇄ {{ (currentRound?.stats?.by_type?.QUOTE_POST) || 0 }}</span>
                <span class="reddit-btn">Share</span>
              </div>
              <div v-else class="twitter-actions">
                <span class="tw-btn">💬 0</span>
                <span class="tw-btn">🔁 {{ (currentRound?.stats?.by_type?.QUOTE_POST) || 0 }}</span>
                <span class="tw-btn">♡ 0</span>
                <span class="tw-btn">📊 —</span>
              </div>
            </div>
            <!-- 无动作占位 -->
            <div v-else class="empty-stage">
              <div class="empty-icon">◌</div>
              <div class="empty-msg">
                <template v-if="allActions.length === 0">
                  还没有任何动作数据，点刷新试试
                </template>
                <template v-else>
                  拖动进度条开始回放
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- stage 下方：round 统计带 -->
        <div class="stage-meta" v-if="currentRound">
          <div class="meta-item">
            <span class="meta-label">本轮动作</span>
            <span class="meta-value">{{ currentRound.stats.total_actions }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">活跃 agent</span>
            <span class="meta-value">{{ currentRound.stats.active_agents_count }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">POST</span>
            <span class="meta-value">{{ currentRound.stats.by_type?.CREATE_POST || 0 }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">COMMENT</span>
            <span class="meta-value">{{ currentRound.stats.by_type?.CREATE_COMMENT || 0 }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">QUOTE</span>
            <span class="meta-value">{{ currentRound.stats.by_type?.QUOTE_POST || 0 }}</span>
          </div>
        </div>
      </div>
    </main>

    <!-- ========== Analyst Mode (原三栏) ========== -->
    <main v-else-if="replayData && analystMode" class="analyst-body">
      <aside class="col-workflow">
        <h3 class="col-title">工作流时间线</h3>
        <div class="workflow-list">
          <div
            v-for="step in replayData.workflow"
            :key="step.step"
            class="workflow-step"
            :class="{ 'is-completed': step.status === 'completed', 'is-running': step.status === 'running' }"
          >
            <div class="step-marker"><span class="step-num">{{ step.step }}</span></div>
            <div class="step-body">
              <div class="step-name">{{ step.name }}</div>
              <div class="step-meta">
                <template v-if="step.step === 1">
                  <div class="meta-line">{{ step.metadata.files?.length || 0 }} 个文件</div>
                </template>
                <template v-else-if="step.step === 2">
                  <div class="meta-line">{{ step.metadata.entities_count }} 个实体</div>
                </template>
                <template v-else-if="step.step === 3">
                  <div class="meta-line">{{ step.metadata.profiles_count }} 个人设</div>
                </template>
                <template v-else-if="step.step === 4">
                  <div class="meta-line">{{ step.metadata.total_simulation_hours }}h / 每轮 {{ step.metadata.minutes_per_round }}min</div>
                </template>
                <template v-else-if="step.step === 5">
                  <div class="meta-line">{{ step.metadata.total_rounds_executed }} 轮 · {{ step.metadata.total_actions }} 动作</div>
                </template>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <section class="col-feed">
        <h3 class="col-title">动作流（全部 {{ allActions.length }} 条）</h3>
        <div class="feed-list" ref="feedListRef">
          <div
            v-for="(action, idx) in allActions"
            :key="idx"
            class="feed-row"
            :class="{ active: idx === currentActionIndex }"
            @click="jumpToIndex(idx)"
          >
            <span class="feed-time mono">r{{ action.round_num }}</span>
            <span class="feed-platform" :class="action.platform">{{ action.platform[0].toUpperCase() }}</span>
            <span class="feed-agent">{{ action.agent_name }}</span>
            <span class="feed-type">{{ action.action_type }}</span>
            <span class="feed-content">{{ truncate(action.action_args?.content || '', 80) }}</span>
          </div>
        </div>
      </section>

      <aside class="col-stats">
        <h3 class="col-title">全局统计</h3>
        <div class="stat-block">
          <div class="stat-row"><span>总动作</span><span class="mono">{{ replayData.aggregate.total_actions }}</span></div>
          <div class="stat-row"><span>有效 rounds</span><span class="mono">{{ replayData.aggregate.rounds_with_actions }}</span></div>
          <div class="stat-row"><span>Twitter</span><span class="mono">{{ replayData.aggregate.platform_totals?.twitter || 0 }}</span></div>
          <div class="stat-row"><span>Reddit</span><span class="mono">{{ replayData.aggregate.platform_totals?.reddit || 0 }}</span></div>
        </div>
        <div class="stat-section">
          <div class="section-label-sm">类型分布</div>
          <div v-for="(count, type) in replayData.aggregate.action_type_distribution" :key="type" class="bar-row">
            <span class="bar-label">{{ type }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: barWidth(count) + '%' }"></div></div>
            <span class="bar-num mono">{{ count }}</span>
          </div>
        </div>
        <div class="stat-section">
          <div class="section-label-sm">Top Agents</div>
          <div v-for="agent in replayData.aggregate.top_agents.slice(0, 8)" :key="agent.agent_id" class="top-agent-row">
            <span class="top-agent-rank mono">#{{ agent.agent_id }}</span>
            <span class="top-agent-name">{{ agent.agent_name }}</span>
            <span class="top-agent-count mono">{{ agent.count }}</span>
          </div>
        </div>
      </aside>
    </main>

    <!-- ========== Scrubber bar (always visible when data ready) ========== -->
    <footer v-if="replayData && allActions.length > 0" class="replay-footer">
      <!-- 上排：时间戳 + Jump to live + live 指示灯 -->
      <div class="footer-top">
        <div class="timestamp-chip mono">
          {{ currentAction ? formatFullTime(currentAction.timestamp) : '--' }}
        </div>
        <button class="jump-live-btn" @click="jumpToLive" :disabled="isAtLive">
          ▶ Jump to live
        </button>
        <div class="live-indicator" :class="{ 'is-live': isSimLive }">
          <span class="live-dot"></span>
          {{ isSimLive ? 'live' : 'ended' }}
        </div>
      </div>

      <!-- 进度条 -->
      <div class="scrubber-row">
        <button class="step-btn" @click="stepBack" :disabled="currentActionIndex === 0">⏮</button>
        <button class="play-btn" @click="togglePlay">{{ isPlaying ? '⏸' : '▶' }}</button>
        <button class="step-btn" @click="stepForward" :disabled="currentActionIndex >= allActions.length - 1">⏭</button>
        <div class="scrubber">
          <input
            type="range"
            min="0"
            :max="allActions.length - 1"
            v-model.number="currentActionIndex"
            @input="pause"
          />
        </div>
        <div class="speed-group">
          <button v-for="s in [0.5, 1, 2, 5, 10]" :key="s" class="speed-btn" :class="{ active: speed === s }" @click="speed = s">{{ s }}x</button>
        </div>
      </div>

      <!-- 底部任务栏 -->
      <div class="footer-bottom">
        <span class="task-icon">{{ taskIcon }}</span>
        <span class="task-label">{{ taskLabel }}</span>
        <span class="task-progress mono">step {{ activeStep }}/5</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSimulationReplay } from '../api/simulation'

const route = useRoute()
const router = useRouter()
const simulationId = route.params.simulationId

const loading = ref(true)
const loadError = ref(null)
const replayData = ref(null)
const currentActionIndex = ref(0)
const isPlaying = ref(false)
const speed = ref(1)
const feedListRef = ref(null)
const analystMode = ref(false)
const initializedViewMode = ref(false)

// 自动轮询：如果 sim 还在 running，每 10s 重新拉数据
let pollTimer = null
let playTimer = null

const allActions = computed(() => {
  if (!replayData.value) return []
  const out = []
  let g = 0
  for (const round of replayData.value.rounds) {
    for (const action of round.actions) {
      out.push({ ...action, _gIdx: g, _round: round })
      g++
    }
  }
  return out
})

const currentAction = computed(() => allActions.value[currentActionIndex.value] || null)
const currentRound = computed(() => currentAction.value?._round || null)

const maxRound = computed(() => {
  const step5 = replayData.value?.workflow?.find(step => step.step === 5)
  const executed = Number(step5?.metadata?.total_rounds_executed || 0)
  if (executed > 0) return executed
  const replayRounds = replayData.value?.rounds?.length || 0
  if (replayRounds > 0) return replayRounds
  const tc = replayData.value?.config?.time_config
  if (tc?.total_simulation_hours && tc?.minutes_per_round) {
    return Math.floor((tc.total_simulation_hours * 60) / tc.minutes_per_round)
  }
  return '?'
})

const currentRoundNumber = computed(() => {
  const total = Number(maxRound.value || 0)
  const roundNum = Number(currentRound.value?.round_num ?? currentAction.value?.round_num ?? 0)
  if (!Number.isFinite(roundNum)) return '-'
  return total > 0 ? Math.min(roundNum + 1, total) : roundNum + 1
})

const isSimLive = computed(() => {
  const s = replayData.value?.simulation?.status
  return s === 'running' || s === 'preparing'
})

const isAtLive = computed(() => currentActionIndex.value >= allActions.value.length - 1)

// 当前激活的 step（基于 workflow status）
const activeStep = computed(() => {
  if (!replayData.value) return 0
  const wf = replayData.value.workflow || []
  for (let i = wf.length - 1; i >= 0; i--) {
    if (wf[i].status === 'running') return wf[i].step
  }
  for (let i = wf.length - 1; i >= 0; i--) {
    if (wf[i].status === 'completed') return wf[i].step
  }
  return 1
})

const taskIcon = computed(() => {
  const wf = replayData.value?.workflow || []
  const step = wf.find(w => w.step === activeStep.value)
  if (!step) return '◌'
  if (step.status === 'completed') return '✓'
  if (step.status === 'running') return '▶'
  return '◌'
})

const taskLabel = computed(() => {
  const wf = replayData.value?.workflow || []
  const step = wf.find(w => w.step === activeStep.value)
  return step?.name || '等待中'
})

const maxTypeCount = computed(() => {
  const dist = replayData.value?.aggregate?.action_type_distribution || {}
  return Math.max(1, ...Object.values(dist))
})

function barWidth(count) {
  return Math.round((count / maxTypeCount.value) * 100)
}

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

function agentInitial(name) {
  return name ? name.slice(0, 1).toUpperCase() : '?'
}

function avatarGradient(agentId) {
  const palette = [
    ['#FF5722', '#FF8A65'],
    ['#3F51B5', '#7986CB'],
    ['#4CAF50', '#81C784'],
    ['#E91E63', '#F06292'],
    ['#00BCD4', '#4DD0E1'],
    ['#FFC107', '#FFD54F'],
    ['#9C27B0', '#BA68C8'],
    ['#795548', '#A1887F'],
  ]
  const [a, b] = palette[(agentId || 0) % palette.length]
  return `background: linear-gradient(135deg, ${a}, ${b})`
}

function getAgentUsername(agentId) {
  const a = replayData.value?.agents?.find(x => x.id === agentId)
  return a?.username || `agent_${agentId}`
}

function formatTime(ts) {
  if (!ts) return '--'
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return '--'
  }
}

function formatFullTime(ts) {
  if (!ts) return '--'
  try {
    const d = new Date(ts)
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    })
  } catch {
    return ts
  }
}

function formatActionType(type) {
  const map = {
    CREATE_POST: '✏️ 发帖',
    CREATE_COMMENT: '💬 评论',
    LIKE_POST: '♡ 点赞',
    QUOTE_POST: '🔁 转发',
    DO_NOTHING: '◌ 观望',
  }
  return map[type] || type
}

async function loadReplay(silent = false) {
  if (!silent) {
    loading.value = true
    loadError.value = null
  }
  try {
    const res = await getSimulationReplay(simulationId)
    if (res.success) {
      const prevLen = allActions.value.length
      const wasAtLive = currentActionIndex.value >= prevLen - 1
      replayData.value = res.data
      const newLen = allActions.value.length

      if (!silent && !initializedViewMode.value && res.data?.aggregate?.cached_case) {
        analystMode.value = true
        currentActionIndex.value = 0
        initializedViewMode.value = true
      } else if (!silent || wasAtLive) {
        // 初次加载或之前处于 live 状态时，自动跳到最新
        currentActionIndex.value = Math.max(0, newLen - 1)
      }
      loadError.value = null
    } else if (!silent) {
      loadError.value = res.error || '未知错误'
    }
  } catch (e) {
    if (!silent) loadError.value = e.message || String(e)
  } finally {
    if (!silent) loading.value = false
  }
}

function reload() {
  pause()
  loadReplay(false)
}

function togglePlay() {
  if (isPlaying.value) pause()
  else play()
}

function play() {
  if (currentActionIndex.value >= allActions.value.length - 1) currentActionIndex.value = 0
  isPlaying.value = true
  scheduleNext()
}

function pause() {
  isPlaying.value = false
  if (playTimer) { clearTimeout(playTimer); playTimer = null }
}

function scheduleNext() {
  if (!isPlaying.value) return
  const interval = 1200 / speed.value
  playTimer = setTimeout(() => {
    if (currentActionIndex.value < allActions.value.length - 1) {
      currentActionIndex.value++
      scheduleNext()
    } else {
      pause()
    }
  }, interval)
}

function stepForward() { pause(); if (currentActionIndex.value < allActions.value.length - 1) currentActionIndex.value++ }
function stepBack() { pause(); if (currentActionIndex.value > 0) currentActionIndex.value-- }
function jumpToIndex(idx) { pause(); currentActionIndex.value = idx }
function jumpToLive() { pause(); currentActionIndex.value = Math.max(0, allActions.value.length - 1) }
function toggleAnalyst() { analystMode.value = !analystMode.value }
function goBack() { router.back() }

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(() => {
    // 只在 sim 还在 running 时轮询
    if (isSimLive.value) loadReplay(true)
  }, 10000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

watch(speed, () => {
  if (isPlaying.value) { if (playTimer) clearTimeout(playTimer); scheduleNext() }
})

onMounted(() => {
  if (simulationId === 'sim_nb_hnw_ai_case' && route.query.mode !== 'process') {
    router.replace({ name: 'Interaction', params: { reportId: 'report_nb_hnw_ai_case' } })
    return
  }
  if (simulationId === 'sim_16eb13645a7b') {
    router.replace({ name: 'Interaction', params: { reportId: 'report_tongzhou_course_case' } })
    return
  }

  loadReplay(false).then(() => startPolling())
})

onUnmounted(() => {
  pause()
  stopPolling()
})
</script>

<style scoped>
.replay-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0A0A0B;
  color: #E8E8E8;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  overflow: hidden;
}

.mono { font-family: 'JetBrains Mono', 'Courier New', monospace; }

/* ========== Header ========== */
.replay-header {
  height: 64px;
  background: #111113;
  border-bottom: 1px solid #1F1F23;
  display: flex;
  align-items: center;
  padding: 0 24px;
  flex-shrink: 0;
  gap: 16px;
}
.header-left { display: flex; align-items: center; gap: 16px; flex: 1; min-width: 0; }
.header-right { display: flex; gap: 8px; align-items: center; }

.back-btn {
  background: transparent;
  border: 1px solid #2A2A2E;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  cursor: pointer;
  color: #C0C0C0;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.back-btn:hover { background: #1A1A1E; color: #FFF; }

.title-block { min-width: 0; }
.title-main { font-size: 14px; font-weight: 700; color: #FFF; letter-spacing: 0.3px; }
.title-sub { font-size: 12px; color: #888; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sub-detail { color: #E0E0E0; }
.platform-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0 4px;
}
.platform-tag.twitter { background: #1DA1F2; color: #FFF; }
.platform-tag.reddit { background: #FF4500; color: #FFF; }

.icon-btn {
  background: transparent;
  border: 1px solid #2A2A2E;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  cursor: pointer;
  color: #C0C0C0;
  font-size: 16px;
}
.icon-btn:hover { background: #1A1A1E; color: #FFF; }

/* ========== State screens ========== */
.screen-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
}
.state-text { color: #888; font-size: 14px; }
.state-text.error { color: #F44336; }
.primary-btn {
  background: #FF5722;
  color: #FFF;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

/* ========== Stage Wrap (Cinematic mode) ========== */
.stage-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 48px 20px;
  min-height: 0;
  overflow: auto;
}

.stage {
  width: 100%;
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.platform-frame {
  background: #FFF;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px #1F1F23;
  color: #1A1A1A;
}
.platform-frame.twitter { background: #FFF; }
.platform-frame.reddit { background: #FFF; }

.platform-frame-head {
  background: #2A2A2E;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #1F1F23;
}
.dot { width: 11px; height: 11px; border-radius: 50%; }
.dot.red { background: #FF5F57; }
.dot.yellow { background: #FEBC2E; }
.dot.green { background: #28C840; }
.platform-url {
  flex: 1;
  text-align: center;
  font-size: 11px;
  color: #999;
  background: #1A1A1E;
  padding: 4px 12px;
  border-radius: 4px;
}

.platform-frame-body {
  padding: 24px 28px;
  min-height: 360px;
}

/* ========== Post card ========== */
.post-card { display: flex; flex-direction: column; gap: 14px; }

.reddit-subreddit-bar {
  font-size: 12px;
  color: #878A8C;
  padding-bottom: 8px;
  border-bottom: 1px solid #EDEFF1;
}

.twitter-top-bar { display: flex; gap: 12px; align-items: center; }
.avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  color: #FFF;
  font-weight: 700;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.tw-names { min-width: 0; }
.tw-display { font-size: 15px; font-weight: 700; color: #0F1419; }
.tw-handle { font-size: 12px; color: #536471; }

.action-type-badge {
  align-self: flex-start;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 4px;
  background: #F0F0F0;
  color: #666;
  font-weight: 600;
}
.action-type-badge.create_post { background: #FFE0B2; color: #E65100; }
.action-type-badge.create_comment { background: #C8E6C9; color: #1B5E20; }
.action-type-badge.quote_post { background: #BBDEFB; color: #0D47A1; }
.action-type-badge.like_post { background: #F8BBD0; color: #880E4F; }
.action-type-badge.do_nothing { background: #ECEFF1; color: #546E7A; }

.post-content {
  font-size: 17px;
  line-height: 1.65;
  color: #0F1419;
  padding: 4px 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.post-content.empty { color: #999; font-size: 14px; }

.reddit-actions, .twitter-actions {
  display: flex;
  gap: 24px;
  padding-top: 12px;
  border-top: 1px solid #EDEFF1;
}
.reddit-btn, .tw-btn {
  font-size: 12px;
  color: #878A8C;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: default;
}

.empty-stage {
  height: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #C0C0C0;
}
.empty-icon { font-size: 48px; opacity: 0.3; }
.empty-msg { font-size: 14px; color: #666; }

/* ========== Stage meta ========== */
.stage-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 16px;
  background: #111113;
  border: 1px solid #1F1F23;
  border-radius: 10px;
}
.meta-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.meta-label { font-size: 10px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }
.meta-value { font-size: 16px; font-weight: 700; color: #FFF; font-family: 'JetBrains Mono', monospace; }

/* ========== Analyst mode ========== */
.analyst-body {
  flex: 1;
  display: grid;
  grid-template-columns: 240px 1fr 280px;
  gap: 1px;
  background: #1F1F23;
  overflow: hidden;
}
.col-workflow, .col-stats, .col-feed {
  background: #111113;
  padding: 20px 16px;
  overflow-y: auto;
}
.col-title { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #666; margin: 0 0 16px; }
.workflow-list { display: flex; flex-direction: column; }
.workflow-step { display: flex; gap: 10px; padding: 12px 0; border-bottom: 1px solid #1F1F23; }
.step-marker { width: 24px; height: 24px; border-radius: 50%; background: #1A1A1E; border: 1px solid #2A2A2E; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.workflow-step.is-completed .step-marker { background: rgba(76, 175, 80, 0.2); border-color: #4CAF50; }
.workflow-step.is-running .step-marker { background: rgba(255, 87, 34, 0.2); border-color: #FF5722; }
.step-num { font-size: 10px; font-weight: 700; color: #C0C0C0; }
.step-name { font-size: 12px; font-weight: 600; color: #E8E8E8; }
.step-meta .meta-line { font-size: 10px; color: #888; margin-top: 2px; }

.feed-list { overflow-y: auto; }
.feed-row { display: grid; grid-template-columns: 30px 18px 90px 100px 1fr; gap: 8px; padding: 6px 8px; font-size: 11px; cursor: pointer; border-radius: 3px; align-items: center; }
.feed-row:hover { background: #1A1A1E; }
.feed-row.active { background: rgba(255, 87, 34, 0.15); }
.feed-time { color: #666; }
.feed-platform { width: 16px; height: 16px; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 9px; }
.feed-platform.twitter { background: #1DA1F2; color: #FFF; }
.feed-platform.reddit { background: #FF4500; color: #FFF; }
.feed-agent { color: #E0E0E0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-type { color: #888; font-size: 10px; }
.feed-content { color: #999; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.stat-block { display: flex; flex-direction: column; gap: 8px; padding: 12px; background: #1A1A1E; border-radius: 6px; margin-bottom: 20px; }
.stat-row { display: flex; justify-content: space-between; font-size: 12px; color: #C0C0C0; }
.stat-section { margin-bottom: 20px; }
.section-label-sm { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #666; margin-bottom: 10px; }
.bar-row { display: grid; grid-template-columns: 70px 1fr 28px; gap: 6px; align-items: center; font-size: 10px; padding: 3px 0; }
.bar-label { color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { background: #1A1A1E; height: 5px; border-radius: 3px; overflow: hidden; }
.bar-fill { background: #FF5722; height: 100%; transition: width 0.3s; }
.bar-num { color: #E8E8E8; text-align: right; }
.top-agent-row { display: grid; grid-template-columns: 24px 1fr 28px; gap: 6px; padding: 4px 0; font-size: 11px; }
.top-agent-rank { color: #666; }
.top-agent-name { color: #E8E8E8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-agent-count { text-align: right; color: #FF5722; font-weight: 600; }

/* ========== Footer scrubber ========== */
.replay-footer {
  background: #0E0E10;
  border-top: 1px solid #1F1F23;
  padding: 14px 32px 12px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.footer-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.timestamp-chip {
  font-size: 11px;
  color: #C0C0C0;
  padding: 5px 10px;
  background: #1A1A1E;
  border: 1px solid #2A2A2E;
  border-radius: 6px;
}
.jump-live-btn {
  background: #FF5722;
  color: #FFF;
  border: none;
  padding: 8px 18px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.jump-live-btn:hover:not(:disabled) { background: #FF6E40; }
.jump-live-btn:disabled { background: #2A2A2E; color: #666; cursor: not-allowed; }
.live-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #666;
}
.live-indicator.is-live { color: #4CAF50; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: #666; }
.live-indicator.is-live .live-dot { background: #4CAF50; animation: live-pulse 1.5s infinite; }
@keyframes live-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.6); }
  50% { box-shadow: 0 0 0 5px rgba(76, 175, 80, 0); }
}

.scrubber-row { display: flex; align-items: center; gap: 12px; }
.step-btn, .play-btn {
  background: transparent;
  border: 1px solid #2A2A2E;
  color: #C0C0C0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.step-btn:hover:not(:disabled), .play-btn:hover { background: #1A1A1E; color: #FFF; }
.step-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.play-btn {
  background: #FF5722;
  border-color: #FF5722;
  color: #FFF;
  width: 44px;
  height: 44px;
  font-size: 16px;
}
.play-btn:hover { background: #FF6E40; }

.scrubber { flex: 1; }
.scrubber input[type="range"] {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  height: 28px;
  margin: 0;
}
.scrubber input[type="range"]::-webkit-slider-runnable-track {
  height: 4px;
  background: #2A2A2E;
  border-radius: 2px;
}
.scrubber input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  background: #FF5722;
  border-radius: 50%;
  margin-top: -6px;
  cursor: pointer;
  box-shadow: 0 0 0 2px rgba(255, 87, 34, 0.2);
}
.scrubber input[type="range"]::-moz-range-track {
  height: 4px;
  background: #2A2A2E;
  border-radius: 2px;
}
.scrubber input[type="range"]::-moz-range-thumb {
  width: 16px;
  height: 16px;
  background: #FF5722;
  border-radius: 50%;
  cursor: pointer;
  border: none;
}

.speed-group { display: flex; gap: 4px; }
.speed-btn {
  background: transparent;
  border: 1px solid #2A2A2E;
  color: #888;
  padding: 5px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
}
.speed-btn:hover { background: #1A1A1E; color: #FFF; }
.speed-btn.active { background: #FF5722; color: #FFF; border-color: #FF5722; }

/* ========== Footer bottom ========== */
.footer-bottom {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: #1A1A1E;
  border-radius: 6px;
  font-size: 12px;
}
.task-icon { color: #4CAF50; font-weight: 700; }
.task-label { color: #E8E8E8; flex: 1; }
.task-progress { color: #666; }
.theme-toggle-slot { width: 18px; height: 18px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; }
</style>
