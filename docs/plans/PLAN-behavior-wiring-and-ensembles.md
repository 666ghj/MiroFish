# Implementation Plan: Wire Up Agent Behavior Config (#1) + Seeded Ensemble Runs (#2)

**Repo:** MiroFish (`backend/` Flask + OASIS 0.2.5 / camel-ai 0.2.78, `frontend/` Vue)
**Author of plan:** Claude (Cowork), 2026-10-09
**Audience:** the engineer or coding agent implementing this. The plan stands on its own; you don't need the conversation that produced it.

---

## 0. TL;DR

1. **Use the behavior fields that are already generated.** `simulation_config_generator.py` makes the LLM fill in per-agent `stance`, `sentiment_bias`, `influence_weight`, `posts_per_hour`, `comments_per_hour` and `response_delay_*`. The Step 2 UI displays them. The run scripts ignore every one of them. The only fields that affect a run are `activity_level`, `active_hours` and the time-of-day multipliers. `scheduled_events` is always `[]`. Platform weights are hardcoded constants that nothing reads. Make each field either drive behavior or get removed. Nothing should be shown in the UI that doesn't affect the run.
2. **Turn one-shot runs into seeded ensembles.** Agent activation uses unseeded module-level `random`, and each run produces one sample. Add a `seed` to every run. Add an *ensemble* that clones a prepared simulation into N replicates with derived seeds and runs them with bounded concurrency. Each replicate finishes with a structured **final poll** of every agent on 1–3 outcome questions. The ensemble then aggregates the polls and the behavioral metrics into distributions (`ensemble_summary.json`/`.md`).

Ship as **4 PRs** (§7). Old simulations must keep running exactly as before (versioned behavior, §2.1).

---

## 1. Verified facts (read these before writing code)

All line numbers refer to `main` as it was before this change (commit `7657031`).

### 1.1 Config that is generated but never used

| Field | Generated at | Read by runner? |
|---|---|---|
| `AgentActivityConfig.stance / sentiment_bias / influence_weight` | `app/services/simulation_config_generator.py` L53–82, LLM prompt ~L815–905 | **No** (grep finds no use outside the generator) |
| `posts_per_hour / comments_per_hour` | same | **No** |
| `response_delay_min / response_delay_max` | same | **No** |
| `EventConfig.scheduled_events` | `_parse_event_config` L721–728 **hardcodes `[]`** | **No** |
| `EventConfig.hot_topics / narrative_direction` | `_generate_event_config` L648–720 | Only counted in an API summary (`app/api/simulation.py` L1287) |
| `PlatformConfig.recency/popularity/relevance_weight, viral_threshold, echo_chamber_strength` | **Hardcoded constants**, not even LLM output: L343–361 | **No** |

What the runner does use: `time_config.*`, `agent_configs[].activity_level`, `agent_configs[].active_hours`, `event_config.initial_posts`.

The frontend presents all of these as real parameters: `frontend/src/components/Step2EnvSetup.vue` L202–323 (agent stance, posts/hr, delay, sentiment, influence, platform weights) and L385–392 (narrative, hot topics).

### 1.2 Activation logic is duplicated three times and unseeded

- `backend/scripts/run_parallel_simulation.py` `get_active_agents_for_round` L1040–1090 (`random.uniform`, `random.random`, `random.sample` on the global module)
- `backend/scripts/run_twitter_simulation.py` ~L490–520 (copy)
- `backend/scripts/run_reddit_simulation.py` ~L490–515 (copy)

In parallel mode, Twitter and Reddit run concurrently in one asyncio process (`asyncio.gather`, L1585) and **share the global `random`**. Interleaving depends on LLM latency, so seeding the global RNG alone would not make the schedule reproducible.

### 1.3 How persona text reaches the agent (OASIS 0.2.5)

- Twitter: `oasis/social_agent/agents_generator.py` `generate_twitter_agent_graph` (L614–649) reads the CSV column **`user_char`** into `profile.other_info.user_profile`. `UserInfo.to_twitter_system_message` (`oasis/social_platform/config/user.py`) puts it in the system prompt as `"Your have profile: {user_profile}."`
- Reddit: `reddit_profiles.json` field **`persona`** goes to the same place, plus age/gender/MBTI/country.
- **So the cheapest, least invasive injection point is to append a behavior block to `user_char` / `persona` in a derived per-run profile file.** You don't need to subclass OASIS.

### 1.4 OASIS platform/recsys limits

- `OasisEnv.__init__` (`oasis/environment/env.py` ~L75–97) builds `Platform` with hardcoded params (`recsys_type="twhin-bert"`, `refresh_rec_post_count=2`, `max_rec_post_len=2`, `following_post_count=3` for Twitter; `reddit` hot-score for Reddit). `oasis.make(platform=<Platform instance>)` is supported, so these *can* be overridden.
- OASIS has **no** recency/popularity/relevance weight knobs and no viral threshold. Implementing them would mean forking the recsys. **Out of scope** (§2.5).
- OASIS recsys itself uses global `random` (`recsys.py` L163, 413, 646–647, 749; `platform.py` L277).
- The feed shows posts from followed accounts (`following_post_count`). **The follow graph is the lever MiroFish controls for influence and echo-chamber effects.**

### 1.5 Run lifecycle

- `SimulationRunner.start_simulation` (`app/services/simulation_runner.py` L371–628) spawns `scripts/run_parallel_simulation.py --config <sim_dir>/simulation_config.json [--max-rounds N]` (cmd built at L528–536). It **never passes `--no-wait`**, so the script parks in IPC command-wait mode after the last round to serve interviews. Completion is published while idle (see `tests/test_simulation_idle_completion.py`).
- Sim dir layout (`backend/uploads/simulations/<sim_id>/`): `state.json`, `simulation_config.json`, `twitter_profiles.csv`, `reddit_profiles.json`, `twitter_simulation.db`, `reddit_simulation.db`, `twitter/actions.jsonl`, `reddit/actions.jsonl`, `run_state.json`, `simulation.log`, `env_status.json`, `ipc_commands/`, `ipc_responses/`.
- Interviews: `ParallelIPCHandler._interview_single_platform` (L317–343) does `ManualAction(ActionType.INTERVIEW, {"prompt": ...})` → `env.step`, then reads the latest `trace` row (`_get_interview_result`, L517–558).
- Zep memory updates are opt-in per run (`enable_graph_memory_update`). The updater writes simulated activity into the **same** graph as the seed facts, with no simulation marker (`zep_graph_memory_updater.py` `to_episode_text`).

### 1.6 Local state to respect

`backend/app/services/simulation_runner.py`, `backend/app/api/simulation.py` and `backend/tests/test_simulation_idle_completion.py` have mtimes newer than the rest of the checkout. They probably carry local, uncommitted work. **Run `git status` and `git diff` first. Build on those versions and don't overwrite them.** Work on a branch (`feat/behavior-and-ensembles`).

Real reference simulation to test against: `backend/uploads/simulations/sim_1b05d92d9701`. It covers HEGAM demerger, Indian markets, 6 agents, 120 sim-hours at 60 min/round, 1–3 agents/hour.

---

## 2. Part #1: Make behavior config real

### 2.1 Versioning (do this first)

- Add a top-level `"behavior_version": 2` to configs produced by the generator, and a `"run": {...}` block (seed etc., §3.1).
- Runner rule: if `behavior_version` is missing or `< 2`, use **legacy behavior** (the current code path, byte-for-byte except the RNG source). Existing sims like `sim_1b05d92d9701` must reproduce legacy semantics.
- Add `BEHAVIOR_V2_ENABLED` env flag (default `true`) as a kill switch.

### 2.2 New shared module: `backend/scripts/sim_behavior.py`

Make it pure functions with no OASIS imports at module level, so it can be unit tested. All three run scripts import it, which removes the triplicated activation code.

```python
@dataclass
class RoundContext:
    round_num: int; simulated_hour: int; minutes_per_round: int

def build_behavior_directive(agent_cfg: dict, requirement_topic: str, locale: str) -> str
def write_effective_profiles(sim_dir: str, config: dict, out_suffix=".effective") -> dict[str, str]
def select_active_agents(config: dict, ctx: RoundContext, rng: random.Random,
                         eligibility: "EligibilityTracker") -> list[int]
class EligibilityTracker:   # response_delay
    def on_trigger(self, round_num: int, rng) -> None   # initial posts / scheduled events
    def is_eligible(self, agent_id: int, round_num: int) -> bool
def plan_seed_follows(config: dict, rng: random.Random) -> list[tuple[int, int]]   # (follower, followee)
def due_scheduled_events(config: dict, round_num: int) -> list[dict]
```

### 2.3 Field-by-field semantics (v2)

**`stance` + `sentiment_bias` → persona directive.** `write_effective_profiles` copies `twitter_profiles.csv` to `twitter_profiles.effective.csv` and `reddit_profiles.json` to `reddit_profiles.effective.json`. It appends to `user_char` / `persona`:

```
[Starting disposition] On "<topic>", you currently lean <supportive|opposing|neutral; observer = you mostly read and rarely post opinions>.
Your tone tends to be <clearly negative | slightly negative | balanced | slightly positive | clearly positive>.
This is your starting view, not a script: update it if you see convincing evidence or arguments.
```

- Map `sentiment_bias` buckets: ≤−0.5, (−0.5,−0.15], (−0.15,0.15), [0.15,0.5), ≥0.5.
- `<topic>` = a short (≤15 word) topic phrase. Generate it once at prepare time from `simulation_requirement` and store it as `event_config.topic`. Fallback: first 120 characters of the requirement.
- The last sentence is **required**. Without it the outcome is fixed before the run starts and stance drift (the thing you want to measure) can't happen.
- Write the directive in the sim's locale (reuse `app/utils/locale.py` / `get_language_instruction()` conventions).
- Never modify the original profile files. The UI and `/profiles` keep reading the originals. The run scripts must load the `.effective` files when `behavior_version >= 2`.

**`posts_per_hour` + `comments_per_hour` + `activity_level` → activation probability.**
- v2 per-agent per-round probability: `p = clamp(activity_level * (1 - exp(-(posts_per_hour + comments_per_hour) * minutes_per_round / 60)), 0, 0.95)`, multiplied by the hour multiplier (peak/off-peak/morning/work, the same buckets as legacy).
- Keep the `agents_per_hour_min/max` cap as an upper bound: if more agents pass the Bernoulli draw than `target_count`, subsample with `rng.sample`.
- An action is still "whatever the LLM picks". OASIS can't force post vs. comment. Document that the rates shape *how often* an agent is woken, not the action type.

**`active_hours`.** Unchanged.

**`response_delay_min/max` → reaction latency.** On every trigger (round-0 initial posts, each fired scheduled event), each agent draws `delay ~ U[min,max]` sim-minutes from `rng`. The agent is ineligible until `trigger_round + ceil(delay / minutes_per_round)`. The latest trigger wins. Agents with no pending trigger are unaffected. Caveat: with 60-min rounds, delays under 60 min round to 1 round.

**`influence_weight` + platform `echo_chamber_strength` → seeded follow graph.** After `env.reset()` and **before** round 0 posts, execute `ManualAction(FOLLOW)` pairs from `plan_seed_follows`:
- For each agent *i* and each other agent *j*: `P(i follows j) = base * norm_influence(j) * (1 + echo * same_stance(i,j) - echo * opposite_stance(i,j))`, clamped to [0, 0.9].
- `base = 0.3`, `norm_influence = influence_weight / max(influence_weight)`, `echo = echo_chamber_strength ∈ [0,1]`.
- `observer` and `neutral` count as neither same nor opposite.
- Twitter: `ActionType.FOLLOW`. Reddit: also `FOLLOW` (present in `OASIS_REDDIT_ACTIONS`). Run both through `env.step` in one batch.
- **Tag these as setup:** log them to `actions.jsonl` with `"round": 0, "phase": "setup"`, exclude them from the Zep memory updater and from agent-stats/timeline counts. Check `SimulationRunner._read_action_log` and the `/timeline` and `/agent-stats` endpoints.
- `echo_chamber_strength`: make it an LLM output in the platform step instead of a constant, or keep the defaults (0.5 Twitter / 0.6 Reddit) but mark it as *applied*. Either is acceptable. The constant is fine for the first PR.

**`scheduled_events` → timed injections ("God's-eye view").**
- Schema (`event_config.scheduled_events[]`):
  ```json
  {"id": "evt_1", "at_sim_hour": 26, "poster_agent_id": 4, "poster_type": "MediaOutlet",
   "content": "...", "source": "user|llm_suggested", "enabled": true}
  ```
- Runner: at the start of round *r*, fire every enabled event with `floor(at_sim_hour*60/minutes_per_round) == r` as `ManualAction(CREATE_POST)` by `poster_agent_id`. Log it as an action with `"phase": "injected", "event_id"`, and call `EligibilityTracker.on_trigger`.
- **The LLM must not auto-invent future events by default.** That would inject made-up facts into a forecast. Keep `scheduled_events = []` from the generator. Optionally return up to 3 entries in a separate `event_config.suggested_events` with `source: "llm_suggested", enabled: false`.
- Add CRUD so users author events: `PUT /api/simulation/<sim_id>/scheduled-events` (replace the list; validate hour range, agent id exists, content non-empty). Allow it only while the sim is in `ready` (prepared, not started) or for new ensemble creation.
- Poster assignment: reuse `_assign_initial_post_agents` logic for events that give only `poster_type`.
- **Out of scope:** live injection into a running sim over IPC. Note it as a follow-up.

**`hot_topics`.** Don't inject into agents. Use as tracked keywords in metrics (§3.5: mention counts per round).

**`narrative_direction`.** **Never inject into agents.** It's the generator's guess at the outcome, and feeding it back makes the forecast circular. Rename the UI label to "Generator's hypothesis (not given to agents)". Pass it to the ReportAgent as a hypothesis to test against ensemble results.

### 2.4 Generator changes (`simulation_config_generator.py`)

- Emit `behavior_version: 2`, `event_config.topic`, `scheduled_events: []`, optional `suggested_events`.
- Validate and clamp LLM agent fields: `stance ∈ {supportive, opposing, neutral, observer}` (else `neutral`), `sentiment_bias ∈ [-1,1]`, `influence_weight ∈ [0.1, 5]`, rates ≥ 0, `0 ≤ delay_min ≤ delay_max`. Put this in a `_sanitize_agent_config` function with unit tests.
- Platform config: drop `recency_weight`, `popularity_weight`, `relevance_weight`, `viral_threshold` from emitted v2 configs. Keep the dataclass fields for reading old configs.

### 2.5 Explicit non-goals for #1

- No recsys fork (recency/popularity weights, viral thresholds).
- No forcing of action types.
- No live mid-run event injection.

### 2.6 Frontend (small, in PR 2)

- `Step2EnvSetup.vue`: remove the four unsupported platform rows (L280–292 and L307–319 equivalents) for v2 configs. Relabel narrative (§2.3).
- Add a "Scheduled events" editor: list, add, remove, set hour, poster and content. It calls the new PUT endpoint.

---

## 3. Part #2: Seeds + ensembles

### 3.1 Seeds for every run

- Config gets `"run": {"seed": <int>, "replicate_index": null, "ensemble_id": null}`. Also accept `--seed` on all three run scripts (CLI overrides config).
- `POST /api/simulation/start` accepts an optional `seed`. If absent, generate `secrets.randbelow(2**31)`, **persist it in `run_state.json` and the config snapshot**, and return it in the response.
- In the script: `random.seed(seed)` at startup (best effort for OASIS-internal randomness), plus **independent RNGs per platform**: `rng_tw = random.Random(f"{seed}:twitter")`, `rng_rd = random.Random(f"{seed}:reddit")`. Pass them into `sim_behavior` functions. No MiroFish code may touch the global `random` after this.
- LLM sampling: verify what `ModelFactory.create(..., model_type=...)` uses for temperature in camel-ai 0.2.78. Add optional `config.run.llm_temperature`; if set, pass `model_config_dict={"temperature": t}`. If the provider supports a `seed` parameter (OpenAI-compatible), pass it too, guarded by try/except.
- **Be honest in docs and UI:** a seed makes the *schedule* reproducible (activation, delays, follow graph, scheduled events). It does *not* make LLM outputs bit-identical. Don't promise "replayable runs".

### 3.2 Ensemble data model

New directory `backend/uploads/ensembles/<ensemble_id>/`:

```
ensemble.json          # definition + status (below)
outcome_questions.json
summary.json           # written by aggregator
summary.md
```

`ensemble.json`:
```json
{
  "ensemble_id": "ens_ab12cd34ef56",
  "base_simulation_id": "sim_1b05d92d9701",
  "project_id": "...", "graph_id": "...",
  "n_replicates": 5, "base_seed": 12345, "concurrency": 1,
  "platform": "parallel", "max_rounds": 48,
  "llm_temperature": null,
  "replicates": [
    {"index": 1, "simulation_id": "sim_1b05d92d9701__r01", "seed": 9876, "status": "pending|running|completed|failed|stopped", "error": null}
  ],
  "status": "created|running|aggregating|completed|partial|failed|stopped",
  "created_at": "...", "updated_at": "...",
  "cost_estimate": {"llm_calls_upper_bound": 0}
}
```

- Replicate seed: `int(sha256(f"{base_seed}:{index}").hexdigest()[:8], 16)`.
- Replicate sim = **clone** of the base sim dir: copy `simulation_config.json` (with the `run` block set: seed, `replicate_index`, `ensemble_id`, and `max_rounds` baked in), `twitter_profiles.csv`, `reddit_profiles.json`, and a fresh `state.json` (new id, status `ready`, `ensemble_id` set). **Don't** copy DBs, logs, run_state, IPC dirs or env_status.
- Add `ensemble_id: Optional[str]` and `replicate_index: Optional[int]` to `SimulationState` (`simulation_manager.py`). Hide replicates from `/list` and `/history` by default (`?include_replicates=true` shows them).

### 3.3 Running replicates

New service `backend/app/services/ensemble_runner.py`:

- `EnsembleManager.create(base_sim_id, n, base_seed=None, max_rounds, platform, concurrency=1, outcome_questions=None, llm_temperature=None)`
  - Validate: base sim is prepared (`config_generated` and `profiles_generated`). `1 ≤ n ≤ 50`. **`max_rounds` required** (cost guard). `1 ≤ concurrency ≤ 4`.
  - Resolve outcome questions (§3.4) and write the replicate clones.
  - Compute `cost_estimate.llm_calls_upper_bound = n * platforms * max_rounds * agents_per_hour_max_effective + n * platforms * n_agents * n_questions`.
- `EnsembleManager.start(ensemble_id)` runs a background thread (daemon) that keeps ≤ `concurrency` replicates running. Each replicate goes through **`SimulationRunner.start_simulation(rep_id, platform, max_rounds, enable_graph_memory_update=False, wait_for_commands=False)`**.
  - Add the `wait_for_commands: bool = True` parameter to `start_simulation`. When False, append `--no-wait` to `cmd` (L528–536) so the process exits and frees resources. Verify that `_monitor_simulation` publishes COMPLETED on exit code 0 with no idle-wait. Add a test.
  - **Replicates must never write to Zep** (`enable_graph_memory_update=False` is forced). N copies of simulated chatter would pollute the knowledge graph.
  - Poll `SimulationRunner.get_run_state(rep_id)` every 2s and update `ensemble.json` atomically: write a temp file, then `os.replace`. Use a per-ensemble lock, as `_finalization_lock` does.
- `stop(ensemble_id)`: stop running replicates via `SimulationRunner.stop_simulation`, mark the rest `stopped`.
- Failure policy: a failed replicate doesn't fail the ensemble. Final status is `completed` (all ok), `partial` (≥ 2 ok, aggregate what exists), or `failed` (< 2 ok).
- Restart recovery: on Flask start (or lazily on `GET`), reconcile any ensemble in `running` from replicate run states. Replicates whose process is gone and not completed → `failed` with error `"interrupted"`. Don't auto-resume.

### 3.4 Final poll (the per-replicate outcome)

Distributions need a number per replicate. Action counts alone don't answer the user's question.

- **Outcome questions** (`outcome_questions.json`), 1–3 items:
  ```json
  [{"id": "q1", "text": "By the close of the 5th session, will HEGAM trade above its 7 Oct close?",
    "type": "probability"},
   {"id": "q2", "text": "What is your current stance on HEGAM?", "type": "choice",
    "options": ["bullish", "neutral", "bearish"]}]
  ```
  Types: `probability` (0–100), `choice` (from `options`), `number` (with `unit`). If the caller doesn't supply them, derive them with one LLM call from `simulation_requirement` (`LLMClient.chat_json`, schema-validated, max 3). They're returned on create so the user can edit them before `start` (`PUT /ensemble/<id>/outcome-questions` while status is `created`).
- **Runner:** after the last round and **before** `env.close()` / command-wait, when `config.run.outcome_questions` is present, interview every agent on **one platform** (Twitter if enabled, else Reddit) with a single prompt:
  ```
  The simulation has ended. Answer as yourself, based only on what you have seen.
  Reply with ONLY a JSON object: {"q1": <0-100>, "q2": "<bullish|neutral|bearish>", "reason": "<one sentence>"}
  ```
  Reuse the interview mechanics: `handle_batch_interview` (L416+) already sends many `INTERVIEW` ManualActions in one `env.step`, then reads each result with `_get_interview_result`. Factor that into a module-level `async def batch_interview(env, agent_graph, db_path, prompts: dict[int,str])` used by both IPC and the poll.
- Parse with tolerant JSON extraction (reuse `llm_client` helpers). Write `final_poll.json` in the replicate dir: `[{agent_id, agent_name, stance_initial, answers:{...}, reason, raw, parse_ok}]`. Unparseable answers → `parse_ok:false` and excluded from stats but counted.
- Exclude poll interviews from `actions.jsonl` metrics (`phase: "poll"`).

### 3.5 Aggregation (`backend/app/services/ensemble_aggregator.py`)

Pure functions over replicate dirs, no LLM calls. Unit test with fixture dirs.

**Per replicate:**
- From `final_poll.json`, per question: `probability` → mean, median and influence-weighted mean across agents. `choice` → share per option. `number` → median.
- Stance drift: compare each agent's `stance_initial` (config) with the poll choice where q is the stance question. Count switched agents.
- From `actions.jsonl` (excluding `phase ∈ {setup, injected, poll}`): total actions, posts, comments; actions per round series; per-stance-group share of posts and of likes/reposts received (join via DB `post` table if needed); top 3 agents by engagement received; `hot_topics` keyword mention counts.

**Across replicates:**
- For each per-replicate scalar: mean, std, min, p10, median, p90, max, n_ok.
- For `probability` questions: the share of replicates where the agent mean > 50.
- Write `summary.json` (machine) and `summary.md` (human). `summary.md` opens with a fixed caveat:
  > These are distributions of *simulated participants' views* across N stochastic runs, not calibrated probabilities of the real-world event. MiroFish has not been backtested for this domain.

### 3.6 API (all under `/api/simulation`, in a new `ensemble` section of `app/api/simulation.py` or a new blueprint file registered in `app/__init__.py`)

| Method | Path | Body / notes |
|---|---|---|
| POST | `/ensemble/create` | `{simulation_id, n_replicates=5, max_rounds (required), base_seed?, platform="parallel", concurrency=1, outcome_questions?, llm_temperature?}` → ensemble.json + questions + cost_estimate |
| PUT | `/ensemble/<id>/outcome-questions` | only while `created` |
| POST | `/ensemble/<id>/start` | |
| POST | `/ensemble/<id>/stop` | |
| GET | `/ensemble/<id>` | status + per-replicate progress (current_round/total_rounds from each run_state) |
| GET | `/ensemble/<id>/summary` | 404 until aggregated |
| GET | `/ensemble/list?simulation_id=` | ensembles for a base sim |
| PUT | `/<simulation_id>/scheduled-events` | from Part #1 |

Follow existing response conventions (`{"success": bool, "data"|"error"}`, `t(...)` i18n keys for messages, plus `locales/` entries in both languages).

### 3.7 Report integration (minimal, PR 4)

- `ReportAgent` gains optional `ensemble_id`. When set, `plan_outline` gets `summary.md` prepended to its planning context. Add a 5th tool `ensemble_stats` (returns `summary.json` sections by key) in `_define_tools` / `_execute_tool`.
- The report prompt must tell the agent to quote ranges from the ensemble, use the caveat sentence, and treat `narrative_direction` as a hypothesis to confirm or reject.
- Report on a base sim with no ensemble: unchanged.

### 3.8 Frontend (PR 4, keep small)

- `Step3Simulation.vue`: a "Runs" number input (default 1). If > 1, call ensemble create → show questions (editable) and cost estimate → start. Show a progress list per replicate.
- `Step4Report.vue`: if an ensemble exists, show the summary table (question → median and p10–p90 across runs) above the report.
- `frontend/src/api/simulation.js`: add the wrappers.

---

## 4. Tests (pytest, `backend/tests/`, run with `uv run pytest`)

New files:

- `test_sim_behavior.py`
  - Same seed → identical `select_active_agents` output over 100 rounds. Different seed → different output.
  - Twitter and Reddit RNGs are independent: consuming one doesn't change the other's sequence.
  - Legacy path (`behavior_version` missing) matches the old function's distribution given the same RNG.
  - Probability formula: rate 0 → never active, activity_level 0 → never, clamp at 0.95, `agents_per_hour_max` cap respected.
  - `EligibilityTracker`: delays block until the expected round; a new trigger overrides.
  - `plan_seed_follows`: with `echo=0`, the stance doesn't matter (statistically, over many seeds); with `echo=1`, the same-stance follow rate is greater than the opposite-stance rate; no self-follows; deterministic per seed.
  - `build_behavior_directive`: contains the "not a script" sentence; never contains `narrative_direction`; sentiment buckets are correct.
  - `write_effective_profiles`: originals are unchanged; the `.effective` CSV keeps the same columns/rows with an extended `user_char`; Reddit JSON is extended in `persona`.
  - `due_scheduled_events`: hour→round mapping, disabled events skipped.
- `test_config_sanitize.py`: clamping/defaulting of bad LLM agent configs; v2 config has no unsupported platform keys; `scheduled_events` stays empty and `suggested_events` are disabled.
- `test_ensemble_manager.py` (patch `SimulationRunner.start_simulation` / `get_run_state` with fakes, in the style of `test_simulation_idle_completion.py`'s `FakeProcess`)
  - Create clones only the right files; replicate seeds are deterministic from `base_seed`; `max_rounds` is required; n and concurrency are bounded.
  - Concurrency limit is never exceeded.
  - `enable_graph_memory_update` is always False for replicates.
  - Failure policy → `completed` / `partial` / `failed`.
  - Restart reconciliation marks orphaned replicates `failed: interrupted`.
  - Replicates hidden from `/list` by default.
- `test_ensemble_aggregator.py`: fixture replicate dirs (hand-written `final_poll.json` and `actions.jsonl`), checking exact expected stats, exclusion of `setup/injected/poll` phases, and handling of `parse_ok:false`.
- `test_runner_no_wait.py`: `start_simulation(wait_for_commands=False)` adds `--no-wait`; exit code 0 → COMPLETED.
- API tests for the new endpoints (Flask test client, as in the existing api tests).

Existing tests must stay green. Run the full suite before each PR.

**Manual end-to-end check** (document results in the PR):
1. Base sim `sim_1b05d92d9701`. Make a v1 config copy and confirm it runs with legacy behavior (no `.effective` files, no setup follows).
2. Re-prepare a v2 sim from the same project. Check that the `.effective` profiles contain directives, the setup follows appear in DB and logs tagged `setup`, and that a user-added scheduled event fires at the right round.
3. Ensemble with `n=3, max_rounds=12, concurrency=1`: three replicate dirs, three `final_poll.json` files, a `summary.md` with the caveat, and no new Zep episodes (check graph episode count before and after).
4. Same `base_seed` twice: identical activation schedules (compare `round_start` + agent ids in `actions.jsonl`), different LLM content.

---

## 5. Acceptance criteria

- [ ] Every agent and platform field shown in Step 2 either changes simulation behavior (with a test proving it) or is no longer shown for v2 configs.
- [ ] `narrative_direction` is never present in any agent prompt (test asserts it).
- [ ] User-authored scheduled events fire at the configured sim hour and are logged as `injected`.
- [ ] Every run records its seed. Same seed → same activation schedule.
- [ ] Ensemble of N replicates runs with bounded concurrency, writes no Zep data, and produces `summary.json`/`summary.md` with per-question distributions and the caveat.
- [ ] Legacy (v1) sims behave as before. The full existing test suite passes.
- [ ] No changes to OASIS site-packages. All customization lives in MiroFish code.

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Directives over-determine outcomes (agents just recite their stance) | "Starting view, not a script" sentence. Measure stance drift. If drift is ~0 across replicates, soften the wording. Make the directive template a constant that's easy to tune. |
| Cost blow-up (N × rounds × agents) | `max_rounds` required, `n ≤ 50`, `concurrency ≤ 4`, upfront `cost_estimate`, defaults n=5 / concurrency=1. |
| API rate limits with concurrent replicates | Concurrency default 1. Each env keeps `semaphore=30`; consider `semaphore = 30 // concurrency`. Optionally route replicates to `LLM_BOOST_*` alternately. |
| OASIS internal randomness breaks reproducibility | Documented: only MiroFish's schedule is guaranteed. Global seed is best effort. |
| Poll answers unparseable | Strict JSON-only prompt, tolerant parser, `parse_ok` flag, and a `parse_rate` in the summary. |
| Setup follows distort agent-stats/timeline | Tag `phase: setup` and filter everywhere actions are counted (grep for readers of `actions.jsonl`). |
| Disk growth (N copies of DBs) | Add replicates to `cleanup_simulation_logs`. Document `DELETE /ensemble/<id>` as a follow-up. |
| Local uncommitted changes in runner/API files | Branch first and rebase onto the working copy. Don't overwrite. |

---

## 7. PR sequence

1. **PR 1: Seeds + shared behavior module (no behavior change).** Create `sim_behavior.py` with the legacy selection, per-platform RNGs, `--seed`, seed in config, run_state and the `/start` response. Switch all three scripts to it. Add `wait_for_commands` / `--no-wait` to `start_simulation`. Tests: determinism, legacy equivalence, no-wait.
2. **PR 2: Behavior v2.** Generator: `behavior_version`, sanitize, topic, drop unsupported platform keys, `suggested_events`. Runner: effective profiles + directives, rate-based activation, response delays, seeded follows, scheduled events. Scheduled-events API. Step 2 UI tweaks. Tests.
3. **PR 3: Ensembles backend.** `ensemble_runner.py`, final poll in the runner, `ensemble_aggregator.py`, API endpoints, SimulationState fields, hidden replicates. Tests and manual E2E.
4. **PR 4: Report + UI.** `ensemble_stats` tool and planning context, Step 3/4 UI, i18n strings.

Each PR must leave `main` runnable.

---

## 8. Open questions for the owner (decide or accept the defaults)

1. Poll platform when both run: **default Twitter only** (halves poll cost). Alternative: both platforms, reported separately.
2. Directive language: **default the sim locale**. Alternative: always English (models often follow English instructions more reliably).
3. Should `echo_chamber_strength` become an LLM-generated value per scenario? **Default: keep constants (0.5/0.6) for now.**
4. Ensemble default size: **5**. For the 6-agent HEGAM-style sims, 10–20 is cheap enough and gives much better distributions.
