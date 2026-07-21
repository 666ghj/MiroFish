<template>
  <div v-if="graphData || projectData" class="graph-ctx-bar">
    <!-- Grupo: identidade Zep -->
    <div class="ctx-group">
      <span class="ctx-engine-badge">ZEP</span>
      <span class="ctx-metric">
        <span class="ctx-num">{{ nodeCount }}</span>
        <span class="ctx-unit">nodes</span>
      </span>
      <span class="ctx-dot" />
      <span class="ctx-metric">
        <span class="ctx-num">{{ edgeCount }}</span>
        <span class="ctx-unit">edges</span>
      </span>
    </div>

    <div class="ctx-sep" />

    <!-- Grupo: entity types da ontologia -->
    <div class="ctx-group ctx-types" v-if="entityTypeList.length">
      <span class="ctx-types-label">{{ $t('graph.ctxTypes') }}</span>
      <span
        v-for="type in entityTypeList.slice(0, 5)"
        :key="type"
        class="ctx-type-tag"
      >{{ type }}</span>
      <span v-if="entityTypeList.length > 5" class="ctx-type-more">
        +{{ entityTypeList.length - 5 }}
      </span>
    </div>

    <div class="ctx-spacer" />

    <!-- Grupo: estado da ingestão -->
    <div class="ctx-group">
      <span class="ctx-state-dot" :class="stateClass" />
      <span class="ctx-state-label">{{ stateLabel }}</span>
      <span v-if="graphId" class="ctx-graph-id">{{ shortGraphId }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  graphData:   { type: Object, default: null },
  projectData: { type: Object, default: null },
  /** Fase atual: -1 upload, 0 ontology, 1 building, 2 complete, 3+ simulation */
  currentPhase: { type: Number, default: -1 },
})

const nodeCount = computed(() => {
  if (!props.graphData) return '—'
  return props.graphData.node_count ?? props.graphData.nodes?.length ?? '—'
})

const edgeCount = computed(() => {
  if (!props.graphData) return '—'
  return props.graphData.edge_count ?? props.graphData.edges?.length ?? '—'
})

/** Entity types: tenta ontologia primeiro, depois infere dos nodes */
const entityTypeList = computed(() => {
  if (props.projectData?.ontology?.entity_types) {
    return props.projectData.ontology.entity_types.map((e) =>
      typeof e === 'string' ? e : e.name || e.type || String(e)
    )
  }
  if (props.graphData?.nodes?.length) {
    const types = new Set()
    props.graphData.nodes.forEach((n) => {
      if (n.labels) n.labels.forEach((l) => { if (l !== 'Entity') types.add(l) })
    })
    return Array.from(types)
  }
  return []
})

const graphId = computed(() => props.projectData?.graph_id || props.graphData?.graph_id || null)

const shortGraphId = computed(() => {
  if (!graphId.value) return ''
  const id = String(graphId.value)
  return id.length > 18 ? id.slice(0, 8) + '…' + id.slice(-6) : id
})

const stateClass = computed(() => {
  if (props.currentPhase >= 2) return 'state--ready'
  if (props.currentPhase === 1) return 'state--building'
  if (props.currentPhase === 0) return 'state--ontology'
  return 'state--idle'
})

const { t } = useI18n()

const stateLabel = computed(() => {
  if (props.currentPhase >= 3) return t('graph.ctxStateMemory')
  if (props.currentPhase === 2) return t('graph.ctxStateReady')
  if (props.currentPhase === 1) return t('graph.ctxStateBuilding')
  if (props.currentPhase === 0) return t('graph.ctxStateOntology')
  return t('graph.ctxStatePending')
})
</script>

<style scoped>
.graph-ctx-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 34px;
  padding: 0 14px;
  background: #FAFAFA;
  border-bottom: 1px solid #EFEFEF;
  flex-shrink: 0;
  overflow: hidden;
}

/* Grupos */
.ctx-group {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}

.ctx-sep {
  width: 1px;
  height: 14px;
  background: #E0E0E0;
  flex-shrink: 0;
}

.ctx-spacer { flex: 1; }

/* Badge ZEP */
.ctx-engine-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 1.5px;
  color: #fff;
  background: #1A1A1A;
  padding: 2px 6px;
  border-radius: 3px;
}

/* Métricas */
.ctx-metric { display: flex; align-items: baseline; gap: 2px; }
.ctx-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: #1A1A1A;
}
.ctx-unit {
  font-size: 10px;
  color: #999;
  font-weight: 500;
}
.ctx-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #CCC;
}

/* Entity types */
.ctx-types { gap: 5px; }
.ctx-types-label {
  font-size: 10px;
  color: #AAAAAA;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  margin-right: 2px;
}
.ctx-type-tag {
  font-size: 10.5px;
  font-weight: 600;
  color: #444;
  background: #EDEDED;
  padding: 1px 7px;
  border-radius: 3px;
}
.ctx-type-more {
  font-size: 10px;
  color: #AAA;
  font-weight: 500;
}

/* Estado */
.ctx-state-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ctx-state-label {
  font-size: 11px;
  font-weight: 600;
  color: #666;
}
.ctx-graph-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #BDBDBD;
  letter-spacing: 0.3px;
}

/* State variants */
.state--ready    { background: #4CAF50; }
.state--building { background: #FF9800; animation: pulse-build 1.2s infinite; }
.state--ontology { background: #2196F3; }
.state--idle     { background: #CCC; }

@keyframes pulse-build {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}
</style>
