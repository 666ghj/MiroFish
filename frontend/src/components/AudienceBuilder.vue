<template>
  <div class="ab">
    <div class="ab-head">
      <div>
        <div class="ab-title">Audience</div>
        <div class="ab-hint">Who your buyers are. This shapes the generated personas.</div>
      </div>
      <div class="ab-actions">
        <button type="button" class="ab-btn" @click="randomize" title="Generate a random sample audience">
          <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="2.5" /><circle cx="5.75" cy="5.75" r="0.9" /><circle cx="10.25" cy="10.25" r="0.9" /><circle cx="10.25" cy="5.75" r="0.9" /><circle cx="5.75" cy="10.25" r="0.9" /><circle cx="8" cy="8" r="0.9" /></svg>
          Random sample
        </button>
        <button type="button" class="ab-btn ab-btn--quiet" @click="reset">Reset</button>
      </div>
    </div>

    <!-- Buyer mix -->
    <section class="ab-block">
      <div class="ab-label-row">
        <span class="ab-label">Buyer mix</span>
        <span class="ab-meta">{{ count }} personas</span>
      </div>
      <div class="mix-bar" role="img" :aria-label="mixAria">
        <span
          v-for="a in ARCHETYPES"
          :key="a.id"
          v-show="pct[a.id] > 0"
          class="mix-seg"
          :style="{ flexGrow: pct[a.id], background: colors[a.id] }"
        >
          <span v-if="pct[a.id] >= 14" class="mix-seg-label" :style="{ color: inkOn(colors[a.id]) }">{{ pct[a.id] }}%</span>
        </span>
      </div>

      <div class="mix-rows">
        <div class="mix-row" v-for="a in ARCHETYPES" :key="a.id">
          <label class="swatch" :style="{ background: colors[a.id] }" :title="`Change ${a.label} color`">
            <input
              type="color"
              :value="colors[a.id]"
              :aria-label="`${a.label} color`"
              @input="setColor(a.id, $event.target.value)"
            />
          </label>
          <div class="mix-text">
            <div class="mix-name">{{ a.label }}</div>
            <div class="mix-desc">{{ a.short }}</div>
          </div>
          <div class="mix-figure">
            <div class="mix-pct">{{ pct[a.id] }}%</div>
            <div class="mix-count">{{ counts[a.id] }} {{ counts[a.id] === 1 ? 'buyer' : 'buyers' }}</div>
          </div>
          <input
            class="range mix-range"
            type="range"
            min="0"
            max="100"
            :value="model.mix[a.id]"
            :aria-label="`${a.label} share`"
            :style="{ '--fill': colors[a.id], '--pos': model.mix[a.id] + '%' }"
            @input="setMix(a.id, +$event.target.value)"
          />
        </div>
      </div>
      <p class="ab-note">Each buyer's color blends these three by how much of each role they play. Hover a dot to see the exact mix.</p>
    </section>

    <!-- Regions -->
    <section class="ab-block">
      <div class="ab-label-row">
        <span class="ab-label">Regions</span>
        <span class="ab-meta">{{ model.regions.length }} selected</span>
      </div>
      <div class="chips">
        <button
          v-for="r in REGIONS"
          :key="r.id"
          type="button"
          class="chip"
          :class="{ on: model.regions.includes(r.id) }"
          :aria-pressed="model.regions.includes(r.id)"
          @click="toggle('regions', r.id)"
        >{{ r.label }}</button>
      </div>
    </section>

    <!-- Company size -->
    <section class="ab-block">
      <div class="ab-label-row">
        <span class="ab-label">Company size</span>
        <span class="ab-meta">employees</span>
      </div>
      <div class="chips">
        <button
          v-for="s in COMPANY_SIZES"
          :key="s.id"
          type="button"
          class="chip"
          :class="{ on: model.company_sizes.includes(s.id) }"
          :aria-pressed="model.company_sizes.includes(s.id)"
          @click="toggle('company_sizes', s.id)"
        >{{ s.label }}</button>
      </div>
    </section>

    <!-- Traits -->
    <section class="ab-block">
      <div class="ab-label-row">
        <span class="ab-label">Buyer behavior</span>
      </div>
      <div class="traits">
        <div class="trait" v-for="t in TRAITS" :key="t.id">
          <div class="trait-top">
            <span class="trait-name">{{ t.label }}</span>
            <span class="trait-val">{{ TRAIT_LEVELS[model.traits[t.id] - 1] }}</span>
          </div>
          <input
            class="range"
            type="range"
            min="1"
            max="5"
            step="1"
            :value="model.traits[t.id]"
            :aria-label="t.label"
            :style="{ '--fill': 'var(--accent)', '--pos': ((model.traits[t.id] - 1) / 4) * 100 + '%' }"
            @input="setTrait(t.id, +$event.target.value)"
          />
          <div class="trait-ends"><span>{{ t.low }}</span><span>{{ t.high }}</span></div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  ARCHETYPES, ARCHETYPE_IDS, REGIONS, COMPANY_SIZES, TRAITS, TRAIT_LEVELS,
  defaultAudience, randomAudience, mixPercents, apportion,
} from '../utils/audience.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  count: { type: Number, default: 12 },
})
const emit = defineEmits(['update:modelValue'])

const model = computed(() => props.modelValue)
const colors = computed(() => model.value.colors)
const pct = computed(() => mixPercents(model.value.mix))
const counts = computed(() => {
  const c = apportion(ARCHETYPE_IDS.map(id => model.value.mix[id] ?? 0), props.count)
  return Object.fromEntries(ARCHETYPE_IDS.map((id, i) => [id, c[i]]))
})
const mixAria = computed(() =>
  'Buyer mix: ' + ARCHETYPES.map(a => `${a.label} ${pct.value[a.id]}%`).join(', ')
)

// Label ink for text printed inside a colored segment: white, or near-black on light colors
function inkOn(hex) {
  const h = (hex || '#000000').replace('#', '')
  const lin = [0, 2, 4].map(i => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  const lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
  return lum > 0.4 ? '#0b0b0b' : '#ffffff'
}

function update(patch) {
  emit('update:modelValue', { ...model.value, ...patch })
}

function setMix(id, value) {
  const mix = { ...model.value.mix, [id]: value }
  // keep at least one archetype in the audience
  if (ARCHETYPE_IDS.every(k => !mix[k])) return
  update({ mix })
}

function setColor(id, value) {
  update({ colors: { ...model.value.colors, [id]: value } })
}

function setTrait(id, value) {
  update({ traits: { ...model.value.traits, [id]: value } })
}

function toggle(key, id) {
  const list = model.value[key]
  const next = list.includes(id) ? list.filter(x => x !== id) : [...list, id]
  if (!next.length) return // at least one must stay selected
  update({ [key]: next })
}

function randomize() {
  emit('update:modelValue', randomAudience({ ...model.value }))
}

function reset() {
  emit('update:modelValue', defaultAudience())
}
</script>

<style scoped>
.ab { display: flex; flex-direction: column; gap: 22px; }

.ab-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.ab-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.ab-hint { font-size: 12px; color: var(--text-tertiary); margin-top: 3px; line-height: 1.4; }
.ab-actions { display: flex; gap: 6px; flex-shrink: 0; }
.ab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 7px;
  padding: 6px 10px;
  transition: border-color 0.15s, background 0.15s;
}
.ab-btn:hover { border-color: #444; background: #1a1a1a; }
.ab-btn svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.3; }
.ab-btn svg circle { fill: currentColor; stroke: none; }
.ab-btn--quiet { background: transparent; color: var(--text-secondary); }

.ab-block { display: flex; flex-direction: column; gap: 10px; }
.ab-label-row { display: flex; justify-content: space-between; align-items: baseline; }
.ab-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.ab-meta { font-size: 11px; color: var(--text-tertiary); }
.ab-note { font-size: 11px; line-height: 1.5; color: var(--text-tertiary); }

/* Tall segmented bar: one whole split into parts, share printed inside */
.mix-bar {
  display: flex;
  gap: 2px;
  height: 24px;
  border-radius: 6px;
  overflow: hidden;
}
.mix-seg {
  display: flex;
  align-items: center;
  min-width: 3px;
  border-radius: 4px;
  transition: flex-grow 0.2s ease;
}
.mix-seg-label { font-size: 11px; font-weight: 600; padding-left: 7px; }

.mix-rows { display: flex; flex-direction: column; gap: 12px; }
.mix-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  grid-template-areas:
    "sw text fig"
    "sw range range";
  column-gap: 10px;
  row-gap: 6px;
  align-items: center;
}
.swatch {
  grid-area: sw;
  align-self: start;
  margin-top: 2px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  position: relative;
  cursor: pointer;
  box-shadow: 0 0 0 2px #000, 0 0 0 3px #333;
  transition: box-shadow 0.15s;
}
.swatch:hover, .swatch:focus-within { box-shadow: 0 0 0 2px #000, 0 0 0 3px #777; }
.swatch input {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  height: 100%;
  cursor: pointer;
  border: none;
  padding: 0;
}
.mix-text { grid-area: text; min-width: 0; }
.mix-name { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.mix-desc { font-size: 11px; color: var(--text-tertiary); margin-top: 1px; }
.mix-figure { grid-area: fig; text-align: right; }
.mix-pct { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.mix-count { font-size: 11px; color: var(--text-tertiary); }
.mix-range { grid-area: range; }

/* Range input: filled track up to the thumb */
.range {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 4px;
  border-radius: 999px;
  background: linear-gradient(to right, var(--fill) 0%, var(--fill) var(--pos), #262626 var(--pos), #262626 100%);
  outline: none;
  cursor: pointer;
}
.range::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #000;
  box-shadow: 0 0 0 1px #3a3a3a;
}
.range::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #000;
}
.range:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 3px var(--accent); }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  font-size: 12px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid #262626;
  border-radius: 999px;
  padding: 5px 11px;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.chip:hover { border-color: #444; color: var(--text-primary); }
.chip.on {
  color: var(--text-primary);
  border-color: rgba(59, 130, 246, 0.6);
  background: rgba(59, 130, 246, 0.12);
}

.traits { display: flex; flex-direction: column; gap: 14px; }
.trait-top { display: flex; justify-content: space-between; margin-bottom: 7px; }
.trait-name { font-size: 12px; color: var(--text-primary); font-weight: 500; }
.trait-val { font-size: 12px; color: var(--text-secondary); }
.trait-ends {
  display: flex;
  justify-content: space-between;
  margin-top: 5px;
  font-size: 10px;
  color: var(--text-tertiary);
}
</style>
