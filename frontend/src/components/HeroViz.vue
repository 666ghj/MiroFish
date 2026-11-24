<template>
  <div class="hviz" ref="container">
    <svg ref="svgRef" class="hviz-svg"></svg>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  count: { type: Number, default: 20 },
})

const container = ref(null)
const svgRef    = ref(null)

let simulation   = null
let pulseTimer   = null
let verdictTimer = null
let svgSel       = null
let linkGroup    = null
let nodeGroup    = null
let linkSel      = null
let nodeSel      = null
let W = 0, H = 0

// Cap for performance — D3 force gets heavy beyond this
const MAX_NODES = 120

const TYPES = [
  'VP Sales', 'Founder', 'CFO', 'SDR Mgr', 'Head of Growth',
  'CRO', 'Account Exec', 'Ops Lead', 'Mktg VP', 'BizDev',
  'Product', 'CEO', 'RevOps', 'CMO', 'Co-Founder',
  'Dir Sales', 'Advisor', 'Sales Ops', 'Growth', 'CTO',
  'Head of Sales', 'GTM Lead', 'Sales Dev', 'BD Mgr', 'Mktg Mgr',
]

const VERDICT = ['interested', 'interested', 'interested', 'neutral', 'neutral', 'objection']
const COLOR   = { interested: '#4ade80', neutral: '#f59e0b', objection: '#f87171' }

function verdictFor(i) {
  const h = ((i * 2654435761) >>> 0) % 6
  return VERDICT[h]
}

function nodeRadius(total) {
  if (total <= 20)  return 14
  if (total <= 40)  return 11
  if (total <= 70)  return 9
  if (total <= 100) return 7
  return 6
}

function showLabels(total) { return total <= 35 }

function linkDensity(n) {
  if (n <= 20)  return 1.5
  if (n <= 50)  return 1.0
  if (n <= 100) return 0.6
  return 0.4
}

function makeLinks(nodes) {
  const n = nodes.length
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

// Mutable node array — shared across updates
let nodes = []

function buildNodeData(count) {
  const n = Math.min(count, MAX_NODES)
  return Array.from({ length: n }, (_, i) => {
    const existing = nodes[i]
    return existing
      ? { ...existing, verdict: existing.verdict, r: nodeRadius(n) }
      : {
          id: i,
          label: TYPES[i % TYPES.length],
          verdict: verdictFor(i),
          r: nodeRadius(n),
          x: W / 2 + (Math.random() - 0.5) * (W * 0.6),
          y: H / 2 + (Math.random() - 0.5) * (H * 0.6),
        }
  })
}

function rebuildGraph(count) {
  if (!svgSel || !simulation) return

  const n = Math.min(count, MAX_NODES)
  nodes = buildNodeData(n)
  const links = makeLinks(nodes)
  const showLbl = showLabels(n)
  const r = nodeRadius(n)

  // Update simulation
  simulation.nodes(nodes)
  // Charge scales so nodes stay spread across the full box at any count
  const charge = -Math.max(30, 180 / Math.sqrt(n) * (n > 60 ? 1.8 : 1))
  simulation.force('link', d3.forceLink(links).id(d => d.id).distance(r * 4.5).strength(0.25))
  simulation.force('charge', d3.forceManyBody().strength(charge).distanceMax(W * 0.6))
  simulation.force('collision', d3.forceCollide(r + 5))
  simulation.force('center', d3.forceCenter(W / 2, H / 2).strength(0.04))
  simulation.alpha(0.5).restart()

  // Links
  linkSel = linkGroup.selectAll('line')
    .data(links)
    .join('line')
    .style('stroke', '#262626')
    .style('stroke-width', 1)
    .style('opacity', 0.6)

  // Nodes
  const entered = nodeGroup.selectAll('g.node')
    .data(nodes, d => d.id)
    .join(
      enter => {
        const g = enter.append('g').attr('class', 'node')
        g.append('circle').attr('class', 'node-ring')
        g.append('circle').attr('class', 'node-core')
        g.append('text').attr('class', 'node-label')
        // Fade in
        g.style('opacity', 0).transition().duration(300).style('opacity', 1)
        return g
      },
      update => update,
      exit => exit.transition().duration(200).style('opacity', 0).remove()
    )

  // Update ring
  entered.select('.node-ring')
    .attr('r', d => d.r + (n > 60 ? 3 : 6))
    .style('fill', 'none')
    .style('stroke', d => COLOR[d.verdict])
    .style('stroke-width', 1)
    .style('opacity', 0.18)

  // Update core
  entered.select('.node-core')
    .attr('r', d => d.r)
    .style('fill', '#101010')
    .style('stroke', d => COLOR[d.verdict])
    .style('stroke-width', 1.5)

  // Update label
  entered.select('.node-label')
    .text(d => showLbl ? d.label : '')
    .attr('text-anchor', 'middle')
    .attr('dy', d => d.r + (n > 60 ? 0 : 13))
    .style('fill', '#737373')
    .style('font-family', "'Inter', sans-serif")
    .style('font-size', '9px')
    .style('font-weight', '600')
    .style('pointer-events', 'none')
    .style('opacity', showLbl ? 1 : 0)

  nodeSel = nodeGroup.selectAll('g.node')
}

onMounted(() => {
  W = container.value?.offsetWidth  || 400
  H = container.value?.offsetHeight || 360

  svgSel = d3.select(svgRef.value).attr('width', W).attr('height', H)

  // Defs
  const defs = svgSel.append('defs')
  const filter = defs.append('filter').attr('id', 'hviz-glow2')
  filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur')
  const merge = filter.append('feMerge')
  merge.append('feMergeNode').attr('in', 'coloredBlur')
  merge.append('feMergeNode').attr('in', 'SourceGraphic')

  // Vignette
  const rad = defs.append('radialGradient').attr('id', 'hviz-fade2')
    .attr('cx', '50%').attr('cy', '50%').attr('r', '50%')
  rad.append('stop').attr('offset', '55%').attr('stop-color', 'transparent')
  rad.append('stop').attr('offset', '100%').attr('stop-color', '#000000')
  svgSel.append('rect').attr('width', W).attr('height', H)
    .attr('fill', 'url(#hviz-fade2)').attr('pointer-events', 'none')
    .style('position', 'relative').style('z-index', 10)

  // Groups
  linkGroup = svgSel.append('g').attr('class', 'links')
  nodeGroup = svgSel.append('g').attr('class', 'nodes')

  // Build initial simulation (empty, will be populated by rebuildGraph)
  simulation = d3.forceSimulation([])
    .force('center', d3.forceCenter(W / 2, H / 2).strength(0.05))
    .alphaDecay(0.003)
    .velocityDecay(0.55)
    .on('tick', () => {
      if (!nodes.length) return
      // Soft boundary — proportional velocity nudge instead of hard clamp
      // so nodes use the full space and never stick to edges
      nodes.forEach(d => {
        const pad = (d.r || 10) + 6
        const k = 0.12
        if (d.x < pad)     d.vx += k * (pad - d.x)
        if (d.x > W - pad) d.vx -= k * (d.x - W + pad)
        if (d.y < pad)     d.vy += k * (pad - d.y)
        if (d.y > H - pad) d.vy -= k * (d.y - H + pad)
        // Absolute fallback — keep within SVG
        d.x = Math.max(0, Math.min(W, d.x || W / 2))
        d.y = Math.max(0, Math.min(H, d.y || H / 2))
      })
      linkSel?.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
               .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      nodeSel?.attr('transform', d => `translate(${d.x},${d.y})`)
    })

  // Initial build
  rebuildGraph(props.count)

  // Pulse animation
  function firePulse() {
    if (!nodes.length) { pulseTimer = setTimeout(firePulse, 1000); return }
    const allLinks = linkGroup.selectAll('line').data()
    if (!allLinks.length) { pulseTimer = setTimeout(firePulse, 800); return }
    const link = allLinks[Math.floor(Math.random() * allLinks.length)]
    if (!link?.source || !link?.target) { pulseTimer = setTimeout(firePulse, 600); return }
    const src = link.source, tgt = link.target
    const col = COLOR[tgt.verdict] || '#4ade80'

    const ball = svgSel.append('circle')
      .attr('r', 3.5).attr('cx', src.x).attr('cy', src.y)
      .style('fill', col).style('opacity', 0.9)
      .style('filter', 'url(#hviz-glow2)')

    ball.transition()
      .duration(700 + Math.random() * 400)
      .ease(d3.easeQuadInOut)
      .attr('cx', tgt.x).attr('cy', tgt.y)
      .style('opacity', 0)
      .on('end', () => {
        ball.remove()
        nodeSel?.filter(d => d.id === tgt.id).select('.node-core')
          .transition().duration(150).style('stroke-width', 3).style('stroke', col)
          .transition().duration(500).style('stroke-width', 1.5).style('stroke', COLOR[tgt.verdict])
        nodeSel?.filter(d => d.id === tgt.id).select('.node-ring')
          .transition().duration(150).style('opacity', 0.45)
          .transition().duration(600).style('opacity', 0.18)
      })

    pulseTimer = setTimeout(firePulse, 400 + Math.random() * 600)
  }
  pulseTimer = setTimeout(firePulse, 1000)

  // Verdict shift
  function shiftVerdict() {
    if (!nodes.length) { verdictTimer = setTimeout(shiftVerdict, 2000); return }
    const all = ['interested', 'interested', 'neutral', 'objection']
    const node = nodes[Math.floor(Math.random() * nodes.length)]
    node.verdict = all[Math.floor(Math.random() * all.length)]
    const col = COLOR[node.verdict]
    nodeSel?.filter(d => d.id === node.id).select('.node-core')
      .transition().duration(500).style('stroke', col)
    nodeSel?.filter(d => d.id === node.id).select('.node-ring')
      .transition().duration(500).style('stroke', col)
    verdictTimer = setTimeout(shiftVerdict, 1200 + Math.random() * 1800)
  }
  verdictTimer = setTimeout(shiftVerdict, 2000)
})

// React to count changes with a small debounce
let rebuildTimeout = null
watch(() => props.count, (newCount) => {
  if (rebuildTimeout) clearTimeout(rebuildTimeout)
  rebuildTimeout = setTimeout(() => rebuildGraph(newCount), 80)
})

onUnmounted(() => {
  if (simulation)    simulation.stop()
  if (pulseTimer)    clearTimeout(pulseTimer)
  if (verdictTimer)  clearTimeout(verdictTimer)
  if (rebuildTimeout) clearTimeout(rebuildTimeout)
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
</style>
