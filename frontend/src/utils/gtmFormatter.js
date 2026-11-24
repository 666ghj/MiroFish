/**
 * GTM brief normalization utilities.
 * Pure functions - no side effects, no imports.
 */

/**
 * Splits a competitors string (comma-separated) or array into a clean array.
 * @param {string|string[]} raw
 * @returns {string[]}
 */
function parseCompetitors(raw) {
  if (Array.isArray(raw)) return raw.map(s => s.trim()).filter(Boolean)
  return (raw ?? '').split(',').map(s => s.trim()).filter(Boolean)
}

/**
 * Converts raw form fields (camelCase) into a normalized API payload (snake_case).
 * Trims all strings and parses competitors into an array.
 *
 * @param {object} formData
 * @returns {object} normalized payload ready for POST /api/gtm/brief
 */
export function formatGTMBrief(formData) {
  return {
    product_name: (formData.productName ?? '').trim(),
    product_description: (formData.productDescription ?? '').trim(),
    icp: (formData.icp ?? '').trim(),
    pricing_model: (formData.pricingModel ?? '').trim(),
    target_market: (formData.targetMarket ?? '').trim(),
    sales_channel: (formData.salesChannel ?? '').trim(),
    pain_point: (formData.painPoint ?? '').trim(),
    competitors: parseCompetitors(formData.competitors),
    gtm_goal: (formData.gtmGoal ?? '').trim(),
    company_stage: (formData.companyStage ?? '').trim() || null,
    team_size: (formData.teamSize ?? '').trim() || null,
    existing_problems: (formData.existingProblems ?? '').trim() || null,
    outreach_strategy: (formData.outreachStrategy ?? '').trim() || null,
    num_personas: Math.max(6, Math.min(500, parseInt(formData.numPersonas) || 12)),
    num_messages: Math.max(2, Math.min(5, parseInt(formData.numMessages) || 3)),
  }
}

const REQUIRED = [
  'productName', 'productDescription', 'icp',
  'pricingModel', 'targetMarket', 'salesChannel',
  'painPoint', 'gtmGoal',
]

const MIN_LENGTHS = {
  productName: 2,
  productDescription: 20,
  icp: 20,
  pricingModel: 2,
  targetMarket: 5,
  painPoint: 20,
}

const FIELD_LABELS = {
  productName: 'Product Name',
  productDescription: 'Product Description',
  icp: 'Ideal Customer Profile',
  pricingModel: 'Pricing Model',
  targetMarket: 'Target Market',
  salesChannel: 'Sales Channel',
  painPoint: 'Main Pain Point',
  gtmGoal: 'GTM Goal',
}

/**
 * Validates raw form data.
 * @param {object} formData
 * @returns {{ field: string, message: string }[]} array of validation errors (empty = valid)
 */
export function validateGTMBrief(formData) {
  const errors = []
  for (const field of REQUIRED) {
    const val = (formData[field] ?? '').toString().trim()
    const label = FIELD_LABELS[field] || field
    if (!val) {
      errors.push({ field, message: `${label} is required` })
    } else if (MIN_LENGTHS[field] && val.length < MIN_LENGTHS[field]) {
      errors.push({ field, message: `${label} must be at least ${MIN_LENGTHS[field]} characters` })
    }
  }
  return errors
}


/**
 * Rough run time and API cost (openai/gpt-4o-mini) for a simulation.
 * Mirrors the backend: personas are scored in batches of 6, up to 3 runs,
 * capped at 60 reaction calls per simulation.
 */
export function estimateRun(numPersonas, numMessages) {
  const p = numPersonas
  const m = numMessages
  const callsPerRun = m * Math.ceil(p / 6)
  const runs = Math.max(1, Math.min(3, Math.floor(60 / callsPerRun)))
  const reactions = p * m * runs * 0.0002   // ~250 output + ~200 input tokens per scored reaction
  const personas = p * 0.0003               // persona generation
  const fixed = 0.006                       // messages + report
  let time = '~30 min'
  if (p <= 12) time = '~2 min'
  else if (p <= 50) time = '~4 min'
  else if (p <= 100) time = '~8 min'
  else if (p <= 200) time = '~15 min'
  return { runs, time, cost: (reactions + personas + fixed).toFixed(2) }
}
