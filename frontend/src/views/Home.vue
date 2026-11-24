<template>
  <div class="home-container">

    <!-- ── Navbar ─────────────────────────────────────────────── -->
    <nav class="navbar">
      <div class="nav-brand">GTM SIM LAB</div>
      <div class="nav-links">
        <router-link to="/simulate" class="nav-cta">Start Simulation</router-link>
        <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" class="github-link">
          GitHub <span class="arrow">↗</span>
        </a>
      </div>
    </nav>

    <div class="main-content">

      <!-- ── Hero ──────────────────────────────────────────────── -->
      <section class="hero-section">
        <div class="hero-orb hero-orb-1"></div>
        <div class="hero-orb hero-orb-2"></div>

        <!-- Left: copy -->
        <div class="hero-left">
        <div class="hero-eyebrow">
          <span class="hero-badge">AI-Powered GTM Lab</span>
          <span class="hero-version">v0.1 · Open Source</span>
        </div>

        <h1 class="hero-title">
          Simulate your GTM<br>
          <span class="hero-title-accent">before you launch outreach.</span>
        </h1>

        <p class="hero-sub">
          Enter a product brief. Get 12 AI-generated buyer personas, 3 outreach angles
          tested against each one, 36 simulated reactions with scores and objections,
          and a GTM report with a 7-day outbound experiment plan — in under 2 minutes.
        </p>

        <div class="hero-actions">
          <router-link to="/simulate" class="btn-hero-primary">Run a Simulation →</router-link>
          <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" class="btn-hero-ghost">View on GitHub ↗</a>
        </div>

        <div class="hero-stats">
          <div class="hero-stat">
            <span class="hero-stat-num">{{ stat1 }}</span>
            <span class="hero-stat-label">Buyer Personas</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">{{ stat2 }}</span>
            <span class="hero-stat-label">Message Angles</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">{{ stat3 }}</span>
            <span class="hero-stat-label">Buyer Reactions</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">~$5</span>
            <span class="hero-stat-label">Per Simulation</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">&lt;2 min</span>
            <span class="hero-stat-label">End to End</span>
          </div>
        </div>
        </div><!-- /hero-left -->

        <!-- Right: live agent network visualization -->
        <div class="hero-right">
          <div class="hviz-frame">
            <div class="hviz-frame-label">Live simulation preview</div>
            <HeroViz />
          </div>
        </div>

      </section>

      <!-- ── Problem ────────────────────────────────────────────── -->
      <section class="problem-section reveal">
        <div class="problem-inner">
          <div class="problem-label">The problem</div>
          <h2 class="problem-title">Founders test their GTM assumptions on real customers.</h2>
          <p class="problem-body">
            Most B2B founders spend weeks crafting cold outreach, only to discover the hard way that
            their ICP doesn't respond, their messaging misses the core objection, or they're
            targeting the wrong segment entirely. By the time real reply data comes in, the damage
            is done — wasted sends, lost time, and no clear direction on what to fix.
          </p>
          <p class="problem-body">
            GTM Simulation Lab gives you signal before you send. Run a full simulation of how your
            target buyers would respond to your outreach — before you spend a single credit on
            an email sequence.
          </p>
        </div>
      </section>

      <!-- ── What you get ──────────────────────────────────────── -->
      <section class="features-section reveal">
        <div class="section-eyebrow">What the simulation produces</div>
        <div class="features-grid">

          <div class="feature-card">
            <div class="feature-title">12 AI Buyer Personas</div>
            <div class="feature-desc">
              ICP-specific archetypes generated from your brief — each with distinct goals,
              pain points, buying triggers, objections, budget sensitivity, and skepticism level.
              Covers the full spectrum from eager early adopters to skeptical CFOs.
            </div>
            <div class="feature-tag">Founder Sellers · VP Sales · CFOs · SDR Managers · 8 more</div>
          </div>

          <div class="feature-card">
            <div class="feature-title">3 Outreach Angles Tested</div>
            <div class="feature-desc">
              Pain-first, ROI-first, and Curiosity-first message variants — written by the AI
              against your product context and tested simultaneously against all 12 personas.
              Each message is under 80 words, founder-style, no buzzwords.
            </div>
            <div class="feature-tag">Pain-First · ROI-First · Curiosity-First</div>
          </div>

          <div class="feature-card">
            <div class="feature-title">36 Simulated Buyer Reactions</div>
            <div class="feature-desc">
              Every persona × message combination generates an interest score, clarity score,
              trust score, likely objection, buying trigger, and a realistic simulated reply —
              so you know exactly where each angle lands.
            </div>
            <div class="feature-tag">Interest · Clarity · Trust · Objection · Simulated Reply</div>
          </div>

          <div class="feature-card feature-card--accent">
            <div class="feature-title">GTM Report + 7-Day Experiment</div>
            <div class="feature-desc">
              Winning angle with reasoning, top objections with suggested rebuttals, best-fit ICP
              segment, risk signals, a recommended agentic workflow, and a day-by-day 7-day
              outbound execution plan you can run immediately.
            </div>
            <div class="feature-tag">Winner Analysis · Rebuttals · Risk Signals · 7-Day Plan</div>
          </div>

        </div>
      </section>

      <!-- ── How it works ──────────────────────────────────────── -->
      <section class="hiw-section reveal">
        <div class="section-eyebrow">How it works</div>
        <h2 class="section-title">Five steps from brief to outbound plan.</h2>

        <div class="hiw-steps-full">
          <div class="hiw-step-full" v-for="(step, i) in steps" :key="i">
            <div class="hiw-sf-num">{{ String(i + 1).padStart(2, '0') }}</div>
            <div class="hiw-sf-title">{{ step.title }}</div>
            <div class="hiw-sf-desc">{{ step.desc }}</div>
          </div>
        </div>

        <div class="hiw-note">
          The simulation runs in under 2 minutes with a connected LLM API. No account required.
          Runs instantly in mock mode without an API key.
        </div>
      </section>

      <!-- ── Who it's for ──────────────────────────────────────── -->
      <section class="for-section reveal">
        <div class="section-eyebrow">Built for</div>
        <h2 class="section-title">GTM-focused founders and sales teams.</h2>

        <div class="for-grid">
          <div class="for-card">
            <div class="for-title">B2B Founders (1–25 employees)</div>
            <div class="for-desc">
              Doing founder-led cold outbound and looking for their first 10 customers.
              Use the simulation to validate ICP assumptions and find the message that
              actually gets replies — before launching a full sequence.
            </div>
            <ul class="for-list">
              <li>Which personas are most likely to convert</li>
              <li>Which message angle opens the most doors</li>
              <li>What objections to expect and how to handle them</li>
            </ul>
          </div>

          <div class="for-card">
            <div class="for-title">GTM Teams Entering a New Segment</div>
            <div class="for-desc">
              Launching a new product line or moving upmarket. Use the simulation to
              pressure-test your new ICP before committing your outbound motion and
              SDR headcount to the wrong hypothesis.
            </div>
            <ul class="for-list">
              <li>Buyer readiness scoring for the new segment</li>
              <li>Side-by-side angle comparison across different personas</li>
              <li>Risk signals that could derail the new market entry</li>
            </ul>
          </div>

          <div class="for-card">
            <div class="for-title">Sales Leaders Building a Playbook</div>
            <div class="for-desc">
              Building a repeatable cold outbound process before scaling the team.
              Use the simulation to create a documented, data-backed playbook so new
              SDRs and AEs ramp faster on the right message.
            </div>
            <ul class="for-list">
              <li>Objection handling scripts derived from simulated reactions</li>
              <li>ICP prioritization based on buyer readiness scores</li>
              <li>Structured 7-day experiment to validate before scaling</li>
            </ul>
          </div>
        </div>
      </section>

      <!-- ── Sample output ─────────────────────────────────────── -->
      <section class="sample-section reveal">
        <div class="section-eyebrow">Sample output</div>
        <h2 class="section-title">Here's what you'll see after a simulation.</h2>

        <div class="sample-grid">

          <!-- Sample persona card -->
          <div class="sample-block">
            <div class="sample-block-label">Buyer Persona</div>
            <div class="sample-persona-card">
              <div class="spc-header">
                <div>
                  <div class="spc-name">Marcus Rivera</div>
                  <div class="spc-title">VP Sales · Series A SaaS · 45 employees</div>
                </div>
                <span class="spc-badge spc-badge--interested">✓ Interested</span>
              </div>
              <div class="spc-row">
                <span class="spc-label">GOAL</span>
                <span class="spc-val">Hit $2M ARR this year by scaling SDR outbound from 3 to 7 reps.</span>
              </div>
              <div class="spc-row">
                <span class="spc-label">OBJECTION</span>
                <span class="spc-chip">What's the actual meeting booking lift vs. our current process?</span>
              </div>
              <div class="spc-row">
                <span class="spc-label">SKEPTICISM</span>
                <div class="spc-skep">
                  <div class="spc-seg spc-seg--filled"></div>
                  <div class="spc-seg spc-seg--filled"></div>
                  <div class="spc-seg spc-seg--filled"></div>
                  <div class="spc-seg"></div>
                  <div class="spc-seg"></div>
                  <span class="spc-skep-label">3 / 5</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Sample reaction row -->
          <div class="sample-block">
            <div class="sample-block-label">Simulated Reaction (ROI-First angle)</div>
            <div class="sample-reaction-card">
              <div class="src-scores">
                <div class="src-score">
                  <span class="src-score-num src-green">8.2</span>
                  <span class="src-score-label">Interest</span>
                </div>
                <div class="src-score">
                  <span class="src-score-num src-amber">6.8</span>
                  <span class="src-score-label">Trust</span>
                </div>
                <div class="src-score">
                  <span class="src-score-num src-green">7.5</span>
                  <span class="src-score-label">Clarity</span>
                </div>
                <div class="src-verdict src-verdict--interested">✓ Interested</div>
              </div>
              <div class="src-reply">
                "40% more meetings is a strong claim. Was that team at our stage?
                Share the case study and I'll loop in my ops lead."
              </div>
              <div class="src-trigger">
                <span class="src-trigger-label">Buying trigger:</span>
                Peer-validated case study from a similarly sized team with the same sales motion.
              </div>
            </div>
          </div>

          <!-- Sample report snippet -->
          <div class="sample-block sample-block--wide">
            <div class="sample-block-label">GTM Report — Winner + Top Objections</div>
            <div class="sample-report-card">
              <div class="srep-winner">
                <span class="srep-star">WINNER</span>
                <div>
                  <div class="srep-winner-label">WINNING ANGLE</div>
                  <div class="srep-winner-angle">ROI-First</div>
                  <div class="srep-winner-stats">7.1 avg interest · 8 interested · 3 neutral · 1 objection</div>
                </div>
              </div>
              <div class="srep-divider"></div>
              <div class="srep-objections">
                <div class="srep-obj-label">TOP OBJECTIONS</div>
                <div class="srep-obj-item">
                  <span class="srep-obj-freq">×4</span>
                  <span class="srep-obj-text">Show me the methodology — sounds like vendor math</span>
                </div>
                <div class="srep-obj-item">
                  <span class="srep-obj-freq">×3</span>
                  <span class="srep-obj-text">We already have a sales engagement tool for this</span>
                </div>
                <div class="srep-obj-item">
                  <span class="srep-obj-freq">×3</span>
                  <span class="srep-obj-text">What's the payback period and total cost?</span>
                </div>
              </div>
            </div>
          </div>

        </div>
      </section>

      <!-- ── Demo Showcase ───────────────────────────────────── -->
      <section class="demo-section reveal" id="demo">
        <div class="section-eyebrow">Example output</div>
        <h2 class="section-title">See what a real simulation produces.</h2>
        <p class="demo-sub">AI-generated output from a real simulation run — Acme AI SDR targeting seed-stage SaaS founders.</p>

        <!-- Tab bar -->
        <div class="demo-tabs">
          <button
            v-for="tab in demoTabs"
            :key="tab.id"
            class="demo-tab"
            :class="{ active: activeDemo === tab.id }"
            @click="activeDemo = tab.id"
          >{{ tab.label }}</button>
        </div>

        <!-- Tab: Personas -->
        <div v-if="activeDemo === 'personas'" class="demo-panel">
          <div class="demo-personas-grid">
            <div
              v-for="p in demoPersonas"
              :key="p.id"
              class="demo-persona-card"
              :class="`demo-persona-card--${p.reaction}`"
            >
              <div class="dpc-header">
                <div>
                  <div class="dpc-name">{{ p.name }}</div>
                  <div class="dpc-title">{{ p.title }}</div>
                </div>
                <span class="dpc-verdict" :class="`dpc-verdict--${p.reaction}`">{{ reactionLabel(p.reaction) }}</span>
              </div>
              <div class="dpc-goal" v-if="p.primary_goal">{{ p.primary_goal }}</div>
              <div class="dpc-objection" v-if="p.objections?.[0]">{{ p.objections[0] }}</div>
            </div>
          </div>
          <div class="demo-more">+ {{ demoPersonasTotal - demoPersonas.length }} more personas generated in a full run</div>
        </div>

        <!-- Tab: Messages -->
        <div v-if="activeDemo === 'messages'" class="demo-panel">
          <div class="demo-messages-grid">
            <div
              v-for="msg in demoMessages"
              :key="msg.id"
              class="demo-msg-card"
              :class="{ 'demo-msg-card--winner': msg.angle === demoWinnerAngle }"
            >
              <div class="dmc-header">
                <span class="dmc-angle">{{ angleLabel(msg.angle) }}</span>
                <span v-if="msg.angle === demoWinnerAngle" class="dmc-winner-badge">WINNER</span>
              </div>
              <div class="dmc-subject">{{ msg.subject_line }}</div>
              <div class="dmc-body">{{ msg.body }}</div>
              <div class="dmc-scores" v-if="demoSummaryFor(msg.id)">
                <span class="dmc-score" :style="{color: scoreColor(demoSummaryFor(msg.id).average_interest_score)}">
                  {{ demoSummaryFor(msg.id).average_interest_score?.toFixed(1) }} avg interest
                </span>
                <span class="dmc-dot">·</span>
                <span class="dmc-score-green">{{ demoSummaryFor(msg.id).positive_count }} interested</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab: Report -->
        <div v-if="activeDemo === 'report'" class="demo-panel">
          <div class="demo-report-wrap">
            <!-- Metric strip -->
            <div class="demo-metrics">
              <div class="dm-metric">
                <div class="dm-val">{{ Math.round((demoReport.best_icp?.confidence_score || 0) * 100) }}%</div>
                <div class="dm-label">ICP Fit</div>
              </div>
              <div class="dm-metric">
                <div class="dm-val">{{ demoReport.buyer_readiness?.score }}/10</div>
                <div class="dm-label">Buyer Readiness</div>
              </div>
              <div class="dm-metric">
                <div class="dm-val">{{ angleLabel(demoReport.winning_message?.angle) }}</div>
                <div class="dm-label">Winning Angle</div>
              </div>
              <div class="dm-metric">
                <div class="dm-val">{{ demoReport.seven_day_experiment?.length || 7 }}-Day</div>
                <div class="dm-label">Experiment Plan</div>
              </div>
            </div>
            <!-- Summary -->
            <div class="demo-summary">
              <div class="demo-summary-label">Executive Summary</div>
              <p class="demo-summary-text">{{ demoReport.executive_summary }}</p>
            </div>
            <!-- Top objections -->
            <div class="demo-objections" v-if="demoReport.top_objections?.length">
              <div class="demo-summary-label">Top Objections</div>
              <div v-for="(obj, i) in demoReport.top_objections.slice(0, 3)" :key="i" class="demo-obj-row">
                <span class="demo-obj-freq">×{{ obj.frequency }}</span>
                <span class="demo-obj-text">{{ obj.objection }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- CTA -->
        <div class="demo-cta">
          <router-link to="/simulate" class="btn-hero-primary">Launch Simulator →</router-link>
          <span class="demo-cta-note">Takes ~2 min · Uses your LLM API key · No account needed</span>
        </div>
      </section>

      <!-- ── Footer ─────────────────────────────────────────────── -->
      <footer class="home-footer">
        <span>GTM Simulation Lab — open source</span>
        <span class="home-footer-sep">·</span>
        <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" rel="noopener" class="home-footer-link">GitHub ↗</a>
        <span class="home-footer-sep">·</span>
        <span>Forked from <a href="https://github.com/666ghj/MiroFish" target="_blank" rel="noopener" class="home-footer-link">MiroFish ↗</a></span>
      </footer>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import HeroViz from '../components/HeroViz.vue'
import { MOCK_PERSONAS_FULL } from '../mock/gtm_preview.js'
import { MOCK_MESSAGES, MOCK_REACTIONS_RESULT } from '../mock/gtm_messages.js'
import { MOCK_REPORT } from '../mock/gtm_report.js'

const steps = [
  { title: 'Input Brief',      desc: 'Describe your product, ICP, pricing, and GTM goal.' },
  { title: 'Buyer Personas',   desc: 'AI generates buyer archetypes tailored to your ICP.' },
  { title: 'Message Testing',  desc: 'Multiple outreach angles tested against every persona.' },
  { title: 'Buyer Reactions',  desc: 'Each persona responds with interest scores, objections, and a simulated reply.' },
  { title: 'GTM Report',       desc: 'Best angle, top objections with rebuttals, and a 7-day outbound experiment plan.' },
]

// Count-up stats
const stat1 = ref(0)
const stat2 = ref(0)
const stat3 = ref(0)

function countUp(setter, target, duration = 1200) {
  const start = performance.now()
  const tick = (now) => {
    const t = Math.min((now - start) / duration, 1)
    const ease = 1 - Math.pow(1 - t, 3)
    setter(Math.round(ease * target))
    if (t < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

let revealObserver = null

onMounted(() => {
  setTimeout(() => countUp(v => { stat1.value = v }, 12), 200)
  setTimeout(() => countUp(v => { stat2.value = v }, 3, 600), 350)
  setTimeout(() => countUp(v => { stat3.value = v }, 36), 500)
  revealObserver = new IntersectionObserver(
    (entries) => entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('revealed') }),
    { threshold: 0.12 }
  )
  document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el))
})

onUnmounted(() => { if (revealObserver) revealObserver.disconnect() })

// Demo showcase data
const activeDemo = ref('personas')
const demoTabs = [
  { id: 'personas', label: 'Buyer Personas' },
  { id: 'messages', label: 'Message Testing' },
  { id: 'report',   label: 'GTM Report' },
]
const demoPersonas = MOCK_PERSONAS_FULL.slice(0, 3)
const demoPersonasTotal = MOCK_PERSONAS_FULL.length
const demoMessages = MOCK_MESSAGES
const demoWinnerAngle = MOCK_REACTIONS_RESULT?.winner?.winner_angle
const demoReport = MOCK_REPORT

function reactionLabel(reaction) {
  return { interested: 'Interested', neutral: 'Neutral', objection: 'Objection' }[reaction] ?? reaction
}

function angleLabel(angle) {
  return { pain_first: 'Pain-First', roi_first: 'ROI-First', curiosity_first: 'Curiosity-First',
           feature_first: 'Feature-First', social_proof_first: 'Social Proof' }[angle] ?? (angle || '')
}

function scoreColor(n) {
  if (!n) return 'var(--text-secondary)'
  if (n >= 7) return 'var(--green)'
  if (n >= 5) return 'var(--amber)'
  return 'var(--red)'
}

function demoSummaryFor(msgId) {
  return (MOCK_REACTIONS_RESULT?.summaries || []).find(s => s.message_id === msgId)
}
</script>

<style scoped>
/* ── Shell ───────────────────────────────────────────────────── */
.home-container {
  min-height: 100vh;
  background: var(--bg-base);
  font-family: var(--font-sans);
  color: var(--text-primary);
}

/* ── Navbar ──────────────────────────────────────────────────── */
.navbar {
  height: 56px;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 40px;
  position: sticky;
  top: 0;
  z-index: 20;
}

.nav-brand {
  font-family: var(--font-mono);
  font-weight: 800;
  letter-spacing: 0.1em;
  font-size: 13px;
  color: var(--text-primary);
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 16px;
}

.github-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: color 0.15s;
}

.github-link:hover { color: var(--text-primary); }
.arrow { font-size: 11px; }

/* ── Main content wrapper ────────────────────────────────────── */
.main-content {
  max-width: 1160px;
  margin: 0 auto;
  padding: 64px 40px 0;
}

/* ── Hero ────────────────────────────────────────────────────── */
.hero-section {
  display: grid;
  grid-template-columns: 1fr 480px;
  gap: 48px;
  align-items: center;
  padding-bottom: 80px;
  border-bottom: 1px solid var(--border-subtle);
  position: relative;
  overflow-x: clip; /* keep the drifting glow from causing sideways scroll on phones */
}

.hero-left {
  max-width: 580px;
}

.hero-right {
  align-self: center;
}

.hviz-frame {
  border-radius: 16px;
  overflow: hidden;
  height: 440px;
  position: relative;
  background: transparent;
}

.hviz-frame-label {
  position: absolute;
  top: 10px;
  left: 14px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  z-index: 10;
  font-family: var(--font-mono);
  opacity: 0.6;
}

.hero-eyebrow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.hero-badge {
  background: var(--accent-dim);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 20px;
}

.hero-version {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.hero-title {
  font-size: 3.2rem;
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1.15;
  color: var(--text-primary);
  margin: 0 0 20px;
}

.hero-title-accent {
  color: var(--accent);
}

.hero-sub {
  font-size: 1rem;
  line-height: 1.7;
  color: var(--text-secondary);
  max-width: 600px;
  margin: 0 0 32px;
}

.hero-stats {
  display: flex;
  align-items: center;
  gap: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 0;
  overflow: hidden;
  width: 100%;
}

.hero-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1 1 0;
  min-width: 0;
  padding: 14px 8px;
  gap: 3px;
}

.hero-stat-sep {
  width: 1px;
  height: 36px;
  background: var(--border-subtle);
  flex-shrink: 0;
}

.hero-stat-num {
  font-size: 20px;
  font-weight: 700;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.hero-stat-label {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

/* ── Main section: How it works + Form ───────────────────────── */
.main-section {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 48px;
  align-items: start;
  border-top: 1px solid var(--border-subtle);
  padding-top: 48px;
}

/* ── Left: How it works ─────────────────────────────────────── */
.how-it-works {
  position: sticky;
  top: 80px;
}

.hiw-header {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 24px;
}

.hiw-steps {
  display: flex;
  flex-direction: column;
}

.hiw-step {
  display: flex;
  gap: 16px;
}

.hiw-step-left {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 28px;
  flex-shrink: 0;
}

.hiw-step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  flex-shrink: 0;
}

.hiw-step-line {
  width: 1px;
  flex: 1;
  min-height: 20px;
  background: var(--border-subtle);
  margin: 4px 0;
}

.hiw-step-content {
  padding-bottom: 20px;
}

.hiw-step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.hiw-step-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* ── keyframes (used by demo panel + spinners elsewhere) ──── */
@keyframes spin  { to { transform: rotate(360deg); } }
@keyframes pulse { 50% { opacity: 0.4; } }

/* ── Buttons ────────────────────────────────────────────────── */
.btn-primary {
  flex: 1;
  padding: 11px 18px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  text-align: center;
}

.btn-primary:hover { background: #2563eb; }

.btn-ghost {
  padding: 11px 14px;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 7px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
  white-space: nowrap;
}

.btn-ghost:hover { border-color: var(--text-secondary); color: var(--text-primary); }

/* ── Footer ─────────────────────────────────────────────────── */
.home-footer {
  margin-top: 64px;
  padding: 20px 0 32px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.home-footer-sep { color: var(--border-muted); }

.home-footer-link {
  color: var(--text-secondary);
  text-decoration: none;
  transition: color 0.15s;
}

.home-footer-link:hover { color: var(--text-primary); }

/* ── Navbar CTA ─────────────────────────────────────────────── */
.nav-cta {
  background: var(--accent);
  color: #fff;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  padding: 7px 16px;
  border-radius: 7px;
  transition: background 0.15s;
}
.nav-cta:hover { background: #2563eb; }

/* ── Hero actions ───────────────────────────────────────────── */
.hero-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 36px;
}

.btn-hero-primary {
  background: var(--accent);
  color: #fff;
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  padding: 12px 24px;
  border-radius: 8px;
  transition: background 0.15s;
}
.btn-hero-primary:hover { background: #2563eb; }

.btn-hero-ghost {
  background: transparent;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  padding: 12px 20px;
  border-radius: 8px;
  border: 1px solid var(--border-muted);
  transition: color 0.15s, border-color 0.15s;
}
.btn-hero-ghost:hover { color: var(--text-primary); border-color: var(--text-secondary); }

/* ── Shared section structure ───────────────────────────────── */
.section-eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 12px;
}

.section-title {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  margin: 0 0 40px;
  line-height: 1.2;
}

/* ── Problem section ────────────────────────────────────────── */
.problem-section {
  padding: 72px 0;
}

.problem-inner {
  max-width: 680px;
}

.problem-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 16px;
}

.problem-title {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  margin: 0 0 20px;
  line-height: 1.25;
}

.problem-body {
  font-size: 1rem;
  line-height: 1.75;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

/* ── Feature cards ──────────────────────────────────────────── */
.features-section {
  padding: 72px 0;
  border-top: 1px solid var(--border-subtle);
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.feature-card {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 24px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.feature-card--accent {
  background: var(--bg-elevated);
  border-color: rgba(59, 130, 246,0.3);
}


.feature-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.3;
}

.feature-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
  flex: 1;
}

.feature-tag {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-surface);
  border-radius: 4px;
  padding: 4px 8px;
  line-height: 1.4;
}

/* ── How it works (full) ────────────────────────────────────── */
.hiw-section {
  padding: 72px 0;
  border-top: 1px solid var(--border-subtle);
}

.hiw-steps-full {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0;
  margin-bottom: 28px;
  position: relative;
}

.hiw-steps-full::before {
  content: '';
  position: absolute;
  top: 18px;
  left: 5%;
  right: 5%;
  height: 1px;
  background: var(--border-muted);
  z-index: 0;
}

.hiw-step-full {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 0 12px;
  position: relative;
  z-index: 1;
}

.hiw-sf-num {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 2px solid var(--border-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 14px;
  flex-shrink: 0;
}

.hiw-sf-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.hiw-sf-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.hiw-note {
  font-size: 13px;
  color: var(--text-tertiary);
  text-align: center;
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
}

/* ── Who it's for ───────────────────────────────────────────── */
.for-section {
  padding: 72px 0;
  border-top: 1px solid var(--border-subtle);
}

.for-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.for-card {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 28px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 12px;
}


.for-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.3;
}

.for-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
}

.for-list {
  list-style: none;
  padding: 0;
  margin: 0;
  border-top: 1px solid var(--border-subtle);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.for-list li {
  font-size: 12px;
  color: var(--text-secondary);
  padding-left: 14px;
  position: relative;
  line-height: 1.5;
}

.for-list li::before {
  content: '→';
  position: absolute;
  left: 0;
  color: var(--accent);
  font-size: 11px;
}

/* ── Sample output ──────────────────────────────────────────── */
.sample-section {
  padding: 72px 0;
  border-top: 1px solid var(--border-subtle);
}

.sample-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.sample-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sample-block--wide {
  grid-column: 1 / -1;
}

.sample-block-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

/* Sample persona card */
.sample-persona-card {
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--green);
  border-radius: 10px;
  padding: 18px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.spc-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.spc-name { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.spc-title { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

.spc-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.spc-badge--interested { background: rgba(74,222,128,0.15); color: var(--green); }

.spc-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 12px;
}

.spc-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
  text-transform: uppercase;
  min-width: 70px;
  padding-top: 2px;
}

.spc-val { color: var(--text-primary); line-height: 1.5; }

.spc-chip {
  font-size: 11px;
  color: var(--red);
  background: rgba(248,113,113,0.12);
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 4px;
  padding: 2px 8px;
  line-height: 1.5;
}

.spc-skep { display: flex; align-items: center; gap: 3px; }

.spc-seg {
  width: 10px;
  height: 4px;
  border-radius: 2px;
  background: var(--border-muted);
}

.spc-seg--filled { background: var(--amber); }

.spc-skep-label { font-size: 11px; color: var(--text-secondary); margin-left: 6px; }

/* Sample reaction card */
.sample-reaction-card {
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
  padding: 18px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.src-scores {
  display: flex;
  gap: 16px;
  align-items: center;
}

.src-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.src-score-num {
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
}

.src-score-label { font-size: 10px; color: var(--text-tertiary); }

.src-green  { color: var(--green); }
.src-amber  { color: var(--amber); }

.src-verdict {
  margin-left: auto;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 4px;
}

.src-verdict--interested { background: rgba(74,222,128,0.15); color: var(--green); }

.src-reply {
  font-size: 13px;
  font-style: italic;
  color: var(--text-secondary);
  line-height: 1.6;
  padding: 10px 14px;
  background: var(--bg-elevated);
  border-radius: 6px;
  border-left: 2px solid var(--border-muted);
}

.src-trigger {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.src-trigger-label { font-weight: 700; color: var(--text-primary); }

/* Sample report card */
.sample-report-card {
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
  padding: 20px;
  background: var(--bg-card);
  display: flex;
  gap: 24px;
}

.srep-winner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex: 1;
}

.srep-star { font-size: 9px; font-weight: 800; letter-spacing: 0.1em; color: var(--accent); background: var(--accent-dim); border: 1px solid rgba(59,130,246,0.25); border-radius: 4px; padding: 3px 8px; }

.srep-winner-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 4px;
}

.srep-winner-angle { font-size: 16px; font-weight: 700; color: var(--text-primary); }

.srep-winner-stats { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }

.srep-divider { width: 1px; background: var(--border-subtle); flex-shrink: 0; }

.srep-objections { flex: 1; }

.srep-obj-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-tertiary);
  text-transform: uppercase;
  margin-bottom: 10px;
}

.srep-obj-item {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 8px;
}

.srep-obj-freq {
  font-size: 11px;
  font-weight: 700;
  color: var(--amber);
  background: rgba(245,158,11,0.12);
  padding: 1px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

.srep-obj-text { font-size: 12px; color: var(--text-secondary); line-height: 1.4; }

/* ── Demo showcase ───────────────────────────────────────────── */
.demo-section {
  padding: 72px 0 80px;
  border-top: 1px solid var(--border-subtle);
}

.demo-sub {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.65;
  margin: -28px 0 32px;
  max-width: 560px;
}

.demo-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 0;
}

.demo-tab {
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
}

.demo-tab.active {
  color: var(--text-primary);
  border-bottom-color: var(--accent);
}

.demo-panel { animation: fadeIn 0.2s ease; }

@keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

/* Personas tab */
.demo-personas-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.demo-persona-card {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 16px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.demo-persona-card--interested { border-left: 3px solid var(--green); }
.demo-persona-card--neutral    { border-left: 3px solid var(--amber); }
.demo-persona-card--objection  { border-left: 3px solid var(--red); }

.dpc-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.dpc-name   { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.dpc-title  { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

.dpc-verdict {
  font-size: 9px; font-weight: 700; padding: 2px 7px;
  border-radius: 3px; white-space: nowrap; flex-shrink: 0;
}
.dpc-verdict--interested { background: rgba(74,222,128,0.12); color: var(--green); }
.dpc-verdict--neutral    { background: rgba(245,158,11,0.12); color: var(--amber); }
.dpc-verdict--objection  { background: rgba(248,113,113,0.12); color: var(--red); }

.dpc-goal { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }

.dpc-objection {
  font-size: 11px; color: var(--red);
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.2);
  border-radius: 4px; padding: 4px 8px; line-height: 1.5;
}

.demo-more {
  font-size: 12px; color: var(--text-tertiary);
  text-align: center; margin-top: 14px;
}

/* Messages tab */
.demo-messages-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.demo-msg-card {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
}

.demo-msg-card--winner { border: 2px solid var(--accent); }

.dmc-header {
  padding: 10px 14px 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.dmc-angle {
  font-size: 10px; font-weight: 800; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--accent);
}

.dmc-winner-badge {
  font-size: 9px; font-weight: 800; background: var(--accent);
  color: #fff; padding: 2px 7px; border-radius: 3px;
  letter-spacing: 0.08em;
}

.dmc-subject {
  padding: 0 14px 6px;
  font-size: 13px; font-weight: 700; color: var(--text-primary);
}

.dmc-body {
  padding: 0 14px 12px;
  font-size: 12px; color: var(--text-secondary);
  line-height: 1.6; flex: 1;
}

.dmc-scores {
  padding: 8px 14px;
  border-top: 1px solid var(--border-subtle);
  font-size: 11px; color: var(--text-tertiary);
  display: flex; gap: 6px; align-items: center;
}

.dmc-score-green { color: var(--green); font-weight: 600; }
.dmc-dot { color: var(--text-tertiary); }

/* Report tab */
.demo-report-wrap { display: flex; flex-direction: column; gap: 20px; }

.demo-metrics {
  display: grid; grid-template-columns: repeat(4, 1fr);
  border: 1px solid var(--border-subtle); border-radius: 8px; overflow: hidden;
}

.dm-metric {
  padding: 14px 18px; border-right: 1px solid var(--border-subtle);
  display: flex; flex-direction: column; gap: 3px;
}
.dm-metric:last-child { border-right: none; }
.dm-val   { font-size: 20px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.02em; }
.dm-label { font-size: 10px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }

.demo-summary {
  background: var(--bg-card); border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent); border-radius: 8px; padding: 16px 18px;
}

.demo-summary-label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 10px;
}

.demo-summary-text { font-size: 13px; color: var(--text-secondary); line-height: 1.75; }

.demo-objections { display: flex; flex-direction: column; gap: 8px; }

.demo-obj-row {
  display: flex; gap: 10px; align-items: baseline;
  font-size: 13px; color: var(--text-secondary);
}

.demo-obj-freq {
  font-size: 11px; font-weight: 700; color: var(--amber);
  background: rgba(245,158,11,0.1); padding: 1px 6px;
  border-radius: 3px; white-space: nowrap;
}

/* Demo CTA */
.demo-cta {
  display: flex; align-items: center; gap: 20px;
  margin-top: 32px; padding-top: 24px;
  border-top: 1px solid var(--border-subtle);
}

.demo-cta-note { font-size: 12px; color: var(--text-tertiary); }

/* ── Hero orbs ──────────────────────────────────────────────── */

.hero-orb {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  filter: blur(80px);
  z-index: 0;
}

.hero-orb-1 {
  width: 520px;
  height: 520px;
  background: radial-gradient(circle, rgba(255,255,255,0.045) 0%, transparent 70%);
  top: -180px;
  left: -160px;
  animation: orb1 12s ease-in-out infinite alternate;
}

.hero-orb-2 {
  width: 380px;
  height: 380px;
  background: radial-gradient(circle, rgba(255,255,255,0.025) 0%, transparent 70%);
  top: 60px;
  right: -60px;
  animation: orb2 16s ease-in-out infinite alternate;
}

/* All hero content must sit above the orbs */
.hero-left, .hero-right { position: relative; z-index: 1; }

@keyframes orb1 {
  0%   { transform: translate(0, 0) scale(1); }
  50%  { transform: translate(60px, 40px) scale(1.08); }
  100% { transform: translate(20px, 80px) scale(0.94); }
}

@keyframes orb2 {
  0%   { transform: translate(0, 0) scale(1); }
  50%  { transform: translate(-40px, 60px) scale(1.12); }
  100% { transform: translate(-70px, 20px) scale(0.9); }
}

/* ── Navbar glass ────────────────────────────────────────────── */
.navbar {
  background: rgba(0, 0, 0, 0.7) !important;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom-color: var(--border-subtle) !important;
}

/* ── Scroll reveal ───────────────────────────────────────────── */
.reveal {
  opacity: 0;
  transform: translateY(28px);
  transition: opacity 0.65s ease, transform 0.65s ease;
}
.reveal.revealed {
  opacity: 1;
  transform: translateY(0);
}

/* ── Feature card hover glow ─────────────────────────────────── */
.feature-card {
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.feature-card:hover {
  transform: translateY(-3px);
  border-color: rgba(59, 130, 246, 0.35);
  box-shadow: 0 0 24px rgba(59, 130, 246, 0.08);
}

/* ── For-card hover ──────────────────────────────────────────── */
.for-card {
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.for-card:hover {
  transform: translateY(-2px);
  border-color: rgba(59, 130, 246, 0.3);
  box-shadow: 0 0 20px rgba(59, 130, 246, 0.06);
}

/* ── How-it-works step number pulse on hover ─────────────────── */
.hiw-step-full:hover .hiw-sf-num {
  border-color: var(--accent);
  box-shadow: 0 0 12px rgba(59, 130, 246, 0.25);
  transition: border-color 0.2s, box-shadow 0.2s;
}

/* ── Stat number glow ────────────────────────────────────────── */
.hero-stat-num {
  transition: color 0.3s;
}
.hero-stat:hover .hero-stat-num {
  color: var(--accent);
}

/* ── Animated accent underline on hero title ─────────────────── */
.hero-title-accent {
  position: relative;
  display: inline-block;
}
.hero-title-accent::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: -4px;
  width: 0;
  height: 2px;
  background: var(--accent);
  animation: underlineGrow 1.2s ease-out 0.4s forwards;
}

@keyframes underlineGrow {
  to { width: 100%; }
}

/* ── Hero badge pulse ────────────────────────────────────────── */
.hero-badge {
  animation: badgePulse 3s ease-in-out infinite;
}

@keyframes badgePulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
  50%       { box-shadow: 0 0 12px 2px rgba(59, 130, 246, 0.2); }
}

/* ── Simulate section accent border ─────────────────────────── */
.simulate-section {
  position: relative;
}
.simulate-section::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(59,130,246,0.4), transparent);
}

/* ── Responsive ─────────────────────────────────────────────── */
@media (max-width: 1100px) {
  .hero-section { grid-template-columns: 1fr; }
  .hero-right { display: none; }
  .features-grid { grid-template-columns: repeat(2, 1fr); }
  .hiw-steps-full { grid-template-columns: repeat(3, 1fr); gap: 20px; }
  .hiw-steps-full::before { display: none; }
}

@media (max-width: 900px) {
  .main-section { grid-template-columns: 1fr; }
  .how-it-works { position: static; }
  .hero-title { font-size: 2.2rem; }
  .hero-stats { flex-wrap: wrap; width: 100%; }
  .hero-stat { flex: 1 1 33%; padding: 12px 6px; }
  .hero-stat-sep { display: none; }
  .preview-personas { grid-template-columns: 1fr; }
  .main-content { padding: 40px 20px 0; }
  .navbar { padding: 0 20px; }
  .features-grid { grid-template-columns: 1fr; }
  .hiw-steps-full { grid-template-columns: 1fr; }
  .for-grid { grid-template-columns: 1fr; }
  .sample-grid { grid-template-columns: 1fr; }
  .sample-block--wide { grid-column: auto; }
  .sample-report-card { flex-direction: column; }
  .srep-divider { width: 100%; height: 1px; }
  .demo-personas-grid { grid-template-columns: 1fr; }
  .demo-messages-grid { grid-template-columns: 1fr; }
  .demo-metrics { grid-template-columns: repeat(2, 1fr); }
  .hero-actions { flex-direction: column; align-items: flex-start; }
  .section-title { font-size: 1.6rem; }
  .nav-cta { display: none; }
}
</style>
