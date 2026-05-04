<template>
  <div class="env-setup-panel">
    <div class="scroll-container">
      <!-- Step 01: 模拟实例 -->
      <div class="step-card" :class="{ 'active': phase === 0, 'completed': phase > 0 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">01</span>
            <span class="step-title">{{ $t('step2.simInstanceInit') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 0" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else class="badge processing">{{ $t('step2.initializing') }}</span>
          </div>
        </div>
        
        <div class="card-content">
          <p class="api-note">POST /api/simulation/create</p>
          <p class="description">
            {{ $t('step2.simInstanceDesc') }}
          </p>

          <div v-if="simulationId" class="info-card">
            <div class="info-row">
              <span class="info-label">Project ID</span>
              <span class="info-value mono">{{ projectData?.project_id }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Graph ID</span>
              <span class="info-value mono">{{ projectData?.graph_id }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Simulation ID</span>
              <span class="info-value mono">{{ simulationId }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Task ID</span>
              <span class="info-value mono">{{ taskId || $t('step2.asyncTaskDone') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 02: 生成 Agent 人设 -->
      <div class="step-card" :class="{ 'active': phase === 1, 'completed': phase > 1 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">02</span>
            <span class="step-title">{{ $t('step2.generateAgentPersona') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 1" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else-if="phase === 1" class="badge processing">{{ prepareProgress }}%</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="api-note">POST /api/simulation/prepare</p>
          <p class="description">
            {{ $t('step2.generateAgentPersonaDesc') }}
          </p>

          <!-- Fase Pre: agent count selector -->
          <div v-if="currentPhase === 'phase_pre'" class="phase-pre-section">
            <div v-if="entityCountLoading" class="phase-pre-loading">
              {{ $t('step2.loadingEntityCount') }}
            </div>
            <div v-else class="phase-pre-form">
              <div class="phase-pre-info">
                <span class="phase-pre-label">{{ $t('step2.availableEntities') }}</span>
                <span class="phase-pre-count">{{ availableEntityCount ?? '—' }}</span>
              </div>
              <div class="phase-pre-input-row">
                <label class="phase-pre-input-label">{{ $t('step2.maxAgentsLabel') }}</label>
                <input
                  v-model.number="maxAgentsInput"
                  type="number"
                  :min="1"
                  :max="availableEntityCount || 9999"
                  class="phase-pre-input"
                  :placeholder="availableEntityCount ?? ''"
                />
                <span v-if="maxAgentsInput !== null && maxAgentsInput < 15" class="phase-pre-warn">
                  {{ $t('step2.minAgentsWarning') }}
                </span>
              </div>
              <div class="phase-pre-footer">
                <button class="continue-btn" @click="confirmPrePhase">
                  {{ $t('step2.startGeneration') }}
                </button>
              </div>
            </div>
          </div>

          <!-- Profiles Stats -->
          <div v-if="profiles.length > 0" class="stats-grid">
            <div class="stat-card">
              <span class="stat-value">{{ profiles.length }}</span>
              <span class="stat-label">{{ $t('step2.currentAgentCount') }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ expectedTotal || '-' }}</span>
              <span class="stat-label">{{ $t('step2.expectedAgentTotal') }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ totalTopicsCount }}</span>
              <span class="stat-label">{{ $t('step2.relatedTopicsCount') }}</span>
            </div>
          </div>

          <!-- Profiles List Preview -->
          <div v-if="profiles.length > 0" class="profiles-preview">
            <div class="preview-header">
              <span class="preview-title">{{ $t('step2.generatedAgentPersonas') }}</span>
            </div>
            <div class="profiles-list">
              <div
                v-for="(profile, idx) in profiles"
                :key="idx"
                class="profile-card"
                :class="{ 'profile-card--clickable': currentPhase === 'phase_a' || currentPhase === 'generating' }"
                @click="(currentPhase === 'phase_a' || currentPhase === 'generating') ? openAgentModal(profile) : selectProfile(profile)"
              >
                <div class="profile-header">
                  <span class="profile-realname">{{ profile.username || 'Unknown' }}</span>
                  <span class="profile-username">@{{ profile.name || `agent_${idx}` }}</span>
                  <span v-if="profile.manually_edited" class="manually-edited-badge">{{ $t('step2.manuallyEditedBadge') }}</span>
                </div>
                <div class="profile-meta">
                  <span class="profile-profession">{{ profile.profession || $t('step2.unknownProfession') }}</span>
                </div>
                <p class="profile-bio">{{ profile.bio || $t('step2.noBio') }}</p>
                <div v-if="profile.interested_topics?.length" class="profile-topics">
                  <span 
                    v-for="topic in profile.interested_topics.slice(0, 3)" 
                    :key="topic" 
                    class="topic-tag"
                  >{{ topic }}</span>
                  <span v-if="profile.interested_topics.length > 3" class="topic-more">
                    +{{ profile.interested_topics.length - 3 }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Fase A: continue button -->
            <div v-if="currentPhase === 'phase_a'" class="phase-a-footer">
              <button
                class="continue-btn"
                :disabled="generateConfigLoading"
                @click="continueToPhaseB"
              >
                <span v-if="generateConfigLoading">{{ $t('step2.generatingConfig') }}</span>
                <span v-else>{{ $t('step2.continueToPhaseB') }}</span>
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- Step 03: 生成双平台模拟配置 -->
      <div class="step-card" :class="{ 'active': phase === 2, 'completed': phase > 2 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">03</span>
            <span class="step-title">{{ $t('step2.dualPlatformConfig') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 2" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else-if="phase === 2" class="badge processing">{{ $t('step2.generating') }}</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="api-note">POST /api/simulation/prepare</p>
          <p class="description">
            {{ $t('step2.dualPlatformConfigDesc') }}
          </p>
          
          <!-- Config Preview + Edit -->
          <div v-if="simulationConfig" class="config-detail-panel">

            <!-- Toolbar: Edit / Save buttons -->
            <div class="config-toolbar">
              <button v-if="!step3EditMode" class="action-btn secondary" @click="step3EditMode = true">
                ✏ {{ $t('common.edit') }}
              </button>
              <template v-else>
                <button class="action-btn secondary" @click="step3EditMode = false">{{ $t('common.cancel') }}</button>
                <button class="continue-btn" :disabled="configSaving" @click="saveFullConfig">
                  <span v-if="configSaving">{{ $t('common.loading') }}</span>
                  <span v-else>{{ $t('common.save') }} ✓</span>
                </button>
              </template>
            </div>

            <!-- Time config -->
            <div class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.simulationDuration') }}</span>
              </div>
              <div class="config-grid" :class="{ editable: step3EditMode }">
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.simulationDuration') }}</span>
                  <input v-if="step3EditMode" class="inline-input" type="number" min="1" max="720"
                    v-model.number="simulationConfig.time_config.total_simulation_hours" />
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.total_simulation_hours }}</span>
                  <span class="config-unit">{{ $t('common.hours') }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.roundDuration') }}</span>
                  <input v-if="step3EditMode" class="inline-input" type="number" min="1" max="1440"
                    v-model.number="simulationConfig.time_config.minutes_per_round" />
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.minutes_per_round }}</span>
                  <span class="config-unit">{{ $t('common.minutes') }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.totalRounds') }}</span>
                  <span class="config-item-value">{{ Math.floor((simulationConfig.time_config?.total_simulation_hours * 60 / simulationConfig.time_config?.minutes_per_round)) || '-' }} {{ $t('common.rounds') }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.activePerHour') }}</span>
                  <template v-if="step3EditMode">
                    <input class="inline-input small" type="number" min="1"
                      v-model.number="simulationConfig.time_config.agents_per_hour_min" />
                    <span class="config-unit">–</span>
                    <input class="inline-input small" type="number" min="1"
                      v-model.number="simulationConfig.time_config.agents_per_hour_max" />
                  </template>
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.agents_per_hour_min }}–{{ simulationConfig.time_config?.agents_per_hour_max }}</span>
                </div>
              </div>
              <div class="time-periods" :class="{ editable: step3EditMode }">
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.peakHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.peak_hours?.join(':00, ') }}:00</span>
                  <span class="period-mult-label">×</span>
                  <input v-if="step3EditMode" class="inline-input small" type="number" min="0.1" max="5" step="0.1"
                    v-model.number="simulationConfig.time_config.peak_activity_multiplier" />
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.peak_activity_multiplier }}</span>
                </div>
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.workHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.work_hours?.[0] }}:00-{{ simulationConfig.time_config?.work_hours?.slice(-1)[0] }}:00</span>
                  <span class="period-mult-label">×</span>
                  <input v-if="step3EditMode" class="inline-input small" type="number" min="0.1" max="5" step="0.1"
                    v-model.number="simulationConfig.time_config.work_activity_multiplier" />
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.work_activity_multiplier }}</span>
                </div>
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.morningHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.morning_hours?.[0] }}:00-{{ simulationConfig.time_config?.morning_hours?.slice(-1)[0] }}:00</span>
                  <span class="period-mult-label">×</span>
                  <input v-if="step3EditMode" class="inline-input small" type="number" min="0.1" max="5" step="0.1"
                    v-model.number="simulationConfig.time_config.morning_activity_multiplier" />
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.morning_activity_multiplier }}</span>
                </div>
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.offPeakHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.off_peak_hours?.[0] }}:00-{{ simulationConfig.time_config?.off_peak_hours?.slice(-1)[0] }}:00</span>
                  <span class="period-mult-label">×</span>
                  <input v-if="step3EditMode" class="inline-input small" type="number" min="0.1" max="5" step="0.1"
                    v-model.number="simulationConfig.time_config.off_peak_activity_multiplier" />
                  <span v-else class="config-item-value">{{ simulationConfig.time_config?.off_peak_activity_multiplier }}</span>
                </div>
              </div>
            </div>

            <!-- Global sim params -->
            <div class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.phaseBTitle') }}</span>
              </div>
              <div class="config-grid" :class="{ editable: step3EditMode }">
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.followingProbability') }}</span>
                  <input v-if="step3EditMode" class="inline-input small" type="number" min="0" max="1" step="0.01"
                    v-model.number="simulationConfig.following_probability" />
                  <span v-else class="config-item-value">{{ simulationConfig.following_probability }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.recsysType') }}</span>
                  <select v-if="step3EditMode" class="inline-input" v-model="simulationConfig.recsys_type">
                    <option value="random">Random</option>
                    <option value="interest">Interest-based</option>
                    <option value="twhin">TWHIN</option>
                  </select>
                  <span v-else class="config-item-value">{{ simulationConfig.recsys_type }}</span>
                </div>
              </div>
            </div>

            <!-- Agent configs -->
            <div class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.agentConfig') }}</span>
                <span class="config-block-badge">{{ simulationConfig.agent_configs?.length || 0 }} {{ $t('common.items') }}</span>
              </div>
              <div class="agents-cards">
                <div
                  v-for="agent in simulationConfig.agent_configs"
                  :key="agent.agent_id"
                  class="agent-card"
                >
                  <div class="agent-card-header">
                    <div class="agent-identity">
                      <span class="agent-id">Agent {{ agent.agent_id }}</span>
                      <span class="agent-name">{{ agent.entity_name }}</span>
                    </div>
                    <div class="agent-tags">
                      <span class="agent-type">{{ agent.entity_type }}</span>
                      <span class="agent-stance" :class="'stance-' + agent.stance">{{ agent.stance }}</span>
                    </div>
                  </div>

                  <!-- Active hours timeline (clickable only in edit mode) -->
                  <div class="agent-timeline">
                    <span class="timeline-label">{{ $t('step2.activeTimePeriod') }}</span>
                    <div class="mini-timeline">
                      <div
                        v-for="hour in 24"
                        :key="hour - 1"
                        class="timeline-hour"
                        :class="{ 'active': agent.active_hours?.includes(hour - 1), 'clickable': step3EditMode }"
                        :title="`${hour - 1}:00`"
                        @click="step3EditMode && toggleAgentHour(agent, hour - 1)"
                      ></div>
                    </div>
                    <div class="timeline-marks">
                      <span>0</span><span>6</span><span>12</span><span>18</span><span>24</span>
                    </div>
                  </div>

                  <!-- Behaviour params (editable or read-only) -->
                  <div class="agent-params">
                    <div class="param-group">
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.postsPerHour') }}</span>
                        <input v-if="step3EditMode" class="inline-input small" type="number" min="0" step="0.1"
                          v-model.number="agent.posts_per_hour" />
                        <span v-else class="config-item-value">{{ agent.posts_per_hour }}</span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.commentsPerHour') }}</span>
                        <input v-if="step3EditMode" class="inline-input small" type="number" min="0" step="0.1"
                          v-model.number="agent.comments_per_hour" />
                        <span v-else class="config-item-value">{{ agent.comments_per_hour }}</span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.responseDelay') }}</span>
                        <template v-if="step3EditMode">
                          <input class="inline-input small" type="number" min="0"
                            v-model.number="agent.response_delay_min" />
                          <span class="config-unit">–</span>
                          <input class="inline-input small" type="number" min="0"
                            v-model.number="agent.response_delay_max" />
                          <span class="config-unit">min</span>
                        </template>
                        <span v-else class="config-item-value">{{ agent.response_delay_min }}–{{ agent.response_delay_max }} min</span>
                      </div>
                    </div>
                    <div class="param-group">
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.activityLevel') }}</span>
                        <input v-if="step3EditMode" class="inline-input small" type="number" min="0" max="1" step="0.01"
                          v-model.number="agent.activity_level" />
                        <span v-else class="config-item-value">{{ agent.activity_level }}</span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.sentimentBias') }}</span>
                        <input v-if="step3EditMode" class="inline-input small" type="number" min="-1" max="1" step="0.1"
                          v-model.number="agent.sentiment_bias" />
                        <span v-else class="config-item-value">{{ agent.sentiment_bias }}</span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.influenceWeight') }}</span>
                        <input v-if="step3EditMode" class="inline-input small" type="number" min="0" step="0.1"
                          v-model.number="agent.influence_weight" />
                        <span v-else class="config-item-value">{{ agent.influence_weight }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Platform configs -->
            <div class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.recommendAlgoConfig') }}</span>
              </div>
              <div class="platforms-grid">
                <div v-if="simulationConfig.twitter_config" class="platform-card">
                  <div class="platform-card-header">
                    <span class="platform-name">{{ $t('step2.platform1Name') }}</span>
                  </div>
                  <div class="platform-params">
                    <div class="param-row" v-for="key in ['recency_weight','popularity_weight','relevance_weight','viral_threshold','echo_chamber_strength']" :key="key">
                      <span class="param-label">{{ $t('step2.' + key.replace(/_([a-z])/g, (_, c) => c.toUpperCase())) }}</span>
                      <input v-if="step3EditMode" class="inline-input small" type="number" min="0" max="1" step="0.01"
                        v-model.number="simulationConfig.twitter_config[key]" />
                      <span v-else class="config-item-value">{{ simulationConfig.twitter_config[key] }}</span>
                    </div>
                  </div>
                </div>
                <div v-if="simulationConfig.reddit_config" class="platform-card">
                  <div class="platform-card-header">
                    <span class="platform-name">{{ $t('step2.platform2Name') }}</span>
                  </div>
                  <div class="platform-params">
                    <div class="param-row" v-for="key in ['recency_weight','popularity_weight','relevance_weight','viral_threshold','echo_chamber_strength']" :key="key">
                      <span class="param-label">{{ $t('step2.' + key.replace(/_([a-z])/g, (_, c) => c.toUpperCase())) }}</span>
                      <input v-if="step3EditMode" class="inline-input small" type="number" min="0" max="1" step="0.01"
                        v-model.number="simulationConfig.reddit_config[key]" />
                      <span v-else class="config-item-value">{{ simulationConfig.reddit_config[key] }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- LLM reasoning -->
            <div v-if="simulationConfig.generation_reasoning" class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.llmConfigReasoning') }}</span>
              </div>
              <div class="reasoning-content">
                <div
                  v-for="(reason, idx) in simulationConfig.generation_reasoning.split('|').slice(0, 2)"
                  :key="idx"
                  class="reasoning-item"
                >
                  <p class="reasoning-text">{{ reason.trim() }}</p>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>

      <!-- Step 04: 初始激活编排 -->
      <div class="step-card" :class="{ 'active': phase === 3, 'completed': phase > 3 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">04</span>
            <span class="step-title">{{ $t('step2.initialActivation') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 3" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else-if="phase === 3" class="badge processing">{{ $t('step2.orchestrating') }}</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="api-note">POST /api/simulation/prepare</p>
          <p class="description">
            {{ $t('step2.initialActivationDesc') }}
          </p>

          <div v-if="simulationConfig?.event_config" class="orchestration-content">
            <!-- 叙事方向 -->
            <div class="narrative-box">
              <span class="box-label narrative-label">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="special-icon">
                  <path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22Z" stroke="url(#paint0_linear)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M16.24 7.76L14.12 14.12L7.76 16.24L9.88 9.88L16.24 7.76Z" fill="url(#paint0_linear)" stroke="url(#paint0_linear)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  <defs>
                    <linearGradient id="paint0_linear" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                      <stop stop-color="#FF5722"/>
                      <stop offset="1" stop-color="#FF9800"/>
                    </linearGradient>
                  </defs>
                </svg>
                {{ $t('step2.narrativeDirection') }}
              </span>
              <p class="narrative-text">{{ simulationConfig.event_config.narrative_direction }}</p>
            </div>

            <!-- 热点话题 -->
            <div class="topics-section">
              <span class="box-label">{{ $t('step2.initialHotTopics') }}</span>
              <div class="hot-topics-grid">
                <span v-for="topic in simulationConfig.event_config.hot_topics" :key="topic" class="hot-topic-tag">
                  # {{ topic }}
                </span>
              </div>
            </div>

            <!-- 初始帖子流 -->
            <div class="initial-posts-section">
              <span class="box-label">{{ $t('step2.initialActivationSeq', { count: simulationConfig.event_config.initial_posts.length }) }}</span>
              <div class="posts-timeline">
                <div v-for="(post, idx) in simulationConfig.event_config.initial_posts" :key="idx" class="timeline-item">
                  <div class="timeline-marker"></div>
                  <div class="timeline-content">
                    <div class="post-header">
                      <span class="post-role">{{ post.poster_type }}</span>
                      <span class="post-agent-info">
                        <span class="post-id">Agent {{ post.poster_agent_id }}</span>
                        <span class="post-username">@{{ getAgentUsername(post.poster_agent_id) }}</span>
                      </span>
                    </div>
                    <p class="post-text">{{ post.content }}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 05: 准备完成 -->
      <div class="step-card" :class="{ 'active': phase >= 3 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">05</span>
            <span class="step-title">{{ $t('step2.setupComplete') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase >= 3" class="badge processing">{{ $t('step1.inProgress') }}</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="api-note">POST /api/simulation/start</p>
          <p class="description">{{ $t('step2.setupCompleteDesc') }}</p>
          
          <!-- 模拟轮数配置 - 只有在配置生成完成且轮数计算出来后才显示 -->
          <div v-if="simulationConfig && autoGeneratedRounds" class="rounds-config-section">
            <div class="rounds-header">
              <div class="header-left">
                <span class="section-title">{{ $t('step2.roundsConfig') }}</span>
                <span class="section-desc">{{ $t('step2.roundsConfigDesc', { hours: simulationConfig?.time_config?.total_simulation_hours || '-', minutesPerRound: simulationConfig?.time_config?.minutes_per_round || '-' }) }}</span>
              </div>
              <label class="switch-control">
                <input type="checkbox" v-model="useCustomRounds">
                <span class="switch-track"></span>
                <span class="switch-label">{{ $t('step2.customToggle') }}</span>
              </label>
            </div>
            
            <Transition name="fade" mode="out-in">
              <div v-if="useCustomRounds" class="rounds-content custom" key="custom">
                <div class="slider-display">
                  <div class="slider-main-value">
                    <span class="val-num">{{ customMaxRounds }}</span>
                    <span class="val-unit">{{ $t('step2.roundsUnit') }}</span>
                  </div>
                  <div class="slider-meta-info">
                    <span>{{ $t('step2.estimatedDuration', { minutes: Math.round(customMaxRounds * 0.6) }) }}</span>
                  </div>
                </div>

                <div class="range-wrapper">
                  <input 
                    type="range" 
                    v-model.number="customMaxRounds" 
                    min="10" 
                    :max="autoGeneratedRounds"
                    step="5"
                    class="minimal-slider"
                    :style="{ '--percent': ((customMaxRounds - 10) / (autoGeneratedRounds - 10)) * 100 + '%' }"
                  />
                  <div class="range-marks">
                    <span>10</span>
                    <span 
                      class="mark-recommend" 
                      :class="{ active: customMaxRounds === 40 }"
                      @click="customMaxRounds = 40"
                      :style="{ position: 'absolute', left: `calc(${(40 - 10) / (autoGeneratedRounds - 10) * 100}% - 30px)` }"
                    >{{ $t('step2.recommendedRounds', { rounds: 40 }) }}</span>
                    <span>{{ autoGeneratedRounds }}</span>
                  </div>
                </div>
              </div>
              
              <div v-else class="rounds-content auto" key="auto">
                <div class="auto-info-card">
                  <div class="auto-value">
                    <span class="val-num">{{ autoGeneratedRounds }}</span>
                    <span class="val-unit">{{ $t('step2.roundsUnit') }}</span>
                  </div>
                  <div class="auto-content">
                    <div class="auto-meta-row">
                      <span class="duration-badge">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <circle cx="12" cy="12" r="10"></circle>
                          <polyline points="12 6 12 12 16 14"></polyline>
                        </svg>
                        {{ $t('step2.estimatedDurationFull', { minutes: Math.round(autoGeneratedRounds * 0.6) }) }}
                      </span>
                    </div>
                    <div class="auto-desc">
                      <p class="highlight-tip" @click="useCustomRounds = true">{{ $t('step2.customTip') }} ➝</p>
                    </div>
                  </div>
                </div>
              </div>
            </Transition>
          </div>

          <div class="action-group dual">
            <button 
              class="action-btn secondary"
              @click="$emit('go-back')"
            >
              ← {{ $t('step2.backToGraphBuild') }}
            </button>
            <button 
              class="action-btn primary"
              :disabled="phase < 3"
              @click="handleStartSimulation"
            >
              {{ $t('step2.startDualWorldSim') }} ➝
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Agent edit/regen modal -->
    <div v-if="agentModalOpen" class="agent-modal-overlay" @click.self="closeAgentModal">
      <div class="agent-modal">
        <div class="modal-header">
          <span class="modal-title">{{ selectedAgent?.name || selectedAgent?.username }}</span>
          <span v-if="selectedAgent?.manually_edited" class="edited-badge">{{ $t('step2.manuallyEditedBadge') }}</span>
          <button class="modal-close" @click="closeAgentModal">✕</button>
        </div>

        <div v-if="agentModalMode === 'edit'" class="modal-body">
          <div class="field-group" v-for="field in ['name', 'bio', 'persona', 'age', 'gender', 'mbti', 'country', 'profession', 'stance']" :key="field">
            <label>{{ $t('step2.agentField_' + field) }}</label>
            <textarea v-if="['bio', 'persona'].includes(field)" v-model="editForm[field]" rows="3" />
            <input v-else v-model="editForm[field]" />
          </div>
          <div class="modal-actions">
            <button class="btn-secondary" @click="closeAgentModal">{{ $t('common.cancel') }}</button>
            <button class="btn-primary" :disabled="editLoading" @click="saveAgent">{{ $t('common.save') }}</button>
          </div>
        </div>

        <div v-else-if="agentModalMode === 'regen'" class="modal-body">
          <p>{{ $t('step2.regenerateAgentHint') }}</p>
          <textarea v-model="regenInstructions" rows="3" :placeholder="$t('step2.extraInstructions')" />
          <div class="modal-actions">
            <button class="btn-secondary" @click="closeAgentModal">{{ $t('common.cancel') }}</button>
            <button class="btn-primary" :disabled="regenLoading" @click="doRegenerate">{{ $t('step2.regenerateAgent') }}</button>
          </div>
        </div>

        <div v-else class="modal-body modal-view">
          <p><strong>Bio:</strong> {{ selectedAgent?.bio }}</p>
          <p><strong>Persona:</strong> {{ selectedAgent?.persona }}</p>
          <div class="modal-actions">
            <button class="btn-secondary" @click="agentModalMode = 'regen'">{{ $t('step2.regenerateAgent') }}</button>
            <button class="btn-danger" @click="confirmDeleteAgent(selectedAgent)">{{ $t('step2.deleteAgent') }}</button>
            <button class="btn-primary" @click="agentModalMode = 'edit'">{{ $t('step2.editAgent') }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Profile Detail Modal -->
    <Transition name="modal">
      <div v-if="selectedProfile" class="profile-modal-overlay" @click.self="selectedProfile = null">
        <div class="profile-modal">
          <div class="modal-header">
          <div class="modal-header-info">
            <div class="modal-name-row">
              <span class="modal-realname">{{ selectedProfile.username }}</span>
              <span class="modal-username">@{{ selectedProfile.name }}</span>
            </div>
            <span class="modal-profession">{{ selectedProfile.profession }}</span>
          </div>
          <button class="close-btn" @click="selectedProfile = null">×</button>
        </div>
        
        <div class="modal-body">
          <!-- 基本信息 -->
          <div class="modal-info-grid">
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalAge') }}</span>
              <span class="info-value">{{ selectedProfile.age || '-' }} {{ $t('step2.yearsOld') }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalGender') }}</span>
              <span class="info-value">{{ { male: $t('step2.genderMale'), female: $t('step2.genderFemale'), other: $t('step2.genderOther') }[selectedProfile.gender] || selectedProfile.gender }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalCountry') }}</span>
              <span class="info-value">{{ selectedProfile.country || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalMbti') }}</span>
              <span class="info-value mbti">{{ selectedProfile.mbti || '-' }}</span>
            </div>
          </div>

          <!-- 简介 -->
          <div class="modal-section">
            <span class="section-label">{{ $t('step2.profileModalBio') }}</span>
            <p class="section-bio">{{ selectedProfile.bio || $t('step2.noBio') }}</p>
          </div>

          <!-- 关注话题 -->
          <div class="modal-section" v-if="selectedProfile.interested_topics?.length">
            <span class="section-label">{{ $t('step2.profileModalTopics') }}</span>
            <div class="topics-grid">
              <span 
                v-for="topic in selectedProfile.interested_topics" 
                :key="topic" 
                class="topic-item"
              >{{ topic }}</span>
            </div>
          </div>

          <!-- 详细人设 -->
          <div class="modal-section" v-if="selectedProfile.persona">
            <span class="section-label">{{ $t('step2.profileModalPersona') }}</span>
            
            <!-- 人设维度概览 -->
            <div class="persona-dimensions">
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimExperience') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimExperienceDesc') }}</span>
              </div>
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimBehavior') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimBehaviorDesc') }}</span>
              </div>
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimMemory') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimMemoryDesc') }}</span>
              </div>
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimSocial') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimSocialDesc') }}</span>
              </div>
            </div>

            <div class="persona-content">
              <p class="section-persona">{{ selectedProfile.persona }}</p>
            </div>
          </div>
        </div>
      </div>
      </div>
    </Transition>

    <!-- Bottom Info / Logs -->
    <div class="system-logs">
      <div class="log-header">
        <span class="log-title">SYSTEM DASHBOARD</span>
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
import { useI18n } from 'vue-i18n'
import {
  prepareSimulation,
  getGraphEntityCount,
  getSimulation,
  getPrepareStatus,
  getTaskStatus,
  getSimulationProfilesRealtime,
  getSimulationConfig,
  getSimulationConfigRealtime,
  patchAgent,
  deleteAgent,
  regenerateAgent,
  generateConfig,
  patchSimulationConfig
} from '../api/simulation'

const { t } = useI18n()

const props = defineProps({
  simulationId: String,  // 从父组件传入
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

// State
const phase = ref(0) // 0: 初始化, 1: 生成人设, 2: 生成配置, 3: 完成
const taskId = ref(null)
const prepareProgress = ref(0)
const currentStage = ref('')
const progressMessage = ref('')
const profiles = ref([])
const entityTypes = ref([])
const expectedTotal = ref(null)
const simulationConfig = ref(null)
const selectedProfile = ref(null)
const showProfilesDetail = ref(true)

// 日志去重：记录上一次输出的关键信息
let lastLoggedMessage = ''
let lastLoggedProfileCount = 0
let lastLoggedConfigStage = ''

// 模拟轮数配置
const useCustomRounds = ref(false) // 默认使用自动配置轮数
const customMaxRounds = ref(40)   // 默认推荐40轮

// Fase pre (agent count selector)
const availableEntityCount = ref(null) // total entities available in the graph
const maxAgentsInput = ref(null)       // user-selected max agents (null = all)
const entityCountLoading = ref(false)

// Fase A/B state
const currentPhase = ref('phase_pre') // 'phase_pre' | 'generating' | 'phase_a' | 'phase_b'
const agentModalOpen = ref(false)
const agentModalMode = ref('view')    // 'view' | 'edit' | 'regen'
const selectedAgent = ref(null)
const editForm = ref({})
const regenInstructions = ref('')
const regenLoading = ref(false)
const editLoading = ref(false)
const deleteConfirmAgent = ref(null)
const generateConfigLoading = ref(false)
const generateConfigTaskId = ref(null)

// Step 03 inline editing state
const step3EditMode = ref(false)
const configSaving = ref(false)

// Watch stage to update phase.
// In the F2A/B flow, config is generated in a separate step (generate-config endpoint),
// so startConfigPolling must NOT be triggered here — only in loadPreparedData / continueToPhaseB.
watch(currentStage, (newStage) => {
  if (newStage === '生成Agent人设' || newStage === 'generating_profiles') {
    phase.value = 1
  } else if (newStage === '生成模拟配置' || newStage === 'generating_config') {
    // Only activate step-03 and config polling when we are past phase_a (i.e. config was
    // explicitly triggered via continueToPhaseB, not during profile generation).
    if (currentPhase.value === 'phase_b' || currentPhase.value === 'generating' && phase.value >= 2) {
      phase.value = 2
      if (!configTimer) {
        addLog(t('log.startGeneratingConfig'))
        startConfigPolling()
      }
    }
  } else if (newStage === '准备模拟脚本' || newStage === 'copying_scripts') {
    phase.value = 2
  }
})

// 从配置中计算自动生成的轮数（不使用硬编码默认值）
const autoGeneratedRounds = computed(() => {
  if (!simulationConfig.value?.time_config) {
    return null // 配置未生成时返回 null
  }
  const totalHours = simulationConfig.value.time_config.total_simulation_hours
  const minutesPerRound = simulationConfig.value.time_config.minutes_per_round
  if (!totalHours || !minutesPerRound) {
    return null // 配置数据不完整时返回 null
  }
  const calculatedRounds = Math.floor((totalHours * 60) / minutesPerRound)
  // 确保最大轮数不小于40（推荐值），避免滑动条范围异常
  return Math.max(calculatedRounds, 40)
})

// Polling timer
let pollTimer = null
let profilesTimer = null
let configTimer = null

// Computed
const displayProfiles = computed(() => {
  if (showProfilesDetail.value) {
    return profiles.value
  }
  return profiles.value.slice(0, 6)
})

// 根据agent_id获取对应的username
const getAgentUsername = (agentId) => {
  if (profiles.value && profiles.value.length > agentId && agentId >= 0) {
    const profile = profiles.value[agentId]
    return profile?.username || `agent_${agentId}`
  }
  return `agent_${agentId}`
}

// 计算所有人设的关联话题总数
const totalTopicsCount = computed(() => {
  return profiles.value.reduce((sum, p) => {
    return sum + (p.interested_topics?.length || 0)
  }, 0)
})

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

// Step 05 launch button — emits next-step
const handleStartSimulation = async () => {
  phase.value = 4
  const params = {}
  if (useCustomRounds.value) {
    params.maxRounds = customMaxRounds.value
    addLog(t('log.startSimCustomRounds', { rounds: customMaxRounds.value }))
  } else {
    addLog(t('log.startSimAutoRounds', { rounds: autoGeneratedRounds.value }))
  }
  emit('next-step', params)
}

const truncateBio = (bio) => {
  if (bio.length > 80) {
    return bio.substring(0, 80) + '...'
  }
  return bio
}

const selectProfile = (profile) => {
  selectedProfile.value = profile
}

// Kick off preparation after the user confirms the pre-phase selector
const confirmPrePhase = () => {
  currentPhase.value = 'generating'
  startPrepareSimulation()
}

// 自动开始准备模拟
const startPrepareSimulation = async () => {
  if (!props.simulationId) {
    addLog(t('log.errorMissingSimId'))
    emit('update-status', 'error')
    return
  }

  // Ensure generating phase is active regardless of how this was invoked
  if (currentPhase.value === 'phase_pre') {
    currentPhase.value = 'generating'
  }

  // 标记第一步完成，开始第二步
  phase.value = 1
  addLog(t('log.simInstanceCreated', { id: props.simulationId }))
  addLog(t('log.preparingSimEnv'))
  emit('update-status', 'processing')

  try {
    const preparePayload = {
      simulation_id: props.simulationId,
      use_llm_for_profiles: true,
      parallel_profile_count: 5
    }
    if (maxAgentsInput.value && maxAgentsInput.value < (availableEntityCount.value ?? Infinity)) {
      preparePayload.max_agents = maxAgentsInput.value
    }
    const res = await prepareSimulation(preparePayload)
    
    if (res.success && res.data) {
      if (res.data.already_prepared) {
        addLog(t('log.detectedExistingPrep'))
        if (res.data.status === 'profiles_ready') {
          await fetchProfilesRealtime()
          addLog(t('log.loadedAgentProfiles', { count: profiles.value.length }))
          currentPhase.value = 'phase_a'
          emit('update-status', 'profiles_ready')
        } else {
          await loadPreparedData()
        }
        return
      }
      
      taskId.value = res.data.task_id
      addLog(t('log.prepareTaskStarted'))
      addLog(t('log.prepareTaskId', { taskId: res.data.task_id }))
      
      // 立即设置预期Agent总数（从prepare接口返回值获取）
      if (res.data.expected_entities_count) {
        expectedTotal.value = res.data.expected_entities_count
        addLog(t('log.zepEntitiesFound', { count: res.data.expected_entities_count }))
        if (res.data.entity_types && res.data.entity_types.length > 0) {
          addLog(t('log.entityTypes', { types: res.data.entity_types.join(', ') }))
        }
      }
      
      addLog(t('log.startPollingProgress'))
      // 开始轮询进度
      startPolling()
      // 开始实时获取 Profiles
      startProfilesPolling()
    } else {
      addLog(t('log.prepareFailed', { error: res.error || t('common.unknownError') }))
      emit('update-status', 'error')
    }
  } catch (err) {
    addLog(t('log.prepareException', { error: err.message }))
    emit('update-status', 'error')
  }
}

const startPolling = () => {
  pollTimer = setInterval(pollPrepareStatus, 2000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const startProfilesPolling = () => {
  profilesTimer = setInterval(fetchProfilesRealtime, 3000)
}

const stopProfilesPolling = () => {
  if (profilesTimer) {
    clearInterval(profilesTimer)
    profilesTimer = null
  }
}

const pollPrepareStatus = async () => {
  if (!taskId.value && !props.simulationId) return
  
  try {
    const res = await getPrepareStatus({
      task_id: taskId.value,
      simulation_id: props.simulationId
    })
    
    if (res.success && res.data) {
      const data = res.data
      
      // 更新进度
      prepareProgress.value = data.progress || 0
      progressMessage.value = data.message || ''
      
      // 解析阶段信息并输出详细日志
      if (data.progress_detail) {
        currentStage.value = data.progress_detail.current_stage_name || ''
        
        // 输出详细进度日志（避免重复）
        const detail = data.progress_detail
        const logKey = `${detail.current_stage}-${detail.current_item}-${detail.total_items}`
        if (logKey !== lastLoggedMessage && detail.item_description) {
          lastLoggedMessage = logKey
          const stageInfo = `[${detail.stage_index}/${detail.total_stages}]`
          if (detail.total_items > 0) {
            addLog(`${stageInfo} ${detail.current_stage_name}: ${detail.current_item}/${detail.total_items} - ${detail.item_description}`)
          } else {
            addLog(`${stageInfo} ${detail.current_stage_name}: ${detail.item_description}`)
          }
        }
      } else if (data.message) {
        // 从消息中提取阶段
        const match = data.message.match(/\[(\d+)\/(\d+)\]\s*([^:]+)/)
        if (match) {
          currentStage.value = match[3].trim()
        }
        // 输出消息日志（避免重复）
        if (data.message !== lastLoggedMessage) {
          lastLoggedMessage = data.message
          addLog(data.message)
        }
      }
      
      // Check completion using simulation_status (set by backend alongside task status).
      // data.status is the task status (processing/completed/failed).
      // data.simulation_status is the actual simulation FSM state.
      const simStatus = data.simulation_status
      const taskStatus = data.status

      if (simStatus === 'profiles_ready') {
        addLog(t('log.prepareComplete'))
        stopPolling()
        stopProfilesPolling()
        await fetchProfilesRealtime()
        addLog(t('log.loadedAgentProfiles', { count: profiles.value.length }))
        currentPhase.value = 'phase_a'
        emit('update-status', 'profiles_ready')
      } else if (simStatus === 'ready' || (data.already_prepared && simStatus && simStatus !== 'profiles_ready')) {
        addLog(t('log.prepareComplete'))
        stopPolling()
        stopProfilesPolling()
        await loadPreparedData()
      } else if (taskStatus === 'failed') {
        addLog(t('log.prepareFailedWithError', { error: data.error || t('common.unknownError') }))
        stopPolling()
        stopProfilesPolling()
      }
    }
  } catch (err) {
    console.warn('轮询状态失败:', err)
  }
}

const fetchProfilesRealtime = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getSimulationProfilesRealtime(props.simulationId, 'reddit')
    
    if (res.success && res.data) {
      const prevCount = profiles.value.length
      profiles.value = res.data.profiles || []
      // 只有当 API 返回有效值时才更新，避免覆盖已有的有效值
      if (res.data.total_expected) {
        expectedTotal.value = res.data.total_expected
      }
      
      // 提取实体类型
      const types = new Set()
      profiles.value.forEach(p => {
        if (p.entity_type) types.add(p.entity_type)
      })
      entityTypes.value = Array.from(types)
      
      // 输出 Profile 生成进度日志（仅当数量变化时）
      const currentCount = profiles.value.length
      if (currentCount > 0 && currentCount !== lastLoggedProfileCount) {
        lastLoggedProfileCount = currentCount
        const total = expectedTotal.value || '?'
        const latestProfile = profiles.value[currentCount - 1]
        const profileName = latestProfile?.name || latestProfile?.username || `Agent_${currentCount}`
        if (currentCount === 1) {
          addLog(t('log.startGeneratingAgentProfiles'))
        }
        addLog(t('log.agentProfile', { current: currentCount, total: total, name: profileName, profession: latestProfile?.profession || t('step2.unknownProfession') }))

        // 如果全部生成完成
        if (expectedTotal.value && currentCount >= expectedTotal.value) {
          addLog(t('log.allProfilesComplete', { count: currentCount }))
        }
      }
    }
  } catch (err) {
    console.warn('获取 Profiles 失败:', err)
  }
}

// 配置轮询
const startConfigPolling = () => {
  configTimer = setInterval(fetchConfigRealtime, 2000)
}

const stopConfigPolling = () => {
  if (configTimer) {
    clearInterval(configTimer)
    configTimer = null
  }
}

const fetchConfigRealtime = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getSimulationConfigRealtime(props.simulationId)
    
    if (res.success && res.data) {
      const data = res.data
      
      // 输出配置生成阶段日志（避免重复）
      if (data.generation_stage && data.generation_stage !== lastLoggedConfigStage) {
        lastLoggedConfigStage = data.generation_stage
        if (data.generation_stage === 'generating_profiles') {
          addLog(t('log.generatingAgentProfileConfig'))
        } else if (data.generation_stage === 'generating_config') {
          addLog(t('log.generatingLLMConfig'))
        }
      }
      
      // Si la config ja és generada, actualitzem simulationConfig però NO saltem a phase=4.
      // La transició phase_b → phase=4 la gestiona exclusivament launchSimulation/loadPreparedData,
      // per garantir que l'usuari vegi el formulari de Fase B (step 03-05) abans de llançar.
      if (data.config_generated && data.config) {
        simulationConfig.value = data.config
        stopConfigPolling()
      }
    }
  } catch (err) {
    console.warn('获取 Config 失败:', err)
  }
}

const loadPreparedData = async () => {
  phase.value = 2
  addLog(t('log.loadingExistingConfig'))

  // 最后获取一次 Profiles
  await fetchProfilesRealtime()
  addLog(t('log.loadedAgentProfiles', { count: profiles.value.length }))

  // 获取配置（使用实时接口）
  try {
    const res = await getSimulationConfigRealtime(props.simulationId)
    if (res.success && res.data) {
      if (res.data.config_generated && res.data.config) {
        simulationConfig.value = res.data.config
        addLog(t('log.configLoadSuccess'))
        addLog(t('log.envSetupComplete'))
        phase.value = 3
        currentPhase.value = 'phase_b'
        emit('update-status', 'completed')
      } else {
        // 配置尚未生成，开始轮询
        addLog(t('log.configGenerating'))
        startConfigPolling()
      }
    }
  } catch (err) {
    addLog(t('log.loadConfigFailed', { error: err.message }))
    emit('update-status', 'error')
  }
}

// ---- Fase A/B helpers ----

// Generic task poller: polls simulation status directly until status reaches targetStatuses.
// Used for generate-config (which moves sim through configuring → ready).
const pollSimStatusUntil = async (targetStatuses, onComplete, intervalMs = 2000, maxWaitMs = 300000) => {
  const deadline = Date.now() + maxWaitMs
  return new Promise((resolve) => {
    const interval = setInterval(async () => {
      try {
        if (Date.now() > deadline) { clearInterval(interval); resolve(); return }
        const res = await getSimulation(props.simulationId)
        const simStatus = res?.data?.status
        if (targetStatuses.includes(simStatus)) {
          clearInterval(interval)
          onComplete && onComplete()
          resolve()
        } else if (simStatus === 'failed') {
          clearInterval(interval)
          resolve()
        }
      } catch {
        clearInterval(interval)
        resolve()
      }
    }, intervalMs)
  })
}

const pollTaskUntilDone = async (taskId, onComplete, intervalMs = 2000) => {
  if (!taskId) { onComplete && onComplete(); return }
  return new Promise((resolve) => {
    const interval = setInterval(async () => {
      try {
        const res = await getTaskStatus(taskId)
        const d = res.data || {}
        const taskStatus = d.status
        if (taskStatus === 'completed') {
          clearInterval(interval)
          onComplete && onComplete(d.result)
          resolve()
        } else if (taskStatus === 'failed') {
          clearInterval(interval)
          resolve()
        }
      } catch {
        clearInterval(interval)
        resolve()
      }
    }, intervalMs)
  })
}

const openAgentModal = (agent, mode = 'view') => {
  selectedAgent.value = agent
  agentModalMode.value = mode
  editForm.value = { ...agent }
  regenInstructions.value = ''
  agentModalOpen.value = true
}

const closeAgentModal = () => {
  agentModalOpen.value = false
  selectedAgent.value = null
}

const saveAgent = async () => {
  if (!selectedAgent.value || !props.simulationId) return
  editLoading.value = true
  try {
    const res = await patchAgent(props.simulationId, selectedAgent.value.user_id, editForm.value)
    // axios interceptor: res = { success, data: updatedProfile }
    if (res.success) {
      const idx = profiles.value.findIndex(p => p.user_id === selectedAgent.value.user_id)
      if (idx !== -1) profiles.value[idx] = res.data
      closeAgentModal()
    }
  } finally {
    editLoading.value = false
  }
}

const confirmDeleteAgent = async (agent) => {
  if (!confirm(t('step2.deleteAgentConfirm'))) return
  try {
    const res = await deleteAgent(props.simulationId, agent.user_id)
    if (res.success) {
      profiles.value = profiles.value.filter(p => p.user_id !== agent.user_id)
      closeAgentModal()
    }
  } catch (err) {
    addLog(`Delete failed: ${err.message}`)
  }
}

const doRegenerate = async () => {
  if (!selectedAgent.value) return
  regenLoading.value = true
  try {
    const res = await regenerateAgent(props.simulationId, selectedAgent.value.user_id, {
      extra_instructions: regenInstructions.value
    })
    // res = { success, data: { task_id } }
    if (res.success) {
      await pollTaskUntilDone(res.data?.task_id, () => {})
      await fetchProfilesRealtime()
      closeAgentModal()
    }
  } finally {
    regenLoading.value = false
  }
}

const continueToPhaseB = async () => {
  generateConfigLoading.value = true
  phase.value = 2  // activar step 03 mentre es genera la config
  addLog(t('log.startGeneratingConfig'))
  startConfigPolling()
  try {
    const res = await generateConfig(props.simulationId)
    if (res.success) {
      // Poll sim status directly (configuring → ready) to avoid conflicts with prepare/status endpoint
      await pollSimStatusUntil(['ready'], async () => {
        stopConfigPolling()
        const configRes = await getSimulationConfig(props.simulationId)
        if (configRes.success) {
          simulationConfig.value = configRes.data
        }
        // phase_b mostra el formulari de paràmetres globals dins step 02,
        // step 03 ja és visible (phase=2) amb la config generada,
        // step 05 s'activa quan l'usuari prem "Llança"
        phase.value = 3
        currentPhase.value = 'phase_b'
        addLog(t('log.configComplete'))
        addLog(t('log.envSetupComplete'))
        emit('update-status', 'completed')
      })
    } else {
      stopConfigPolling()
      phase.value = 1
    }
  } finally {
    generateConfigLoading.value = false
  }
}

const saveFullConfig = async () => {
  if (!props.simulationId || !simulationConfig.value) return
  configSaving.value = true
  try {
    await patchSimulationConfig(props.simulationId, simulationConfig.value)
    step3EditMode.value = false
    addLog(t('log.configSaved'))
  } catch (err) {
    addLog(`Config save failed: ${err.message}`)
  } finally {
    configSaving.value = false
  }
}

const toggleAgentHour = (agent, hour) => {
  if (!agent.active_hours) agent.active_hours = []
  const idx = agent.active_hours.indexOf(hour)
  if (idx === -1) {
    agent.active_hours.push(hour)
    agent.active_hours.sort((a, b) => a - b)
  } else {
    agent.active_hours.splice(idx, 1)
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

const fetchEntityCount = async (graphId) => {
  if (!graphId || availableEntityCount.value !== null) return
  entityCountLoading.value = true
  try {
    const res = await getGraphEntityCount(graphId)
    const count = res?.data?.filtered_count ?? res?.filtered_count ?? null
    availableEntityCount.value = count
    if (maxAgentsInput.value === null) maxAgentsInput.value = count
  } catch (err) {
    console.warn('[Step2] getGraphEntityCount failed:', err?.message ?? err)
  } finally {
    entityCountLoading.value = false
  }
}

// Watch graph_id so entity count loads even when projectData arrives after mount
watch(() => props.projectData?.graph_id, (graphId) => {
  if (graphId && currentPhase.value === 'phase_pre') fetchEntityCount(graphId)
})

onMounted(async () => {
  if (!props.simulationId) return
  addLog(t('log.step2Init'))

  // Check current simulation state and restore the correct phase without re-launching preparation
  try {
    const simRes = await getSimulation(props.simulationId)
    const simStatus = simRes?.data?.status
    if (simStatus && simStatus !== 'created') {
      if (simStatus === 'profiles_ready') {
        // Agents generated, awaiting Fase A — load profiles and show edit controls
        currentPhase.value = 'generating'
        await fetchProfilesRealtime()
        addLog(t('log.loadedAgentProfiles', { count: profiles.value.length }))
        currentPhase.value = 'phase_a'
        emit('update-status', 'profiles_ready')
      } else {
        // Any other non-created status: let startPrepareSimulation detect already_prepared
        startPrepareSimulation()
      }
      return
    }
  } catch { /* ignore */ }

  // Fresh simulation (status=created) — fetch entity count for phase_pre selector
  if (props.projectData?.graph_id) {
    fetchEntityCount(props.projectData.graph_id)
  }
})

onUnmounted(() => {
  stopPolling()
  stopProfilesPolling()
  stopConfigPolling()
})
</script>

<style scoped>
.env-setup-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.scroll-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Step Card */
.step-card {
  background: #FFF;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  border: 1px solid #EAEAEA;
  transition: all 0.3s ease;
  position: relative;
}

.step-card.active {
  border-color: #FF5722;
  box-shadow: 0 4px 12px rgba(255, 87, 34, 0.08);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.step-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: #E0E0E0;
}

.step-card.active .step-num,
.step-card.completed .step-num {
  color: #000;
}

.step-title {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.5px;
}

.badge {
  font-size: 10px;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}

.badge.success { background: #E8F5E9; color: #2E7D32; }
.badge.processing { background: #FF5722; color: #FFF; }
.badge.pending { background: #F5F5F5; color: #999; }
.badge.accent { background: #E3F2FD; color: #1565C0; }

.card-content {
  /* No extra padding - uses step-card's padding */
}

.api-note {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #999;
  margin-bottom: 8px;
}

.description {
  font-size: 12px;
  color: #666;
  line-height: 1.5;
  margin-bottom: 16px;
}

/* Action Section */
.action-section {
  margin-top: 16px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.primary {
  background: #000;
  color: #FFF;
}

.action-btn.primary:hover:not(:disabled) {
  opacity: 0.8;
}

.action-btn.secondary {
  background: #F5F5F5;
  color: #333;
}

.action-btn.secondary:hover:not(:disabled) {
  background: #E5E5E5;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-group {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.action-group.dual {
  display: grid;
  grid-template-columns: 1fr 1fr;
}

.action-group.dual .action-btn {
  width: 100%;
}

/* Info Card */
.info-card {
  background: #F5F5F5;
  border-radius: 6px;
  padding: 16px;
  margin-top: 16px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px dashed #E0E0E0;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 12px;
  color: #666;
}

.info-value {
  font-size: 13px;
  font-weight: 500;
}

.info-value.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  background: #F9F9F9;
  padding: 16px;
  border-radius: 6px;
}

.stat-card {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #000;
  font-family: 'JetBrains Mono', monospace;
}

.stat-label {
  font-size: 9px;
  color: #999;
  text-transform: uppercase;
  margin-top: 4px;
  display: block;
}

/* Profiles Preview */
.profiles-preview {
  margin-top: 20px;
  border-top: 1px solid #E5E5E5;
  padding-top: 16px;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.preview-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.profiles-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-height: 320px;
  overflow-y: auto;
  padding-right: 4px;
}

.profiles-list::-webkit-scrollbar {
  width: 4px;
}

.profiles-list::-webkit-scrollbar-thumb {
  background: #DDD;
  border-radius: 2px;
}

.profiles-list::-webkit-scrollbar-thumb:hover {
  background: #CCC;
}

.profile-card {
  background: #FAFAFA;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.profile-card:hover {
  border-color: #999;
  background: #FFF;
}

.profile-card--clickable:hover {
  border-color: #1a1a1a;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.profile-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.profile-realname {
  font-size: 14px;
  font-weight: 700;
  color: #000;
}

.profile-username {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #999;
}

.profile-meta {
  margin-bottom: 8px;
}

.profile-profession {
  font-size: 11px;
  color: #666;
  background: #F0F0F0;
  padding: 2px 8px;
  border-radius: 3px;
}

.profile-bio {
  font-size: 12px;
  color: #444;
  line-height: 1.6;
  margin: 0 0 10px 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.profile-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.topic-tag {
  font-size: 10px;
  color: #1565C0;
  background: #E3F2FD;
  padding: 2px 8px;
  border-radius: 10px;
}

.topic-more {
  font-size: 10px;
  color: #999;
  padding: 2px 6px;
}

/* Config Preview */
/* Config Detail Panel */
.config-detail-panel {
  margin-top: 16px;
}

.config-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
}

.config-toolbar .action-btn,
.config-toolbar .continue-btn {
  padding: 6px 14px;
  font-size: 12px;
}

.config-block {
  margin-top: 16px;
  border-top: 1px solid #E5E5E5;
  padding-top: 12px;
}

.config-block:first-child {
  margin-top: 0;
  border-top: none;
  padding-top: 0;
}

.config-block-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.config-block-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.config-block-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: #F1F5F9;
  color: #475569;
  padding: 2px 8px;
  border-radius: 10px;
}

/* Config Grid */
.config-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.config-item {
  background: #F9F9F9;
  padding: 12px 14px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-item-label {
  font-size: 11px;
  color: #94A3B8;
}

.config-item-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 600;
  color: #1E293B;
}

/* Time Periods */
.time-periods {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.period-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #F9F9F9;
  border-radius: 6px;
}

.period-label {
  font-size: 12px;
  font-weight: 500;
  color: #64748B;
  min-width: 70px;
}

.period-hours {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #475569;
  flex: 1;
}

.period-multiplier {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  color: #6366F1;
  background: #EEF2FF;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Agents Cards */
.agents-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}

.agents-cards::-webkit-scrollbar {
  width: 4px;
}

.agents-cards::-webkit-scrollbar-thumb {
  background: #DDD;
  border-radius: 2px;
}

.agents-cards::-webkit-scrollbar-thumb:hover {
  background: #CCC;
}

.agent-card {
  background: #F9F9F9;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 14px;
  transition: all 0.2s ease;
}

.agent-card:hover {
  border-color: #999;
  background: #FFF;
}

/* Agent Card Header */
.agent-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F1F5F9;
}

.agent-identity {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.agent-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #94A3B8;
}

.agent-name {
  font-size: 14px;
  font-weight: 600;
  color: #1E293B;
}

.agent-tags {
  display: flex;
  gap: 6px;
}

.agent-type {
  font-size: 10px;
  color: #64748B;
  background: #F1F5F9;
  padding: 2px 8px;
  border-radius: 4px;
}

.agent-stance {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 4px;
}

.stance-neutral {
  background: #F1F5F9;
  color: #64748B;
}

.stance-supportive {
  background: #DCFCE7;
  color: #16A34A;
}

.stance-opposing {
  background: #FEE2E2;
  color: #DC2626;
}

.stance-observer {
  background: #FEF3C7;
  color: #D97706;
}

/* Agent Timeline */
.agent-timeline {
  margin-bottom: 14px;
}

.timeline-label {
  display: block;
  font-size: 10px;
  color: #94A3B8;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.mini-timeline {
  display: flex;
  gap: 2px;
  height: 16px;
  background: #F8FAFC;
  border-radius: 4px;
  padding: 3px;
}

.timeline-hour {
  flex: 1;
  background: #E2E8F0;
  border-radius: 2px;
  transition: all 0.2s;
}

.timeline-hour.active {
  background: linear-gradient(180deg, #6366F1, #818CF8);
}

.timeline-marks {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: #94A3B8;
}

/* Agent Params */
.agent-params {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.param-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.param-item .param-label {
  font-size: 10px;
  color: #94A3B8;
}

.param-item .param-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.param-value.with-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mini-bar {
  height: 4px;
  background: linear-gradient(90deg, #6366F1, #A855F7);
  border-radius: 2px;
  min-width: 4px;
  max-width: 40px;
}

.param-value.positive {
  color: #16A34A;
}

.param-value.negative {
  color: #DC2626;
}

.param-value.neutral {
  color: #64748B;
}

.param-value.highlight {
  color: #6366F1;
}

/* Platforms Grid */
.platforms-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.platform-card {
  background: #F9F9F9;
  padding: 14px;
  border-radius: 6px;
}

.platform-card-header {
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #E5E5E5;
}

.platform-name {
  font-size: 13px;
  font-weight: 600;
  color: #333;
}

.platform-params {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.param-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.param-label {
  font-size: 12px;
  color: #64748B;
}

.param-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #1E293B;
}

/* Reasoning Content */
.reasoning-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reasoning-item {
  padding: 12px 14px;
  background: #F9F9F9;
  border-radius: 6px;
}

.reasoning-text {
  font-size: 13px;
  color: #555;
  line-height: 1.7;
  margin: 0;
}

/* Profile Modal */
.profile-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.profile-modal {
  background: #FFF;
  border-radius: 16px;
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 24px;
  background: #FFF;
  border-bottom: 1px solid #F0F0F0;
}

.modal-header-info {
  flex: 1;
}

.modal-name-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.modal-realname {
  font-size: 20px;
  font-weight: 700;
  color: #000;
}

.modal-username {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: #999;
}

.modal-profession {
  font-size: 12px;
  color: #666;
  background: #F5F5F5;
  padding: 4px 10px;
  border-radius: 4px;
  display: inline-block;
  font-weight: 500;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  color: #999;
  border-radius: 50%;
  font-size: 24px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  transition: color 0.2s;
  padding: 0;
}

.close-btn:hover {
  color: #333;
}

.modal-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

/* 基本信息网格 */
.modal-info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px 16px;
  margin-bottom: 32px;
  padding: 0;
  background: transparent;
  border-radius: 0;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 11px;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.info-value {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}

.info-value.mbti {
  font-family: 'JetBrains Mono', monospace;
  color: #FF5722;
}

/* 模块区域 */
.modal-section {
  margin-bottom: 28px;
}

.section-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.section-bio {
  font-size: 14px;
  color: #333;
  line-height: 1.6;
  margin: 0;
  padding: 16px;
  background: #F9F9F9;
  border-radius: 6px;
  border-left: 3px solid #E0E0E0;
}

/* 话题标签 */
.topics-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.topic-item {
  font-size: 11px;
  color: #1565C0;
  background: #E3F2FD;
  padding: 4px 10px;
  border-radius: 12px;
  transition: all 0.2s;
  border: none;
}

.topic-item:hover {
  background: #BBDEFB;
  color: #0D47A1;
}

/* 详细人设 */
.persona-dimensions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.dimension-card {
  background: #F8F9FA;
  padding: 12px;
  border-radius: 6px;
  border-left: 3px solid #DDD;
  transition: all 0.2s;
}

.dimension-card:hover {
  background: #F0F0F0;
  border-left-color: #999;
}

.dim-title {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: #333;
  margin-bottom: 4px;
}

.dim-desc {
  display: block;
  font-size: 10px;
  color: #888;
  line-height: 1.4;
}

.persona-content {
  max-height: none;
  overflow: visible;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

.persona-content::-webkit-scrollbar {
  width: 4px;
}

.persona-content::-webkit-scrollbar-thumb {
  background: #DDD;
  border-radius: 2px;
}

.section-persona {
  font-size: 13px;
  color: #555;
  line-height: 1.8;
  margin: 0;
  text-align: justify;
}

/* System Logs */
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
  height: 80px; /* Approx 4 lines visible */
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

/* Spinner */
.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid #E5E5E5;
  border-top-color: #FF5722;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
/* Orchestration Content */
.orchestration-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-top: 16px;
}

.box-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.narrative-box {
  background: #FFFFFF;
  padding: 20px 24px;
  border-radius: 12px;
  border: 1px solid #EEF2F6;
  box-shadow: 0 4px 24px rgba(0,0,0,0.03);
  transition: all 0.3s ease;
}

.narrative-box .box-label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #666;
  font-size: 13px;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
  font-weight: 600;
}

.special-icon {
  filter: drop-shadow(0 2px 4px rgba(255, 87, 34, 0.2));
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.narrative-box:hover .special-icon {
  transform: rotate(180deg);
}

.narrative-text {
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  font-size: 14px;
  color: #334155;
  line-height: 1.8;
  margin: 0;
  text-align: justify;
  letter-spacing: 0.01em;
}

.topics-section {
  background: #FFF;
}

.hot-topics-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hot-topic-tag {
  font-size: 12px;
  color:rgba(255, 86, 34, 0.88);
  background: #FFF3E0;
  padding: 4px 10px;
  border-radius: 12px;
  font-weight: 500;
}

.hot-topic-more {
  font-size: 11px;
  color: #999;
  padding: 4px 6px;
}

.initial-posts-section {
  border-top: 1px solid #EAEAEA;
  padding-top: 16px;
}

.posts-timeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-left: 8px;
  border-left: 2px solid #F0F0F0;
  margin-top: 12px;
}

.timeline-item {
  position: relative;
  padding-left: 20px;
}

.timeline-marker {
  position: absolute;
  left: 0;
  top: 14px;
  width: 12px;
  height: 2px;
  background: #DDD;
}

.timeline-content {
  background: #F9F9F9;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #EEE;
}

.post-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.post-role {
  font-size: 11px;
  font-weight: 700;
  color: #333;
  text-transform: uppercase;
}

.post-agent-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.post-id,
.post-username {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #666;
  line-height: 1;
  vertical-align: baseline;
}

.post-username {
  margin-right: 6px;
}

.post-text {
  font-size: 12px;
  color: #555;
  line-height: 1.5;
  margin: 0;
}

/* 模拟轮数配置样式 */
.rounds-config-section {
  margin: 24px 0;
  padding-top: 24px;
  border-top: 1px solid #EAEAEA;
}

.rounds-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1E293B;
}

.section-desc {
  font-size: 12px;
  color: #94A3B8;
}

.desc-highlight {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: #1E293B;
  background: #F1F5F9;
  padding: 1px 6px;
  border-radius: 4px;
  margin: 0 2px;
}

/* Switch Control */
.switch-control {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px 4px 4px;
  border-radius: 20px;
  transition: background 0.2s;
}

.switch-control:hover {
  background: #F8FAFC;
}

.switch-control input {
  display: none;
}

.switch-track {
  width: 36px;
  height: 20px;
  background: #E2E8F0;
  border-radius: 10px;
  position: relative;
  transition: all 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.switch-track::after {
  content: '';
  position: absolute;
  left: 2px;
  top: 2px;
  width: 16px;
  height: 16px;
  background: #FFF;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  transition: transform 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.switch-control input:checked + .switch-track {
  background: #000;
}

.switch-control input:checked + .switch-track::after {
  transform: translateX(16px);
}

.switch-label {
  font-size: 12px;
  font-weight: 500;
  color: #64748B;
}

.switch-control input:checked ~ .switch-label {
  color: #1E293B;
}

/* Slider Content */
.rounds-content {
  animation: fadeIn 0.3s ease;
}

.slider-display {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 16px;
}

.slider-main-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.val-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 24px;
  font-weight: 700;
  color: #000;
}

.val-unit {
  font-size: 12px;
  color: #666;
  font-weight: 500;
}

.slider-meta-info {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #64748B;
  background: #F1F5F9;
  padding: 4px 8px;
  border-radius: 4px;
}

.range-wrapper {
  position: relative;
  padding: 0 2px;
}

.minimal-slider {
  -webkit-appearance: none;
  width: 100%;
  height: 4px;
  background: #E2E8F0;
  border-radius: 2px;
  outline: none;
  background-image: linear-gradient(#000, #000);
  background-size: var(--percent, 0%) 100%;
  background-repeat: no-repeat;
  cursor: pointer;
}

.minimal-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #FFF;
  border: 2px solid #000;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1);
  transition: transform 0.1s;
  margin-top: -6px; /* Center thumb */
}

.minimal-slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.minimal-slider::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 2px;
}

.range-marks {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #94A3B8;
  position: relative;
}

.mark-recommend {
  cursor: pointer;
  transition: color 0.2s;
  position: relative;
}

.mark-recommend:hover {
  color: #000;
}

.mark-recommend.active {
  color: #000;
  font-weight: 600;
}

.mark-recommend::after {
  content: '';
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  width: 1px;
  height: 4px;
  background: #CBD5E1;
}

/* Auto Info */
.auto-info-card {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #F8FAFC;
  padding: 16px 20px;
  border-radius: 8px;
}

.auto-value {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  gap: 4px;
  padding-right: 24px;
  border-right: 1px solid #E2E8F0;
}

.auto-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  justify-content: center;
}

.auto-meta-row {
  display: flex;
  align-items: center;
}

.duration-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  color: #64748B;
  background: #FFFFFF;
  border: 1px solid #E2E8F0;
  padding: 3px 8px;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.auto-desc {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.auto-desc p {
  margin: 0;
  font-size: 13px;
  color: #64748B;
  line-height: 1.5;
}

.highlight-tip {
  margin-top: 4px !important;
  font-size: 12px !important;
  color: #000 !important;
  font-weight: 500;
  cursor: pointer;
}

.highlight-tip:hover {
  text-decoration: underline;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Modal Transition */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .profile-modal {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.modal-leave-active .profile-modal {
  transition: all 0.3s ease-in;
}

.modal-enter-from .profile-modal,
.modal-leave-to .profile-modal {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

/* Fase A footer */
.phase-pre-section { padding: 12px 0 4px; }
.phase-pre-loading { color: #888; font-size: 13px; }
.phase-pre-info { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 14px; color: #444; }
.phase-pre-count { font-weight: 600; font-size: 20px; color: #1a1a1a; }
.phase-pre-input-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.phase-pre-input-label { font-size: 13px; color: #555; white-space: nowrap; }
.phase-pre-input {
  width: 90px; padding: 6px 10px; border: 1px solid #D0D0D0; border-radius: 6px;
  font-size: 14px; text-align: center;
}
.phase-pre-input:focus { outline: none; border-color: #1a1a1a; }
.phase-pre-warn { font-size: 12px; color: #E07B00; }
.phase-pre-footer { display: flex; justify-content: flex-end; padding-top: 12px; }

.phase-a-footer {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0;
  border-top: 1px solid #EAEAEA;
  margin-top: 16px;
}

.continue-btn {
  padding: 10px 24px;
  background: #000;
  color: #FFF;
  border: none;
  border-radius: 6px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
}
.continue-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Fase B section */
.phase-b-section { padding: 16px 0; }
.section-subtitle { font-size: 13px; color: #666; margin-bottom: 16px; }
.config-form { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0; }
.config-field label { display: block; font-size: 12px; font-weight: 600; color: #666; margin-bottom: 4px; text-transform: uppercase; }
.config-field input, .config-field select { width: 100%; padding: 8px 12px; border: 1px solid #E0E0E0; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
.phase-b-footer { display: flex; justify-content: space-between; padding-top: 16px; border-top: 1px solid #EAEAEA; }

/* Agent action button and badge */
.agent-action-btn { background: none; border: none; cursor: pointer; padding: 4px 8px; font-size: 18px; color: #666; margin-left: auto; }
.agent-action-btn:hover { color: #000; }
.manually-edited-badge {
  background: #FFF3CD; color: #856404;
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;
}

/* Agent edit/regen modal */
.agent-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}

.agent-modal {
  background: #FFF; border-radius: 12px; padding: 24px;
  width: 560px; max-height: 80vh; overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
}

.agent-modal .modal-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 16px;
  padding: 0;
  border-bottom: none;
}

.modal-title { font-weight: 700; font-size: 18px; flex: 1; }

.edited-badge {
  background: #FFF3CD; color: #856404;
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;
}

.modal-close { background: none; border: none; cursor: pointer; font-size: 18px; }

.agent-modal .modal-body { padding: 0; overflow: visible; flex: unset; }
.agent-modal .modal-body.modal-view p { font-size: 14px; color: #444; line-height: 1.6; margin-bottom: 10px; }
.agent-modal .field-group { margin-bottom: 12px; }
.agent-modal label { display: block; font-size: 12px; font-weight: 600; color: #666; margin-bottom: 4px; text-transform: uppercase; }
.agent-modal input, .agent-modal textarea {
  width: 100%; padding: 8px 12px; border: 1px solid #E0E0E0;
  border-radius: 6px; font-size: 14px; resize: vertical;
  box-sizing: border-box;
}

.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
.btn-primary { padding: 8px 16px; background: #000; color: #FFF; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
.btn-secondary { padding: 8px 16px; background: #F5F5F5; color: #333; border: 1px solid #DDD; border-radius: 6px; cursor: pointer; font-weight: 600; }
.btn-danger { padding: 8px 16px; background: #FFF; color: #D32F2F; border: 1px solid #FFCDD2; border-radius: 6px; cursor: pointer; font-weight: 600; }
.btn-primary:disabled, .btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
