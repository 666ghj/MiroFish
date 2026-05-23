<template>
  <div class="panel">
    <h3>Longitudinal Δ (T0 → T1)</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <svg v-else ref="chart" :width="width" :height="height"></svg>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import { getResults } from '../../api/interview'

const props = defineProps({ simId: String, status: Object })
const chart = ref(null)
const loading = ref(true)
const error = ref(null)
const width = 640
const height = 360

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    // service interceptor returns the envelope {success, data, error} directly
    const r = await getResults(props.simId, 'longitudinal')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate)
  } catch (e) { error.value = String(e) }
  finally { loading.value = false }
}

function draw(agg) {
  const items = Object.entries(agg.per_item || {})
  if (items.length === 0) return
  const svg = d3.select(chart.value)
  svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 60, left: 80 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const x = d3.scaleBand().domain(items.map(([k]) => k)).range([0, w]).padding(0.1)
  const y = d3.scaleLinear().domain([-4, 4]).range([h, 0])
  const color = d3.scaleDiverging(d3.interpolateRdBu).domain([-4, 0, 4])
  g.selectAll('rect').data(items).enter().append('rect')
    .attr('x', d => x(d[0]))
    .attr('y', d => y(Math.max(0, d[1].mean_delta || 0)))
    .attr('width', x.bandwidth())
    .attr('height', d => Math.abs(y(d[1].mean_delta || 0) - y(0)))
    .attr('fill', d => color(d[1].mean_delta || 0))
  g.append('g').attr('transform', `translate(0,${y(0)})`)
    .call(d3.axisBottom(x)).selectAll('text')
    .attr('transform', 'rotate(-40)').attr('text-anchor', 'end')
  g.append('g').call(d3.axisLeft(y))
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
