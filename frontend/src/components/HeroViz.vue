<template>
  <div class="hviz" ref="container" @mouseleave="hover = null">
    <svg ref="svgRef" class="hviz-svg" role="img" :aria-label="ariaLabel"></svg>

    <!-- Hover card: exact blend for one buyer -->
    <div
      v-if="interactive && hover"
      class="hviz-tip"
      :style="tipStyle"
      role="tooltip"
    >
      <div class="tip-head">
        <span class="tip-dot" :style="{ background: hover.color }"></span>
        <span class="tip-role">{{ hover.role }}</span>
      </div>
      <div class="tip-sub">{{ regionLabel(hover.region) }} · {{ hover.size }} employees</div>
      <div class="tip-bar" aria-hidden="true">
        <span
          v-for="a in ARCHETYPES"
          :key="a.id"
          v-show="hover.weights[a.id] > 0"
          :style="{ flexGrow: hover.weights[a.id], background: colors[a.id] }"
        ></span>
      </div>
      <div class="tip-rows">
        <div class="tip-row" v-for="a in ARCHETYPES" :key="a.id">
          <span class="tip-swatch" :style="{ background: colors[a.id] }"></span>
          <span class="tip-name">{{ a.label }}</span>
          <span class="tip-val">{{ hover.weights[a.id] }}%</span>
        </div>
      </div>
      <div class="tip-foot">Risk appetite {{ hover.risk }}/5 · {{ riskWord(hover.risk) }}</div>
    </div>

    <!-- Legend: names the three primaries (identity is never color alone) -->
    <div v-if="legend" class="hviz-legend">
      <span v-for="a in ARCHETYPES" :key="a.id" class="lg-item">
        <span class="lg-swatch" :style="{ background: colors[a.id] }"></span>{{ a.label }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import {
  ARCHETYPES, ARCHETYPE_IDS, defaultAudience, generateAudienceNodes,
  blendColor, regionLabel,
} from '../utils/audience.js'

const props = defineProps({
  count: { type: Number, default: 20 },
  /** Audience config from utils/audience.js; defaults to the balanced audience */
  audience: { type: Object, default: null },
  /** Show a hover card with the exact blend for each buyer */
  interactive: { type: Boolean, default: true },
  /** Show the three-archetype legend */
  legend: { type: Boolean, default: true },
})

const container = ref(null)
const svgRef = ref(null)
const hover = ref(null)

const aud = computed(() => props.audience || defaultAudience())
const colors = computed(() => ({ ...defaultAudience().colors, ...(aud.value.colors || {}) }))
const ariaLabel = computed(() =>
  `Network of ${Math.min(props.count, MAX_NODES)} simulated buyers, colored by their mix of decision maker, champion, and evaluator`
)

let simulation = null
let pulseTimer = null
let svgSel = null
let linkGroup = null
let nodeGroup = null
let linkSel = null
let nodeSel = null
let W = 0, H = 0

// Cap for performance - D3 force gets heavy beyond this
const MAX_NODES = 120

function nodeRadius(total) {
  if (total <= 20) return 13
  if (total <= 40) return 10
  if (total <= 70) return 8
  if (total <= 100) return 7
  return 6
}

function showLabels(total) { return total <= 35 }

function linkDensity(n) {
  if (n <= 20) return 1.5
  if (n <= 50) return 1.0
  if (n <= 100) return 0.6
  return 0.4
}

function makeLinks(n) {
  const target = Math.max(n, Math.floor(n * linkDensity(n)))
  const used = new Set()
  const links = []
  let attempts = 0
  while (links.length < target && attempts < target * 12) {
    attempts++
    const a = Math.floor(Math.random() * n)
    const b = Math.floor(Math.random() * n)
    const key = `${Math.min(a, b)}-${Math.max(a, b)}`
    if (a !== b && !used.has(key)) {
      used.add(key)
      links.push({ source: a, target: b })
    }
  }
  return links
}

function riskWord(r) {
  return ['Very risk-averse', 'Risk-averse', 'Moderate', 'Open to new tools', 'Early adopter'][r - 1] || ''
}

const tipStyle = computed(() => {
  if (!hover.value) return {}
  const x = hover.value.x, y = hover.value.y
  const left = x > W - 230 ? x - 222 : x + 18
  const top = Math.min(Math.max(8, y - 60), Math.max(8, H - 210))
  return { left: `${left}px`, top: `${top}px` }
})

// Mutable node array - positions survive audience changes
let nodes = []

function syncNodes(count) {
  const n = Math.min(count, MAX_NODES)
  const people = generateAudienceNodes(aud.value, n)
  const r = nodeRadius(n)
  nodes = people.map((p, i) => {
    const prev = nodes[i]
    return {
      ...p,
      color: blendColor(p.weights, colors.value),
      r,
      x: prev?.x ?? W / 2 + (Math.random() - 0.5) * (W * 0.6),
      y: prev?.y ?? H / 2 + (Math.random() - 0.5) * (H * 0.6),
      vx: prev?.vx ?? 0,
      vy: prev?.vy ?? 0,
    }
  })
}

const pie = d3.pie().sort(null).value(d => d.value).padAngle(0.07)

function ringData(d) {
  return pie(ARCHETYPE_IDS.map(id => ({ id, value: d.weights[id] || 0 })).filter(s => s.value > 0))
}

function paint(n) {
  const showLbl = showLabels(n)
  const ringOn = nodeRadius(n) >= 8
  const arc = d3.arc()

  const joined = nodeGroup.selectAll('g.node')
    .data(nodes, d => d.id)
    .join(
      enter => {
        const g = enter.append('g').attr('class', 'node')
        g.append('circle').attr('class', 'node-hit')
        g.append('g').attr('class', 'node-ring')
        g.append('circle').attr('class', 'node-core')
        g.append('text').attr('class', 'node-label')
        g.style('opacity', 0).transition().duration(300).style('opacity', 1)
        return g
      },
      update => update,
      exit => exit.transition().duration(200).style('opacity', 0).remove()
    )

  joined.select('.node-hit')
    .attr('r', d => d.r + 9)
    .style('fill', 'transparent')
    .style('cursor', props.interactive ? 'pointer' : 'default')
    .on('mouseenter', (_, d) => { if (props.interactive) hover.value = { ...d } })
    .on('mouseleave', () => { hover.value = null })

  // Composition ring: one arc per archetype, sized by the exact weight
  joined.select('.node-ring')
    .style('display', ringOn ? null : 'none')
    .style('pointer-events', 'none')
    .selectAll('path')
    .data(d => ringData(d).map(s => ({ ...s, r: d.r })))
    .join('path')
    .attr('d', s => arc.innerRadius(s.r + 3).outerRadius(s.r + 5.5)(s))
    .style('fill', s => colors.value[s.data.id])
    .style('opacity', 0.95)

  joined.select('.node-core')
    .attr('r', d => d.r)
    .style('pointer-events', 'none')
    .style('fill', d => d.color)
    .style('fill-opacity', 0.62)
    .style('stroke', d => d.color)
    .style('stroke-width', 1.75)

  joined.select('.node-label')
    .text(d => showLbl ? d.role : '')
    .attr('text-anchor', 'middle')
    .attr('dy', d => d.r + (ringOn ? 17 : 12))
    .style('fill', '#8a8a8a')
    .style('font-family', "'Inter', sans-serif")
    .style('font-size', '9px')
    .style('font-weight', '600')
    .style('pointer-events', 'none')

  nodeSel = nodeGroup.selectAll('g.node')
}

function rebuildGraph(count) {
  if (!svgSel || !simulation) return
  const n = Math.min(count, MAX_NODES)
  syncNodes(n)
  const links = makeLinks(nodes.length)
  const r = nodeRadius(n)

  simulation.nodes(nodes)
  // Small labelled networks need more room; larger ones keep the original spacing
  const charge = n <= 20 ? -320 / Math.sqrt(n) : -Math.max(30, 180 / Math.sqrt(n) * (n > 60 ? 1.8 : 1))
  simulation.force('link', d3.forceLink(links).id(d => d.id).distance(r * 4.8).strength(0.25))
  simulation.force('charge', d3.forceManyBody().strength(charge).distanceMax(W * 0.6))
  simulation.force('collision', d3.forceCollide(r + (showLabels(n) ? 14 : 8)))
  simulation.force('center', d3.forceCenter(W / 2, H / 2).strength(0.02))
  simulation.alpha(0.5).restart()

  linkSel = linkGroup.selectAll('line')
    .data(links)
    .join('line')
    .style('stroke', '#262626')
    .style('stroke-width', 1)
    .style('opacity', 0.6)

  paint(n)
}

/** Audience changed (mix, colors, regions...): recolor and reassign roles in place. */
function recolor() {
  if (!svgSel) return
  const n = nodes.length
  if (!n) return
  syncNodes(n)
  simulation.nodes(nodes)
  // links reference node objects; re-point them at the refreshed objects
  linkSel?.each(l => {
    l.source = nodes[l.source.index ?? l.source.id] || l.source
    l.target = nodes[l.target.index ?? l.target.id] || l.target
  })
  simulation.force('link')?.links(linkSel ? linkSel.data() : [])
  simulation.alpha(0.08).restart()
  paint(n)
  if (hover.value) {
    const h = nodes.find(d => d.id === hover.value.id)
    hover.value = h ? { ...h } : null
  }
}

onMounted(() => {
  W = container.value?.offsetWidth || 400
  H = container.value?.offsetHeight || 360

  svgSel = d3.select(svgRef.value).attr('width', W).attr('height', H)

  const defs = svgSel.append('defs')
  const filter = defs.append('filter').attr('id', 'hviz-glow2')
  filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur')
  const merge = filter.append('feMerge')
  merge.append('feMergeNode').attr('in', 'coloredBlur')
  merge.append('feMergeNode').attr('in', 'SourceGraphic')

  linkGroup = svgSel.append('g').attr('class', 'links')
  nodeGroup = svgSel.append('g').attr('class', 'nodes')

  simulation = d3.forceSimulation([])
    .force('center', d3.forceCenter(W / 2, H / 2).strength(0.05))
    .alphaDecay(0.003)
    .velocityDecay(0.55)
    .on('tick', () => {
      if (!nodes.length) return
      // Soft boundary - proportional velocity nudge so nodes use the full space
      nodes.forEach(d => {
        const pad = (d.r || 10) + 10
        const k = 0.12
        if (d.x < pad) d.vx += k * (pad - d.x)
        if (d.x > W - pad) d.vx -= k * (d.x - W + pad)
        if (d.y < pad) d.vy += k * (pad - d.y)
        if (d.y > H - pad - (props.legend ? 22 : 0)) d.vy -= k * (d.y - H + pad + (props.legend ? 22 : 0))
        d.x = Math.max(0, Math.min(W, d.x || W / 2))
        d.y = Math.max(0, Math.min(H, d.y || H / 2))
      })
      linkSel?.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      nodeSel?.attr('transform', d => `translate(${d.x},${d.y})`)
      if (hover.value) {
        const h = nodes.find(n => n.id === hover.value.id)
        if (h) hover.value = { ...h }
      }
    })

  rebuildGraph(props.count)

  // Pulses travel in the color of the buyer they start from
  function firePulse() {
    const allLinks = linkSel ? linkSel.data() : []
    if (!nodes.length || !allLinks.length) { pulseTimer = setTimeout(firePulse, 800); return }
    const link = allLinks[Math.floor(Math.random() * allLinks.length)]
    const src = link?.source, tgt = link?.target
    if (!src || !tgt || src.x == null) { pulseTimer = setTimeout(firePulse, 600); return }
    const col = src.color || '#3987e5'

    const ball = svgSel.append('circle')
      .attr('r', 3.2).attr('cx', src.x).attr('cy', src.y)
      .style('fill', col).style('opacity', 0.95)
      .style('filter', 'url(#hviz-glow2)')
      .style('pointer-events', 'none')

    ball.transition()
      .duration(700 + Math.random() * 400)
      .ease(d3.easeQuadInOut)
      .attr('cx', tgt.x).attr('cy', tgt.y)
      .style('opacity', 0)
      .on('end', () => {
        ball.remove()
        nodeSel?.filter(d => d.id === tgt.id).select('.node-core')
          .transition().duration(150).style('fill-opacity', 0.95).style('stroke-width', 2.5)
          .transition().duration(600).style('fill-opacity', 0.62).style('stroke-width', 1.75)
      })

    pulseTimer = setTimeout(firePulse, 400 + Math.random() * 600)
  }
  pulseTimer = setTimeout(firePulse, 1000)
})

let rebuildTimeout = null
watch(() => props.count, (newCount) => {
  if (rebuildTimeout) clearTimeout(rebuildTimeout)
  rebuildTimeout = setTimeout(() => rebuildGraph(newCount), 80)
})

let recolorTimeout = null
watch(aud, () => {
  if (recolorTimeout) clearTimeout(recolorTimeout)
  recolorTimeout = setTimeout(recolor, 40)
}, { deep: true })

onUnmounted(() => {
  if (simulation) simulation.stop()
  if (pulseTimer) clearTimeout(pulseTimer)
  if (rebuildTimeout) clearTimeout(rebuildTimeout)
  if (recolorTimeout) clearTimeout(recolorTimeout)
})
</script>

<style scoped>
.hviz {
  width: 100%;
  height: 100%;
  position: relative;
}
.hviz-svg {
  display: block;
  width: 100%;
  height: 100%;
}

.hviz-tip {
  position: absolute;
  z-index: 20;
  width: 210px;
  padding: 12px;
  border-radius: 10px;
  background: rgba(10, 10, 10, 0.96);
  border: 1px solid #2a2a2a;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.6);
  pointer-events: none;
  font-family: var(--font-sans);
}
.tip-head { display: flex; align-items: center; gap: 8px; }
.tip-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.tip-role { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.tip-sub { font-size: 11px; color: var(--text-tertiary); margin: 3px 0 10px 18px; }
.tip-bar {
  display: flex;
  gap: 2px;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 10px;
}
.tip-bar span { display: block; min-width: 2px; }
.tip-rows { display: flex; flex-direction: column; gap: 5px; }
.tip-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.tip-swatch { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.tip-name { color: var(--text-secondary); flex: 1; }
.tip-val { color: var(--text-primary); font-weight: 600; }
.tip-foot {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #1f1f1f;
  font-size: 11px;
  color: var(--text-tertiary);
}

.hviz-legend {
  position: absolute;
  left: 12px;
  bottom: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 11px;
  color: var(--text-secondary);
  pointer-events: none;
}
.lg-item { display: inline-flex; align-items: center; gap: 6px; }
.lg-swatch { width: 8px; height: 8px; border-radius: 2px; }
</style>
