<template>
  <div class="gtm-form">
    <!-- Section 01: Product -->
    <div class="form-section">
      <div class="section-label">01 / Product</div>

      <div class="field-group">
        <label class="field-label">Product Name <span class="required">*</span></label>
        <input
          v-model="form.productName"
          type="text"
          class="field-input"
          :class="{ error: errors.productName }"
          placeholder="e.g. Acme AI SDR"
          @blur="touchField('productName')"
        />
        <span v-if="errors.productName" class="field-error">{{ errors.productName }}</span>
      </div>

      <div class="field-group">
        <label class="field-label">Product Description <span class="required">*</span></label>
        <textarea
          v-model="form.productDescription"
          class="field-input field-textarea"
          :class="{ error: errors.productDescription }"
          placeholder="// What does your product do? Who is it for? What makes it different?"
          rows="3"
          @blur="touchField('productDescription')"
        />
        <span v-if="errors.productDescription" class="field-error">{{ errors.productDescription }}</span>
      </div>

      <div class="field-group">
        <label class="field-label">Pricing Model <span class="required">*</span></label>
        <input
          v-model="form.pricingModel"
          type="text"
          class="field-input"
          :class="{ error: errors.pricingModel }"
          placeholder="e.g. $500/mo per seat, usage-based, freemium"
          @blur="touchField('pricingModel')"
        />
        <span v-if="errors.pricingModel" class="field-error">{{ errors.pricingModel }}</span>
      </div>
    </div>

    <!-- Section 02: Buyer -->
    <div class="form-section">
      <div class="section-label">02 / Buyer</div>

      <div class="field-group">
        <label class="field-label">Ideal Customer Profile (ICP) <span class="required">*</span></label>
        <textarea
          v-model="form.icp"
          class="field-input field-textarea"
          :class="{ error: errors.icp }"
          placeholder="// B2B SaaS companies, 10–200 employees, sales team of 3–10, Series A or bootstrapped..."
          rows="3"
          @blur="touchField('icp')"
        />
        <span v-if="errors.icp" class="field-error">{{ errors.icp }}</span>
      </div>

      <div class="field-group">
        <label class="field-label">Target Market <span class="required">*</span></label>
        <input
          v-model="form.targetMarket"
          type="text"
          class="field-input"
          :class="{ error: errors.targetMarket }"
          placeholder="e.g. US, SMB SaaS founders and VP Sales"
          @blur="touchField('targetMarket')"
        />
        <span v-if="errors.targetMarket" class="field-error">{{ errors.targetMarket }}</span>
      </div>
    </div>

    <!-- Section 03: GTM Strategy -->
    <div class="form-section">
      <div class="section-label">03 / GTM Strategy</div>

      <div class="field-row">
        <div class="field-group half">
          <label class="field-label">Sales Channel <span class="required">*</span></label>
          <select
            v-model="form.salesChannel"
            class="field-input field-select"
            :class="{ error: errors.salesChannel }"
            @blur="touchField('salesChannel')"
          >
            <option value="" disabled>Select channel...</option>
            <option value="outbound_email">Outbound Email</option>
            <option value="linkedin">LinkedIn</option>
            <option value="cold_call">Cold Call</option>
            <option value="plg">Product-Led Growth</option>
            <option value="inbound">Inbound / Content</option>
            <option value="partnerships">Partnerships</option>
          </select>
          <span v-if="errors.salesChannel" class="field-error">{{ errors.salesChannel }}</span>
        </div>

        <div class="field-group half">
          <label class="field-label">GTM Goal <span class="required">*</span></label>
          <select
            v-model="form.gtmGoal"
            class="field-input field-select"
            :class="{ error: errors.gtmGoal }"
            @blur="touchField('gtmGoal')"
          >
            <option value="" disabled>Select goal...</option>
            <option value="first_10_customers">Land first 10 customers</option>
            <option value="expand_segment">Expand existing segment</option>
            <option value="new_market">Enter new market</option>
            <option value="reactivate_churned">Reactivate churned customers</option>
          </select>
          <span v-if="errors.gtmGoal" class="field-error">{{ errors.gtmGoal }}</span>
        </div>
      </div>

      <div class="field-group">
        <label class="field-label">Main Pain Point <span class="required">*</span></label>
        <textarea
          v-model="form.painPoint"
          class="field-input field-textarea"
          :class="{ error: errors.painPoint }"
          placeholder="// SDRs spend 70% of time on research and list building..."
          rows="3"
          @blur="touchField('painPoint')"
        />
        <span v-if="errors.painPoint" class="field-error">{{ errors.painPoint }}</span>
      </div>

      <div class="field-group">
        <label class="field-label">Competitors <span class="field-hint">(comma-separated)</span></label>
        <input
          v-model="form.competitors"
          type="text"
          class="field-input"
          placeholder="Apollo, Outreach, Clay"
        />
      </div>
    </div>

    <!-- Section 04: Simulation Parameters (hidden when SimulatePage owns these) -->
    <div v-if="!hideParams" class="form-section params-section">
      <div class="section-label">04 / Simulation Parameters</div>

      <div class="field-group">
        <label class="field-label">
          Buyer Personas
          <span class="param-count">{{ form.numPersonas }}</span>
        </label>
        <input
          v-model.number="form.numPersonas"
          type="range"
          class="field-slider"
          min="6" max="500" step="1"
        />
        <div class="slider-hints">
          <span>6</span>
          <span>50</span>
          <span>100</span>
          <span>200</span>
          <span>500</span>
        </div>
        <div class="param-note">
          {{ personaCostNote }}
        </div>
      </div>

      <div class="field-group" style="margin-top: 4px">
        <label class="field-label">Message Variants</label>
        <div class="radio-row">
          <label v-for="n in [2, 3, 4, 5]" :key="n" class="radio-option" :class="{ active: form.numMessages === n }">
            <input type="radio" v-model.number="form.numMessages" :value="n" hidden />
            <span class="radio-label">{{ n }}</span>
          </label>
        </div>
        <div class="param-note">Number of outreach angles to generate and test.</div>
      </div>
    </div>

    <!-- Section 05: Optional -->
    <div class="form-section optional-section">
      <div class="section-label">
        05 / Optional
        <button class="toggle-optional" @click="showOptional = !showOptional" type="button">
          {{ showOptional ? '▲ hide' : '▼ show' }}
        </button>
      </div>

      <div v-if="showOptional" class="optional-fields">
        <div class="field-row">
          <div class="field-group half">
            <label class="field-label">Company Stage</label>
            <input v-model="form.companyStage" type="text" class="field-input" placeholder="Pre-seed, Seed, Series A..." />
          </div>
          <div class="field-group half">
            <label class="field-label">Team Size</label>
            <input v-model="form.teamSize" type="text" class="field-input" placeholder="e.g. 8 people, solo founder" />
          </div>
        </div>

        <div class="field-group">
          <label class="field-label">Existing GTM Problems</label>
          <textarea v-model="form.existingProblems" class="field-input field-textarea" placeholder="// What's broken or missing in your current GTM?" rows="2" />
        </div>

        <div class="field-group">
          <label class="field-label">Current Outreach Strategy</label>
          <textarea v-model="form.outreachStrategy" class="field-input field-textarea" placeholder="// What have you already tried?" rows="2" />
        </div>
      </div>
    </div>

    <!-- Submit (hidden when parent page owns the button) -->
    <div v-if="!hideParams" class="form-submit">
      <div v-if="submitAttempted && globalErrors.length" class="global-error">
        {{ globalErrors.length }} field{{ globalErrors.length > 1 ? 's' : '' }} need attention above.
      </div>
      <button class="submit-btn" :disabled="loading" @click="handleSubmit">
        <span v-if="!loading">Run GTM Simulation →</span>
        <span v-else>Building simulation...</span>
      </button>
    </div>

    <!-- Inline submit for SimulatePage (triggers same validation + emit) -->
    <div v-else class="form-submit-inline">
      <div v-if="submitAttempted && globalErrors.length" class="global-error">
        {{ globalErrors.length }} field{{ globalErrors.length > 1 ? 's' : '' }} need attention above.
      </div>
      <button class="submit-btn" :disabled="loading" @click="handleSubmit">
        <span v-if="!loading">Run Simulation →</span>
        <span v-else>Submitting brief...</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, watchEffect } from 'vue'
import { validateGTMBrief, formatGTMBrief } from '../utils/gtmFormatter.js'

const props = defineProps({
  loading: {
    type: Boolean,
    default: false,
  },
  initialData: {
    type: Object,
    default: null,
  },
  hideParams: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['submit'])

const showOptional = ref(false)
const submitAttempted = ref(false)
const touched = reactive({})

const form = reactive({
  productName: '',
  productDescription: '',
  pricingModel: '',
  icp: '',
  targetMarket: '',
  salesChannel: '',
  gtmGoal: '',
  painPoint: '',
  competitors: '',
  numPersonas: 12,
  numMessages: 3,
  companyStage: '',
  teamSize: '',
  existingProblems: '',
  outreachStrategy: '',
})

const personaCostNote = computed(() => {
  const n = form.numPersonas
  const reactions = n * form.numMessages
  const cost = (n * 0.008).toFixed(2)
  if (n <= 12)  return `${n} personas · ${reactions} reactions · fast (~1 min) · ~$${cost}`
  if (n <= 50)  return `${n} personas · ${reactions} reactions · ~2–3 min · ~$${cost}`
  if (n <= 100) return `${n} personas · ${reactions} reactions · ~5–8 min · ~$${cost} — deep signal`
  if (n <= 200) return `${n} personas · ${reactions} reactions · ~10–15 min · ~$${cost} — very deep`
  return `${n} personas · ${reactions} reactions · ~20–40 min · ~$${cost} — exhaustive simulation`
})

function applyInitialData(data) {
  if (!data) return
  Object.assign(form, data)
  // Show optional section if any optional fields are populated
  if (data.companyStage || data.teamSize || data.existingProblems || data.outreachStrategy) {
    showOptional.value = true
  }
}

onMounted(() => applyInitialData(props.initialData))
watch(() => props.initialData, applyInitialData)

const allErrors = computed(() => {
  const errs = validateGTMBrief(form)
  const map = {}
  for (const e of errs) map[e.field] = e.message
  return map
})

const errors = computed(() => {
  const visible = {}
  for (const [field, msg] of Object.entries(allErrors.value)) {
    if (submitAttempted.value || touched[field]) {
      visible[field] = msg
    }
  }
  return visible
})

const globalErrors = computed(() => Object.values(allErrors.value))

function touchField(field) {
  touched[field] = true
}

function handleSubmit() {
  submitAttempted.value = true
  if (globalErrors.value.length > 0) return
  emit('submit', formatGTMBrief(form))
}
</script>

<style scoped>
.gtm-form {
  display: flex;
  flex-direction: column;
  font-family: var(--font-sans);
}

/* Sections */
.form-section {
  border-bottom: 1px solid var(--border-subtle);
  padding: 18px 20px;
  background: var(--bg-card);
}

.form-section:last-of-type {
  border-bottom: none;
}

.optional-section {
  background: var(--bg-surface);
}

.section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Fields */
.field-group { margin-bottom: 14px; }
.field-group:last-child { margin-bottom: 0; }
.field-group.half { flex: 1; min-width: 140px; }

.field-row {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
}

.field-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 5px;
  letter-spacing: 0.02em;
}

.field-hint  { font-weight: 400; color: var(--text-tertiary); margin-left: 4px; }
.required    { color: var(--red); }

.field-input {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-elevated);
  border: 1px solid var(--border-muted);
  border-radius: 5px;
  padding: 9px 11px;
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  -webkit-appearance: none;
}

.field-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(59, 130, 246,0.15);
}

.field-input.error { border-color: var(--red); }

.field-input::placeholder { color: var(--text-tertiary); }

.field-textarea {
  resize: vertical;
  min-height: 80px;
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.6;
}

.field-select {
  cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%238888aa'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 28px;
}

.field-select option {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.field-error {
  display: block;
  font-size: 11px;
  color: var(--red);
  margin-top: 4px;
}

/* Optional toggle */
.toggle-optional {
  background: none;
  border: none;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 0;
  letter-spacing: 0.05em;
  transition: color 0.15s;
}
.toggle-optional:hover { color: var(--text-primary); }

.optional-fields { margin-top: 6px; }

/* Parameters section */
.params-section { background: var(--bg-elevated); }

.param-count {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 800;
  color: var(--accent);
  margin-left: 8px;
}

.field-slider {
  width: 100%;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: linear-gradient(to right, var(--accent) 0%, var(--accent) calc((var(--val, 0)) * 1%), var(--border-muted) calc((var(--val, 0)) * 1%), var(--border-muted) 100%);
  border-radius: 2px;
  outline: none;
  cursor: pointer;
  margin: 10px 0 6px;
  border: none;
  padding: 0;
}

.field-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px; height: 16px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  border: 2px solid var(--bg-card);
  box-shadow: 0 0 6px rgba(59,130,246,0.4);
}

.field-slider::-moz-range-thumb {
  width: 16px; height: 16px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  border: 2px solid var(--bg-card);
}

.slider-hints {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  margin-bottom: 6px;
}

.param-note {
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1.5;
  margin-top: 4px;
}

.radio-row {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}

.radio-option {
  flex: 1;
  border: 1px solid var(--border-muted);
  border-radius: 6px;
  padding: 8px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.radio-option.active {
  border-color: var(--accent);
  background: var(--accent-dim);
}

.radio-label {
  font-size: 14px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.radio-option.active .radio-label { color: var(--accent); }

/* Submit */
.form-submit { padding: 16px 20px; border-top: 1px solid var(--border-subtle); background: var(--bg-card); }
.form-submit-inline { padding: 20px 0 0; }

.global-error {
  font-size: 12px;
  color: var(--red);
  margin-bottom: 10px;
}

.submit-btn {
  width: 100%;
  padding: 12px 20px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.submit-btn:hover:not(:disabled) { background: #2563eb; }
.submit-btn:active:not(:disabled) { transform: translateY(1px); }
.submit-btn:disabled { background: var(--border-muted); cursor: not-allowed; color: var(--text-tertiary); }
</style>
