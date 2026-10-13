<template>
  <div class="demo-graph">
    <div class="graph-viewport" tabindex="0" aria-label="Saved knowledge graph; scroll horizontally on small screens">
    <div class="graph-canvas" aria-label="Saved LoopLunch knowledge graph">
      <div class="graph-caption">{{ graph.nodes.length }} entities · {{ graph.edges.length }} saved relationships</div>
      <svg viewBox="0 0 600 410" aria-hidden="true" preserveAspectRatio="none">
        <line v-for="edge in connections" :key="edge.key"
          :x1="edge.from.x" :y1="edge.from.y" :x2="edge.to.x" :y2="edge.to.y"
          :class="{ connected: edge.source === selectedId || edge.target === selectedId }" />
      </svg>
      <button v-for="node in positionedNodes" :key="node.id" type="button"
        class="graph-node" :class="{ selected: node.id === selectedId, organization: organizations.has(node.type) }"
        :style="{ left: `${node.x / 6}%`, top: `${node.y / 4.1}%` }"
        :aria-pressed="node.id === selectedId" @click="selectedId = node.id">
        <span class="node-dot" aria-hidden="true"></span><span>{{ node.name }}</span>
      </button>
      <span class="graph-hint">Select an entity to explore its connections</span>
    </div>
    </div>
    <div class="graph-details" aria-live="polite">
      <span class="eyebrow">{{ friendlyType(selected.type) }}</span>
      <h3>{{ selected.name }}</h3>
      <p>{{ selected.summary.split('\n')[0] }}</p>
      <details v-if="selected.summary.includes('\n')" class="memory-details">
        <summary>More saved graph memory</summary>
        <p class="memory-text">{{ selected.summary.split('\n').slice(1).join('\n') }}</p>
      </details>
      <h4>{{ relatedEdges.length }} recorded relationships</h4>
      <div class="relationships">
        <details v-for="edge in relatedEdges" :key="edge.id">
          <summary>{{ nameFor(edge.source) }} <span aria-hidden="true">→</span> {{ nameFor(edge.target) }}<small>{{ friendlyType(edge.label) }}</small></summary>
          <p>{{ edge.fact }}</p>
        </details>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ graph: { type: Object, required: true } })
const selectedId = ref(props.graph.nodes.find(node => node.name === 'Maya Tan')?.id || props.graph.nodes[0].id)
const organizations = new Set(['HostEmployer', 'LunchVenture', 'KitchenSupplier', 'Organization'])
const positions = {
  'LoopLunch': [300, 200], 'Maya Tan': [185, 90], 'Daniel Koh': [420, 90],
  'Aisha Lim': [105, 210], 'HarborWorks': [175, 330], 'Ravi Menon': [495, 205],
  'FreshBatch Kitchen': [425, 330], 'Singapore': [70, 90],
  'Reddit': [70, 335], 'Singapore dollar': [535, 90],
}
// Fixed positions keep this saved example stable as visitors move between stages.
const positionedNodes = computed(() => props.graph.nodes.map((node, index) => {
  const [x, y] = positions[node.name] || [100 + index * 40, 200]
  return { ...node, x, y }
}))
const nodeMap = computed(() => new Map(positionedNodes.value.map(node => [node.id, node])))
const selected = computed(() => nodeMap.value.get(selectedId.value))
const relatedEdges = computed(() => props.graph.edges.filter(edge => edge.source === selectedId.value || edge.target === selectedId.value))
const connections = computed(() => {
  const pairs = new Map()
  for (const edge of props.graph.edges) {
    if (edge.source === edge.target) continue
    const key = [edge.source, edge.target].sort().join(':')
    if (!pairs.has(key) && nodeMap.value.has(edge.source) && nodeMap.value.has(edge.target)) {
      pairs.set(key, { ...edge, key, from: nodeMap.value.get(edge.source), to: nodeMap.value.get(edge.target) })
    }
  }
  return [...pairs.values()]
})
const nameFor = id => nodeMap.value.get(id)?.name || 'Entity'
const friendlyType = value => value.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase()
</script>

<style scoped>
.demo-graph { border: 1px solid #e3e3df; background: white; }
.graph-viewport { overflow-x: auto; }
.graph-viewport:focus-visible { outline: 2px solid #d93a00; outline-offset: -2px; }
.graph-canvas { min-width: 560px; height: 410px; position: relative; background: radial-gradient(#d6d6ce .8px, transparent .8px) 0 0 / 18px 18px, #fafaf7; overflow: hidden; }
.graph-caption, .graph-hint { position: absolute; left: 20px; font-size: 11px; color: #666; z-index: 1; }
.graph-caption { top: 18px; } .graph-hint { bottom: 14px; }
svg { position: absolute; inset: 0; width: 100%; height: 100%; }
line { stroke: #d4d4ce; stroke-width: 1; } line.connected { stroke: #e7683e; stroke-width: 1.8; }
.graph-node { position: absolute; transform: translate(-50%, -13px); width: 100px; border: 0; background: none; color: #555; cursor: pointer; font-size: 10px; line-height: 1.4; display: flex; align-items: center; flex-direction: column; gap: 8px; }
.graph-node > span:last-child { background: #fafaf7e8; padding: 2px 4px; }
.node-dot { width: 25px; height: 25px; border-radius: 50%; background: #fff; border: 2px solid #5d6b65; box-shadow: 0 0 0 5px #fafaf7; }
.organization .node-dot { border-radius: 6px; background: #dce5dd; }
.selected .node-dot { background: #f4511e; border-color: #f4511e; box-shadow: 0 0 0 6px #fce2d6; }
.selected { color: #b3310a; font-weight: 700; }
.graph-node:focus-visible { outline: 2px solid #d93a00; outline-offset: 5px; }
.graph-details { padding: 26px; border-top: 1px solid #e3e3df; }
.eyebrow { text-transform: uppercase; font-size: 10px; letter-spacing: .12em; color: #b83c17; }
h3 { font-size: 24px; margin: 8px 0 14px; } p { font-family: system-ui, sans-serif; font-size: 14px; line-height: 1.7; color: #555; }
h4 { font-size: 12px; margin: 24px 0 12px; }
.relationships { max-height: 260px; overflow-y: auto; }
details { border-top: 1px solid #eee; padding: 12px 0; }
summary { cursor: pointer; font-size: 12px; line-height: 1.6; }
small { display: block; color: #777; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; margin-left: 14px; }
details p { margin: 12px 0 0; } .memory-details { margin-top: 16px; } .memory-text { white-space: pre-line; }
@media (max-width: 600px) { .graph-details { padding: 20px; } }
</style>
