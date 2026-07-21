<template>
  <div class="setup-card" :class="cardClass">
    <div class="card-head">
      <div class="card-label">
        <span class="card-num">02</span>
        <span class="card-title">{{ $t('step2.generateAgentPersona') }}</span>
      </div>
      <span class="card-badge" :class="badgeClass">
        <template v-if="phase > 1">{{ $t('common.completed') }}</template>
        <template v-else-if="phase === 1">{{ prepareProgress }}%</template>
        <template v-else>{{ $t('common.pending') }}</template>
      </span>
    </div>

    <div class="card-body">
      <p class="api-route">POST /api/simulation/prepare</p>
      <p class="card-desc">{{ $t('step2.generateAgentPersonaDesc') }}</p>

      <!-- Stats quando há perfis -->
      <div v-if="profiles.length > 0" class="stats-row">
        <div class="stat-item">
          <span class="stat-num">{{ profiles.length }}</span>
          <span class="stat-lbl">{{ $t('step2.currentAgentCount') }}</span>
        </div>
        <div class="stat-sep" />
        <div class="stat-item">
          <span class="stat-num">{{ expectedTotal || '?' }}</span>
          <span class="stat-lbl">{{ $t('step2.expectedAgentTotal') }}</span>
        </div>
        <div class="stat-sep" />
        <div class="stat-item">
          <span class="stat-num">{{ totalTopicsCount }}</span>
          <span class="stat-lbl">{{ $t('step2.relatedTopicsCount') }}</span>
        </div>
      </div>

      <!-- Progress bar durante geração -->
      <div v-if="phase === 1 && prepareProgress > 0" class="progress-bar-wrap">
        <div class="progress-bar-track">
          <div class="progress-bar-fill" :style="{ width: prepareProgress + '%' }" />
        </div>
        <span class="progress-pct">{{ prepareProgress }}%</span>
      </div>

      <!-- Lista de personas -->
      <div v-if="profiles.length > 0" class="profiles-section">
        <div class="profiles-header">
          <span class="profiles-label">{{ $t('step2.generatedAgentPersonas') }}</span>
          <button
            v-if="profiles.length > 6"
            class="btn-toggle-all"
            @click="showAll = !showAll"
          >
            {{ showAll ? $t('step2.showLess') : $t('step2.showAll', { count: profiles.length }) }}
          </button>
        </div>

        <div class="profiles-grid">
          <div
            v-for="(profile, idx) in visibleProfiles"
            :key="idx"
            class="profile-card"
            @click="$emit('select-profile', profile)"
            tabindex="0"
          >
            <div class="profile-top">
              <div class="profile-name-block">
                <span class="profile-realname">{{ profile.username || 'Unknown' }}</span>
                <span class="profile-handle">@{{ profile.name || `agent_${idx}` }}</span>
              </div>
              <span class="profile-type-tag" v-if="profile.entity_type">{{ profile.entity_type }}</span>
            </div>
            <span class="profile-profession">{{ profile.profession || $t('step2.unknownProfession') }}</span>
            <p class="profile-bio">{{ truncate(profile.bio || $t('step2.noBio'), 90) }}</p>
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
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  phase:          { type: Number, required: true },
  profiles:       { type: Array,  default: () => [] },
  prepareProgress:{ type: Number, default: 0 },
  expectedTotal:  { type: Number, default: null },
})

defineEmits(['select-profile'])

const showAll = ref(false)

const cardClass = computed(() => ({
  'card--pending':   props.phase < 1,
  'card--active':    props.phase === 1,
  'card--completed': props.phase > 1,
}))

const badgeClass = computed(() => {
  if (props.phase > 1) return 'badge--done'
  if (props.phase === 1) return 'badge--active'
  return 'badge--pending'
})

const visibleProfiles = computed(() =>
  showAll.value ? props.profiles : props.profiles.slice(0, 6)
)

const totalTopicsCount = computed(() =>
  props.profiles.reduce((sum, p) => sum + (p.interested_topics?.length || 0), 0)
)

const truncate = (str, n) => str && str.length > n ? str.slice(0, n) + '…' : str
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid #F0F0F0;
}
.card-label { display: flex; align-items: center; gap: 10px; }
.card-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: #CCCCCC;
}
.card-title { font-size: 13px; font-weight: 700; color: #1A1A1A; }

.card-badge {
  font-size: 10.5px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 20px;
}
.badge--done    { background: #F0FBF2; color: #2A7D3A; }
.badge--active  { background: #FFF3EE; color: #D44B00; }
.badge--pending { background: #F5F5F5; color: #AAAAAA; }

.card-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }

.api-route {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #AAAAAA;
  margin: 0;
}

.card-desc {
  font-size: 12.5px;
  color: #555;
  margin: 0;
  line-height: 1.55;
}

/* Stats */
.stats-row {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #F8F8F8;
  border-radius: 8px;
  padding: 12px 16px;
}
.stat-item { display: flex; flex-direction: column; gap: 2px; }
.stat-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: #1A1A1A;
  line-height: 1;
}
.stat-lbl { font-size: 10.5px; color: #888; font-weight: 500; }
.stat-sep { width: 1px; height: 28px; background: #E5E5E5; }

/* Progress */
.progress-bar-wrap { display: flex; align-items: center; gap: 10px; }
.progress-bar-track {
  flex: 1;
  height: 4px;
  background: #EFEFEF;
  border-radius: 2px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: #FF5722;
  border-radius: 2px;
  transition: width 0.4s ease;
}
.progress-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #888;
  flex-shrink: 0;
}

/* Profiles section */
.profiles-section { display: flex; flex-direction: column; gap: 10px; }
.profiles-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.profiles-label {
  font-size: 11px;
  font-weight: 700;
  color: #AAAAAA;
  text-transform: uppercase;
  letter-spacing: 0.6px;
}
.btn-toggle-all {
  font-size: 11px;
  color: #666;
  background: none;
  border: none;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* Profile grid */
.profiles-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.profile-card {
  background: #FAFAFA;
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  padding: 12px 13px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 5px;
  transition: border-color 0.15s, background 0.15s;
}
.profile-card:hover { background: #F3F3F3; border-color: #E0E0E0; }

.profile-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
}
.profile-name-block { display: flex; flex-direction: column; gap: 1px; }
.profile-realname { font-size: 12.5px; font-weight: 700; color: #1A1A1A; }
.profile-handle { font-size: 10.5px; color: #AAAAAA; font-family: 'JetBrains Mono', monospace; }

.profile-type-tag {
  font-size: 9.5px;
  font-weight: 700;
  color: #666;
  background: #EDEDED;
  padding: 2px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  white-space: nowrap;
}

.profile-profession { font-size: 11px; color: #888; font-weight: 500; }

.profile-bio {
  font-size: 11.5px;
  color: #555;
  line-height: 1.5;
  margin: 0;
}

.profile-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}
.topic-tag {
  font-size: 10px;
  background: #EDEDED;
  color: #555;
  padding: 2px 7px;
  border-radius: 3px;
}
.topic-more { font-size: 10px; color: #AAAAAA; align-self: center; }
</style>
