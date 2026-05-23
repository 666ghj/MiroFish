<template>
  <div class="panel">
    <h3>Stakeholder typology (PCA)</h3>
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
const chart = ref(null); const loading = ref(true); const error = ref(null)
const width = 640, height = 480

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    // service interceptor returns the envelope {success, data, error} directly
    const r = await getResults(props.simId, 'diversity')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate)
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}

function draw(agg) {
  // The /results endpoint returns aggregate.json which contains clusters + agent_ids.
  // For v1 use clusters only, distributing them across a notional 2D layout per cluster.
  const clusters = agg.clusters || []
  if (!clusters.length) return
  const svg = d3.select(chart.value); svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 30, left: 30 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const points = []
  clusters.forEach((c, i) => {
    (c.agent_ids || []).forEach((aid, k) => {
      const angle = (i / clusters.length) * 2 * Math.PI
      const radius = (k % 5 + 1) * 0.15 + 0.2
      points.push({ x: 0.5 + Math.cos(angle) * radius, y: 0.5 + Math.sin(angle) * radius,
                    cluster: c.cluster_id, agent_id: aid })
    })
  })
  const x = d3.scaleLinear().domain([0, 1]).range([0, w])
  const y = d3.scaleLinear().domain([0, 1]).range([h, 0])
  const color = d3.scaleOrdinal(d3.schemeCategory10)
  g.selectAll('circle').data(points).enter().append('circle')
    .attr('cx', d => x(d.x)).attr('cy', d => y(d.y)).attr('r', 5)
    .attr('fill', d => color(d.cluster)).attr('opacity', .7)
    .append('title').text(d => `agent ${d.agent_id} · cluster ${d.cluster}`)
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
