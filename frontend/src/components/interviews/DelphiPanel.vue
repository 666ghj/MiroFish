<template>
  <div class="panel">
    <h3>Delphi convergence (R1→R3)</h3>
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
const width = 640, height = 420

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    // service interceptor returns the envelope {success, data, error} directly
    const r = await getResults(props.simId, 'delphi')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate)
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}

function draw(agg) {
  const themes = agg.themes || []
  if (!themes.length) return
  const svg = d3.select(chart.value); svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 80, left: 60 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const x = d3.scaleBand().domain(themes.map(t => t.theme_id)).range([0, w]).padding(0.15)
  const y = d3.scaleLinear().domain([0, agg.n_r1 || 1]).range([h, 0])
  const bars = themes.map((t) => ({
    theme: t.theme_id, label: t.label,
    nr1: agg.n_r1, nr2: agg.n_r2, nr3: agg.n_r3,
  }))
  g.selectAll('rect').data(bars).enter().append('rect')
    .attr('x', d => x(d.theme)).attr('y', d => y(d.nr3))
    .attr('width', x.bandwidth()).attr('height', d => h - y(d.nr3))
    .attr('fill', d3.schemeCategory10[2])
  g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x))
    .selectAll('text').attr('transform', 'rotate(-30)').attr('text-anchor', 'end')
  g.append('g').call(d3.axisLeft(y))
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
