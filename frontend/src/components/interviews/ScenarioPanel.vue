<template>
  <div class="panel">
    <h3>Scenarios: desirability × plausibility</h3>
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
const width = 520, height = 520

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    // service interceptor returns the envelope {success, data, error} directly
    const r = await getResults(props.simId, 'scenario')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate.polarity || {})
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}

function draw(polarity) {
  const pts = Object.entries(polarity)
    .filter(([, v]) => v && v.n > 0)
    .map(([sid, v]) => ({
      sid, x: v.mean_plausibility, y: v.mean_desirability,
      n: v.n, sdx: v.sd_plausibility, sdy: v.sd_desirability,
    }))
  if (!pts.length) return
  const svg = d3.select(chart.value); svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 40, left: 40 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const x = d3.scaleLinear().domain([1, 7]).range([0, w])
  const y = d3.scaleLinear().domain([1, 7]).range([h, 0])
  g.append('line').attr('x1', 0).attr('x2', w).attr('y1', y(4)).attr('y2', y(4)).attr('stroke', '#ccc')
  g.append('line').attr('x1', x(4)).attr('x2', x(4)).attr('y1', 0).attr('y2', h).attr('stroke', '#ccc')
  g.selectAll('circle').data(pts).enter().append('circle')
    .attr('cx', d => x(d.x)).attr('cy', d => y(d.y))
    .attr('r', d => 6 + Math.sqrt(d.n))
    .attr('fill', d3.schemeCategory10[1]).attr('opacity', .7)
  g.selectAll('text.lbl').data(pts).enter().append('text')
    .attr('class', 'lbl').attr('x', d => x(d.x) + 8).attr('y', d => y(d.y))
    .text(d => `${d.sid} (n=${d.n})`)
  g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x))
  g.append('g').call(d3.axisLeft(y))
  g.append('text').attr('x', w/2).attr('y', h+34).attr('text-anchor', 'middle').text('plausibility')
  g.append('text').attr('transform', `rotate(-90)`).attr('x', -h/2).attr('y', -28)
    .attr('text-anchor', 'middle').text('desirability')
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
