# GTM Simulation Lab

> **Simulate your GTM before launching outreach.**

An open-source simulator for B2B founders. Describe your product and buyer, shape the audience, and get AI buyer personas, scored reactions to several cold-email angles, the objections to prepare for, and a 7-day outbound plan that respects local outreach law. All before you send a single real email.

---

## What it does

| Step | What happens |
|------|-------------|
| 1. **Brief** | Your product, ICP, pricing, channel, pain point, and goal |
| 2. **Audience** | Buyer role mix (decision maker, champion, evaluator), regions, company sizes, industries, what buyers use today, and five behavior traits |
| 3. **Market intelligence** | For each region: cold-outreach rules per country, buying culture, fiscal year-ends, local time, public holidays, World Bank indicators, and this week's headlines |
| 4. **Personas** | 12 by default (up to 500), generated in parallel batches that follow the audience and live market context |
| 5. **Message testing** | 2 to 5 cold emails, each on a different angle |
| 6. **Reactions** | Every persona scores every email for interest, clarity, trust, and urgency, three times in shuffled order; the winner is reported with its win rate |
| 7. **Report** | Winning angle, top objections with rebuttals, best segment, risks, workflow, and a 7-day experiment |

### Built to be trusted

- **Repeated, not one-shot.** Reactions run three times; a winner that flips between runs is called a tie.
- **No silent fake data.** If the AI service is unavailable, you see clearly labelled sample data and the reason. Partial results say how many were generated; they are never padded.
- **Each buyer judged alone**, in small batches, with no built-in rule about which roles should like you.
- **Sources on everything live.** Economic data shows its year; outreach rules are marked settled or contested and are not legal advice.

---

## Quick start

### Prerequisites

- Python 3.11 or 3.12
- Node.js 18+
- An OpenAI-compatible API key (OpenRouter recommended), or none at all in mock mode

### Run locally

```bash
git clone https://github.com/sanketmuchhala/GTM-SImulator.git
cd GTM-SImulator
cp .env.example .env          # add your LLM_API_KEY

# Backend (http://localhost:5001)
cd backend
pip install -r requirements.txt
python run.py

# Frontend (http://localhost:3000), in a second terminal
cd frontend
npm install
npm run dev
```

### Mock mode (no API key)

```bash
cd backend
MOCK_MODE=true python run.py
```

Every step serves pre-generated sample data from `backend/mock_data/`, labelled as sample data in the UI. Live market intelligence still works because it does not need an LLM.

### Docker

`docker compose up --build` builds this repository's `Dockerfile` (backend and frontend in one container, ports 3000 and 5001). It is not covered by CI; the manual steps above are the tested path.

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | API key for any OpenAI-compatible provider |
| `LLM_BASE_URL` | Provider URL, e.g. `https://openrouter.ai/api/v1` |
| `LLM_MODEL_NAME` | Model, e.g. `openai/gpt-4o-mini` |
| `MOCK_MODE` | `true` serves labelled sample data and lets the server start without a key |
| `VITE_API_BASE_URL` | Frontend only: backend URL when deployed (e.g. Vercel to Render) |
| `ZEP_API_KEY` | Optional, only for the legacy social-simulation flow |

A default run (12 personas, 3 angles) makes 22 LLM calls (2 persona batches, 1 for messages, 18 for reactions, 1 for the report) and costs roughly $0.03 on gpt-4o-mini.

---

## Architecture

```
POST /api/gtm/brief                  brief + audience, saved to uploads/gtm_briefs/<id>/
GET  /api/gtm/market?regions=...     region profiles + live signals (no LLM)
POST /api/gtm/personas/<id>          batched persona generation, with meta (source, generated/requested)
POST /api/gtm/messages/<id>          2 to 5 message variants
POST /api/gtm/reactions/<id>         3 shuffled runs, averaged, with win rate and stability
POST /api/gtm/report/<id>            report + 7-day plan that respects outreach rules and holidays

POST /api/idea/sessions              Idea Studio (in progress): chat sessions
POST /api/idea/sessions/<id>/messages   streamed co-founder reply (Server-Sent Events)
```

Everything is cached per brief as JSON under `backend/uploads/`. No database, no accounts.

### Live data sources (no API keys)

| Source | Used for |
|--------|----------|
| [World Bank Indicators API](https://data.worldbank.org/) | GDP growth, inflation, unemployment |
| [Nager.Date](https://date.nager.at/) | Public holidays in the next 60 days |
| [Google News RSS](https://news.google.com/) | This week's business headlines per region |

Each source is cached and fails soft: a region always returns its static profile.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3 (Composition API), Vue Router, D3 |
| Backend | Flask, Python 3.11, gunicorn (threaded workers) |
| LLM | Any OpenAI-compatible API via `backend/app/utils/llm_client.py` |
| Persistence | JSON files under `backend/uploads/` |
| Deploy | Render (backend, `render.yaml`) and Vercel (frontend) |

The repository also contains the original multi-agent social simulation flow (OASIS, Zep) it was forked from. The GTM flow does not use it.

---

## Project structure

```
frontend/src/
  views/        Home, SimulatePage, GTMPersonasView, GTMMessageTestingView, GTMReportView
  components/   GTMBriefForm, AudienceBuilder, MarketIntel, HeroViz (buyer network), PersonaCard
  api/          gtm.js, idea.js (streaming), index.js (axios)
  store/        gtmSimulation.js
  utils/        audience.js (roles, color blending), gtmFormatter.js, downloadMarkdown.js
  mock/         offline sample data

backend/app/
  api/          gtm.py, idea.py
  services/     gtm_persona_generator, gtm_message_generator, gtm_reaction_simulator,
                gtm_aggregator, gtm_report_generator, gtm_audience, gtm_market, idea_chat
  models/       gtm_brief.py, idea_session.py
  utils/        llm_client.py, text_style.py, logger.py
backend/tests/  pytest suite (no network, stubbed LLM)
backend/mock_data/
```

Run the tests with `cd backend && python -m pytest -q`.

---

## FAQ

**Is this real buyer data?**
No. Personas, reactions, and scores are AI-generated. Use the result as a directional first read and confirm the winning angle with a small real send.

**Are the outreach rules legal advice?**
No. They summarise published guidance as of November 2026, and several countries are marked contested. Check with local counsel before relying on them.

**Can I export the report?**
Yes. The report page opens a print-ready version with every section and the 7-day plan; use your browser's Save as PDF.

---

## Roadmap

- [x] Brief, personas, message testing, reactions, report
- [x] Multi-run scoring with win rate, labelled sample data
- [x] Audience builder with blended buyer-role colors
- [x] Live market intelligence per region
- [x] Batched persona generation for large audiences
- [ ] Idea Studio: talk through an early idea with an AI co-founder and watch it sharpen live
- [ ] History of past simulations
- [ ] Real reply ingestion to calibrate the simulation

---

## License

[AGPL-3.0](LICENSE)
