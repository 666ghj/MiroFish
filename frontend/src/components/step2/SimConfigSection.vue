<template>
  <div class="setup-card" :class="cardClass">
    <div class="card-head">
      <div class="card-label">
        <span class="card-num">03</span>
        <span class="card-title">{{ $t('step2.dualPlatformConfig') }}</span>
      </div>
      <span class="card-badge" :class="badgeClass">
        <template v-if="phase > 2">{{ $t('common.completed') }}</template>
        <template v-else-if="phase === 2">{{ $t('step2.generating') }}</template>
        <template v-else>{{ $t('common.pending') }}</template>
      </span>
    </div>

    <div class="card-body">
      <p class="api-route">POST /api/simulation/prepare</p>
      <p class="card-desc">{{ $t('step2.dualPlatformConfigDesc') }}</p>

      <template v-if="simulationConfig">
        <!-- Bloco: Configuração de tempo -->
        <div class="config-section">
          <span class="section-label">{{ $t('step2.simulationDuration') }}</span>
          <div class="kv-grid">
            <div class="kv-item">
              <span class="kv-key">{{ $t('step2.simulationDuration') }}</span>
              <span class="kv-val">{{ simulationConfig.time_config?.total_simulation_hours || '—' }}h</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">{{ $t('step2.roundDuration') }}</span>
              <span class="kv-val">{{ simulationConfig.time_config?.minutes_per_round || '—' }}min</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">{{ $t('step2.totalRounds') }}</span>
              <span class="kv-val">{{ calculatedRounds }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">{{ $t('step2.activePerHour') }}</span>
              <span class="kv-val">
                {{ simulationConfig.time_config?.agents_per_hour_min }}–{{ simulationConfig.time_config?.agents_per_hour_max }}
              </span>
            </div>
          </div>

          <!-- Time periods -->
          <div class="time-periods" v-if="simulationConfig.time_config">
            <div class="period-row" v-for="period in timePeriods" :key="period.key">
              <span class="period-name">{{ period.label }}</span>
              <span class="period-range">{{ period.range }}</span>
              <span class="period-mult">×{{ period.multiplier }}</span>
            </div>
          </div>
        </div>

        <!-- Bloco: Agentes -->
        <div class="config-section" v-if="simulationConfig.agent_configs?.length">
          <div class="section-head">
            <span class="section-label">{{ $t('step2.agentConfig') }}</span>
            <span class="section-count">{{ simulationConfig.agent_configs.length }}</span>
          </div>
          <div class="agents-list">
            <div
              v-for="agent in simulationConfig.agent_configs"
              :key="agent.agent_id"
              class="agent-row"
            >
              <div class="agent-ident">
                <span class="agent-id">A{{ agent.agent_id }}</span>
                <span class="agent-name">{{ agent.entity_name }}</span>
              </div>
              <div class="agent-tags">
                <span class="tag-type">{{ agent.entity_type }}</span>
                <span class="tag-stance" :class="'stance-' + agent.stance">{{ agent.stance }}</span>
              </div>
              <!-- 24h mini timeline -->
              <div class="mini-timeline" :title="$t('step2.activeTimePeriod')">
                <div
                  v-for="h in 24"
                  :key="h - 1"
                  class="tl-hour"
                  :class="{ active: agent.active_hours?.includes(h - 1) }"
                />
              </div>
              <div class="agent-params">
                <span>{{ agent.posts_per_hour }}<small>p/h</small></span>
                <span>{{ agent.activity_level ? (agent.activity_level * 100).toFixed(0) : '—' }}%</span>
                <span
                  :class="agent.sentiment_bias > 0 ? 'pos' : agent.sentiment_bias < 0 ? 'neg' : ''"
                >
                  {{ agent.sentiment_bias > 0 ? '+' : '' }}{{ agent.sentiment_bias?.toFixed(1) ?? '0.0' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Bloco: Plataformas -->
        <div class="config-section" v-if="simulationConfig.twitter_config || simulationConfig.reddit_config">
          <span class="section-label">{{ $t('step2.recommendAlgoConfig') }}</span>
          <div class="platforms-row">
            <div v-if="simulationConfig.twitter_config" class="platform-block">
              <span class="platform-name">{{ $t('step2.platform1Name') }}</span>
              <div class="platform-kv">
                <span>{{ $t('step2.recencyWeight') }}</span>
                <span>{{ simulationConfig.twitter_config.recency_weight }}</span>
              </div>
              <div class="platform-kv">
                <span>{{ $t('step2.popularityWeight') }}</span>
                <span>{{ simulationConfig.twitter_config.popularity_weight }}</span>
              </div>
              <div class="platform-kv">
                <span>{{ $t('step2.echoChamberStrength') }}</span>
                <span>{{ simulationConfig.twitter_config.echo_chamber_strength }}</span>
              </div>
            </div>
            <div v-if="simulationConfig.reddit_config" class="platform-block">
              <span class="platform-name">{{ $t('step2.platform2Name') }}</span>
              <div class="platform-kv">
                <span>{{ $t('step2.recencyWeight') }}</span>
                <span>{{ simulationConfig.reddit_config.recency_weight }}</span>
              </div>
              <div class="platform-kv">
                <span>{{ $t('step2.popularityWeight') }}</span>
                <span>{{ simulationConfig.reddit_config.popularity_weight }}</span>
              </div>
              <div class="platform-kv">
                <span>{{ $t('step2.echoChamberStrength') }}</span>
                <span>{{ simulationConfig.reddit_config.echo_chamber_strength }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Reasoning -->
        <div class="config-section" v-if="simulationConfig.generation_reasoning">
          <span class="section-label">{{ $t('step2.llmConfigReasoning') }}</span>
          <div class="reasoning-text">
            {{ simulationConfig.generation_reasoning.split('|')[0]?.trim() }}
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  phase:            { type: Number,  required: true },
  simulationConfig: { type: Object,  default: null },
})

const cardClass = computed(() => ({
  'card--pending':   props.phase < 2,
  'card--active':    props.phase === 2,
  'card--completed': props.phase > 2,
}))

const badgeClass = computed(() => {
  if (props.phase > 2) return 'badge--done'
  if (props.phase === 2) return 'badge--active'
  return 'badge--pending'
})

const calculatedRounds = computed(() => {
  const tc = props.simulationConfig?.time_config
  if (!tc?.total_simulation_hours || !tc?.minutes_per_round) return '—'
  return Math.floor((tc.total_simulation_hours * 60) / tc.minutes_per_round)
})

const timePeriods = computed(() => {
  const tc = props.simulationConfig?.time_config
  if (!tc) return []
  return [
    { key: 'peak',     label: t('step2.peakHours'),    range: (tc.peak_hours?.[0] ?? '') + ':00…',     multiplier: tc.peak_activity_multiplier },
    { key: 'work',     label: t('step2.workHours'),    range: (tc.work_hours?.[0] ?? '') + ':00…',     multiplier: tc.work_activity_multiplier },
    { key: 'morning',  label: t('step2.morningHours'), range: (tc.morning_hours?.[0] ?? '') + ':00…',  multiplier: tc.morning_activity_multiplier },
    { key: 'offpeak',  label: t('step2.offPeakHours'), range: (tc.off_peak_hours?.[0] ?? '') + ':00…', multiplier: tc.off_peak_activity_multiplier },
  ].filter(p => p.multiplier !== undefined)
})
</script>

<style scoped>
.setup-card {
  background: #fff;
  border: 1px solid #EBEBEB;
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s, opacity 0.2s;
}
.setup-card.card--active    { border-color: #D0D0D0; }
.setup-card.card--completed { border-color: #E8E8E8; opacity: 0.9; }
.setup-card.card--pending   { opacity: 0.55; }

.card-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid #F0F0F0;
}
.card-label { display: flex; align-items: center; gap: 10px; }
.card-num { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700; color: #CCCCCC; }
.card-title { font-size: 13px; font-weight: 700; color: #1A1A1A; }

.card-badge { font-size: 10.5px; font-weight: 700; padding: 3px 10px; border-radius: 20px; }
.badge--done    { background: #F0FBF2; color: #2A7D3A; }
.badge--active  { background: #FFF3EE; color: #D44B00; }
.badge--pending { background: #F5F5F5; color: #AAAAAA; }

.card-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; }

.api-route { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #AAAAAA; margin: 0; }
.card-desc  { font-size: 12.5px; color: #555; margin: 0; line-height: 1.55; }

/* Config sections */
.config-section { display: flex; flex-direction: column; gap: 8px; }

.section-head { display: flex; align-items: center; gap: 8px; }
.section-label {
  font-size: 10.5px; font-weight: 700; color: #AAAAAA;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.section-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; color: #CCCCCC;
  background: #F0F0F0; padding: 1px 6px; border-radius: 3px;
}

/* KV grid */
.kv-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
.kv-item {
  display: flex; align-items: baseline; justify-content: space-between;
  background: #F8F8F8; border-radius: 6px; padding: 8px 10px;
}
.kv-key { font-size: 11px; color: #888; }
.kv-val { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; color: #1A1A1A; }

/* Time periods */
.time-periods { display: flex; flex-direction: column; gap: 4px; }
.period-row {
  display: flex; align-items: center; gap: 10px;
  font-size: 11.5px; padding: 3px 0;
}
.period-name { color: #888; width: 80px; flex-shrink: 0; }
.period-range { color: #555; flex: 1; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; }
.period-mult { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #444; font-weight: 700; }

/* Agents list */
.agents-list { display: flex; flex-direction: column; gap: 6px; }
.agent-row {
  display: flex; align-items: center; gap: 10px;
  background: #F8F8F8; border-radius: 7px; padding: 8px 12px;
  flex-wrap: wrap;
}
.agent-ident { display: flex; align-items: center; gap: 6px; min-width: 120px; }
.agent-id { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #AAAAAA; }
.agent-name { font-size: 12px; font-weight: 700; color: #1A1A1A; }
.agent-tags { display: flex; gap: 4px; flex-shrink: 0; }
.tag-type {
  font-size: 9.5px; font-weight: 700;
  background: #EDEDED; color: #555; padding: 2px 6px; border-radius: 3px;
}
.tag-stance {
  font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 3px;
  background: #F0F0F0; color: #666;
}
.stance-positive { background: #E8F5E9; color: #2E7D32; }
.stance-negative { background: #FFEBEE; color: #C62828; }
.stance-neutral  { background: #F5F5F5; color: #757575; }

/* Mini timeline */
.mini-timeline { display: flex; gap: 1px; flex: 1; min-width: 80px; }
.tl-hour { height: 8px; flex: 1; background: #E8E8E8; border-radius: 1px; }
.tl-hour.active { background: #FF5722; }

.agent-params {
  display: flex; gap: 10px; font-size: 11px; color: #666;
  font-family: 'JetBrains Mono', monospace;
}
.agent-params small { font-size: 9px; color: #AAAAAA; }
.pos { color: #2E7D32; }
.neg { color: #C62828; }

/* Platforms */
.platforms-row { display: flex; gap: 10px; }
.platform-block {
  flex: 1; background: #F8F8F8; border-radius: 8px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 7px;
}
.platform-name { font-size: 11.5px; font-weight: 700; color: #1A1A1A; margin-bottom: 2px; }
.platform-kv {
  display: flex; justify-content: space-between;
  font-size: 11px; color: #777;
}
.platform-kv span:last-child {
  font-family: 'JetBrains Mono', monospace; color: #333; font-weight: 600;
}

/* Reasoning */
.reasoning-text {
  font-size: 12px; color: #555; line-height: 1.6;
  background: #F8F8F8; border-radius: 7px; padding: 10px 12px;
  border-left: 2px solid #E0E0E0;
}
</style>
