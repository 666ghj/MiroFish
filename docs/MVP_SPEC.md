# MVP Specification

## MVP User Flow
1. User lands on home page → clicks "Simulate Your GTM"
2. Fills out GTM Brief form (8 fields)
3. Reviews generated ICP summary → clicks "Generate Personas"
4. Reviews 12 buyer persona cards → clicks "Test Messages"
5. Reviews message × persona reaction matrix → clicks "Run Simulation"
6. Views aggregated results (response rates, objections, segment scores)
7. Clicks "Generate GTM Report"
8. Reviews report → downloads as Markdown

---

## Input Fields (GTM Brief)

| Field | Type | Required | Example |
|-------|------|----------|---------|
| `product_description` | textarea | yes | "AI SDR that automates outbound prospecting" |
| `icp` | textarea | yes | "B2B SaaS companies, 10–200 employees, sales team of 3–10" |
| `pricing` | text | yes | "$500/mo per seat" |
| `target_market` | text | yes | "US, SMB SaaS founders and VP Sales" |
| `sales_channel` | select | yes | outbound email / LinkedIn / cold call / PLG |
| `main_pain_point` | textarea | yes | "SDRs spend 70% of time on research and list building" |
| `competitors` | text | no | "Apollo, Outreach, Clay" |
| `gtm_goal` | select | yes | first 10 customers / expand existing segment / enter new market |

---

## 12 Buyer Persona Types

1. Skeptical VP Sales (Series A, 50–200 employees)
2. Enthusiastic Founder-Seller (pre-revenue, 1–10 employees)
3. Budget-Constrained Sales Lead (bootstrapped SMB)
4. Process-Driven RevOps Manager
5. Tech-Forward SDR Manager
6. Conservative Enterprise Procurement Lead
7. Curious but Overwhelmed Startup Operator
8. Previous Bad Experience Buyer
9. Competitor-Loyal Sales Director
10. Champion Inside Buyer (internal advocate)
11. Influencer-Led Decision Maker (follows KOLs)
12. Late Majority Evaluator (needs proof/case studies)

Each persona object:
```json
{
  "persona_id": "skeptical_vp_sales",
  "name": "Alex Chen",
  "role": "VP of Sales",
  "company_size": "50–200 employees",
  "pain_point": "Sales team is hitting quota inconsistently",
  "skepticism_level": 4,
  "preferred_channel": "LinkedIn",
  "likely_objection": "We already have a process for this."
}
```

---

## 3 Message Angles

1. **Pain-Led** — Opens with the problem; empathizes before pitching
2. **ROI-Led** — Opens with quantified business outcome
3. **Social-Proof-Led** — Opens with a relevant customer reference

Each message variant:
```json
{
  "angle": "pain_led",
  "subject_line": "Your SDRs are wasting 70% of their day",
  "opening_line": "Most sales teams I talk to say their reps spend more time on research than actual selling...",
  "value_prop": "Our AI handles list-building and first-touch research automatically.",
  "cta": "Worth a 15-min call this week?",
  "estimated_word_count": 87
}
```

---

## Response Schema (per persona × message)

```json
{
  "persona_id": "skeptical_vp_sales",
  "message_angle": "pain_led",
  "reaction": "objection",
  "sentiment_score": 2.1,
  "likely_response": "We already have a process for this.",
  "objection_category": "status_quo_bias",
  "interest_signal": false
}
```

`reaction` values: `"interested"` | `"neutral"` | `"objection"`
`objection_category` values: `"status_quo_bias"` | `"price"` | `"trust"` | `"timing"` | `"competitor"` | `"not_relevant"`

---

## Report Schema

```json
{
  "report_id": "gtm_report_abc123",
  "generated_at": "2025-05-13T12:00:00Z",
  "brief_summary": "...",
  "icp_validation": {
    "score": 72,
    "notes": "ICP is well-defined. Consider narrowing to Series A companies.",
    "recommended_refinement": "Focus on VP Sales at 50–150 employee SaaS companies."
  },
  "best_message_angle": {
    "winner": "pain_led",
    "estimated_reply_rate": "8–12%",
    "reasoning": "Pain-led messaging resonated with 8 of 12 personas."
  },
  "top_objections": [
    {
      "objection": "We already have a process for this.",
      "frequency": 5,
      "rebuttal": "Acknowledge their process. Ask: how long does research take per rep per day?"
    }
  ],
  "segment_readiness": [
    {
      "segment": "Skeptical VP Sales",
      "score": 45,
      "notes": "Needs case studies and ROI proof before engaging."
    }
  ],
  "seven_day_experiment": {
    "day_1_3": "Build a list of 50 VP Sales contacts at 50–150 employee SaaS companies.",
    "day_4_5": "Send pain-led sequence to 25. Send ROI-led sequence to 25.",
    "day_6_7": "Measure reply rates. Follow up with interested leads.",
    "success_metric": "3+ positive replies or meeting requests"
  },
  "sections": []
}
```

---

## Fallback Mock Data Requirement
- Every API endpoint must support a `?mock=true` query param returning pre-generated JSON
- Mock data must cover all 12 persona types and all 3 message angles
- Mock report must be complete and downloadable
- App must be fully demoable with `MOCK_MODE=true` env var (no LLM or Zep API keys needed)
- Mock data files live in `backend/mock_data/`

---

## Downloadable Report Requirement
- Report downloadable as Markdown (`.md`) — reuse existing `/api/report/<id>/download` pattern
- PDF export: deferred to Phase 7 (browser print-to-PDF is acceptable fallback for MVP)
