<template>
  <div class="demo-page" lang="en">
    <nav class="demo-navbar" aria-label="Main navigation">
      <RouterLink to="/" class="brand">My Own Researcher</RouterLink>
      <div class="nav-links">
        <RouterLink to="/">Workspace</RouterLink>
        <RouterLink to="/demo" aria-current="page" class="active-link">Demo</RouterLink>
        <a href="https://github.com/Handriantog/My-Own-Researcher" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
      </div>
    </nav>

    <main class="demo-main">
      <header class="demo-hero">
        <div class="hero-copy">
          <p class="eyebrow"><span class="live-dot" aria-hidden="true"></span> A saved run, ready to explore</p>
          <h1>From a question<br>to a <em>clearer picture.</em></h1>
          <p class="hero-description">Follow one document through a knowledge graph, a conversation between simulated stakeholders, and a research report. See what you get before starting your own.</p>
          <div class="hero-meta"><span>No setup or AI calls</span><span>English example</span><span>13 October 2026</span></div>
        </div>
        <div class="scenario-card">
          <div class="scenario-label"><span>THE EXAMPLE</span><span>01 / LOOPLUNCH</span></div>
          <h2>A lunch venture.<br>Three possible decisions.</h2>
          <div class="price-options"><span>S$12<small>encourage trial</small></span><span>S$14<small>protect margins</small></span><span>Wait<small>prove readiness</small></span></div>
          <p>Should a Singapore office lunch venture launch its pilot, and under what conditions?</p>
          <span class="fiction-label">Fictional scenario · Recorded simulation</span>
        </div>
      </header>

      <section class="run-overview" aria-label="Example run coverage">
        <div class="stat"><strong>{{ demo.personas.length }}</strong><span>simulated personas</span></div>
        <div class="stat"><strong>{{ demo.coverage.totalActions }}</strong><span>recorded actions</span></div>
        <div class="stat"><strong>{{ demo.coverage.round }}<small> / {{ demo.coverage.plannedRounds }}</small></strong><span>rounds reached / planned</span></div>
        <div class="coverage-note"><span class="coverage-badge">Stopped early</span><p>The report covers the recorded activity. It does not establish the full scenario outcome.</p></div>
      </section>

      <section class="walkthrough" aria-label="Demo walkthrough">
        <div class="stage-tabs" role="tablist" aria-label="Research stages">
          <button v-for="(step, index) in steps" :id="`tab-${step.id}`" :key="step.id" type="button" role="tab"
            :aria-selected="activeStep === index" :aria-controls="`panel-${step.id}`" :tabindex="activeStep === index ? 0 : -1"
            :class="{ selected: activeStep === index }" @click="selectStep(index)" @keydown="onTabKey($event, index)">
            <span class="step-number">0{{ index + 1 }}</span>{{ step.label }}<span class="tab-arrow" aria-hidden="true">↗</span>
          </button>
        </div>

        <div :id="`panel-${currentStep.id}`" :key="currentStep.id" class="stage-panel" role="tabpanel" :aria-labelledby="`tab-${currentStep.id}`" tabindex="0">
          <aside class="stage-guide">
            <p class="eyebrow">0{{ activeStep + 1 }} / {{ currentStep.kicker }}</p>
            <h2>{{ currentStep.title }}</h2>
            <p class="guide-intro">{{ currentStep.description }}</p>
            <dl><dt>You provide</dt><dd>{{ currentStep.input }}</dd><dt>You get</dt><dd>{{ currentStep.output }}</dd><dt>Why it matters</dt><dd>{{ currentStep.why }}</dd></dl>
            <p class="snapshot-note">You’re exploring a saved example. Nothing here starts a simulation or uses your AI account.</p>
          </aside>

          <div class="stage-content">
            <template v-if="currentStep.id === 'brief'">
              <div class="artifact-header"><span>SOURCE DOCUMENT</span><a :href="briefUrl" target="_blank" rel="noopener noreferrer">Open original PDF ↗</a></div>
              <article class="brief-preview">
                <div class="paper-topline"><span>MY OWN RESEARCHER</span><span>MOCK BUSINESS BRIEF</span></div>
                <h3>LoopLunch</h3><p class="paper-subtitle">Office lunch subscriptions · Decision brief</p>
                <p class="paper-notice">All people, companies and figures are fictional.</p>
                <h4>The opportunity</h4><p>Prepaid weekday lunches, delivered in one batch to a Singapore office building. Two menus. One shared collection point.</p>
                <div class="brief-facts"><div><strong>S$10,000</strong><span>available reserve</span></div><div><strong>6 weeks</strong><span>proposed pilot</span></div><div><strong>S$3,000</strong><span>maximum pilot loss</span></div></div>
                <h4>The tension</h4><p>Lower pricing may encourage trial. Higher pricing gives more room for costs. But survey interest is not paid demand, and the trial missed its delivery target.</p>
                <details class="source-details"><summary>Read the full extracted source</summary><pre>{{ demo.sourceText }}</pre></details>
              </article>
              <div class="question-card"><span class="eyebrow">THE RESEARCH QUESTION</span><p>{{ demo.question }}</p></div>
            </template>

            <template v-else-if="currentStep.id === 'graph'">
              <div class="artifact-header"><span>EXPLORE THE KNOWLEDGE GRAPH</span><span>Saved after simulation</span></div>
              <DemoGraph :graph="demo.graph" />
              <p class="artifact-note">The map groups connections between entities. Select an entity to read individual relationships, including memory added during the run.</p>
            </template>

            <template v-else-if="currentStep.id === 'personas'">
              <div class="artifact-header"><span>MEET THE SIMULATED STAKEHOLDERS</span><span>{{ demo.personas.length }} personas</span></div>
              <div class="persona-grid">
                <button v-for="person in demo.personas" :key="person.id" type="button" class="persona-card" :class="{ chosen: person.id === selectedPersonaId }" :aria-pressed="person.id === selectedPersonaId" @click="selectedPersonaId = person.id">
                  <span class="avatar" aria-hidden="true">{{ initials(person.name) }}</span><span><strong>{{ person.name }}</strong><small>{{ friendlyType(person.role) }}</small></span>
                </button>
              </div>
              <article class="persona-detail" aria-live="polite">
                <span class="eyebrow">{{ friendlyType(selectedPersona.role) }}</span><h3>{{ selectedPersona.name }}</h3><p>{{ selectedPersona.profession }}</p>
                <h4>Opening position</h4><blockquote>{{ selectedPersona.openingPosition }}</blockquote>
                <details><summary>Read the generated persona</summary><p class="persona-text">{{ selectedPersona.persona }}</p></details>
              </article>
              <div class="setup-strip"><div><strong>Twitter + Reddit</strong><span>simulated environments</span></div><div><strong>{{ demo.timeConfig.minutes_per_round }} min</strong><span>simulated time per round</span></div><div><strong>{{ demo.timeConfig.total_simulation_hours }} hours</strong><span>planned scenario</span></div></div>
            </template>

            <template v-else-if="currentStep.id === 'discussion'">
              <div class="artifact-header"><span>THE RECORDED DISCUSSION</span><span>{{ demo.coverage.twitterActions }} Twitter · {{ demo.coverage.redditActions }} Reddit actions</span></div>
              <div class="discussion-toolbar">
                <div class="platform-filters" aria-label="Filter posts by platform"><button v-for="platform in platforms" :key="platform.id" type="button" :aria-pressed="platformFilter === platform.id" :class="{ chosen: platformFilter === platform.id }" @click="platformFilter = platform.id">{{ platform.label }}</button></div>
                <label>Round <select v-model="roundFilter"><option value="all">All rounds</option><option v-for="round in availableRounds" :key="round" :value="String(round)">{{ round === 0 ? '0 · Opening posts' : round }}</option></select></label>
              </div>
              <p class="artifact-note">{{ filteredPosts.length }} written posts and comments shown. The {{ demo.coverage.totalActions }} recorded actions also include reactions and “do nothing” actions. Round 0 contains the prepared opening posts.</p>
              <div class="discussion-feed" tabindex="0" aria-label="Recorded simulation posts">
                <article v-for="post in filteredPosts" :key="post.id" class="post-card">
                  <div class="post-heading"><span class="avatar small-avatar" aria-hidden="true">{{ initials(post.agent) }}</span><div><strong>{{ post.agent }}</strong><span>{{ platformLabel(post.platform) }} · Round {{ post.round }} · {{ actionLabel(post.type) }}</span></div></div>
                  <p>{{ post.content }}</p>
                  <blockquote v-if="post.originalContent"><strong>{{ post.originalAuthor }}</strong>{{ post.originalContent }}</blockquote>
                </article>
                <p v-if="!filteredPosts.length" class="empty-feed">No written posts in this selection. Try another round or platform.</p>
              </div>
              <p class="artifact-note">These are verbatim saved agent outputs from a fictional scenario. Twitter reached round {{ demo.coverage.twitterRounds }}; Reddit reached round {{ demo.coverage.redditRounds }}.</p>
            </template>

            <template v-else-if="currentStep.id === 'report'">
              <div class="artifact-header"><span>THE RESEARCH REPORT</span><a :href="reportUrl" download="looplunch-report.md">Download Markdown ↓</a></div>
              <article class="report-preview">
                <div class="report-topline"><span class="eyebrow">REPORT / LOOPLUNCH</span><span class="coverage-badge">Partial simulation</span></div>
                <h3>Conditional pricing.<br>Unproven readiness.</h3>
                <p class="report-lead">The recorded discussion supports launch conditions, not a confirmed price or a green light to launch.</p>
                <div class="finding"><span>01</span><div><h4>Validate paid demand</h4><p>Stated interest does not establish repeat purchasing. Check paid commitments for each weekday.</p></div></div>
                <div class="finding"><span>02</span><div><h4>Prove operational readiness</h4><p>Delivery reliability, supplier terms, lobby access and refund responsibilities remain unresolved.</p></div></div>
                <div class="finding"><span>03</span><div><h4>Make the decision conditional</h4><p>Evaluate either price against verified demand, costs and service capacity. Retain postponement if those conditions are unmet.</p></div></div>
                <p class="report-caveat">Summary of the saved report. The run stopped at round 37 of 336; its findings do not establish the eventual launch decision. The report distinguishes retrieved graph summaries from direct agent transcripts.</p>
                <details class="full-report"><summary>Read the full saved report <span aria-hidden="true">↓</span></summary><DemoReport :text="reportText" /></details>
              </article>
            </template>
          </div>
        </div>

        <div class="stage-footer"><span>0{{ activeStep + 1 }} <span class="muted">/ 05</span></span><div><button v-if="activeStep > 0" type="button" class="back-button" @click="advanceStep(activeStep - 1)">← Previous</button><button v-if="activeStep < steps.length - 1" type="button" class="next-button" @click="advanceStep(activeStep + 1)">{{ steps[activeStep + 1].label }} →</button><RouterLink v-else to="/#research" class="next-button">Start your own research →</RouterLink></div></div>
      </section>

      <footer class="demo-footer"><div><p class="eyebrow">YOUR QUESTION IS NEXT</p><h2>Bring a document.<br>Explore the possibilities.</h2><p>Your source material and your question shape the next run.</p></div><RouterLink to="/#research" class="primary-link">Start your own research <span aria-hidden="true">↗</span></RouterLink></footer>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DemoGraph from '../components/demo/DemoGraph.vue'
import DemoReport from '../components/demo/DemoReport.vue'
import demo from '../demo/looplunch-demo.json'
import reportText from '../demo/looplunch-report.md?raw'
import reportUrl from '../demo/looplunch-report.md?url'

const route = useRoute()
const router = useRouter()
const briefUrl = `${import.meta.env.BASE_URL}demo/looplunch-brief.pdf`
const steps = [
  { id: 'brief', label: 'The question', kicker: 'Start with context', title: 'One document. A real decision to explore.', description: 'The example begins with a two-page fictional business brief and a specific research question.', input: 'A PDF, Markdown or text document, plus the question you want to investigate.', output: 'Extracted source material and a focused scenario for the research workflow.', why: 'Grounding the scenario in your material gives the agents shared facts, constraints and points of disagreement.' },
  { id: 'graph', label: 'Knowledge graph', kicker: 'Connect the context', title: 'Make the relationships visible.', description: 'People, organizations and their connections become a graph you can inspect. This snapshot also includes memory from the simulation.', input: 'The source document from the first step.', output: 'Entities, relationship facts and their saved context. Here: 10 entities and 160 relationships.', why: 'You can see who is connected, what they care about and which conditions shape the scenario.' },
  { id: 'personas', label: 'Simulation setup', kicker: 'Give perspectives a voice', title: 'Same question. Different incentives.', description: 'The system creates personas from the graph, then configures how they participate in the simulated discussion.', input: 'The graph and your research question.', output: 'Seven generated personas, starting positions and a schedule for two simulated platforms.', why: 'A founder, operator, host and supplier can test the same proposal from different perspectives.' },
  { id: 'discussion', label: 'The discussion', kicker: 'Watch the responses', title: 'See the trade-offs surface.', description: 'Browse what the agents actually posted. Their exchanges turn the initial pricing question into questions about demand, delivery and responsibility.', input: 'The prepared personas and simulation settings.', output: 'A recorded action timeline. This run captured 102 actions before it was stopped.', why: 'The discussion makes assumptions and disagreements visible, giving the report evidence to examine.' },
  { id: 'report', label: 'The report', kicker: 'Turn activity into findings', title: 'A report you can question.', description: 'The report gathers the available evidence, identifies risks and describes the conditions needed before making a decision.', input: 'The recorded simulation and saved graph memory.', output: 'A structured report with findings, evidence limits and conditional recommendations.', why: 'You get a starting point for further research, with a clear distinction between simulated evidence and an established outcome.' },
]
const activeStep = computed(() => Math.max(0, steps.findIndex(step => `#${step.id}` === route.hash)))
const currentStep = computed(() => steps[activeStep.value])
const selectedPersonaId = ref(2)
const selectedPersona = computed(() => demo.personas.find(person => person.id === selectedPersonaId.value))
const platformFilter = ref('all')
const roundFilter = ref('all')
const platforms = [{ id: 'all', label: 'All platforms' }, { id: 'twitter', label: 'Twitter' }, { id: 'reddit', label: 'Reddit' }]
const writtenPosts = demo.actions.filter(action => action.content)
const availableRounds = [...new Set(writtenPosts.map(action => action.round))].sort((a, b) => a - b)
const filteredPosts = computed(() => writtenPosts.filter(post => (platformFilter.value === 'all' || post.platform === platformFilter.value) && (roundFilter.value === 'all' || post.round === Number(roundFilter.value))))
const initials = name => name.split(' ').map(word => word[0]).slice(0, 2).join('')
const friendlyType = value => value.replace(/([a-z])([A-Z])/g, '$1 $2')
const platformLabel = value => platforms.find(platform => platform.id === value)?.label || value
const actionLabel = value => ({ CREATE_POST: 'Post', CREATE_COMMENT: 'Comment', QUOTE_POST: 'Quote post', REPOST: 'Repost' }[value] || value.toLowerCase().replaceAll('_', ' '))

async function selectStep(index) {
  await router.replace({ path: '/demo', hash: `#${steps[index].id}` })
}
async function advanceStep(index) {
  await selectStep(index)
  await nextTick()
  document.getElementById(`tab-${steps[index].id}`)?.focus()
}
function onTabKey(event, index) {
  const next = { ArrowRight: (index + 1) % steps.length, ArrowLeft: (index + steps.length - 1) % steps.length, Home: 0, End: steps.length - 1 }[event.key]
  if (next === undefined) return
  event.preventDefault()
  advanceStep(next)
}
</script>

<style scoped>
.demo-page { --accent: #dc461d; --ink: #20221f; --line: #dddfd7; --muted: #696d64; background: #fafaf7; color: var(--ink); font-family: 'Space Grotesk', system-ui, sans-serif; min-height: 100vh; }
.demo-navbar { min-height: 64px; background: #151714; color: white; padding: 0 40px; display: flex; justify-content: space-between; align-items: center; gap: 24px; }
.demo-navbar a { color: inherit; text-decoration: none; }
.brand { font-family: 'JetBrains Mono', monospace; font-size: 17px; font-weight: 800; letter-spacing: .02em; }
.nav-links { display: flex; align-items: center; gap: 24px; font-size: 13px; }
.nav-links .active-link { border-bottom: 2px solid #fc794e; padding: 22px 0 20px; }
.demo-main { max-width: 1320px; margin: 0 auto; padding: 64px 40px 0; }
.demo-hero { display: grid; grid-template-columns: 1.15fr 1fr; align-items: center; gap: 64px; margin-bottom: 46px; }
.eyebrow { font-family: 'JetBrains Mono', monospace; font-size: 10px; line-height: 1.6; letter-spacing: .11em; text-transform: uppercase; font-weight: 500; color: var(--accent); }
.live-dot { display: inline-block; height: 6px; width: 6px; background: var(--accent); margin-right: 8px; }
h1 { font-size: clamp(34px, 4.4vw, 56px); font-weight: 500; letter-spacing: -.055em; line-height: 1.12; margin: 22px 0; }
h1 em { font-weight: 500; font-style: normal; color: var(--accent); }
.hero-description { font-family: system-ui, sans-serif; font-size: 15px; color: #62675e; line-height: 1.8; max-width: 540px; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 10px; color: var(--muted); margin-top: 25px; }
.hero-meta span + span::before { content: '·'; margin-right: 16px; }
.scenario-card { padding: 30px; background: #eceee5; border: 1px solid #dce0d2; position: relative; }
.scenario-card::before { content: ''; width: 26px; height: 4px; position: absolute; left: 30px; top: -1px; background: var(--accent); }
.scenario-label { display: flex; justify-content: space-between; gap: 12px; font-family: monospace; font-size: 9px; letter-spacing: .1em; color: #68705d; }
.scenario-card h2 { font-size: 28px; font-weight: 500; letter-spacing: -.035em; line-height: 1.2; margin: 28px 0; }
.price-options { display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid #ced4c3; border-bottom: 1px solid #ced4c3; padding: 20px 0; gap: 8px; }
.price-options > span { font-size: 27px; letter-spacing: -.05em; }
.price-options small { display: block; font-size: 10px; letter-spacing: 0; margin-top: 8px; color: #68705d; }
.scenario-card > p { font-size: 13px; line-height: 1.65; margin: 20px 0; max-width: 350px; }
.fiction-label { font-size: 9px; color: #68705d; }
.run-overview { display: grid; grid-template-columns: .8fr .8fr 1fr 1.5fr; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 24px 0; margin-bottom: 48px; }
.stat { display: flex; flex-direction: column; gap: 6px; border-right: 1px solid var(--line); padding: 0 26px; }
.stat:first-child { padding-left: 0; }
.stat strong { font-size: 32px; font-weight: 500; letter-spacing: -.04em; }
.stat strong small { color: #8b8f85; font-size: 19px; font-weight: 400; }
.stat > span { font-size: 10px; color: var(--muted); }
.coverage-note { padding-left: 28px; }
.coverage-badge { display: inline-block; font-size: 10px; font-weight: 600; color: #91401f; background: #f9e7da; border: 1px solid #f0d0b9; padding: 4px 7px; white-space: nowrap; }
.coverage-note p { font-family: system-ui, sans-serif; font-size: 11px; line-height: 1.6; color: var(--muted); margin-top: 8px; }
.stage-tabs { display: flex; border-bottom: 1px solid var(--line); overflow-x: auto; }
.stage-tabs button { flex: 1 0 auto; color: #74776e; border: 0; background: none; padding: 19px 16px; cursor: pointer; font-size: 12px; border-bottom: 3px solid transparent; text-align: left; }
.stage-tabs button:first-child { padding-left: 0; }
.step-number { font-family: monospace; font-size: 10px; margin-right: 10px; color: #8c9085; }
.tab-arrow { float: right; padding-left: 14px; opacity: 0; }
.stage-tabs .selected { color: var(--ink); border-bottom-color: var(--accent); }
.selected .step-number { color: var(--accent); } .selected .tab-arrow { opacity: 1; color: var(--accent); }
.stage-panel { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 52px; padding: 42px 0; align-items: start; }
.stage-guide h2 { font-size: 27px; font-weight: 500; line-height: 1.25; letter-spacing: -.04em; margin: 17px 0; }
.guide-intro { font-family: system-ui, sans-serif; color: var(--muted); font-size: 13px; line-height: 1.8; }
dl { margin-top: 28px; border-top: 1px solid var(--line); padding-top: 6px; }
dt { font-size: 11px; font-weight: 700; margin-top: 20px; }
dd { font-family: system-ui, sans-serif; font-size: 12px; color: var(--muted); line-height: 1.75; margin-top: 5px; }
.snapshot-note { border-left: 2px solid #d6dbcc; margin-top: 28px; padding-left: 12px; font-size: 10px; line-height: 1.7; color: #72796a; }
.stage-content { min-width: 0; }
.artifact-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; font-family: monospace; font-size: 10px; color: #70776a; letter-spacing: .025em; }
.artifact-header a { color: #a93412; text-underline-offset: 4px; }
.artifact-note { font-family: system-ui, sans-serif; font-size: 11px; color: var(--muted); line-height: 1.7; margin: 14px 0; }
.brief-preview { background: white; border: 1px solid var(--line); padding: 32px 38px; box-shadow: 5px 5px 0 #eff0e9; }
.paper-topline { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; font-size: 8px; letter-spacing: .08em; color: #74776e; }
.brief-preview h3 { font-size: 38px; letter-spacing: -.04em; margin: 26px 0 3px; font-weight: 600; }
.paper-subtitle { font-size: 12px; color: #6e7368; }
.paper-notice { padding: 9px 0; margin-top: 17px; border-top: 1px solid #eee; border-bottom: 1px solid #eee; font-size: 10px; color: #8c583e; }
.brief-preview h4 { margin: 25px 0 8px; font-size: 13px; }
.brief-preview h4 + p { font-family: system-ui, sans-serif; font-size: 13px; line-height: 1.8; color: #595f53; }
.brief-facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 23px 0; padding: 18px; background: #f7f8f3; }
.brief-facts strong { display: block; font-size: 20px; font-weight: 500; letter-spacing: -.04em; }
.brief-facts span { display: block; color: #74796c; font-size: 9px; margin-top: 6px; }
summary { cursor: pointer; font-size: 12px; line-height: 1.5; }
.source-details { margin-top: 22px; border-top: 1px solid #eee; padding-top: 18px; }
.source-details pre { white-space: pre-wrap; font-family: system-ui, sans-serif; font-size: 12px; line-height: 1.8; color: #555; margin-top: 18px; overflow-wrap: anywhere; max-height: 440px; overflow: auto; }
.question-card { margin-top: 24px; padding: 24px 28px; background: #242820; color: white; }
.question-card .eyebrow { color: #f59a75; } .question-card p { margin-top: 12px; font-size: 17px; line-height: 1.65; }
.persona-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.persona-card { border: 1px solid var(--line); display: flex; align-items: center; gap: 12px; background: white; padding: 14px; cursor: pointer; text-align: left; min-width: 0; color: inherit; }
.persona-card.chosen { border-color: #cb5228; background: #fff6ed; }
.avatar { display: inline-flex; justify-content: center; align-items: center; border-radius: 50%; background: #e9eddf; color: #505a42; width: 34px; height: 34px; font-family: monospace; font-size: 11px; flex-shrink: 0; }
.persona-card strong { display: block; font-size: 12px; font-weight: 600; } .persona-card small { display: block; font-size: 10px; color: #74796d; margin-top: 4px; }
.persona-detail { padding: 28px; background: white; border: 1px solid var(--line); margin-top: 20px; }
.persona-detail h3 { font-size: 25px; margin: 7px 0 12px; } .persona-detail > p, .persona-text { font-family: system-ui, sans-serif; font-size: 13px; line-height: 1.8; color: #62685b; }
.persona-detail h4 { font-size: 11px; margin: 24px 0 10px; }
.persona-detail blockquote { padding-left: 17px; border-left: 2px solid #e56e45; font-family: system-ui, sans-serif; font-size: 14px; line-height: 1.8; color: #444b3d; }
.persona-detail details { margin-top: 23px; border-top: 1px solid var(--line); padding-top: 17px; } .persona-text { margin-top: 15px; white-space: pre-line; }
.setup-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 20px; }
.setup-strip strong { font-size: 12px; font-weight: 500; display: block; }.setup-strip span { display: block; margin-top: 6px; font-size: 9px; color: var(--muted); }
.discussion-toolbar { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 15px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.platform-filters { display: flex; gap: 6px; }
.platform-filters button { border: 1px solid var(--line); padding: 7px 10px; background: white; color: #62685b; font-size: 11px; cursor: pointer; }
.platform-filters .chosen { background: #30352a; color: white; border-color: #30352a; }
.discussion-toolbar label { display: flex; align-items: center; gap: 10px; font-size: 10px; color: #707768; }
select { font-family: inherit; max-width: 160px; padding: 7px; border: 1px solid var(--line); color: #41483a; background: white; font-size: 11px; }
.discussion-feed { max-height: 730px; overflow-y: auto; border: 1px solid var(--line); background: #f0f2e9; padding: 15px; }
.post-card { padding: 22px; border: 1px solid #e1e4d9; background: white; margin-bottom: 12px; } .post-card:last-child { margin-bottom: 0; }
.post-heading { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; } .post-heading strong { font-size: 12px; } .post-heading div > span { display: block; font-size: 9px; color: #787f70; margin-top: 5px; }
.small-avatar { width: 30px; height: 30px; font-size: 10px; }
.post-card > p { font-family: system-ui, sans-serif; font-size: 13px; line-height: 1.8; white-space: pre-wrap; }
.post-card blockquote { padding: 15px; background: #f7f8f3; margin-top: 17px; font-family: system-ui, sans-serif; font-size: 11px; line-height: 1.8; color: #62695b; border-left: 2px solid #cdd4bf; }
.post-card blockquote strong { display: block; margin-bottom: 5px; } .empty-feed { font-size: 13px; padding: 30px; line-height: 1.8; }
.report-preview { background: white; border: 1px solid var(--line); padding: 32px; }
.report-topline { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.report-preview > h3 { font-size: 36px; letter-spacing: -.05em; font-weight: 500; line-height: 1.15; margin: 25px 0 18px; }
.report-lead { font-family: system-ui, sans-serif; font-size: 15px; color: #62695a; line-height: 1.75; margin-bottom: 26px; }
.finding { display: flex; gap: 20px; border-top: 1px solid var(--line); padding: 20px 0; }
.finding > span { color: #bf4c26; font-size: 10px; padding-top: 3px; }.finding h4 { font-size: 14px; font-weight: 600; }.finding p { margin-top: 7px; font-family: system-ui, sans-serif; font-size: 12px; line-height: 1.8; color: #6d7364; }
.report-caveat { font-family: system-ui, sans-serif; background: #f7f5ee; padding: 16px; font-size: 11px; line-height: 1.8; color: #726b5c; }
.full-report { margin-top: 25px; }.full-report > summary { padding: 15px 0; border-top: 1px solid var(--line); font-weight: 600; }.full-report > summary span { float: right; }
.stage-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-top: 1px solid var(--line); padding: 20px 0; font-size: 11px; }
.muted { color: #92998a; }.stage-footer > div { display: flex; gap: 15px; align-items: center; }
.back-button { border: 0; background: none; color: #676f5e; cursor: pointer; padding: 10px 0; font-size: 11px; }
.next-button { display: inline-block; background: #30352a; color: white; padding: 12px 17px; font-size: 11px; text-decoration: none; border: none; cursor: pointer; }
.demo-footer { display: flex; align-items: center; justify-content: space-between; gap: 30px; padding: 58px 0; margin-top: 24px; border-top: 1px solid var(--line); }
.demo-footer h2 { font-size: 32px; font-weight: 500; line-height: 1.15; letter-spacing: -.04em; margin: 15px 0; }.demo-footer div > p:last-child { font-size: 12px; color: var(--muted); }
.primary-link { background: #dc461d; color: white; padding: 17px 20px; text-decoration: none; font-size: 13px; display: flex; gap: 30px; align-items: center; white-space: nowrap; }
button:hover, a:hover { filter: brightness(.9); }
a:focus-visible, button:focus-visible, select:focus-visible, summary:focus-visible, [tabindex]:focus-visible { outline: 2px solid #cc471c; outline-offset: 4px; }
@media (max-width: 1000px) { .demo-hero { gap: 30px; }.stage-panel { grid-template-columns: 210px minmax(0, 1fr); gap: 30px; }.stage-tabs button { font-size: 11px; padding-right: 12px; padding-left: 12px; }.tab-arrow { display: none; }.scenario-card { padding: 25px; }.stat { padding: 0 17px; } }
@media (max-width: 760px) { .demo-navbar { padding: 18px 24px; flex-wrap: wrap; gap: 18px; }.nav-links { gap: 22px; }.nav-links .active-link { padding: 0 0 5px; }.demo-main { padding: 35px 24px 0; }.demo-hero { grid-template-columns: 1fr; gap: 28px; }.scenario-card h2 { margin: 22px 0; }.run-overview { grid-template-columns: repeat(3, 1fr); margin-bottom: 26px; gap: 20px 0; }.stat { padding: 0 12px; }.stat:nth-child(3) { border: none; }.stat strong { font-size: 28px; }.stat strong small { font-size: 15px; }.stat > span { font-size: 9px; }.coverage-note { grid-column: 1 / -1; border-top: 1px solid var(--line); padding: 16px 0 0; }.coverage-note p { display: inline; margin-left: 10px; }.stage-panel { grid-template-columns: 1fr; padding: 27px 0; gap: 26px; }.stage-guide h2 { font-size: 25px; }.stage-guide dl { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 10px; padding-top: 16px; margin-top: 17px; }.stage-guide dt, .stage-guide dd { margin: 0; }.snapshot-note { margin-top: 18px; }.demo-footer { align-items: flex-start; flex-direction: column; }.demo-footer h2 { font-size: 29px; }.brief-preview { padding: 25px; }.report-preview { padding: 25px; } }
@media (max-width: 420px) { .demo-main { padding-left: 18px; padding-right: 18px; }.demo-navbar { padding-left: 18px; padding-right: 18px; }.brand { font-size: 15px; }.brief-facts { padding: 13px; gap: 10px; }.brief-facts strong { font-size: 17px; }.brief-facts span { font-size: 8px; }.persona-grid { grid-template-columns: 1fr; }.setup-strip strong { font-size: 10px; }.report-preview > h3 { font-size: 29px; }.stage-footer > div { gap: 10px; }.next-button { padding: 11px; font-size: 10px; }.hero-meta { gap: 8px; }.hero-meta span + span::before { margin-right: 8px; } }
</style>
