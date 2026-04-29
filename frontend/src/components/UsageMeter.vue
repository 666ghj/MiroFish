<!--
  UsageMeter

  Always-visible cost meter. Two modes:

  * If a `simulationId` prop is given, polls that simulation's
    per-run usage snapshot. Shows cap + over-cap warning when set.
  * Otherwise polls the host-wide global snapshot, useful for the
    home / history pages where no specific simulation is in focus.

  The meter is purely observational — it does not abort on its own;
  the backend's UsageTracker has its own cap-event the simulation
  runner listens to.
-->
<template>
  <div class="usage-meter" :class="{ 'over-cap': snapshot?.over_cap }">
    <div class="row">
      <span class="label">{{ headline }}</span>
      <span class="cost" :title="$t('usage.totalCostTooltip')">
        ${{ formattedCost }}
      </span>
    </div>
    <div class="row sub">
      <span>
        {{ snapshot?.requests || 0 }} {{ $t('usage.requests') }}
      </span>
      <span>
        {{ formattedTokens }} {{ $t('usage.tokens') }}
      </span>
      <span v-if="snapshot?.cap_usd">
        {{ $t('usage.capLabel') }}: ${{ snapshot.cap_usd.toFixed(2) }}
      </span>
    </div>
    <div v-if="snapshot?.over_cap" class="warning">
      ⚠ {{ $t('usage.overCap') }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { getSimulationUsage, getGlobalUsage } from '../api/simulation'

const props = defineProps({
  // When set, show per-simulation usage and poll that endpoint.
  simulationId: { type: String, default: null },
  // Polling interval in milliseconds. Default 5s — fast enough to
  // feel live, slow enough not to stress the backend during a real run.
  intervalMs: { type: Number, default: 5000 },
})

const snapshot = ref(null)
let timer = null

async function fetchOnce() {
  try {
    let res
    if (props.simulationId) {
      res = await getSimulationUsage(props.simulationId)
      snapshot.value = res?.data?.data || null
    } else {
      res = await getGlobalUsage()
      snapshot.value = res?.data?.data?.global || null
    }
  } catch (e) {
    // Silent — the meter must never spam errors at the user; the
    // worst case is the bar just stops updating.
    snapshot.value = snapshot.value || null
  }
}

function startPolling() {
  stopPolling()
  fetchOnce()
  timer = setInterval(fetchOnce, props.intervalMs)
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(startPolling)
onBeforeUnmount(stopPolling)

watch(
  () => [props.simulationId, props.intervalMs],
  () => {
    snapshot.value = null
    startPolling()
  }
)

const headline = (() => {
  return props.simulationId
    ? `${props.simulationId.slice(0, 12)}…`
    : 'TOTAL'
})()

const formattedCost = (() => {
  const v = snapshot.value?.cost_usd
  return typeof v === 'number' ? v.toFixed(4) : '0.0000'
})

const formattedTokens = (() => {
  const v = snapshot.value?.total_tokens || 0
  if (v < 1000) return v
  if (v < 1_000_000) return (v / 1000).toFixed(1) + 'K'
  return (v / 1_000_000).toFixed(2) + 'M'
})
</script>

<style scoped>
.usage-meter {
  position: fixed;
  bottom: 24px;
  /* Sit to the LEFT of the EmergencyStopButton (right: 24px) so they
     do not overlap. EmergencyStopButton width is ~180px + padding. */
  right: 240px;
  z-index: 9998;

  min-width: 240px;
  padding: 10px 16px;
  border: 2px solid #000000;
  border-radius: 14px;
  background: #ffffff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}

.usage-meter.over-cap {
  border-color: #b30000;
  background: #fff5f5;
}

.row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}

.row.sub {
  margin-top: 4px;
  font-size: 10px;
  color: #555;
}

.label {
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.cost {
  font-weight: 700;
  font-size: 16px;
}

.warning {
  margin-top: 6px;
  font-weight: 700;
  color: #b30000;
  font-size: 11px;
}
</style>
