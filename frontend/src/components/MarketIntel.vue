<template>
  <div class="mi">
    <div class="mi-head">
      <div>
        <div class="mi-title">Market intelligence</div>
        <div class="mi-hint">
          <template v-if="loading">Checking {{ regions.length }} {{ regions.length === 1 ? 'region' : 'regions' }}...</template>
          <template v-else-if="data">
            <span class="live-dot" :class="{ off: !live }"></span>{{ live ? 'Live' : 'Profiles only' }} · updated {{ updatedAt }}
          </template>
          <template v-else-if="error">{{ error }}</template>
        </div>
      </div>
      <button type="button" class="mi-refresh" :disabled="loading" @click="load" title="Refresh market data">
        <svg viewBox="0 0 16 16" aria-hidden="true" :class="{ spin: loading }"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" /></svg>
      </button>
    </div>

    <div v-if="loading && !data" class="mi-skeleton">
      <div class="sk" v-for="i in regions.length" :key="i"></div>
    </div>

    <details
      v-for="(r, idx) in data?.regions || []"
      :key="r.id"
      class="region"
      :open="idx === 0"
    >
      <summary>
        <span class="region-name">{{ r.label }}</span>
        <span class="status" :class="`status--${r.outreach.rule}`">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path :d="ICONS[r.outreach.rule]" /></svg>
          {{ SHORT[r.outreach.rule] }}
        </span>
        <svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
      </summary>

      <div class="region-body">
        <!-- Right now -->
        <div class="row-clocks">
          <span v-for="c in r.countries" :key="c.code" class="clock" :title="c.local.tz">
            <span class="clock-dot" :class="{ open: c.local.open }"></span>
            <strong>{{ c.code }}</strong> {{ c.local.weekday }} {{ c.local.time }}
            <span class="clock-state">{{ c.local.open ? 'open' : 'closed' }}</span>
          </span>
        </div>

        <!-- Outreach rules -->
        <div class="block">
          <div class="block-label">Cold outreach rules</div>
          <div class="rules">
            <div class="rule" v-for="c in r.countries" :key="c.code">
              <div class="rule-top">
                <span class="rule-dot" :class="`dot--${c.rule}`"></span>
                <span class="rule-country">{{ c.name }}</span>
                <span class="rule-law">{{ c.law }}</span>
                <span v-if="c.confidence === 'contested'" class="contested" title="Published guidance disagrees on this point">contested</span>
              </div>
              <div class="rule-label">{{ c.rule_label }}</div>
              <div class="rule-note">{{ c.note }}</div>
            </div>
          </div>
        </div>

        <!-- Economy -->
        <div class="block" v-if="hasIndicators(r)">
          <div class="block-label">Economy <span class="block-src">World Bank, latest year</span></div>
          <table class="econ">
            <thead>
              <tr><th></th><th>GDP growth</th><th>Inflation</th><th>Unemployment</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in r.countries" :key="c.code">
                <td class="econ-c">{{ c.code }}</td>
                <td v-for="k in ['gdp_growth', 'inflation', 'unemployment']" :key="k">
                  <template v-if="c.indicators[k]">{{ c.indicators[k].value }}%<span class="yr">{{ c.indicators[k].year }}</span></template>
                  <span v-else class="na">n/a</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Timing -->
        <div class="block">
          <div class="block-label">Timing now</div>
          <ul class="timing">
            <li v-for="f in r.fiscal_years" :key="f.label">
              <strong>{{ f.label }}:</strong> fiscal year ends {{ fmtDate(f.ends) }} ({{ f.days_left }} days)
            </li>
            <li v-for="t in r.timing.filter(t => !t.includes('fiscal year ends'))" :key="t">{{ t }}</li>
          </ul>
        </div>

        <!-- Holidays -->
        <div class="block" v-if="live">
          <div class="block-label">Public holidays, next 60 days</div>
          <div v-if="r.holidays.length" class="holidays">
            <div class="holiday" v-for="h in r.holidays.slice(0, 5)" :key="h.date + h.name">
              <span class="h-date">{{ fmtDate(h.date) }}</span>
              <span class="h-name">{{ h.name }}</span>
              <span class="h-cc">{{ h.country }}</span>
            </div>
          </div>
          <div v-else class="empty">
            {{ r.countries.some(c => c.holidays_supported) ? 'None in the next 60 days.' : 'Holiday feed not available for this region.' }}
          </div>
        </div>

        <!-- Headlines -->
        <div class="block" v-if="live && r.headlines.length">
          <div class="block-label">This week's headlines</div>
          <a
            v-for="h in r.headlines.slice(0, 3)"
            :key="h.url"
            class="headline"
            :href="h.url"
            target="_blank"
            rel="noopener"
          >
            <span class="hl-title">{{ h.title }}</span>
            <span class="hl-meta">{{ h.source }}<template v-if="h.date"> · {{ fmtNewsDate(h.date) }}</template></span>
          </a>
        </div>

        <!-- Culture -->
        <div class="block">
          <div class="block-label">How they buy</div>
          <p class="culture">{{ r.culture }}</p>
          <p class="culture culture--muted">{{ r.sales_cycle }}</p>
          <div class="tags">
            <span v-for="ch in r.channels" :key="ch" class="tag">{{ ch }}</span>
          </div>
          <div class="meta-line">{{ r.languages.join(', ') }} · {{ r.currency }}</div>
        </div>
      </div>
    </details>

    <p v-if="data" class="mi-foot">
      {{ data.disclaimer }} Sources:
      <template v-for="(s, i) in data.sources" :key="s.url"><a :href="s.url" target="_blank" rel="noopener">{{ s.name }}</a><span v-if="i < data.sources.length - 1">, </span></template>.
    </p>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { getMarketIntel } from '../api/gtm.js'

const props = defineProps({
  regions: { type: Array, required: true },
  live: { type: Boolean, default: true },
})

const data = ref(null)
const loading = ref(false)
const error = ref('')
const updatedAt = ref('')

// Status palette is reserved for state, and always paired with an icon and a label
const SHORT = {
  opt_out: 'Cold email OK',
  role_based: 'Role-relevant only',
  changing: 'Tightening soon',
  unclear: 'Unclear',
  opt_in: 'Consent required',
}
const ICONS = {
  opt_out: 'M4 8.5l2.5 2.5L12 5.5',
  role_based: 'M8 4.5v4M8 11v.5',
  changing: 'M8 4.5v4M8 11v.5',
  unclear: 'M6.5 6a1.6 1.6 0 1 1 2.2 1.5c-.5.2-.7.6-.7 1.1M8 11v.5',
  opt_in: 'M5 5l6 6M11 5l-6 6',
}

let timer = null
let seq = 0

async function load() {
  if (!props.regions.length) { data.value = null; return }
  const mine = ++seq
  loading.value = true
  error.value = ''
  try {
    const res = await getMarketIntel(props.regions, props.live)
    if (mine !== seq) return
    if (!res.success) throw new Error(res.error || 'Market data unavailable')
    data.value = res.data
    updatedAt.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    if (mine === seq) error.value = 'Market data is unavailable right now.'
  } finally {
    if (mine === seq) loading.value = false
  }
}

watch(() => [props.regions.join(','), props.live], () => {
  clearTimeout(timer)
  timer = setTimeout(load, 350)
}, { immediate: true })

onUnmounted(() => clearTimeout(timer))

function hasIndicators(r) {
  return r.countries.some(c => Object.keys(c.indicators || {}).length)
}

function fmtDate(iso) {
  const d = new Date(iso + 'T12:00:00')
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' })
}

function fmtNewsDate(s) {
  const d = new Date(s)
  return isNaN(d) ? '' : d.toLocaleDateString([], { day: 'numeric', month: 'short' })
}
</script>

<style scoped>
.mi { display: flex; flex-direction: column; gap: 10px; }
.mi-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.mi-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.mi-hint { font-size: 12px; color: var(--text-tertiary); margin-top: 3px; display: flex; align-items: center; gap: 6px; }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.15); }
.live-dot.off { background: #555; box-shadow: none; }
.mi-refresh {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  border: 1px solid #2a2a2a;
  background: #141414;
  color: var(--text-secondary);
}
.mi-refresh:hover { color: var(--text-primary); border-color: #444; }
.mi-refresh svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.mi-skeleton { display: flex; flex-direction: column; gap: 8px; }
.sk { height: 46px; border-radius: 8px; background: linear-gradient(90deg, #111 0%, #1a1a1a 50%, #111 100%); background-size: 200% 100%; animation: shimmer 1.2s infinite; }
@keyframes shimmer { to { background-position: -200% 0; } }

.region { border: 1px solid #222; border-radius: 10px; background: #0a0a0a; }
.region[open] { border-color: #2a2a2a; }
.region summary {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
}
.region summary::-webkit-details-marker { display: none; }
.region-name { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; }
.chev { width: 14px; height: 14px; fill: none; stroke: #666; stroke-width: 1.6; transition: transform 0.15s; }
.region[open] .chev { transform: rotate(180deg); }

.status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px 3px 6px;
  border-radius: 999px;
  color: var(--text-primary);
  border: 1px solid;
}
.status svg { width: 12px; height: 12px; fill: none; stroke-width: 2; stroke-linecap: round; }
.status--opt_out { background: rgba(74, 222, 128, 0.1); border-color: rgba(74, 222, 128, 0.3); }
.status--opt_out svg { stroke: var(--green); }
.status--role_based, .status--changing { background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.3); }
.status--role_based svg, .status--changing svg { stroke: var(--amber); }
.status--unclear { background: #161616; border-color: #333; }
.status--unclear svg { stroke: #aaa; }
.status--opt_in { background: rgba(248, 113, 113, 0.1); border-color: rgba(248, 113, 113, 0.3); }
.status--opt_in svg { stroke: var(--red); }

.region-body { padding: 0 14px 14px; display: flex; flex-direction: column; gap: 16px; }

.row-clocks { display: flex; flex-wrap: wrap; gap: 6px; }
.clock {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-secondary);
  padding: 4px 8px;
  border: 1px solid #222;
  border-radius: 6px;
}
.clock strong { color: var(--text-primary); font-weight: 600; }
.clock-dot { width: 6px; height: 6px; border-radius: 50%; background: #555; }
.clock-dot.open { background: var(--green); }
.clock-state { color: var(--text-tertiary); }

.block { display: flex; flex-direction: column; gap: 8px; }
.block-label { font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.06em; }
.block-src { text-transform: none; letter-spacing: 0; font-weight: 400; color: var(--text-tertiary); margin-left: 4px; }

.rules { display: flex; flex-direction: column; gap: 10px; }
.rule-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.rule-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot--opt_out { background: var(--green); }
.dot--role_based, .dot--changing { background: var(--amber); }
.dot--unclear { background: #888; }
.dot--opt_in { background: var(--red); }
.rule-country { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.rule-law { font-size: 11px; color: var(--text-tertiary); }
.contested {
  font-size: 10px;
  color: var(--text-secondary);
  border: 1px dashed #444;
  border-radius: 4px;
  padding: 0 5px;
}
.rule-label { font-size: 12px; color: var(--text-primary); margin: 3px 0 2px 13px; }
.rule-note { font-size: 11px; line-height: 1.5; color: var(--text-tertiary); margin-left: 13px; }

.econ { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.econ th { text-align: right; font-weight: 500; font-size: 10px; color: var(--text-tertiary); padding: 0 0 6px; }
.econ td { text-align: right; padding: 5px 0; color: var(--text-primary); border-top: 1px solid #1a1a1a; }
.econ .econ-c { text-align: left; font-weight: 600; }
.yr { font-size: 9px; color: var(--text-tertiary); margin-left: 3px; }
.na { color: #555; }

.timing { list-style: none; display: flex; flex-direction: column; gap: 6px; }
.timing li { font-size: 12px; line-height: 1.5; color: var(--text-secondary); padding-left: 12px; position: relative; }
.timing li::before { content: ''; position: absolute; left: 0; top: 7px; width: 4px; height: 4px; border-radius: 50%; background: var(--accent); }
.timing strong { color: var(--text-primary); font-weight: 600; }

.holidays { display: flex; flex-direction: column; gap: 4px; }
.holiday { display: grid; grid-template-columns: 52px 1fr auto; gap: 8px; font-size: 12px; align-items: baseline; }
.h-date { color: var(--text-primary); font-weight: 600; }
.h-name { color: var(--text-secondary); }
.h-cc { font-size: 10px; color: var(--text-tertiary); }
.empty { font-size: 12px; color: var(--text-tertiary); }

.headline {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid #1f1f1f;
  border-radius: 7px;
  text-decoration: none;
  transition: border-color 0.15s;
}
.headline:hover { border-color: #3a3a3a; }
.hl-title { font-size: 12px; line-height: 1.45; color: var(--text-primary); }
.hl-meta { font-size: 10px; color: var(--text-tertiary); }

.culture { font-size: 12px; line-height: 1.55; color: var(--text-secondary); }
.culture--muted { color: var(--text-tertiary); }
.tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag { font-size: 11px; color: var(--text-secondary); padding: 2px 8px; border: 1px solid #262626; border-radius: 999px; }
.meta-line { font-size: 11px; color: var(--text-tertiary); }

.mi-foot { font-size: 10px; line-height: 1.5; color: var(--text-tertiary); }
.mi-foot a { color: var(--text-secondary); }
</style>
