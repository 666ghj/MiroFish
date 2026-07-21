<template>
  <div class="setup-card" :class="cardClass">
    <div class="card-head">
      <div class="card-label">
        <span class="card-num">04</span>
        <span class="card-title">{{ $t('step2.initialActivation') }}</span>
      </div>
      <span class="card-badge" :class="badgeClass">
        <template v-if="phase > 3">{{ $t('common.completed') }}</template>
        <template v-else-if="phase === 3">{{ $t('step2.orchestrating') }}</template>
        <template v-else>{{ $t('common.pending') }}</template>
      </span>
    </div>

    <div class="card-body">
      <p class="api-route">POST /api/simulation/prepare</p>
      <p class="card-desc">{{ $t('step2.initialActivationDesc') }}</p>

      <template v-if="eventConfig">
        <!-- Narrative direction -->
        <div class="narrative-block">
          <span class="block-label">{{ $t('step2.narrativeDirection') }}</span>
          <p class="narrative-text">{{ eventConfig.narrative_direction }}</p>
        </div>

        <!-- Hot topics -->
        <div class="topics-block" v-if="eventConfig.hot_topics?.length">
          <span class="block-label">{{ $t('step2.initialHotTopics') }}</span>
          <div class="hot-topics">
            <span v-for="topic in eventConfig.hot_topics" :key="topic" class="hot-tag">
              # {{ topic }}
            </span>
          </div>
        </div>

        <!-- Initial posts timeline -->
        <div class="posts-block" v-if="eventConfig.initial_posts?.length">
          <span class="block-label">
            {{ $t('step2.initialActivationSeq', { count: eventConfig.initial_posts.length }) }}
          </span>
          <div class="posts-timeline">
            <div
              v-for="(post, idx) in eventConfig.initial_posts"
              :key="idx"
              class="post-item"
            >
              <div class="post-marker" />
              <div class="post-content">
                <div class="post-meta">
                  <span class="post-type">{{ post.poster_type }}</span>
                  <span class="post-agent">
                    Agent {{ post.poster_agent_id }}
                    <span class="post-username">@{{ getAgentUsername(post.poster_agent_id) }}</span>
                  </span>
                </div>
                <p class="post-text">{{ post.content }}</p>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  phase:            { type: Number,  required: true },
  simulationConfig: { type: Object,  default: null },
  profiles:         { type: Array,   default: () => [] },
})

const cardClass = computed(() => ({
  'card--pending':   props.phase < 3,
  'card--active':    props.phase === 3,
  'card--completed': props.phase > 3,
}))

const badgeClass = computed(() => {
  if (props.phase > 3) return 'badge--done'
  if (props.phase === 3) return 'badge--active'
  return 'badge--pending'
})

const eventConfig = computed(() => props.simulationConfig?.event_config || null)

const getAgentUsername = (agentId) => {
  const profile = props.profiles[agentId]
  return profile?.name || profile?.username || `agent_${agentId}`
}
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
.setup-card.card--pending   { opacity: 0.5; }

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

.block-label {
  font-size: 10.5px; font-weight: 700; color: #AAAAAA;
  text-transform: uppercase; letter-spacing: 0.5px;
}

.narrative-block { display: flex; flex-direction: column; gap: 7px; }
.narrative-text {
  font-size: 12.5px; color: #333; line-height: 1.65; margin: 0;
  background: #F8F8F8; border-radius: 7px; padding: 11px 13px;
  border-left: 3px solid #FF5722;
}

.topics-block { display: flex; flex-direction: column; gap: 7px; }
.hot-topics { display: flex; flex-wrap: wrap; gap: 6px; }
.hot-tag {
  font-size: 11.5px; font-weight: 600; color: #333;
  background: #F0F0F0; padding: 4px 10px; border-radius: 4px;
}

.posts-block { display: flex; flex-direction: column; gap: 7px; }
.posts-timeline { display: flex; flex-direction: column; gap: 8px; }

.post-item { display: flex; gap: 10px; align-items: flex-start; }
.post-marker {
  width: 7px; height: 7px; border-radius: 50%;
  background: #D0D0D0; flex-shrink: 0; margin-top: 6px;
}

.post-content { flex: 1; }
.post-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.post-type {
  font-size: 9.5px; font-weight: 700; color: #888;
  text-transform: uppercase; letter-spacing: 0.4px;
}
.post-agent { font-size: 11px; color: #555; }
.post-username { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #AAAAAA; margin-left: 4px; }

.post-text {
  font-size: 12px; color: #333; line-height: 1.6; margin: 0;
  background: #F8F8F8; border-radius: 6px; padding: 8px 10px;
}
</style>
