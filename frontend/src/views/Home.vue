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
          <span class="hero-badge">GTM Simulation Lab</span>
          <span class="hero-version">Open source · No signup</span>
        </div>

        <h1 class="hero-title">
          Simulate your GTM<br>
          <span class="hero-title-accent">before you launch outreach.</span>
        </h1>

        <p class="hero-sub">
          Describe your product and buyer. AI personas built from your ICP react to several
          outreach angles, every reaction is scored across repeated runs, and you get the
          winning message, the objections to prepare for, and a 7-day outbound plan.
          All before you send a single email.
        </p>

        <div class="hero-actions">
          <router-link to="/simulate" class="btn-hero-primary">Run a Simulation →</router-link>
          <a href="https://github.com/sanketmuchhala/GTM-SImulator" target="_blank" class="btn-hero-ghost">View on GitHub ↗</a>
        </div>

        <div class="hero-stats">
          <div class="hero-stat">
            <span class="hero-stat-num">{{ stat1 }}</span>
            <span class="hero-stat-label">Personas</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">{{ stat2 }}</span>
            <span class="hero-stat-label">Angles</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">{{ stat3 }}x</span>
            <span class="hero-stat-label">Scoring runs</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">~2 min</span>
            <span class="hero-stat-label">Per run</span>
          </div>
          <div class="hero-stat-sep"></div>
          <div class="hero-stat">
            <span class="hero-stat-num">&lt;$0.10</span>
            <span class="hero-stat-label">In API cost</span>
          </div>
        </div>
        </div><!-- /hero-left -->

        <!-- Right: live agent network visualization -->
        <div class="hero-right">
          <div class="hviz-frame">
            <div class="hviz-frame-label">Buyer network preview</div>
            <HeroViz />
          </div>
        </div>

      </section>

      <!-- ── Problem ────────────────────────────────────────────── -->
      <section class="problem-section reveal">
        <div class="problem-inner">
          <div class="problem-label">The problem</div>
          <h2 class="problem-title">Most founders test their GTM on real prospects.</h2>
          <p class="problem-body">
            You write a sequence, send it to a few hundred people, and wait. Two weeks later the
            replies are thin and you still don't know why. Was it the segment, the angle, or an
            objection you never addressed? Meanwhile the best accounts on your list have already
            seen your weakest message.
          </p>
          <p class="problem-body">
            GTM Simulation Lab gives you a first read before you send. It won't replace real reply
            data, but it shows you which angle to lead with, which buyers to start with, and which
            objections to answer up front, so your first real test is a sharper one.
          </p>
        </div>
      </section>

      <!-- ── What you get ──────────────────────────────────────── -->
      <section class="features-section reveal">
        <div class="section-eyebrow">What the simulation produces</div>
        <div class="features-grid">

          <div class="feature-card">
            <div class="feature-title">Buyer personas from your ICP</div>
            <div class="feature-desc">
              Twelve buyers by default, generated from your brief. Each one has its own goals,
              pain points, buying triggers, objections, budget sensitivity, and skepticism level,
              from eager early adopters to the CFO who has to sign off.
            </div>
            <div class="feature-tag">Founders · VP Sales · RevOps · CFOs · SDR managers</div>
          </div>

          <div class="feature-card">
            <div class="feature-title">Outreach angles, written for you</div>
            <div class="feature-desc">
              Two to five cold emails, each built on a different angle and written from your
              product context. Every message stays under 80 words, sounds like a founder wrote
              it, and is tested against every persona.
            </div>
            <div class="feature-tag">Pain · ROI · Curiosity · Feature · Social proof</div>
          </div>

          <div class="feature-card">
            <div class="feature-title">Reactions scored three times</div>
            <div class="feature-desc">
              Every persona reads every message and scores it for interest, clarity, trust, and
              urgency, with a likely objection, a buying trigger, and the reply they would send.
              The whole pass runs three times in a shuffled order and the scores are averaged.
            </div>
            <div class="feature-tag">Interest · Clarity · Trust · Urgency · Reply</div>
          </div>

          <div class="feature-card feature-card--accent">
            <div class="feature-title">A report you can act on</div>
            <div class="feature-desc">
              The winning angle and how often it won, the top objections with rebuttals, your
              best-fit segment, risk signals, an outbound workflow, and a day-by-day 7-day
              experiment you can start on Monday.
            </div>
            <div class="feature-tag">Winner · Rebuttals · Risks · Workflow · 7-day plan</div>
          </div>

        </div>
      </section>

      <!-- Trust -->
      <section class="trust-section reveal">
        <div class="section-eyebrow">Why you can trust the read</div>
        <h2 class="section-title">Built to show you signal, not noise.</h2>
        <div class="trust-grid">
          <div class="trust-card">
            <div class="trust-title">Repeated, not one-shot</div>
            <div class="trust-desc">
              One LLM pass can flip on a whim. Each simulation runs three times with personas in
              a different order, and the winner is reported with its win rate.
            </div>
          </div>
          <div class="trust-card">
            <div class="trust-title">Ties are called ties</div>
            <div class="trust-desc">
              When two angles trade wins across runs, the result is marked too close to call
              instead of crowning a winner you would regret betting on.
            </div>
          </div>
          <div class="trust-card">
            <div class="trust-title">Each buyer judged alone</div>
            <div class="trust-desc">
              Personas are scored in small batches against their own goals and skepticism, with
              no built-in rule about which roles should like you.
            </div>
          </div>
          <div class="trust-card">
            <div class="trust-title">Sample data is labelled</div>
            <div class="trust-desc">
              If the AI service is down, you see clearly marked sample data and the reason. It
              is never passed off as results for your brief.
            </div>
          </div>
        </div>
        <p class="trust-note">
          Treat the output as a directional first read. Confirm the winning angle with a small
          real send before you scale it.
        </p>
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
          A default run (12 personas, 3 angles) takes about two minutes. No account needed.
        </div>
      </section>

      <!-- ── Who it's for ──────────────────────────────────────── -->
      <section class="for-section reveal">
        <div class="section-eyebrow">Built for</div>
        <h2 class="section-title">GTM-focused founders and sales teams.</h2>

        <div class="for-grid">
          <div class="for-card">
            <div class="for-title">Founders doing outbound</div>
            <div class="for-desc">
              You are selling it yourself and hunting for your first ten customers. Check your
              ICP and find the message most likely to get a reply before you burn your best
              accounts on a first draft.
            </div>
            <ul class="for-list">
              <li>Which buyers lean in, and which push back</li>
              <li>Which angle to lead your first sequence with</li>
              <li>The objections to answer before they come up</li>
            </ul>
          </div>

          <div class="for-card">
            <div class="for-title">Teams entering a new segment</div>
            <div class="for-desc">
              You are moving upmarket or launching a new product line. Pressure-test the new
              ICP before you commit SDR time and budget to a hypothesis nobody has checked.
            </div>
            <ul class="for-list">
              <li>Buyer readiness for the new segment</li>
              <li>Side-by-side angles across different roles</li>
              <li>Risks that could stall the launch</li>
            </ul>
          </div>

          <div class="for-card">
            <div class="for-title">Sales leaders writing a playbook</div>
            <div class="for-desc">
              You want a repeatable outbound motion before you hire. Turn the simulation into
              a written playbook so new reps start on the message that already tested best.
            </div>
            <ul class="for-list">
              <li>Objection handling drawn from simulated replies</li>
              <li>Segments ranked by buyer readiness</li>
              <li>A 7-day experiment to validate before scaling</li>
            </ul>
          </div>
        </div>
      </section>

      <!-- ── Demo Showcase ───────────────────────────────────── -->
      <section class="demo-section reveal" id="demo">
        <div class="section-eyebrow">Example run</div>
        <h2 class="section-title">What you get back.</h2>
        <p class="demo-sub">Output from a simulation of Acme AI SDR, an AI sales assistant pitched to seed-stage SaaS founders.</p>

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
          <div class="demo-more">Plus {{ demoPersonasTotal - demoPersonas.length }} more personas in the full run</div>
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
          <router-link to="/simulate" class="btn-hero-primary">Run your own simulation →</router-link>
          <span class="demo-cta-note">About 2 minutes · No account needed</span>
        </div>
      </section>

      <!-- ── Footer ─────────────────────────────────────────────── -->
      <footer class="home-footer">
        <span>GTM Simulation Lab · open source</span>
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
  { title: 'Write the brief',  desc: 'Your product, ICP, pricing, channel, and the goal for this campaign.' },
  { title: 'Meet your buyers', desc: 'Personas built from your ICP, each with goals, pains, and objections.' },
  { title: 'Draft the angles', desc: 'Two to five cold emails, each built on a different angle.' },
  { title: 'Score reactions',  desc: 'Every buyer reads every email. Three runs, scores averaged, winner checked.' },
  { title: 'Get the plan',     desc: 'Winning angle, rebuttals, risks, and a 7-day outbound experiment.' },
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
  setTimeout(() => countUp(v => { stat3.value = v }, 3, 600), 500)
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

/* Trust section */
.trust-section {
  padding: 72px 0;
  border-top: 1px solid var(--border-subtle);
}

.trust-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--border-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  overflow: hidden;
}

.trust-card {
  background: var(--bg-base);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trust-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.trust-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.65;
}

.trust-note {
  margin-top: 20px;
  font-size: 13px;
  color: var(--text-tertiary);
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
  .trust-grid { grid-template-columns: repeat(2, 1fr); }
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
  .trust-grid { grid-template-columns: 1fr; }
  .hiw-steps-full { grid-template-columns: 1fr; }
  .for-grid { grid-template-columns: 1fr; }
  .srep-divider { width: 100%; height: 1px; }
  .demo-personas-grid { grid-template-columns: 1fr; }
  .demo-messages-grid { grid-template-columns: 1fr; }
  .demo-metrics { grid-template-columns: repeat(2, 1fr); }
  .hero-actions { flex-direction: column; align-items: flex-start; }
  .section-title { font-size: 1.6rem; }
  .nav-cta { display: none; }
}
</style>
