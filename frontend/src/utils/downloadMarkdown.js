/**
 * Builds a full multi-section GTM simulation PDF.
 * Opens a styled HTML page and triggers the browser print dialog (Save as PDF).
 *
 * Sections:
 *  1. Cover - brand header, metrics strip, brief summary, executive summary
 *  2. Buyer Personas - all 12 in a grid
 *  3. Message Testing - 3 angle cards + reaction score table
 *  4. GTM Report - ICP, winning message, readiness, objections, risks, workflow, 7-day plan
 */

/* ── helpers ─────────────────────────────────────────────── */

function esc(str) {
  return (str || '').toString()
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function slug(text) {
  return (text || 'report').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

function formatDate(isoString) {
  try {
    return new Date(isoString).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  } catch {
    return new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  }
}

const ANGLE_LABEL = { pain_first: 'Pain-First', roi_first: 'ROI-First', curiosity_first: 'Curiosity-First' }
function angleLabel(a) { return ANGLE_LABEL[a] ?? (a || 'N/A') }

const SEVERITY_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' }
function sevColor(s) { return SEVERITY_COLOR[s] ?? '#94a3b8' }

const BUDGET_COLOR   = { low: '#22c55e', medium: '#f59e0b', high: '#ef4444' }
function budgetColor(b) { return BUDGET_COLOR[b] ?? '#94a3b8' }

const VERDICT_COLOR  = { interested: '#22c55e', neutral: '#f59e0b', objection: '#ef4444' }
const VERDICT_LABEL  = { interested: 'Interested', neutral: 'Neutral', objection: 'Objection' }
function verdictColor(v) { return VERDICT_COLOR[v] ?? '#94a3b8' }
function verdictLabel(v) { return VERDICT_LABEL[v] ?? (v || '') }

function scoreColor(n) {
  if (n >= 7) return '#22c55e'
  if (n >= 5) return '#f59e0b'
  return '#ef4444'
}

function channelLabel(c) {
  const map = {
    outbound_email: 'Outbound Email', linkedin: 'LinkedIn', cold_call: 'Cold Call',
    plg: 'PLG', inbound: 'Inbound', partnerships: 'Partnerships',
  }
  return map[c] ?? c
}

function goalLabel(g) {
  const map = {
    first_10_customers: 'First 10 Customers', expand_segment: 'Expand Segment',
    new_market: 'New Market', reactivate_churned: 'Reactivate Churned',
  }
  return map[g] ?? g
}

/* ── Section builders ────────────────────────────────────── */

function buildCover(brief, report, date) {
  const name = esc(brief?.product_name || 'Your Product')
  const icp = report?.best_icp || {}
  const wm  = report?.winning_message || {}
  const br  = report?.buyer_readiness || {}
  const icpPct = Math.round((icp.confidence_score || 0) * 100)
  const days = (report?.seven_day_experiment || []).length

  const briefRows = [
    brief?.product_description && ['Product', brief.product_description],
    brief?.pricing_model        && ['Pricing', brief.pricing_model],
    brief?.icp                  && ['ICP', brief.icp],
    brief?.target_market        && ['Market', brief.target_market],
    brief?.sales_channel        && ['Channel', channelLabel(brief.sales_channel)],
    brief?.gtm_goal             && ['GTM Goal', goalLabel(brief.gtm_goal)],
    brief?.pain_point           && ['Pain Point', brief.pain_point],
    brief?.competitors          && ['Competitors', brief.competitors],
  ].filter(Boolean)

  return `
  <div class="cover-section">
    <div class="doc-header">
      <div>
        <div class="doc-brand">GTM SIMULATION LAB</div>
        <div class="doc-title">${name}</div>
        <div class="doc-sub">GTM Simulation Report</div>
      </div>
      <div class="doc-meta">
        <div>${date}</div>
        <div style="margin-top:4px;color:#6366f1;font-weight:700">Full Simulation</div>
      </div>
    </div>

    <div class="metrics">
      <div class="metric">
        <div class="metric-val" style="color:#6366f1">${icpPct}%</div>
        <div class="metric-label">ICP Fit</div>
      </div>
      <div class="metric">
        <div class="metric-val" style="color:${scoreColor(br.score || 0)}">${br.score ?? '-'}/10</div>
        <div class="metric-label">Buyer Readiness</div>
      </div>
      <div class="metric">
        <div class="metric-val">${esc(angleLabel(wm.angle))}</div>
        <div class="metric-label">Winning Angle</div>
      </div>
      <div class="metric">
        <div class="metric-val">${days > 0 ? days + '-Day' : '-'}</div>
        <div class="metric-label">Experiment Plan</div>
      </div>
    </div>

    <div class="conf-note">
      <strong>Simulation note:</strong> All personas, reactions, and scores are AI-generated synthetic data. Use as directional signal; validate with real outbound before committing to strategy.
    </div>

    ${report?.executive_summary ? `
    <div class="section">
      <div class="section-title">Executive Summary</div>
      <div class="section-body">${esc(report.executive_summary)}</div>
    </div>` : ''}

    ${briefRows.length ? `
    <div class="section">
      <div class="section-title">GTM Brief</div>
      <div class="brief-grid">
        ${briefRows.map(([k, v]) => `
          <div class="brief-row">
            <div class="brief-key">${esc(k)}</div>
            <div class="brief-val">${esc(v)}</div>
          </div>`).join('')}
      </div>
    </div>` : ''}
  </div>`
}

function buildPersonas(personas) {
  if (!personas || !personas.length) return ''

  const cards = personas.map(p => {
    const skepSegs = Array.from({ length: 5 }, (_, i) =>
      `<div class="seg${i < (p.skepticism_level || 0) ? ' seg-filled' : ''}"></div>`
    ).join('')

    return `
    <div class="persona-card">
      <div class="pc-header">
        <div>
          <div class="pc-name">${esc(p.name)}</div>
          <div class="pc-title">${esc(p.title)}</div>
          <div class="pc-company">${esc(p.company_type)}${p.company_stage ? ' · ' + esc(p.company_stage) : ''}</div>
        </div>
        <div class="pc-verdict" style="background:${verdictColor(p.reaction)}20;color:${verdictColor(p.reaction)};border:1px solid ${verdictColor(p.reaction)}40">
          ${esc(verdictLabel(p.reaction))}
        </div>
      </div>
      ${p.primary_goal ? `
      <div class="pc-row">
        <span class="pc-label">GOAL</span>
        <span class="pc-val">${esc(p.primary_goal)}</span>
      </div>` : ''}
      ${p.objections?.[0] ? `
      <div class="pc-row">
        <span class="pc-label">OBJECTION</span>
        <span class="pc-chip">${esc(p.objections[0])}</span>
      </div>` : ''}
      ${p.likely_response ? `
      <div class="pc-row">
        <span class="pc-label">REPLY</span>
        <span class="pc-val pc-italic">"${esc(p.likely_response)}"</span>
      </div>` : ''}
      <div class="pc-footer">
        <div class="pc-skep-wrap">
          <span class="pc-skep-label">Skepticism</span>
          <div class="pc-skep">${skepSegs}</div>
          <span class="pc-skep-num">${p.skepticism_level || 0}/5</span>
        </div>
        ${p.budget_sensitivity ? `
        <span class="pc-budget" style="color:${budgetColor(p.budget_sensitivity)}">
          ${esc(p.budget_sensitivity.toUpperCase())} budget sensitivity
        </span>` : ''}
      </div>
    </div>`
  }).join('')

  return `
  <div class="page-break"></div>
  <div class="section-header">
    <div class="section-header-eyebrow">Step 2</div>
    <div class="section-header-title">Buyer Personas</div>
    <div class="section-header-sub">${personas.length} AI-generated buyer archetypes from your ICP</div>
  </div>
  <div class="personas-grid">${cards}</div>`
}

function buildMessages(messages, reactions, summaries, winner, personas) {
  if (!messages || !messages.length) return ''

  const winnerAngle = winner?.winner_angle
  const personaMap = {}
  if (personas) personas.forEach(p => { personaMap[p.id] = p })

  const msgCards = messages.map(msg => {
    const summary = (summaries || []).find(s => s.message_id === msg.id || s.angle === msg.angle)
    const msgReactions = (reactions || []).filter(r => r.message_id === msg.id)
    const isWinner = msg.angle === winnerAngle
    const intCount  = msgReactions.filter(r => r.verdict === 'interested').length
    const neutCount = msgReactions.filter(r => r.verdict === 'neutral').length
    const objCount  = msgReactions.filter(r => r.verdict === 'objection').length
    const avgScore  = summary?.average_interest_score ?? (msgReactions.length
      ? (msgReactions.reduce((s, r) => s + (r.interest_score || 0), 0) / msgReactions.length).toFixed(1)
      : '-')

    return `
    <div class="msg-card${isWinner ? ' msg-card--winner' : ''}">
      ${isWinner ? '<div class="msg-winner-banner">WINNING ANGLE</div>' : ''}
      <div class="msg-card-inner">
        <div class="msg-angle">${esc(angleLabel(msg.angle))}</div>
        <div class="msg-subject">${esc(msg.subject_line)}</div>
        <div class="msg-body">${esc(msg.body)}</div>
        <div class="msg-scores">
          <div class="msg-score-item">
            <span class="msg-score-val" style="color:${scoreColor(parseFloat(avgScore))}">${avgScore}</span>
            <span class="msg-score-label">Avg Interest</span>
          </div>
          <div class="msg-score-item">
            <span class="msg-score-val" style="color:#22c55e">${intCount}</span>
            <span class="msg-score-label">Interested</span>
          </div>
          <div class="msg-score-item">
            <span class="msg-score-val" style="color:#f59e0b">${neutCount}</span>
            <span class="msg-score-label">Neutral</span>
          </div>
          <div class="msg-score-item">
            <span class="msg-score-val" style="color:#ef4444">${objCount}</span>
            <span class="msg-score-label">Objections</span>
          </div>
        </div>
      </div>
    </div>`
  }).join('')

  // Reaction table - group by persona, show each message's score
  const personaIds = [...new Set((reactions || []).map(r => r.persona_id))]
  const tableRows = personaIds.slice(0, 20).map(pid => {
    const pReactions = (reactions || []).filter(r => r.persona_id === pid)
    const persona = personaMap[pid] || { name: pid }
    const cells = messages.map(msg => {
      const r = pReactions.find(r => r.message_id === msg.id)
      if (!r) return '<td class="rt-cell">-</td>'
      return `<td class="rt-cell">
        <span style="color:${scoreColor(r.interest_score || 0)};font-weight:700">${r.interest_score ?? '-'}</span>
        <span class="rt-verdict" style="color:${verdictColor(r.verdict)}">${verdictLabel(r.verdict)}</span>
      </td>`
    }).join('')
    return `<tr>
      <td class="rt-name">${esc(persona.name)}</td>
      ${cells}
    </tr>`
  }).join('')

  const tableHeaders = messages.map(m =>
    `<th class="${m.angle === winnerAngle ? 'rt-winner-col' : ''}">${esc(angleLabel(m.angle))}${m.angle === winnerAngle ? ' (winner)' : ''}</th>`
  ).join('')

  return `
  <div class="page-break"></div>
  <div class="section-header">
    <div class="section-header-eyebrow">Step 3</div>
    <div class="section-header-title">Message Testing</div>
    <div class="section-header-sub">${messages.length} outreach angles tested against ${personaIds.length} buyer personas · ${(reactions || []).length} simulated reactions</div>
  </div>
  <div class="msg-cards">${msgCards}</div>
  ${tableRows ? `
  <div class="section" style="margin-top:28px">
    <div class="section-title">Reaction Scores by Persona</div>
    <table class="reaction-table">
      <thead>
        <tr>
          <th class="rt-name-col">Persona</th>
          ${tableHeaders}
        </tr>
      </thead>
      <tbody>${tableRows}</tbody>
    </table>
  </div>` : ''}`
}

function buildReport(report, brief, reactions) {
  if (!report) return ''

  const icp  = report.best_icp || {}
  const wm   = report.winning_message || {}
  const br   = report.buyer_readiness || {}
  const objs = report.top_objections || []
  const risks = report.risk_signals || []
  const wf   = report.recommended_workflow || {}
  const days = report.seven_day_experiment || []
  const icpPct = Math.round((icp.confidence_score || 0) * 100)

  const objRows = objs.map((o, i) => `
    <tr>
      <td class="obj-num">${i + 1}</td>
      <td class="obj-text">${esc(o.objection)}</td>
      <td class="obj-freq">×${o.frequency || 1}</td>
      <td class="obj-resp">${esc(o.suggested_response)}</td>
    </tr>`).join('')

  const riskItems = risks.map(r => `
    <div class="risk-item">
      <div class="risk-header">
        <span class="risk-badge" style="background:${sevColor(r.severity)}20;color:${sevColor(r.severity)};border:1px solid ${sevColor(r.severity)}40">
          ${(r.severity || '').toUpperCase()}
        </span>
        <span class="risk-signal">${esc(r.signal)}</span>
      </div>
      <div class="risk-mit"><strong>Mitigation:</strong> ${esc(r.mitigation)}</div>
    </div>`).join('')

  const wfSteps = (wf.steps || []).map((s, i) => `
    <div class="wf-step">
      <div class="wf-num">${i + 1}</div>
      <div class="wf-text">${esc(s)}</div>
    </div>`).join('')

  const dayItems = days.map(d => `
    <div class="day-card">
      <div class="day-header">Day ${d.day}</div>
      <div class="day-goal-text">${esc(d.goal)}</div>
      <div class="day-row"><span class="day-label">Action</span><span class="day-val">${esc(d.action)}</span></div>
      <div class="day-row"><span class="day-label">Metric</span><span class="day-val">${esc(d.success_metric)}</span></div>
    </div>`).join('')

  return `
  <div class="page-break"></div>
  <div class="section-header">
    <div class="section-header-eyebrow">Step 5</div>
    <div class="section-header-title">GTM Report</div>
    <div class="section-header-sub">Recommendations, risk signals, and your 7-day outbound plan</div>
  </div>

  <!-- ICP -->
  <div class="section">
    <div class="section-title">Best ICP Segment</div>
    <div class="info-box">
      <div class="info-row"><span class="info-key">Segment</span><span class="info-val fw">${esc(icp.segment)}</span></div>
      <div class="info-row">
        <span class="info-key">ICP Fit</span>
        <span class="info-val">
          <span style="font-size:18px;font-weight:700;color:#6366f1">${icpPct}%</span>
          <div class="conf-bar-wrap"><div class="conf-bar" style="width:${icpPct}%"></div></div>
        </span>
      </div>
      ${icp.reasoning ? `<div class="info-row"><span class="info-key">Reasoning</span><span class="info-val">${esc(icp.reasoning)}</span></div>` : ''}
    </div>
  </div>

  <!-- Winning message -->
  <div class="section">
    <div class="section-title">Winning Message: ${esc(angleLabel(wm.angle))}</div>
    <div class="info-box">
      <div class="info-row">
        <span class="info-key">Avg Interest</span>
        <span class="info-val fw" style="color:${scoreColor(wm.average_score || 0)}">${wm.average_score ?? 'N/A'} / 10</span>
      </div>
      <div class="info-row"><span class="info-key">Subject Line</span><span class="info-val fw">${esc(wm.recommended_subject_line)}</span></div>
      ${wm.reasoning ? `<div class="info-row"><span class="info-key">Why it wins</span><span class="info-val">${esc(wm.reasoning)}</span></div>` : ''}
      ${wm.recommended_body ? `<div class="message-body">${esc(wm.recommended_body)}</div>` : ''}
    </div>
  </div>

  <!-- Buyer readiness -->
  <div class="section">
    <div class="section-title">Buyer Readiness</div>
    <div class="readiness-box">
      <div class="readiness-score" style="color:${scoreColor(br.score || 0)}">${br.score ?? '-'}</div>
      <div class="readiness-detail">
        <div class="readiness-label">${(br.label || 'N/A').toUpperCase()} · out of 10</div>
        ${br.reasoning ? `<div class="readiness-reasoning">${esc(br.reasoning)}</div>` : ''}
      </div>
    </div>
  </div>

  <!-- Objections -->
  ${objs.length ? `
  <div class="section">
    <div class="section-title">Top Objections + Suggested Responses</div>
    <table>
      <thead><tr><th>#</th><th>Objection</th><th>Freq</th><th>Suggested Response</th></tr></thead>
      <tbody>${objRows}</tbody>
    </table>
  </div>` : ''}

  <!-- Risk signals -->
  ${risks.length ? `
  <div class="section">
    <div class="section-title">Risk Signals</div>
    ${riskItems}
  </div>` : ''}

  <!-- Workflow -->
  ${wf.steps?.length ? `
  <div class="section">
    <div class="section-title">${esc(wf.title || 'Recommended GTM Workflow')}</div>
    ${wfSteps}
  </div>` : ''}

  <!-- 7-day -->
  ${days.length ? `
  <div class="section">
    <div class="section-title">7-Day Outbound Experiment</div>
    <div class="days-grid">${dayItems}</div>
  </div>` : ''}

  <!-- Next experiment -->
  ${report.next_experiment ? `
  <div class="section">
    <div class="section-title">Next Experiment to Run</div>
    <div class="next-exp">${esc(report.next_experiment)}</div>
  </div>` : ''}`
}

/* ── CSS ─────────────────────────────────────────────────── */

const CSS = `
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  font-size: 12.5px;
  color: #111;
  background: #fff;
  line-height: 1.6;
}

.page { max-width: 860px; margin: 0 auto; padding: 48px 48px 64px; }

/* ── Doc header ── */
.doc-header {
  border-bottom: 2px solid #111;
  padding-bottom: 20px;
  margin-bottom: 28px;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
}
.doc-brand { font-size: 10px; font-weight: 800; letter-spacing: 0.18em; text-transform: uppercase; color: #6366f1; }
.doc-title  { font-size: 26px; font-weight: 700; letter-spacing: -0.03em; color: #111; margin-top: 6px; }
.doc-sub    { font-size: 13px; color: #888; margin-top: 3px; }
.doc-meta   { text-align: right; font-size: 11px; color: #888; line-height: 1.8; }

/* ── Metrics ── */
.metrics {
  display: grid; grid-template-columns: repeat(4, 1fr);
  border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; margin-bottom: 24px;
}
.metric { padding: 14px 18px; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; gap: 3px; }
.metric:last-child { border-right: none; }
.metric-val   { font-size: 20px; font-weight: 700; color: #111; letter-spacing: -0.02em; }
.metric-label { font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.06em; }

/* ── Conf note ── */
.conf-note {
  background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px;
  padding: 10px 14px; font-size: 11px; color: #92400e; margin-bottom: 28px;
}

/* ── Section header (between major blocks) ── */
.section-header {
  margin: 0 0 24px;
  padding: 20px 0 16px;
  border-top: 2px solid #111;
}
.section-header-eyebrow {
  font-size: 10px; font-weight: 800; letter-spacing: 0.14em;
  text-transform: uppercase; color: #6366f1; margin-bottom: 4px;
}
.section-header-title { font-size: 20px; font-weight: 700; letter-spacing: -0.03em; color: #111; }
.section-header-sub   { font-size: 12px; color: #888; margin-top: 4px; }

/* ── Generic section ── */
.section { margin-bottom: 28px; }
.section-title {
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: #6366f1; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 1px solid #f0f0f0;
}
.section-body { font-size: 13px; color: #333; line-height: 1.75; }

/* ── Brief grid ── */
.brief-grid { display: flex; flex-direction: column; gap: 0; border: 1px solid #e8e8e8; border-radius: 6px; overflow: hidden; }
.brief-row  { display: flex; border-bottom: 1px solid #f4f4f4; }
.brief-row:last-child { border-bottom: none; }
.brief-key  { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: #888; min-width: 110px; padding: 10px 12px; background: #fafafa; flex-shrink: 0; }
.brief-val  { font-size: 12px; color: #222; padding: 10px 12px; line-height: 1.6; }

/* ── Page break ── */
.page-break { page-break-before: always; }

/* ── Persona cards ── */
.personas-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 8px;
}
.persona-card {
  border: 1px solid #e8e8e8; border-radius: 8px; padding: 14px;
  display: flex; flex-direction: column; gap: 8px; background: #fafafa;
}
.pc-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.pc-name    { font-size: 13px; font-weight: 700; color: #111; }
.pc-title   { font-size: 10px; color: #555; margin-top: 2px; }
.pc-company { font-size: 10px; color: #888; margin-top: 1px; }
.pc-verdict {
  font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 3px;
  white-space: nowrap; flex-shrink: 0; margin-top: 2px;
}
.pc-row { display: flex; gap: 6px; font-size: 11px; align-items: flex-start; }
.pc-label { font-size: 8px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #aaa; min-width: 64px; padding-top: 2px; flex-shrink: 0; }
.pc-val   { color: #333; line-height: 1.5; }
.pc-italic { font-style: italic; color: #555; }
.pc-chip  { font-size: 10px; color: #ef4444; background: #fef2f2; border: 1px solid #fecaca; border-radius: 3px; padding: 1px 6px; line-height: 1.5; }
.pc-footer { display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #eeeeee; padding-top: 8px; flex-wrap: wrap; gap: 4px; }
.pc-skep-wrap { display: flex; align-items: center; gap: 4px; }
.pc-skep { display: flex; gap: 2px; }
.seg { width: 8px; height: 3px; border-radius: 2px; background: #e0e0e0; }
.seg-filled { background: #f59e0b; }
.pc-skep-label { font-size: 9px; color: #aaa; }
.pc-skep-num   { font-size: 9px; color: #888; }
.pc-budget { font-size: 9px; font-weight: 700; }

/* ── Message cards ── */
.msg-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.msg-card {
  border: 1px solid #e8e8e8; border-radius: 8px; overflow: hidden;
  display: flex; flex-direction: column;
}
.msg-card--winner { border: 2px solid #6366f1; }
.msg-winner-banner {
  background: #6366f1; color: #fff; font-size: 10px; font-weight: 800;
  letter-spacing: 0.1em; text-align: center; padding: 5px 10px;
}
.msg-card-inner { padding: 14px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.msg-angle   { font-size: 10px; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; color: #6366f1; }
.msg-subject { font-size: 13px; font-weight: 700; color: #111; line-height: 1.3; }
.msg-body    { font-size: 11px; color: #444; line-height: 1.6; flex: 1; white-space: pre-wrap; }
.msg-scores  { display: flex; gap: 12px; border-top: 1px solid #f0f0f0; padding-top: 10px; }
.msg-score-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.msg-score-val   { font-size: 16px; font-weight: 700; line-height: 1; }
.msg-score-label { font-size: 9px; color: #aaa; text-transform: uppercase; letter-spacing: 0.06em; }

/* ── Reaction table ── */
.reaction-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.reaction-table th {
  text-align: left; font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: #888; padding: 8px 10px; border-bottom: 2px solid #e0e0e0;
}
.reaction-table td { padding: 8px 10px; border-bottom: 1px solid #f4f4f4; vertical-align: top; }
.rt-name-col { min-width: 130px; }
.rt-winner-col { color: #6366f1; }
.rt-name  { font-weight: 600; color: #222; font-size: 11px; }
.rt-cell  { text-align: center; }
.rt-verdict { display: block; font-size: 9px; margin-top: 2px; }

/* ── Info boxes ── */
.info-box { border: 1px solid #e8e8e8; border-left: 3px solid #6366f1; border-radius: 6px; padding: 16px 18px; background: #fafafe; }
.info-row { display: flex; gap: 10px; margin-bottom: 10px; font-size: 12px; }
.info-row:last-child { margin-bottom: 0; }
.info-key { font-weight: 700; color: #666; min-width: 120px; flex-shrink: 0; font-size: 11px; }
.info-val { color: #222; }
.fw { font-weight: 600; }
.message-body {
  font-size: 11px; font-family: 'Courier New', Courier, monospace;
  background: #f4f4f8; border: 1px solid #e0e0e0; border-radius: 4px;
  padding: 12px 14px; margin-top: 12px; white-space: pre-wrap; line-height: 1.7; color: #222;
}

/* ── Confidence bar ── */
.conf-bar-wrap { height: 4px; background: #e8e8e8; border-radius: 2px; margin-top: 5px; overflow: hidden; }
.conf-bar      { height: 100%; background: #6366f1; border-radius: 2px; }

/* ── Objections table ── */
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #888; padding: 8px 10px; border-bottom: 2px solid #e0e0e0; }
td { padding: 10px 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
.obj-num  { color: #aaa; width: 24px; }
.obj-text { color: #222; font-weight: 500; }
.obj-freq { color: #d97706; font-weight: 700; width: 40px; }
.obj-resp { color: #555; }

/* ── Risk signals ── */
.risk-item { border: 1px solid #e8e8e8; border-radius: 6px; padding: 12px 14px; margin-bottom: 10px; }
.risk-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.risk-badge  { font-size: 9px; font-weight: 700; letter-spacing: 0.06em; padding: 2px 8px; border-radius: 3px; flex-shrink: 0; }
.risk-signal { font-size: 12px; font-weight: 600; color: #111; }
.risk-mit    { font-size: 11px; color: #555; line-height: 1.6; }

/* ── Workflow ── */
.wf-step { display: flex; gap: 12px; margin-bottom: 10px; align-items: flex-start; }
.wf-num  { width: 22px; height: 22px; border-radius: 50%; background: #6366f1; color: #fff; font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
.wf-text { font-size: 12px; color: #333; line-height: 1.6; padding-top: 2px; }

/* ── 7-day grid ── */
.days-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.day-card  { border: 1px solid #e8e8e8; border-radius: 6px; padding: 10px 12px; background: #fafafa; }
.day-header    { font-size: 11px; font-weight: 800; color: #6366f1; margin-bottom: 4px; }
.day-goal-text { font-size: 11px; font-weight: 600; color: #111; margin-bottom: 8px; line-height: 1.4; }
.day-row   { display: flex; gap: 4px; font-size: 10px; margin-bottom: 3px; line-height: 1.5; }
.day-label { font-weight: 700; color: #aaa; flex-shrink: 0; min-width: 46px; }
.day-val   { color: #333; }

/* ── Readiness ── */
.readiness-box    { display: flex; align-items: center; gap: 20px; border: 1px solid #e8e8e8; border-radius: 6px; padding: 16px 18px; background: #fafafa; }
.readiness-score  { font-size: 40px; font-weight: 700; letter-spacing: -0.04em; line-height: 1; }
.readiness-label  { font-size: 12px; font-weight: 700; color: #555; margin-bottom: 6px; }
.readiness-reasoning { font-size: 12px; color: #555; line-height: 1.6; }

/* ── Next experiment ── */
.next-exp { background: #f8f8fe; border: 1px solid rgba(99,102,241,0.2); border-left: 3px solid #6366f1; border-radius: 6px; padding: 14px 16px; font-size: 13px; color: #333; line-height: 1.7; }

/* ── Footer ── */
.doc-footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid #e0e0e0; font-size: 10px; color: #bbb; display: flex; justify-content: space-between; }

/* ── Print ── */
@media print {
  body { font-size: 11.5px; }
  .page { padding: 0; max-width: 100%; }
  .page-break { page-break-before: always; break-before: page; }
  .days-grid { grid-template-columns: repeat(4, 1fr); }
  .personas-grid { grid-template-columns: repeat(3, 1fr); }
  .msg-cards { grid-template-columns: repeat(3, 1fr); }
  @page { margin: 18mm 16mm; }
}
`

/* ── Main builder ────────────────────────────────────────── */

function buildHTML({ report, brief, personas, messages, reactions, summaries, winner }) {
  const date = formatDate(report?.created_at)
  const name = brief?.product_name || 'Your Product'

  const cover    = buildCover(brief, report, date)
  const personaSection = buildPersonas(personas)
  const msgSection     = buildMessages(messages, reactions, summaries, winner, personas)
  const reportSection  = buildReport(report, brief, reactions)

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>GTM Report: ${esc(name)}</title>
<style>${CSS}</style>
</head>
<body>
<div class="page">
  ${cover}
  ${personaSection}
  ${msgSection}
  ${reportSection}
  <div class="doc-footer">
    <span>GTM Simulation Lab · synthetic buyer data, not real responses</span>
    <span>${esc(date)}</span>
  </div>
</div>
<script>window.onload = function() { window.print(); }<\/script>
</body>
</html>`
}

/* ── Export ──────────────────────────────────────────────── */

export function downloadGTMReport(payload) {
  const html = buildHTML(payload)
  const win = window.open('', '_blank')
  if (!win) {
    // Popup blocked - fall back to HTML download
    const name = payload?.brief?.product_name || 'report'
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `gtm-report-${slug(name)}.html`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    return
  }
  win.document.write(html)
  win.document.close()
}
