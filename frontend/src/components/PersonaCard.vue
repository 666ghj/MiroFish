<template>
  <!-- COMPACT MODE: for Home.vue quick preview (3-persona teaser) -->
  <div v-if="compact" class="persona-card" :class="persona.reaction">
    <div class="persona-name">{{ persona.name }}</div>
    <div class="persona-role">{{ persona.title || persona.role }}</div>
    <div class="persona-company">{{ persona.company_type || persona.company }} · {{ persona.company_stage }}</div>
    <div class="persona-reaction-badge" :class="persona.reaction">
      {{ reactionLabel }}
    </div>
    <div class="persona-quote">"{{ persona.likely_response }}"</div>
  </div>

  <!-- FULL MODE: for GTMPersonasView grid -->
  <div v-else class="persona-card-full" :class="[persona.reaction, { dark }]">
    <!-- Header -->
    <div class="pcf-header">
      <div class="pcf-identity">
        <div class="pcf-name">{{ persona.name }}</div>
        <div class="pcf-title">{{ persona.title }}</div>
        <div class="pcf-company">
          {{ persona.company_type }} · {{ persona.company_stage }}<template v-if="persona.region"> · {{ regionName }}</template>
        </div>
      </div>
      <div class="pcf-badges">
        <span class="reaction-badge" :class="persona.reaction">{{ reactionLabel }}</span>
        <div class="skep-bar" :title="`Skepticism: ${persona.skepticism_level}/5`">
          <div
            v-for="i in 5"
            :key="i"
            class="skep-seg"
            :class="{ filled: i <= (persona.skepticism_level || 0) }"
          ></div>
        </div>
        <span class="skep-label">Skepticism {{ persona.skepticism_level }}/5</span>
      </div>
    </div>

    <!-- Role mix: exact blend of the three buying roles, shown as color and numbers -->
    <div class="pcf-mix" :title="mixTitle">
      <div class="pcf-mix-head">
        <span class="pcf-mix-dot" :style="{ background: blended }"></span>
        <span class="pcf-mix-text">
          <template v-for="(a, i) in mixParts" :key="a.id"><span v-if="i" class="pcf-mix-sep"> · </span><strong>{{ a.value }}%</strong> {{ a.label }}</template>
        </span>
      </div>
      <div class="pcf-mix-bar" aria-hidden="true">
        <span
          v-for="a in mixBar"
          :key="a.id"
          :style="{ flexGrow: a.value, background: a.color }"
        ></span>
      </div>
    </div>

    <!-- Goal -->
    <div class="pcf-row">
      <span class="pcf-row-label">GOAL</span>
      <span class="pcf-row-value">{{ persona.primary_goal }}</span>
    </div>

    <!-- Pain Points -->
    <div class="pcf-row" v-if="persona.pain_points?.length">
      <span class="pcf-row-label">PAINS</span>
      <span class="pcf-row-value">{{ persona.pain_points.join(' · ') }}</span>
    </div>

    <!-- Top Objection -->
    <div class="pcf-row" v-if="persona.objections?.length">
      <span class="pcf-row-label">OBJECTION</span>
      <span class="pcf-objection-chip">{{ persona.objections[0] }}</span>
    </div>

    <!-- Buying Triggers -->
    <div class="pcf-row" v-if="persona.buying_triggers?.length">
      <span class="pcf-row-label">TRIGGERS</span>
      <span class="pcf-row-value">{{ persona.buying_triggers.slice(0, 2).join(' · ') }}</span>
    </div>

    <!-- Divider -->
    <div class="pcf-divider"></div>

    <!-- Budget / Risk / Channel -->
    <div class="pcf-meta-row">
      <span class="pcf-meta-item">
        Budget: <strong :class="`sens-${persona.budget_sensitivity}`">{{ (persona.budget_sensitivity || '').toUpperCase() }}</strong>
      </span>
      <span class="pcf-meta-sep">·</span>
      <span class="pcf-meta-item">
        Risk: <strong :class="`risk-${persona.risk_tolerance}`">{{ (persona.risk_tolerance || '').toUpperCase() }}</strong>
      </span>
      <span class="pcf-meta-sep">·</span>
      <span class="pcf-meta-item">
        Best: <strong>{{ angleLabel }}</strong>
      </span>
    </div>

    <!-- Summary -->
    <div class="pcf-summary">"{{ persona.summary }}"</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ARCHETYPES, defaultAudience, personaWeights, blendColor, regionLabel } from '../utils/audience.js'

const props = defineProps({
  persona: { type: Object, required: true },
  compact: { type: Boolean, default: false },
  /** Use dark theme (for dark-bg simulation views) */
  dark:    { type: Boolean, default: false },
  /** Archetype colors chosen on the simulate page (falls back to the defaults) */
  colors:  { type: Object, default: null },
})

const roleColors = computed(() => ({ ...defaultAudience().colors, ...(props.colors || {}) }))
const weights = computed(() => personaWeights(props.persona))
const blended = computed(() => blendColor(weights.value, roleColors.value))
const mixParts = computed(() =>
  ARCHETYPES
    .map(a => ({ id: a.id, label: a.label, value: weights.value[a.id] || 0, color: roleColors.value[a.id] }))
    .filter(a => a.value > 0)
    .sort((x, y) => y.value - x.value)
)
// Bar keeps a fixed archetype order so cards can be compared at a glance
const mixBar = computed(() => ARCHETYPES
  .map(a => ({ id: a.id, value: weights.value[a.id] || 0, color: roleColors.value[a.id] }))
  .filter(a => a.value > 0))
const mixTitle = computed(() => mixParts.value.map(a => `${a.label} ${a.value}%`).join(', '))
const regionName = computed(() => regionLabel(props.persona.region))

const reactionLabel = computed(() => {
  const map = { interested: 'Interested', neutral: 'Neutral', objection: 'Objection' }
  return map[props.persona.reaction] ?? props.persona.reaction
})

const angleLabel = computed(() => {
  const map = { pain_led: 'Pain-Led', roi_led: 'ROI-Led', social_proof_led: 'Social Proof' }
  return map[props.persona.likely_message_angle] ?? props.persona.likely_message_angle ?? '-'
})
</script>

<style scoped>
/* ── COMPACT MODE ─────────────────────────────────────────────── */
.persona-card {
  flex: 1;
  min-width: 140px;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 12px;
  background: #FAFAFA;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.persona-card.interested { border-left: 3px solid #4CAF50; }
.persona-card.neutral    { border-left: 3px solid #FF9800; }
.persona-card.objection  { border-left: 3px solid #E53935; }

.persona-name { font-weight: 700; font-size: 13px; color: #111; }
.persona-role { font-size: 11px; color: #555; font-family: 'JetBrains Mono', monospace; }
.persona-company { font-size: 10px; color: #888; }

.persona-reaction-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 2px;
  width: fit-content;
  margin-top: 4px;
}
.persona-reaction-badge.interested { background: #E8F5E9; color: #2E7D32; }
.persona-reaction-badge.neutral    { background: #FFF3E0; color: #E65100; }
.persona-reaction-badge.objection  { background: #FFEBEE; color: #C62828; }

.persona-quote {
  font-size: 11px;
  color: #555;
  font-style: italic;
  margin-top: 6px;
  line-height: 1.4;
  border-top: 1px solid #EEE;
  padding-top: 6px;
}

/* ── FULL MODE - light (default) ─────────────────────────── */
.persona-card-full {
  background: #fff;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.persona-card-full:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); }

.persona-card-full.interested { border-left: 3px solid #4CAF50; }
.persona-card-full.neutral    { border-left: 3px solid #FF9800; }
.persona-card-full.objection  { border-left: 3px solid #E53935; }

/* Header */
.pcf-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.pcf-identity { flex: 1; min-width: 0; }

.pcf-name  { font-weight: 700; font-size: 14px; color: #111; line-height: 1.2; }
.pcf-title { font-size: 11px; color: #555; margin-top: 3px; }
.pcf-company { font-size: 10px; color: #999; margin-top: 2px; }

/* Badges */
.pcf-badges {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
  flex-shrink: 0;
}

.reaction-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 3px 7px;
  border-radius: 4px;
  white-space: nowrap;
}
.reaction-badge.interested { background: #e8f5e9; color: #2e7d32; }
.reaction-badge.neutral    { background: #fff3e0; color: #e65100; }
.reaction-badge.objection  { background: #ffebee; color: #c62828; }

.skep-bar { display: flex; gap: 2px; cursor: help; }

.skep-seg {
  width: 8px; height: 4px;
  border-radius: 1px;
  background: #e0e0e0;
}
.skep-seg.filled { background: #e65100; }

.skep-label {
  font-size: 9px;
  color: #aaa;
  margin-top: 1px;
}

/* Info rows */
.pcf-row { display: flex; gap: 8px; font-size: 12px; line-height: 1.5; }

.pcf-row-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: #999;
  white-space: nowrap;
  padding-top: 2px;
  min-width: 62px;
  text-transform: uppercase;
}

.pcf-row-value { color: #333; }
.objection-text { font-style: italic; color: #555; }

.pcf-objection-chip {
  display: inline-block;
  font-size: 11px;
  color: #c62828;
  background: #ffebee;
  border: 1px solid #ffcdd2;
  border-radius: 4px;
  padding: 2px 8px;
  line-height: 1.5;
}

/* Divider */
.pcf-divider { height: 1px; background: #f0f0f0; margin: 2px 0; }

/* Meta row */
.pcf-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: #777;
  flex-wrap: wrap;
}

.pcf-meta-sep { color: #ddd; }
.pcf-meta-item strong { font-weight: 700; font-size: 9px; }

.sens-low, .risk-low     { color: #2e7d32; }
.sens-medium, .risk-medium { color: #e65100; }
.sens-high, .risk-high   { color: #c62828; }

/* Summary quote */
.pcf-summary {
  font-size: 12px;
  font-style: italic;
  color: #666;
  line-height: 1.5;
  border-top: 1px solid #f0f0f0;
  padding-top: 10px;
}

/* ── FULL MODE - dark variant ─────────────────────────────── */
.persona-card-full.dark {
  background: var(--bg-card);
  border-color: var(--border-subtle);
}

.persona-card-full.dark:hover {
  box-shadow: 0 4px 20px rgba(59, 130, 246, 0.1);
  border-color: var(--border-muted);
}

.persona-card-full.dark.interested { border-left-color: var(--green); }
.persona-card-full.dark.neutral    { border-left-color: var(--amber); }
.persona-card-full.dark.objection  { border-left-color: var(--red); }

.persona-card-full.dark .pcf-name    { color: var(--text-primary); }
.persona-card-full.dark .pcf-title   { color: var(--text-secondary); }
.persona-card-full.dark .pcf-company { color: var(--text-tertiary); }

.persona-card-full.dark .reaction-badge.interested { background: rgba(74,222,128,0.12); color: var(--green); }
.persona-card-full.dark .reaction-badge.neutral    { background: rgba(245,158,11,0.12); color: var(--amber); }
.persona-card-full.dark .reaction-badge.objection  { background: rgba(248,113,113,0.12); color: var(--red); }

.persona-card-full.dark .skep-seg         { background: var(--border-muted); }
.persona-card-full.dark .skep-seg.filled  { background: var(--amber); }
.persona-card-full.dark .skep-label       { color: var(--text-tertiary); }

.persona-card-full.dark .pcf-row-label { color: var(--text-tertiary); }
.persona-card-full.dark .pcf-row-value { color: #d4d4d4; }

/* Role mix */
.pcf-mix { display: flex; flex-direction: column; gap: 7px; margin: 2px 0 4px; }
.pcf-mix-head { display: flex; align-items: center; gap: 8px; }
.pcf-mix-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 2px #000, 0 0 0 3px #2a2a2a;
}
.pcf-mix-text { font-size: 11px; color: var(--text-tertiary); line-height: 1.4; }
.pcf-mix-text strong { color: var(--text-primary); font-weight: 600; }
.pcf-mix-sep { color: #3a3a3a; }
.pcf-mix-bar { display: flex; gap: 2px; height: 4px; border-radius: 999px; overflow: hidden; }
.pcf-mix-bar span { display: block; min-width: 2px; }

.persona-card-full.dark .pcf-objection-chip {
  background: rgba(248,113,113,0.1);
  border-color: rgba(248,113,113,0.25);
  color: var(--red);
}

.persona-card-full.dark .pcf-divider { background: var(--border-subtle); }

.persona-card-full.dark .pcf-meta-row  { color: var(--text-secondary); }
.persona-card-full.dark .pcf-meta-sep  { color: var(--border-muted); }
.persona-card-full.dark .sens-low, .persona-card-full.dark .risk-low     { color: var(--green); }
.persona-card-full.dark .sens-medium, .persona-card-full.dark .risk-medium { color: var(--amber); }
.persona-card-full.dark .sens-high, .persona-card-full.dark .risk-high   { color: var(--red); }

.persona-card-full.dark .pcf-summary { color: var(--text-secondary); border-top-color: var(--border-subtle); }
</style>
