<!--
  EmergencyStopButton

  Floating "panic button" that force-stops every running simulation
  on the host. The user-visible safety net for the subprocess-leak
  bug where children kept burning LLM credits after the backend died.

  Always visible (any page) so it can be hit fast from any state.
  Confirms before firing because it is destructive.
-->
<template>
  <Transition name="fade">
    <button
      v-if="visible"
      class="emergency-stop-btn"
      :class="{ working: working }"
      :disabled="working"
      :title="$t('emergency.tooltip')"
      @click="onClick"
    >
      <span class="dot"></span>
      <span class="label">
        {{ working ? $t('emergency.stopping') : $t('emergency.stopAll') }}
      </span>
    </button>
  </Transition>
</template>

<script setup>
import { ref } from 'vue'
import { emergencyStopAll } from '../api/simulation'

const props = defineProps({
  // Allow the parent to hide the button on screens where it would
  // not make sense (e.g. the very first landing page).
  visible: { type: Boolean, default: true },
})

const emit = defineEmits(['stopped'])

const working = ref(false)

async function onClick() {
  // Use a native confirm rather than a fancy modal so even a half-broken
  // page can fire the panic button.
  const ok = window.confirm(
    'Stop ALL running simulations now?\n\n' +
      'This force-kills every simulation subprocess on this machine. ' +
      'In-flight LLM calls will be cancelled. Use this if a run is ' +
      'leaking credits or if you cannot reach the normal Stop button.'
  )
  if (!ok) return

  working.value = true
  try {
    const res = await emergencyStopAll()
    const data = res?.data?.data || {}
    const msg = data.message || 'Sent emergency stop.'
    window.alert(msg)
    emit('stopped', data)
  } catch (e) {
    window.alert('Emergency stop request failed: ' + (e?.message || e))
  } finally {
    working.value = false
  }
}
</script>

<style scoped>
.emergency-stop-btn {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;

  display: flex;
  align-items: center;
  gap: 10px;

  padding: 12px 18px;
  border: 2px solid #b30000;
  border-radius: 999px;
  background: #ffffff;
  color: #b30000;

  font-family: inherit;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;

  cursor: pointer;
  box-shadow: 0 6px 20px rgba(179, 0, 0, 0.25);
  transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;
}

.emergency-stop-btn:hover {
  background: #b30000;
  color: #ffffff;
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(179, 0, 0, 0.35);
}

.emergency-stop-btn:hover .dot {
  background: #ffffff;
}

.emergency-stop-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.emergency-stop-btn.working {
  background: #b30000;
  color: #ffffff;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #b30000;
  box-shadow: 0 0 0 4px rgba(179, 0, 0, 0.15);
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.3); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 200ms ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
