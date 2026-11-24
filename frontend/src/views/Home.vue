<template>
  <div class="home">

    <!-- Navbar -->
    <header class="nav">
      <div class="container nav-inner">
        <router-link to="/" class="brand">
          <img src="/favicon.svg" alt="" class="brand-mark" width="24" height="24" />
          <span>GTM Simulation Lab</span>
        </router-link>
        <nav class="nav-links" aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#results">Results</a>
          <a href="#example">Example</a>
          <a href="#faq">FAQ</a>
        </nav>
        <div class="nav-actions">
          <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" rel="noopener" class="nav-github">GitHub</a>
          <router-link to="/simulate" class="btn btn-primary btn-sm">Start simulation</router-link>
        </div>
      </div>
    </header>

    <main>

      <!-- Hero -->
      <section class="hero">
        <div class="hero-glow" aria-hidden="true"></div>
        <div class="container hero-inner">
          <div class="hero-copy">
            <div class="pill">
              <span class="pill-dot"></span>
              Open source · Free to run
            </div>
            <h1 class="hero-title">
              Simulate your GTM
              <span class="hero-title-accent">before you launch outreach.</span>
            </h1>
            <p class="hero-sub">
              Describe your product and buyer. AI personas built from your ICP read your cold
              emails, every reaction is scored across repeated runs, and you get the angle to
              lead with, the objections to prepare for, and a 7-day outbound plan.
            </p>
            <div class="hero-actions">
              <router-link to="/simulate" class="btn btn-primary btn-lg">Run a simulation <span aria-hidden="true">→</span></router-link>
              <a href="#example" class="btn btn-ghost btn-lg">See an example</a>
            </div>
            <ul class="hero-meta">
              <li>No signup</li>
              <li>Any OpenAI-compatible model</li>
              <li>AGPL-3.0</li>
            </ul>
          </div>
          <div class="hero-visual">
            <div class="viz-frame">
              <div class="viz-frame-label">Buyer network preview</div>
              <HeroViz />
            </div>
          </div>
        </div>
      </section>

      <!-- KPI row -->
      <section class="kpis" aria-label="By the numbers">
        <div class="container">
          <div class="kpi-grid">
            <div class="kpi" v-for="k in kpis" :key="k.label">
              <div class="kpi-label">{{ k.label }}</div>
              <div class="kpi-value">{{ k.value }}</div>
              <div class="kpi-caption">{{ k.caption }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- Problem -->
      <section class="section section--first">
        <div class="container"><div class="split">
          <div>
            <div class="eyebrow">The problem</div>
            <h2 class="section-title">Most founders test their GTM on real prospects.</h2>
          </div>
          <div class="split-body">
            <p>
              You write a sequence, send it to a few hundred people, and wait. Two weeks later the
              replies are thin and you still don't know why. Was it the segment, the angle, or an
              objection you never addressed? Meanwhile your best accounts have already seen your
              weakest message.
            </p>
            <p>
              GTM Simulation Lab gives you a first read before you send. It won't replace real
              reply data, but it tells you which angle to lead with, which buyers to start with,
              and which objections to answer up front, so your first real test is a sharper one.
            </p>
          </div>
        </div></div>
      </section>

      <!-- How it works -->
      <section class="section" id="how">
        <div class="container">
          <div class="section-head">
            <div class="eyebrow">How it works</div>
            <h2 class="section-title">From brief to outbound plan in five steps.</h2>
            <p class="section-sub">You fill in one form. Everything after that is generated, scored, and summarised for you.</p>
          </div>
          <ol class="steps">
            <li class="step" v-for="(step, i) in steps" :key="step.title">
              <div class="step-num">{{ String(i + 1).padStart(2, '0') }}</div>
              <div class="step-title">{{ step.title }}</div>
              <p class="step-desc">{{ step.desc }}</p>
              <div class="step-out">{{ step.out }}</div>
            </li>
          </ol>
        </div>
      </section>

      <!-- Results you can trust -->
      <section class="section" id="results">
        <div class="container results">
          <div class="results-copy">
            <div class="eyebrow">Results you can trust</div>
            <h2 class="section-title">Signal, not a coin flip.</h2>
            <p class="section-sub">
              A single LLM pass can change its mind on a rerun. The simulator is built so that
              a winner has to earn it.
            </p>
            <ul class="checks">
              <li v-for="c in trust" :key="c.title">
                <svg class="check-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 10.5l3.2 3.2L15 7" /></svg>
                <div>
                  <div class="check-title">{{ c.title }}</div>
                  <div class="check-desc">{{ c.desc }}</div>
                </div>
              </li>
            </ul>
          </div>

          <div class="result-card" role="figure" aria-label="Sample result: average interest by angle">
            <div class="rc-head">
              <div>
                <div class="rc-kicker">Sample run · Acme AI SDR</div>
                <div class="rc-title">Average interest by angle</div>
              </div>
              <span class="status" :class="sampleClose ? 'status--warn' : 'status--good'">
                <svg v-if="sampleClose" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 4.5v4M8 11v.5" /></svg>
                <svg v-else viewBox="0 0 16 16" aria-hidden="true"><path d="M4 8.5l2.5 2.5L12 5.5" /></svg>
                {{ sampleClose ? 'Too close to call' : 'Clear winner' }}
              </span>
            </div>

            <div class="meters">
              <div class="meter-row" v-for="row in sampleRows" :key="row.angle">
                <div class="meter-name">{{ angleLabel(row.angle) }}</div>
                <div class="meter-track"><div class="meter-fill" :style="{ width: row.score * 10 + '%' }"></div></div>
                <div class="meter-value">{{ row.score.toFixed(1) }}</div>
              </div>
              <div class="meter-scale" aria-hidden="true"><span>0</span><span>5</span><span>10</span></div>
            </div>

            <div class="rc-stats">
              <div class="rc-stat">
                <div class="rc-stat-value">{{ sampleGap.toFixed(1) }} pts</div>
                <div class="rc-stat-label">Gap between top two</div>
              </div>
              <div class="rc-stat">
                <div class="rc-stat-value">{{ sampleRows[0]?.positive }} of {{ sampleRows[0]?.total }}</div>
                <div class="rc-stat-label">Interested in top angle</div>
              </div>
              <div class="rc-stat">
                <div class="rc-stat-value">{{ samplePersonaCount }}</div>
                <div class="rc-stat-label">Buyer personas</div>
              </div>
            </div>

            <p class="rc-note">
              {{ sampleClose
                ? 'The top angles are within half a point, so the report tells you to test both with real outbound instead of crowning one.'
                : 'One angle led clearly, so the report recommends leading with it.' }}
            </p>
          </div>
        </div>
      </section>

      <!-- What you get -->
      <section class="section">
        <div class="container">
          <div class="section-head">
            <div class="eyebrow">What you get</div>
            <h2 class="section-title">Everything you need for the first send.</h2>
          </div>
          <div class="feature-grid">
            <div class="feature" v-for="f in features" :key="f.title">
              <div class="feature-icon" aria-hidden="true">{{ f.icon }}</div>
              <div class="feature-title">{{ f.title }}</div>
              <p class="feature-desc">{{ f.desc }}</p>
              <div class="feature-tags">
                <span v-for="t in f.tags" :key="t">{{ t }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Example run -->
      <section class="section" id="example">
        <div class="container">
          <div class="section-head">
            <div class="eyebrow">Example run</div>
            <h2 class="section-title">What you get back.</h2>
            <p class="section-sub">Output from a simulation of Acme AI SDR, an AI sales assistant pitched to seed-stage SaaS founders.</p>
          </div>

          <div class="tabs" role="tablist">
            <button
              v-for="tab in demoTabs"
              :key="tab.id"
              class="tab"
              :class="{ active: activeDemo === tab.id }"
              role="tab"
              :aria-selected="activeDemo === tab.id"
              @click="activeDemo = tab.id"
            >{{ tab.label }}</button>
          </div>

          <div class="panel">
            <!-- Personas -->
            <div v-if="activeDemo === 'personas'">
              <div class="persona-grid">
                <div v-for="p in demoPersonas" :key="p.id" class="persona">
                  <div class="persona-head">
                    <div>
                      <div class="persona-name">{{ p.name }}</div>
                      <div class="persona-role">{{ p.title }}</div>
                    </div>
                    <span class="verdict" :class="`verdict--${p.reaction}`">{{ reactionLabel(p.reaction) }}</span>
                  </div>
                  <div class="persona-field" v-if="p.primary_goal">
                    <div class="field-label">Goal</div>
                    <div class="field-value">{{ p.primary_goal }}</div>
                  </div>
                  <div class="persona-field" v-if="p.objections?.[0]">
                    <div class="field-label">Main objection</div>
                    <div class="field-value">{{ p.objections[0] }}</div>
                  </div>
                </div>
              </div>
              <div class="panel-foot">Plus {{ demoPersonasTotal - demoPersonas.length }} more personas in the full run</div>
            </div>

            <!-- Messages -->
            <div v-if="activeDemo === 'messages'" class="message-grid">
              <div v-for="msg in demoMessages" :key="msg.id" class="message">
                <div class="message-angle">{{ angleLabel(msg.angle) }}</div>
                <div class="message-subject">{{ msg.subject_line }}</div>
                <div class="message-body">{{ msg.body }}</div>
                <div class="message-foot" v-if="demoSummaryFor(msg.id)">
                  <span><strong>{{ demoSummaryFor(msg.id).average_interest_score?.toFixed(1) }}</strong> avg interest</span>
                  <span><strong>{{ demoSummaryFor(msg.id).positive_count }}</strong> interested</span>
                </div>
              </div>
            </div>

            <!-- Report -->
            <div v-if="activeDemo === 'report'" class="report">
              <div class="report-kpis">
                <div class="report-kpi">
                  <div class="kpi-label">ICP fit</div>
                  <div class="report-kpi-value">{{ Math.round((demoReport.best_icp?.confidence_score || 0) * 100) }}%</div>
                </div>
                <div class="report-kpi">
                  <div class="kpi-label">Buyer readiness</div>
                  <div class="report-kpi-value">{{ demoReport.buyer_readiness?.score }}<span>/10</span></div>
                </div>
                <div class="report-kpi">
                  <div class="kpi-label">Lead with</div>
                  <div class="report-kpi-value">{{ angleLabel(demoReport.winning_message?.angle) }}</div>
                </div>
                <div class="report-kpi">
                  <div class="kpi-label">Experiment</div>
                  <div class="report-kpi-value">{{ demoReport.seven_day_experiment?.length || 7 }} days</div>
                </div>
              </div>
              <div class="report-block">
                <div class="field-label">Executive summary</div>
                <p class="report-text">{{ demoReport.executive_summary }}</p>
              </div>
              <div class="report-block" v-if="demoReport.top_objections?.length">
                <div class="field-label">Top objections</div>
                <ul class="objections">
                  <li v-for="(obj, i) in demoReport.top_objections.slice(0, 3)" :key="i">{{ obj.objection }}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Built for -->
      <section class="section">
        <div class="container">
          <div class="section-head">
            <div class="eyebrow">Built for</div>
            <h2 class="section-title">Teams that sell before they scale.</h2>
          </div>
          <div class="audience-grid">
            <div class="audience" v-for="a in audiences" :key="a.title">
              <div class="audience-title">{{ a.title }}</div>
              <p class="audience-desc">{{ a.desc }}</p>
              <ul class="audience-list">
                <li v-for="item in a.items" :key="item">{{ item }}</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <!-- FAQ -->
      <section class="section" id="faq">
        <div class="container faq-wrap">
          <div>
            <div class="eyebrow">FAQ</div>
            <h2 class="section-title">Questions founders ask.</h2>
          </div>
          <div class="faq">
            <details v-for="(q, i) in faqs" :key="q.q" :open="i === 0">
              <summary>{{ q.q }}</summary>
              <p>{{ q.a }}</p>
            </details>
          </div>
        </div>
      </section>

      <!-- Final CTA -->
      <section class="cta">
        <div class="container">
          <div class="cta-card">
            <h2 class="cta-title">Test your next campaign before it ships.</h2>
            <p class="cta-sub">About two minutes from brief to report. No signup, no credit card.</p>
            <div class="hero-actions cta-actions">
              <router-link to="/simulate" class="btn btn-primary btn-lg">Run a simulation <span aria-hidden="true">→</span></router-link>
              <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" rel="noopener" class="btn btn-ghost btn-lg">Star on GitHub</a>
            </div>
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <footer class="footer">
      <div class="container footer-inner">
        <div class="footer-brand">
          <router-link to="/" class="brand">
            <img src="/favicon.svg" alt="" class="brand-mark" width="20" height="20" />
            <span>GTM Simulation Lab</span>
          </router-link>
          <p>Simulate your GTM before launching outreach.</p>
        </div>
        <div class="footer-links">
          <router-link to="/simulate">Start simulation</router-link>
          <a href="#how">How it works</a>
          <a href="#faq">FAQ</a>
          <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" rel="noopener">GitHub</a>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import HeroViz from '../components/HeroViz.vue'
import { MOCK_PERSONAS_FULL } from '../mock/gtm_preview.js'
import { MOCK_MESSAGES, MOCK_REACTIONS_RESULT } from '../mock/gtm_messages.js'
import { MOCK_REPORT } from '../mock/gtm_report.js'

// Headline numbers. Each one is checkable against the default run:
// 12 personas x 3 angles x 3 scoring runs, gpt-4o-mini pricing.
const kpis = [
  { label: 'Scored reactions per run', value: '108', caption: '12 personas × 3 angles × 3 runs' },
  { label: 'Brief to report', value: '~2 min', caption: 'Typical default run' },
  { label: 'API cost per run', value: '~$0.03', caption: 'Estimated on gpt-4o-mini' },
  { label: 'Scores per reaction', value: '4', caption: 'Interest, clarity, trust, urgency' },
]

const steps = [
  { title: 'Write the brief', desc: 'Your product, ICP, pricing, channel, and the goal for this campaign.', out: 'One form' },
  { title: 'Meet your buyers', desc: 'Personas built from your ICP, each with goals, pains, triggers, and objections.', out: '12 personas' },
  { title: 'Draft the angles', desc: 'Cold emails under 80 words, each built on a different angle.', out: '2 to 5 emails' },
  { title: 'Score reactions', desc: 'Every buyer reads every email. Three shuffled runs, scores averaged.', out: '108 scores' },
  { title: 'Get the plan', desc: 'The angle to lead with, rebuttals, risks, and a day-by-day experiment.', out: '7-day plan' },
]

const trust = [
  { title: 'Repeated, not one-shot', desc: 'Every simulation runs three times with personas in a new order. The winner is reported with its win rate.' },
  { title: 'Ties are called ties', desc: 'When angles trade wins across runs, the result is marked too close to call.' },
  { title: 'Each buyer judged alone', desc: 'Personas are scored in small batches against their own goals and skepticism, with no built-in bias about roles.' },
  { title: 'Sample data is labelled', desc: 'If the AI service is down you see clearly marked sample data and the reason, never fake results for your brief.' },
]

const features = [
  { icon: '01', title: 'Buyer personas', desc: 'Generated from your ICP, from eager early adopters to the CFO who signs off. Each has goals, pains, triggers, objections, and a skepticism level.', tags: ['Founders', 'VP Sales', 'RevOps', 'CFOs'] },
  { icon: '02', title: 'Outreach angles', desc: 'Two to five cold emails written from your product context. Under 80 words each, founder voice, no buzzwords.', tags: ['Pain', 'ROI', 'Curiosity', 'Feature', 'Social proof'] },
  { icon: '03', title: 'Scored reactions', desc: 'Every persona scores every email and writes the reply they would send, with their likely objection and buying trigger.', tags: ['Interest', 'Clarity', 'Trust', 'Urgency'] },
  { icon: '04', title: 'A report you can act on', desc: 'The winning angle and its win rate, top objections with rebuttals, your best segment, risks, and a 7-day experiment.', tags: ['Winner', 'Rebuttals', 'Risks', '7-day plan'] },
]

const audiences = [
  { title: 'Founders doing outbound', desc: 'Selling it yourself and hunting for your first ten customers.', items: ['Which buyers lean in, and which push back', 'Which angle to lead your first sequence with', 'The objections to answer before they come up'] },
  { title: 'Teams entering a new segment', desc: 'Moving upmarket or launching a new product line.', items: ['Buyer readiness for the new segment', 'Side-by-side angles across different roles', 'Risks that could stall the launch'] },
  { title: 'Sales leaders writing a playbook', desc: 'Building a repeatable motion before you hire.', items: ['Objection handling from simulated replies', 'Segments ranked by buyer readiness', 'A 7-day experiment to validate before scaling'] },
]

const faqs = [
  { q: 'How accurate is a simulation?', a: 'Treat it as a directional first read, not a forecast. Personas are generated from your brief, so a sharper brief gives a sharper result. Use it to decide what to test first, then confirm the winning angle with a small real send.' },
  { q: 'Which AI model does it use?', a: 'Any OpenAI-compatible API. The hosted version uses gpt-4o-mini through OpenRouter. If you run it yourself, set LLM_BASE_URL and LLM_MODEL_NAME to use the provider and model you prefer.' },
  { q: 'What happens to my brief?', a: 'It is sent to the configured model provider to generate the simulation and saved as JSON files on the server running the app. There is no account and no database. Run it yourself to keep everything on your own machine.' },
  { q: 'What if the AI service is unavailable?', a: 'You will see clearly labelled sample data and the reason it was used. Sample data is never presented as results for your brief.' },
  { q: 'How many personas can I simulate?', a: 'The default is 12, which is what the scoring and cost numbers on this page assume. Larger runs are possible, but start with the default for the most reliable results.' },
  { q: 'Can I run it myself?', a: 'Yes. It is open source under AGPL-3.0, with a Flask backend and a Vue frontend. Clone the repository from GitHub and add an API key.' },
]

// Sample result card: real numbers from the bundled example run.
const summaries = MOCK_REACTIONS_RESULT?.summaries || []
const sampleRows = computed(() =>
  summaries
    .map(s => ({
      angle: s.angle,
      score: s.average_interest_score || 0,
      positive: s.positive_count || 0,
      total: (s.positive_count || 0) + (s.neutral_count || 0) + (s.negative_count || 0),
    }))
    .sort((a, b) => b.score - a.score)
)
const sampleGap = computed(() => {
  const r = sampleRows.value
  return r.length > 1 ? r[0].score - r[1].score : 0
})
const sampleClose = computed(() => Boolean(MOCK_REACTIONS_RESULT?.winner?.close_test) || sampleGap.value < 0.5)
const samplePersonaCount = MOCK_PERSONAS_FULL.length

// Example run tabs
const activeDemo = ref('personas')
const demoTabs = [
  { id: 'personas', label: 'Buyer personas' },
  { id: 'messages', label: 'Message testing' },
  { id: 'report', label: 'GTM report' },
]
const demoPersonas = MOCK_PERSONAS_FULL.slice(0, 3)
const demoPersonasTotal = MOCK_PERSONAS_FULL.length
const demoMessages = MOCK_MESSAGES
const demoReport = MOCK_REPORT

function reactionLabel(reaction) {
  return { interested: 'Interested', neutral: 'Neutral', objection: 'Objection' }[reaction] ?? reaction
}

function angleLabel(angle) {
  return { pain_first: 'Pain-first', roi_first: 'ROI-first', curiosity_first: 'Curiosity-first',
           feature_first: 'Feature-first', social_proof_first: 'Social proof' }[angle] ?? (angle || '')
}

function demoSummaryFor(msgId) {
  return summaries.find(s => s.message_id === msgId)
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  --line: #1f1f1f;
  --line-strong: #2e2e2e;
  --panel: #0b0b0b;
  --ring: rgba(59, 130, 246, 0.35);
}

.container {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
}

a { color: inherit; text-decoration: none; }

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 8px;
  font-weight: 600;
  transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.15s;
  white-space: nowrap;
}
.btn-sm { font-size: 13px; padding: 8px 14px; }
.btn-lg { font-size: 15px; padding: 13px 22px; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent-hover); }
.btn-ghost { border: 1px solid var(--line-strong); color: var(--text-primary); }
.btn-ghost:hover { border-color: #4a4a4a; background: #0d0d0d; }
.btn:active { transform: translateY(1px); }

/* Nav */
.nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--line);
}
.nav-inner {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 650;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.brand-mark { border-radius: 6px; }
.nav-links { display: flex; gap: 28px; }
.nav-links a, .nav-github {
  font-size: 14px;
  color: var(--text-secondary);
  transition: color 0.15s;
}
.nav-links a:hover, .nav-github:hover { color: var(--text-primary); }
.nav-actions { display: flex; align-items: center; gap: 20px; }

/* Hero */
.hero {
  position: relative;
  padding: 104px 0 88px;
  overflow-x: clip;
}
.hero-glow {
  position: absolute;
  inset: -200px 0 auto 0;
  height: 700px;
  background: radial-gradient(ellipse 60% 50% at 30% 40%, rgba(255, 255, 255, 0.05), transparent 70%);
  pointer-events: none;
}
.hero-inner {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: 56px;
  align-items: center;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 28px;
}
.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.15);
}
.hero-title {
  font-size: clamp(40px, 5.6vw, 64px);
  line-height: 1.04;
  letter-spacing: -0.035em;
  font-weight: 700;
  margin-bottom: 24px;
}
.hero-title-accent {
  display: block;
  color: var(--text-secondary);
}
.hero-sub {
  font-size: 18px;
  line-height: 1.65;
  color: var(--text-secondary);
  max-width: 540px;
  margin-bottom: 36px;
}
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; }
.hero-meta {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 28px;
  font-size: 13px;
  color: var(--text-tertiary);
}
.hero-meta li { display: inline-flex; align-items: center; gap: 8px; }
.hero-meta li::before {
  content: '';
  width: 14px;
  height: 14px;
  background: no-repeat center / 14px url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='%2360a5fa' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 10.5l3.2 3.2L15 7'/%3E%3C/svg%3E");
}

/* Borderless network visual, as on the original landing page */
.viz-frame {
  position: relative;
  height: 440px;
  border-radius: 16px;
  overflow: hidden;
  background: transparent;
}
.viz-frame-label {
  position: absolute;
  top: 10px;
  left: 14px;
  z-index: 10;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  opacity: 0.6;
}

/* KPI row (stat tiles) */
.kpis { padding-bottom: 24px; }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  background: var(--line);
  gap: 1px;
}
.kpi {
  background: var(--bg-base);
  padding: 28px 28px 26px;
}
.kpi-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 10px;
}
.kpi-value {
  font-size: 40px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1;
  color: var(--text-primary);
  margin-bottom: 10px;
}
.kpi-caption { font-size: 13px; color: var(--text-tertiary); }

/* Sections */
.section { padding: 112px 0 0; }
.section-head { max-width: 640px; margin-bottom: 48px; }
.eyebrow {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 14px;
}
.section-title {
  font-size: clamp(28px, 3.6vw, 40px);
  line-height: 1.12;
  letter-spacing: -0.03em;
  font-weight: 650;
}
.section-sub {
  margin-top: 16px;
  font-size: 17px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.split {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 64px;
  padding-top: 72px;
  border-top: 1px solid var(--line);
}
.split-body p {
  font-size: 17px;
  line-height: 1.75;
  color: var(--text-secondary);
}
.split-body p + p { margin-top: 20px; }

/* Steps */
.steps {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.step {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 22px 20px;
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.step-num { font-family: var(--font-mono); font-size: 12px; color: var(--text-tertiary); }
.step-title { font-size: 15px; font-weight: 600; }
.step-desc { font-size: 14px; line-height: 1.6; color: var(--text-secondary); flex: 1; }
.step-out {
  align-self: flex-start;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  padding: 4px 10px;
  border-radius: 999px;
  background: #161616;
  border: 1px solid var(--line-strong);
}

/* Results */
.results {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 64px;
  align-items: center;
}
.checks { list-style: none; margin-top: 36px; display: flex; flex-direction: column; gap: 22px; }
.checks li { display: flex; gap: 14px; }
.check-icon {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  padding: 3px;
  border-radius: 6px;
  background: var(--accent-dim);
  fill: none;
  stroke: #60a5fa;
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  margin-top: 1px;
}
.check-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.check-desc { font-size: 14px; line-height: 1.6; color: var(--text-secondary); }

.result-card {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  padding: 28px;
  box-shadow: 0 30px 80px -50px rgba(59, 130, 246, 0.3);
}
.rc-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 28px;
}
.rc-kicker { font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px; }
.rc-title { font-size: 16px; font-weight: 600; }

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 10px 5px 8px;
  border-radius: 999px;
  color: var(--text-primary);
}
.status svg { width: 14px; height: 14px; fill: none; stroke-width: 2; stroke-linecap: round; }
.status--warn { background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); }
.status--warn svg { stroke: var(--amber); }
.status--good { background: rgba(74, 222, 128, 0.1); border: 1px solid rgba(74, 222, 128, 0.3); }
.status--good svg { stroke: var(--green); }

/* Meter list: name, bar, figure per row; one hue, track is a lighter step of the same ramp */
.meters { display: flex; flex-direction: column; gap: 14px; }
.meter-row {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr) 36px;
  align-items: center;
  gap: 14px;
}
.meter-name { font-size: 14px; color: var(--text-secondary); }
.meter-track {
  height: 8px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.14);
  overflow: hidden;
}
.meter-fill { height: 100%; border-radius: 999px; background: var(--accent); }
.meter-value { font-size: 14px; font-weight: 600; text-align: right; color: var(--text-primary); }
.meter-scale {
  display: flex;
  justify-content: space-between;
  margin-left: 126px;
  margin-right: 50px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.rc-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  margin-top: 28px;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--line);
}
.rc-stat { background: var(--panel); padding: 14px 16px; }
.rc-stat-value { font-size: 18px; font-weight: 600; letter-spacing: -0.02em; }
.rc-stat-label { font-size: 12px; color: var(--text-tertiary); margin-top: 4px; }
.rc-note { margin-top: 20px; font-size: 13px; line-height: 1.6; color: var(--text-secondary); }

/* Features */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.feature {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 28px;
  background: var(--panel);
  transition: border-color 0.2s;
}
.feature:hover { border-color: var(--line-strong); }
.feature-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 12px;
  color: #60a5fa;
  background: var(--accent-dim);
  margin-bottom: 20px;
}
.feature-title { font-size: 17px; font-weight: 600; margin-bottom: 10px; }
.feature-desc { font-size: 15px; line-height: 1.65; color: var(--text-secondary); }
.feature-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 20px; }
.feature-tags span {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 3px 9px;
  border-radius: 6px;
  border: 1px solid var(--line-strong);
}

/* Example run */
.tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 10px;
  margin-bottom: 20px;
  max-width: 100%;
  overflow-x: auto;
}
.tab {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  padding: 8px 14px;
  border-radius: 7px;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.tab:hover { color: var(--text-primary); }
.tab.active { background: #1a1a1a; color: var(--text-primary); }

.panel {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  padding: 24px;
}
.panel-foot { margin-top: 18px; font-size: 13px; color: var(--text-tertiary); text-align: center; }

.persona-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.persona {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  background: var(--bg-base);
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.persona-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.persona-name { font-size: 15px; font-weight: 600; }
.persona-role { font-size: 13px; color: var(--text-tertiary); margin-top: 3px; }
.verdict {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--text-primary);
  border: 1px solid var(--line-strong);
}
.verdict::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: 1px;
  background: var(--text-tertiary);
}
.verdict--interested::before { background: var(--green); }
.verdict--neutral::before { background: var(--amber); }
.verdict--objection::before { background: var(--red); }
.field-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}
.field-value { font-size: 14px; line-height: 1.55; color: var(--text-secondary); }

.message-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.message {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  background: var(--bg-base);
  display: flex;
  flex-direction: column;
}
.message-angle { font-size: 12px; font-weight: 600; color: #60a5fa; margin-bottom: 10px; }
.message-subject { font-size: 15px; font-weight: 600; line-height: 1.4; margin-bottom: 12px; }
.message-body {
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-secondary);
  white-space: pre-line;
  flex: 1;
}
.message-foot {
  display: flex;
  gap: 16px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  font-size: 13px;
  color: var(--text-tertiary);
}
.message-foot strong { color: var(--text-primary); font-weight: 600; }

.report { display: flex; flex-direction: column; gap: 24px; }
.report-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
.report-kpi { background: var(--bg-base); padding: 18px 20px; }
.report-kpi .kpi-label { margin-bottom: 8px; }
.report-kpi-value { font-size: 24px; font-weight: 600; letter-spacing: -0.02em; }
.report-kpi-value span { font-size: 14px; color: var(--text-tertiary); font-weight: 500; }
.report-text { font-size: 15px; line-height: 1.7; color: var(--text-secondary); max-width: 820px; }
.objections { list-style: none; display: flex; flex-direction: column; gap: 8px; }
.objections li {
  font-size: 14px;
  color: var(--text-secondary);
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-base);
}

/* Audience */
.audience-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.audience {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 28px;
  background: var(--panel);
}
.audience-title { font-size: 17px; font-weight: 600; margin-bottom: 8px; }
.audience-desc { font-size: 15px; line-height: 1.6; color: var(--text-secondary); margin-bottom: 20px; }
.audience-list { list-style: none; display: flex; flex-direction: column; gap: 10px; }
.audience-list li {
  font-size: 14px;
  color: var(--text-secondary);
  padding-left: 18px;
  position: relative;
  line-height: 1.5;
}
.audience-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

/* FAQ */
.faq-wrap {
  display: grid;
  grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
  gap: 64px;
}
.faq { border-top: 1px solid var(--line); }
.faq details { border-bottom: 1px solid var(--line); }
.faq summary {
  list-style: none;
  cursor: pointer;
  padding: 22px 36px 22px 0;
  font-size: 16px;
  font-weight: 600;
  position: relative;
}
.faq summary::-webkit-details-marker { display: none; }
.faq summary::after {
  content: '+';
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 20px;
  font-weight: 400;
  color: var(--text-tertiary);
  transition: transform 0.2s;
}
.faq details[open] summary::after { transform: translateY(-50%) rotate(45deg); }
.faq summary:hover { color: #fff; }
.faq details p {
  padding: 0 36px 24px 0;
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-secondary);
}

/* CTA */
.cta { padding: 112px 0; }
.cta-card {
  position: relative;
  text-align: center;
  padding: 72px 32px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background:
    radial-gradient(ellipse 50% 80% at 50% 0%, rgba(59, 130, 246, 0.14), transparent 70%),
    var(--panel);
  overflow: hidden;
}
.cta-title {
  font-size: clamp(28px, 4vw, 44px);
  letter-spacing: -0.03em;
  line-height: 1.1;
  font-weight: 650;
}
.cta-sub { margin-top: 16px; font-size: 17px; color: var(--text-secondary); }
.cta-actions { justify-content: center; margin-top: 32px; }

/* Footer */
.footer { border-top: 1px solid var(--line); padding: 40px 0 48px; }
.footer-inner {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 32px;
  flex-wrap: wrap;
}
.footer-brand p { margin-top: 10px; font-size: 13px; color: var(--text-tertiary); }
.footer-links { display: flex; flex-wrap: wrap; gap: 12px 28px; }
.footer-links a { font-size: 14px; color: var(--text-secondary); transition: color 0.15s; }
.footer-links a:hover { color: var(--text-primary); }

/* Responsive */
@media (max-width: 1024px) {
  .nav-links { display: none; }
  .hero-inner, .results, .split, .faq-wrap { grid-template-columns: 1fr; gap: 48px; }
  .hero { padding: 72px 0 64px; }
  .viz-frame { height: 360px; }
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .steps { grid-template-columns: repeat(2, 1fr); }
  .persona-grid, .message-grid, .audience-grid { grid-template-columns: 1fr; }
  .report-kpis { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 640px) {
  .container { padding: 0 16px; }
  .nav-github { display: none; }
  .hero-sub { font-size: 16px; }
  .section { padding-top: 80px; }
  .section-head { margin-bottom: 32px; }
  .kpi { padding: 20px; }
  .kpi-value { font-size: 30px; }
  .steps, .feature-grid { grid-template-columns: 1fr; }
  .meter-row { grid-template-columns: 92px minmax(0, 1fr) 32px; gap: 10px; }
  .meter-scale { margin-left: 102px; margin-right: 42px; }
  .rc-stats { grid-template-columns: 1fr; }
  .result-card, .panel, .feature, .audience { padding: 20px; }
  .cta { padding: 80px 0; }
  .cta-card { padding: 48px 20px; }
  .split { padding-top: 56px; }
}
</style>
