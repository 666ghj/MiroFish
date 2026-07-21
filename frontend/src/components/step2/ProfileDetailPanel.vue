<template>
  <Transition name="modal">
    <div v-if="profile" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-panel">
        <!-- Header -->
        <div class="modal-head">
          <div class="modal-identity">
            <span class="modal-realname">{{ profile.username }}</span>
            <span class="modal-handle">@{{ profile.name }}</span>
          </div>
          <div class="modal-head-right">
            <span class="modal-type-tag" v-if="profile.entity_type">{{ profile.entity_type }}</span>
            <button class="modal-close" @click="$emit('close')" :aria-label="$t('common.close')">✕</button>
          </div>
        </div>

        <!-- Body -->
        <div class="modal-body">
          <!-- Profession + bio -->
          <div class="modal-section">
            <span class="section-lbl">{{ $t('step2.profileModalProfession') }}</span>
            <span class="section-val">{{ profile.profession || $t('step2.unknownProfession') }}</span>
          </div>

          <div class="modal-section" v-if="profile.bio">
            <span class="section-lbl">{{ $t('step2.profileModalBio') }}</span>
            <p class="section-bio">{{ profile.bio }}</p>
          </div>

          <!-- Topics -->
          <div class="modal-section" v-if="profile.interested_topics?.length">
            <span class="section-lbl">{{ $t('step2.profileModalTopics') }}</span>
            <div class="topics-grid">
              <span v-for="topic in profile.interested_topics" :key="topic" class="topic-chip">
                {{ topic }}
              </span>
            </div>
          </div>

          <!-- Persona -->
          <div class="modal-section" v-if="profile.persona">
            <span class="section-lbl">{{ $t('step2.profileModalPersona') }}</span>

            <div class="persona-dims">
              <div class="dim-item">
                <span class="dim-title">{{ $t('step2.personaDimExperience') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimExperienceDesc') }}</span>
              </div>
              <div class="dim-item">
                <span class="dim-title">{{ $t('step2.personaDimBehavior') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimBehaviorDesc') }}</span>
              </div>
              <div class="dim-item">
                <span class="dim-title">{{ $t('step2.personaDimMemory') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimMemoryDesc') }}</span>
              </div>
              <div class="dim-item">
                <span class="dim-title">{{ $t('step2.personaDimSocial') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimSocialDesc') }}</span>
              </div>
            </div>

            <p class="persona-text">{{ profile.persona }}</p>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
defineProps({
  profile: { type: Object, default: null },
})
defineEmits(['close'])
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; z-index: 500;
  background: rgba(0, 0, 0, 0.35);
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
}

.modal-panel {
  background: #fff; border-radius: 12px;
  width: 100%; max-width: 560px; max-height: 85vh;
  display: flex; flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

/* Head */
.modal-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 20px 22px; border-bottom: 1px solid #F0F0F0; flex-shrink: 0;
}
.modal-identity { display: flex; flex-direction: column; gap: 3px; }
.modal-realname { font-size: 17px; font-weight: 800; color: #0A0A0A; }
.modal-handle {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px; color: #AAAAAA;
}

.modal-head-right { display: flex; align-items: center; gap: 10px; }
.modal-type-tag {
  font-size: 10px; font-weight: 700;
  background: #EDEDED; color: #555; padding: 3px 8px; border-radius: 4px;
}
.modal-close {
  background: none; border: none; cursor: pointer;
  font-size: 16px; color: #BBBBBB; padding: 2px 6px;
  transition: color 0.15s;
}
.modal-close:hover { color: #333; }

/* Body */
.modal-body {
  overflow-y: auto; padding: 20px 22px;
  display: flex; flex-direction: column; gap: 18px;
}
.modal-body::-webkit-scrollbar { width: 4px; }
.modal-body::-webkit-scrollbar-thumb { background: #DDD; border-radius: 2px; }

.modal-section { display: flex; flex-direction: column; gap: 8px; }

.section-lbl {
  font-size: 10px; font-weight: 700; color: #BBBBBB;
  text-transform: uppercase; letter-spacing: 0.7px;
}

.section-val { font-size: 13px; font-weight: 600; color: #1A1A1A; }

.section-bio {
  font-size: 12.5px; color: #444; line-height: 1.65;
  margin: 0;
}

/* Topics */
.topics-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.topic-chip {
  font-size: 11.5px; color: #444;
  background: #F0F0F0; padding: 4px 10px; border-radius: 4px;
}

/* Persona */
.persona-dims {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 4px;
}
.dim-item {
  background: #F8F8F8; border-radius: 7px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 3px;
}
.dim-title { font-size: 11px; font-weight: 700; color: #333; }
.dim-desc  { font-size: 10.5px; color: #888; line-height: 1.4; }

.persona-text {
  font-size: 12px; color: #444; line-height: 1.7;
  margin: 0; background: #F8F8F8; border-radius: 7px; padding: 12px 14px;
}

/* Transitions */
.modal-enter-active, .modal-leave-active { transition: opacity 0.22s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }

.modal-enter-active .modal-panel,
.modal-leave-active .modal-panel {
  transition: transform 0.22s ease;
}
.modal-enter-from .modal-panel { transform: scale(0.96) translateY(8px); }
.modal-leave-to .modal-panel   { transform: scale(0.96) translateY(8px); }
</style>
