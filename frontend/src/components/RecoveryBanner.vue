<template>
  <div v-if="error || (state.inFlight && state.lastError)" class="recovery-banner" role="alert" aria-live="polite">
    <div>
      <strong>{{ $t('recovery.attention') }}</strong>
      <p>{{ error || state.lastError }}</p>
      <small v-if="hint">{{ hint }}</small>
      <small v-if="state.scheduled || state.inFlight">{{ state.attempt ? $t('recovery.retrying', { attempt: state.attempt, max: state.max }) : $t('recovery.working') }}</small>
    </div>
    <button v-if="state.manual" type="button" :disabled="busy" @click="controller.manualRetry()">{{ busy ? $t('recovery.working') : (label || $t('recovery.retry')) }}</button>
  </div>
</template>
<script setup>
import { shallowRef, watch, onUnmounted } from 'vue'
import { createRetryController } from '../utils/autoRetry'

const props = defineProps({
  error: String, hint: String, label: String, busy: Boolean,
  retryKey: { type: String, required: true },
  autoRetry: { type: Boolean, default: true },
  completed: Boolean,
})
const emit = defineEmits(['retry'])
let storage
try { storage = window.sessionStorage } catch {}
const state = shallowRef({})
const controller = createRetryController({
  storage,
  retry: metadata => emit('retry', metadata),
  onChange: value => { state.value = value },
})
watch(() => [props.retryKey, props.error, props.busy, props.autoRetry, props.completed], () => {
  controller.update({ retryKey: props.retryKey, error: props.error, busy: props.busy,
    autoRetry: props.autoRetry, completed: props.completed })
}, { immediate: true, flush: 'sync' })
onUnmounted(() => controller.dispose())
</script>
<style scoped>
.recovery-banner { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-shrink: 0; margin: 12px; padding: 14px 16px; border: 1px solid #e8b6a8; border-radius: 8px; color: #873921; background: #fff5ef; font-size: 13px; }
p { margin: 5px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
small { display: block; line-height: 1.5; }
button { flex-shrink: 0; border: 1px solid #873921; border-radius: 5px; background: white; color: inherit; padding: 9px 12px; cursor: pointer; }
button:disabled { opacity: .6; cursor: wait; }
</style>
