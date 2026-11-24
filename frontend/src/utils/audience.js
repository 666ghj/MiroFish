/**
 * Audience model for the buyer network.
 *
 * Every buyer is a blend of three buying-committee archetypes (the "primaries").
 * A persona's color is the weighted mix of the three archetype colors, so a
 * founder who is 60% decision maker, 30% champion and 10% evaluator gets exactly
 * that blend. The same weights drive the composition ring drawn around each node.
 *
 * Default colors are slots 1-3 of the dataviz reference palette (dark steps),
 * validated all-pairs on the #000 surface: CVD dE 9.4, normal-vision dE 20.9.
 */

export const ARCHETYPES = [
  {
    id: 'decision_maker',
    label: 'Decision maker',
    short: 'Owns the budget and the final call',
    color: '#3987e5',
  },
  {
    id: 'champion',
    label: 'Champion',
    short: 'Feels the pain and pushes for change',
    color: '#d95926',
  },
  {
    id: 'evaluator',
    label: 'Evaluator',
    short: 'Checks fit, risk, and integration',
    color: '#199e70',
  },
]

export const ARCHETYPE_IDS = ARCHETYPES.map(a => a.id)

// Base blend per role, in percent [decision_maker, champion, evaluator].
export const ROLES = [
  { label: 'Founder',          w: [60, 30, 10] },
  { label: 'CEO',              w: [75, 10, 15] },
  { label: 'CFO',              w: [65, 0, 35] },
  { label: 'CRO',              w: [50, 35, 15] },
  { label: 'Agency Owner',     w: [55, 35, 10] },
  { label: 'Enterprise Buyer', w: [45, 5, 50] },
  { label: 'VP Sales',         w: [35, 55, 10] },
  { label: 'Head of Sales',    w: [30, 60, 10] },
  { label: 'Head of Growth',   w: [20, 65, 15] },
  { label: 'CMO',              w: [40, 45, 15] },
  { label: 'SDR Manager',      w: [10, 75, 15] },
  { label: 'Account Exec',     w: [5, 80, 15] },
  { label: 'Marketing Lead',   w: [15, 60, 25] },
  { label: 'Startup Operator', w: [35, 45, 20] },
  { label: 'Enablement Lead',  w: [5, 55, 40] },
  { label: 'RevOps Lead',      w: [10, 25, 65] },
  { label: 'Sales Ops',        w: [5, 30, 65] },
  { label: 'CTO',              w: [30, 5, 65] },
  { label: 'Procurement',      w: [20, 0, 80] },
  { label: 'Skeptical Buyer',  w: [25, 0, 75] },
]

// Backend persona_type -> role, for personas that arrive without an archetype_mix.
const PERSONA_TYPE_ROLE = {
  founder_seller: 'Founder',
  vp_sales: 'VP Sales',
  revops_lead: 'RevOps Lead',
  sdr_manager: 'SDR Manager',
  marketing_lead: 'Marketing Lead',
  cfo: 'CFO',
  enterprise_buyer: 'Enterprise Buyer',
  startup_operator: 'Startup Operator',
  agency_owner: 'Agency Owner',
  sales_enablement: 'Enablement Lead',
  skeptical_buyer: 'Skeptical Buyer',
  champion_user: 'Account Exec',
}

export const REGIONS = [
  { id: 'north_america', label: 'North America' },
  { id: 'latam', label: 'Latin America' },
  { id: 'uk_ireland', label: 'UK & Ireland' },
  { id: 'western_europe', label: 'Western Europe' },
  { id: 'dach', label: 'DACH' },
  { id: 'nordics', label: 'Nordics' },
  { id: 'middle_east', label: 'Middle East' },
  { id: 'africa', label: 'Africa' },
  { id: 'india', label: 'India' },
  { id: 'southeast_asia', label: 'Southeast Asia' },
  { id: 'anz', label: 'Australia & NZ' },
  { id: 'east_asia', label: 'Japan & Korea' },
]

export const COMPANY_SIZES = [
  { id: '1-10', label: '1-10' },
  { id: '11-50', label: '11-50' },
  { id: '51-200', label: '51-200' },
  { id: '201-1000', label: '201-1k' },
  { id: '1000+', label: '1k+' },
]

export const TRAITS = [
  { id: 'risk_appetite', label: 'Risk appetite', low: 'Risk-averse', high: 'Early adopter' },
  { id: 'budget_sensitivity', label: 'Budget sensitivity', low: 'Budget-flexible', high: 'Price-sensitive' },
  { id: 'skepticism', label: 'Skepticism', low: 'Trusting', high: 'Skeptical' },
  { id: 'decision_speed', label: 'Decision speed', low: 'Committee-led', high: 'One fast decider' },
  { id: 'tech_maturity', label: 'Tech maturity', low: 'Legacy tools', high: 'Modern stack' },
]

export const INDUSTRIES = [
  { id: 'saas', label: 'SaaS' },
  { id: 'fintech', label: 'Fintech' },
  { id: 'healthcare', label: 'Healthcare' },
  { id: 'ecommerce', label: 'E-commerce' },
  { id: 'manufacturing', label: 'Manufacturing' },
  { id: 'services', label: 'Services' },
  { id: 'logistics', label: 'Logistics' },
  { id: 'education', label: 'Education' },
  { id: 'public', label: 'Public sector' },
  { id: 'media', label: 'Media' },
]

export const CURRENT_SOLUTIONS = [
  { id: 'manual', label: 'Spreadsheets' },
  { id: 'competitor', label: 'A competitor' },
  { id: 'in_house', label: 'In-house tool' },
  { id: 'nothing', label: 'Nothing yet' },
]

export const TRAIT_LEVELS = ['Very low', 'Low', 'Moderate', 'High', 'Very high']

export function defaultAudience() {
  return {
    mix: { decision_maker: 30, champion: 45, evaluator: 25 },
    colors: Object.fromEntries(ARCHETYPES.map(a => [a.id, a.color])),
    regions: ['north_america'],
    company_sizes: ['11-50', '51-200'],
    traits: { risk_appetite: 3, budget_sensitivity: 3, skepticism: 3, decision_speed: 3, tech_maturity: 3 },
    industries: ['saas'],
    current_solutions: ['manual'],
    live_market: true,
    seed: 7,
  }
}

// ── Seeded randomness ────────────────────────────────────────────────────────

export function rng(seed) {
  let t = (seed >>> 0) || 1
  return () => {
    t += 0x6d2b79f5
    let r = Math.imul(t ^ (t >>> 15), 1 | t)
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r)
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296
  }
}

function pick(rand, list) {
  return list[Math.floor(rand() * list.length)]
}

function shuffle(rand, list) {
  const a = [...list]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

/** Integer split of `total` proportional to `weights` (largest remainder). */
export function apportion(weights, total) {
  const sum = weights.reduce((s, w) => s + Math.max(0, w), 0) || 1
  const exact = weights.map(w => (Math.max(0, w) / sum) * total)
  const out = exact.map(Math.floor)
  let left = total - out.reduce((s, v) => s + v, 0)
  const order = exact.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0])
  for (let k = 0; k < order.length && left > 0; k++, left--) out[order[k][1]]++
  return out
}

/** Audience mix as whole percentages that sum to 100. */
export function mixPercents(mix) {
  const p = apportion(ARCHETYPE_IDS.map(id => mix[id] ?? 0), 100)
  return Object.fromEntries(ARCHETYPE_IDS.map((id, i) => [id, p[i]]))
}

export function randomAudience(base = defaultAudience()) {
  const seed = Math.floor(Math.random() * 1e9)
  const rand = rng(seed)
  const raw = ARCHETYPE_IDS.map(() => 10 + rand() * 90)
  const pct = apportion(raw, 100)
  const regionCount = 1 + Math.floor(rand() * 3)
  const regions = shuffle(rand, REGIONS.map(r => r.id)).slice(0, regionCount)
  const start = Math.floor(rand() * COMPANY_SIZES.length)
  const span = 1 + Math.floor(rand() * 2)
  const sizes = COMPANY_SIZES.slice(start, start + span).map(s => s.id)
  return {
    ...base,
    mix: Object.fromEntries(ARCHETYPE_IDS.map((id, i) => [id, pct[i]])),
    regions,
    company_sizes: sizes,
    traits: Object.fromEntries(TRAITS.map(t => [t.id, 1 + Math.floor(rand() * 5)])),
    industries: shuffle(rand, INDUSTRIES.map(i => i.id)).slice(0, 1 + Math.floor(rand() * 2)),
    current_solutions: shuffle(rand, CURRENT_SOLUTIONS.map(c => c.id)).slice(0, 1 + Math.floor(rand() * 2)),
    seed,
  }
}

// ── Color: weighted blend in OKLab ──────────────────────────────────────────
// A plain OKLab average greys out mixed roles; restoring all of the lost chroma
// sends balanced mixes to arbitrary hues. Restoring 35% keeps two-way blends lively
// while a balanced three-way persona reads as a softer, clearly "mixed" color.
const CHROMA_RESTORE = 0.35

function srgbToLinear(c) {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function linearToSrgb(c) {
  return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
}

export function hexToOklab(hex) {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map(i => srgbToLinear(parseInt(h.slice(i, i + 2), 16) / 255))
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

export function oklabToHex([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ]
  return '#' + rgb
    .map(c => Math.round(Math.min(1, Math.max(0, linearToSrgb(c))) * 255).toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Blend archetype colors by weight.
 * @param {Record<string, number>} weights  archetype id -> weight (any scale)
 * @param {Record<string, string>} colors   archetype id -> hex
 */
export function blendColor(weights, colors) {
  const ids = ARCHETYPE_IDS.filter(id => (weights[id] || 0) > 0)
  const total = ids.reduce((s, id) => s + weights[id], 0)
  if (!total) return '#737373'
  let L = 0, A = 0, B = 0, C = 0
  for (const id of ids) {
    const w = weights[id] / total
    const [l, a, b] = hexToOklab(colors[id] || '#737373')
    L += w * l; A += w * a; B += w * b
    C += w * Math.hypot(a, b)
  }
  const c = Math.hypot(A, B)
  const target = c + CHROMA_RESTORE * (C - c)
  if (c > 1e-4) { A *= target / c; B *= target / c }
  return oklabToHex([L, A, B])
}

// ── Personas ────────────────────────────────────────────────────────────────

function weightsFrom(arr) {
  return Object.fromEntries(ARCHETYPE_IDS.map((id, i) => [id, arr[i]]))
}

export function dominantOf(weights) {
  return ARCHETYPE_IDS.reduce((best, id) => ((weights[id] || 0) > (weights[best] || 0) ? id : best), ARCHETYPE_IDS[0])
}

const ROLES_BY_DOMINANT = Object.fromEntries(
  ARCHETYPE_IDS.map(id => [id, ROLES.filter(r => dominantOf(weightsFrom(r.w)) === id)])
)

/** Role blend plus a small seeded variation, as whole percents summing to 100, same dominant archetype. */
function jitteredBlend(rand, base) {
  const dom = base.indexOf(Math.max(...base))
  const raw = base.map(v => Math.max(0, v + (rand() - 0.5) * 16))
  const maxOther = Math.max(...raw.filter((_, i) => i !== dom))
  if (raw[dom] <= maxOther) raw[dom] = maxOther + 4
  return apportion(raw, 100)
}

/**
 * Build the buyers shown in the network for an audience.
 * Dominant archetypes follow the audience mix exactly (largest remainder).
 */
export function generateAudienceNodes(audience, count) {
  const a = audience || defaultAudience()
  const rand = rng(a.seed || 1)
  const counts = apportion(ARCHETYPE_IDS.map(id => a.mix?.[id] ?? 0), count)
  const dominants = shuffle(rand, ARCHETYPE_IDS.flatMap((id, i) => Array(counts[i]).fill(id)))
  const regions = a.regions?.length ? a.regions : ['north_america']
  const regionSlots = shuffle(rand, Array.from({ length: count }, (_, i) => regions[i % regions.length]))
  const risk = a.traits?.risk_appetite ?? 3
  const sizes = a.company_sizes?.length ? a.company_sizes : ['11-50']
  return dominants.map((dom, i) => {
    const role = pick(rand, ROLES_BY_DOMINANT[dom])
    const blend = jitteredBlend(rand, role.w)
    const r = rand()
    const personalRisk = Math.min(5, Math.max(1, risk + (r < 0.2 ? -1 : r > 0.8 ? 1 : 0)))
    return {
      id: i,
      role: role.label,
      weights: weightsFrom(blend),
      dominant: dom,
      region: regionSlots[i],
      risk: personalRisk,
      size: pick(rand, sizes),
    }
  })
}

/** Archetype weights for a generated persona (uses archetype_mix when present). */
export function personaWeights(persona) {
  const mix = persona?.archetype_mix
  if (mix && ARCHETYPE_IDS.some(id => Number(mix[id]) > 0)) {
    const p = apportion(ARCHETYPE_IDS.map(id => Number(mix[id]) || 0), 100)
    return weightsFrom(p)
  }
  const roleLabel = PERSONA_TYPE_ROLE[persona?.persona_type]
  const role = ROLES.find(r => r.label === roleLabel)
  return weightsFrom(role ? role.w : [34, 33, 33])
}

export function regionLabel(id) {
  return REGIONS.find(r => r.id === id)?.label ?? id ?? ''
}

export function archetypeLabel(id) {
  return ARCHETYPES.find(a => a.id === id)?.label ?? id
}
