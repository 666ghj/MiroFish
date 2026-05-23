# Stakeholder Interview Subagents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a four-subagent post-simulation interview system (Longitudinal, Diversity, Delphi, Scenario) over MiroFish-simulated stakeholders, plus a cross-method synthesiser, exposed via `/api/interview` and rendered in a new Vue Step4b.

**Architecture:** Deterministic instrument runners (not ReACT). Shared `StakeholderInterviewer` base loads persona + Zep memory digest and administers per-instrument JSON-schema-validated prompts via the existing `LLMClient`. Four subagents own their own instrument YAML + output schema. `InterviewOrchestrator` fans out parallel post-sim execution; `InterviewSynthesizer` aggregates. Files: backend Python services + new Flask blueprint; frontend new Vue component with d3 viz.

**Tech Stack:** Python 3.12, Flask, pydantic v2, PyYAML, scikit-learn (PCA, k-means), scipy (Wilcoxon), numpy, pytest; Vue 3, axios, d3 v7, vue-i18n.

**Spec:** `docs/superpowers/specs/2026-05-23-stakeholder-interview-subagents-design.md`

---

## Phase 0 — Setup

### Task 0: Add deps and pytest scaffold

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/pytest.ini`

- [ ] **Step 1: Add deps to `backend/pyproject.toml`**

In the `dependencies` array (after `pydantic>=2.0.0`), add:
```toml
    "PyYAML>=6.0",
    "scikit-learn>=1.4",
    "scipy>=1.12",
    "numpy>=1.26",
    "pandas>=2.1",
```

- [ ] **Step 2: Create `backend/pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra --strict-markers
markers =
    integration: marks integration tests (deselect with -m 'not integration')
```

- [ ] **Step 3: Create `backend/tests/__init__.py`**

Empty file.

- [ ] **Step 4: Create `backend/tests/conftest.py`**

```python
import os
import sys
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LLM_API_KEY", "test")
os.environ.setdefault("LLM_BASE_URL", "https://example.invalid")
os.environ.setdefault("LLM_MODEL_NAME", "test-model")
os.environ.setdefault("ZEP_API_KEY", "test")

@pytest.fixture
def tmp_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    return tmp_path
```

- [ ] **Step 5: Install + verify**

Run: `cd backend && uv sync --python 3.12 && uv run pytest -q`
Expected: `0 tests collected` (no failures). Confirms infrastructure works.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/pytest.ini backend/tests/__init__.py backend/tests/conftest.py
git commit -m "chore(interviews): add deps and pytest scaffold for interview subsystem"
```

---

### Task 1: Add interview config keys

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Read current config**

Open `backend/app/config.py` and locate the `Config` class.

- [ ] **Step 2: Add config keys**

Add inside the `Config` class (preserving existing keys):
```python
    # Interview subsystem
    INTERVIEW_MAX_TOKENS_PER_RUN = int(os.environ.get("INTERVIEW_MAX_TOKENS_PER_RUN", 15_000_000))
    INTERVIEW_MAX_WORKERS = int(os.environ.get("INTERVIEW_MAX_WORKERS", 8))
    INTERVIEW_DEFAULT_LANGUAGE = os.environ.get("INTERVIEW_DEFAULT_LANGUAGE", "de")
    LLM_STUB_MODE = os.environ.get("LLM_STUB_MODE", "false").lower() == "true"
```

- [ ] **Step 3: Verify import**

Run: `cd backend && uv run python -c "from app.config import Config; print(Config.INTERVIEW_MAX_WORKERS, Config.LLM_STUB_MODE)"`
Expected: `8 False`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(interviews): add interview config keys (token budget, workers, language, stub mode)"
```

---

## Phase 1 — Foundation

### Task 2: Pydantic models for instruments and responses

**Files:**
- Create: `backend/app/models/interview.py`
- Create: `backend/tests/interviews/__init__.py`
- Test: `backend/tests/interviews/test_models.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/interviews/__init__.py` (empty), then `backend/tests/interviews/test_models.py`:
```python
import pytest
from pydantic import ValidationError
from app.models.interview import (
    LikertItem, LikertInstrument, LikertResponse,
    InterviewPhase, SubagentKind,
)

def test_likert_item_requires_de_and_en():
    item = LikertItem(item_id="x1", de="Frage", en="Question", scale=5)
    assert item.scale == 5

def test_likert_item_rejects_bad_scale():
    with pytest.raises(ValidationError):
        LikertItem(item_id="x1", de="d", en="e", scale=2)

def test_likert_instrument_unique_item_ids():
    with pytest.raises(ValidationError):
        LikertInstrument(
            name="t",
            items=[LikertItem(item_id="a", de="d", en="e", scale=5),
                   LikertItem(item_id="a", de="d", en="e", scale=5)],
        )

def test_likert_response_validates_scale_range():
    with pytest.raises(ValidationError):
        LikertResponse(agent_id=1, phase=InterviewPhase.T0,
                       responses={"a": 6}, confidence={"a": 0.5})

def test_subagent_kind_enum():
    assert SubagentKind.LONGITUDINAL.value == "longitudinal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_models.py -v`
Expected: ImportError (module not yet created).

- [ ] **Step 3: Create `backend/app/models/interview.py`**

```python
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

class InterviewPhase(str, Enum):
    T0 = "T0"
    T1 = "T1"

class SubagentKind(str, Enum):
    LONGITUDINAL = "longitudinal"
    DIVERSITY = "diversity"
    DELPHI = "delphi"
    SCENARIO = "scenario"

class LikertItem(BaseModel):
    item_id: str
    de: str
    en: str
    scale: int = Field(ge=3, le=7)
    family: Optional[str] = None
    reverse_coded: bool = False

    @field_validator("scale")
    @classmethod
    def odd_scale(cls, v: int) -> int:
        if v not in (3, 5, 7):
            raise ValueError("scale must be 3, 5, or 7")
        return v

class LikertInstrument(BaseModel):
    name: str
    version: str = "1.0"
    language_default: str = "de"
    items: list[LikertItem]

    @model_validator(mode="after")
    def unique_item_ids(self) -> "LikertInstrument":
        ids = [i.item_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate item_id in instrument")
        return self

class LikertResponse(BaseModel):
    agent_id: int
    phase: InterviewPhase
    responses: dict[str, int]
    confidence: dict[str, float] = Field(default_factory=dict)
    open_comment: Optional[str] = None
    memory_available: bool = True
    failed_items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def values_in_range(self) -> "LikertResponse":
        for k, v in self.responses.items():
            if not 1 <= v <= 7:
                raise ValueError(f"response {k}={v} out of 1..7 range")
        for k, v in self.confidence.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"confidence {k}={v} out of 0..1 range")
        return self

class QSortStatement(BaseModel):
    statement_id: str
    de: str
    en: str

class QSortInstrument(BaseModel):
    name: str
    version: str = "1.0"
    statements: list[QSortStatement]
    distribution: list[int]  # e.g. [2,3,4,6,4,3,2] for -3..+3

class QSortResponse(BaseModel):
    agent_id: int
    placements: dict[str, int]  # statement_id -> bucket (-3..+3)
    likert_axes: dict[str, int]  # axis_id -> 1..7

class DelphiOpenResponse(BaseModel):
    agent_id: int
    round: int = 1
    answers: dict[str, str]  # question_id -> free text

class DelphiRatingResponse(BaseModel):
    agent_id: int
    round: int
    ratings: dict[str, dict[str, int]]  # theme_id -> {importance, plausibility}
    justification: Optional[str] = None

class ScenarioRating(BaseModel):
    desirability: int = Field(ge=1, le=7)
    plausibility: int = Field(ge=1, le=7)
    impact_on_my_group: int = Field(ge=1, le=7)
    fairness: int = Field(ge=1, le=7)
    if_woke_up_response: str

class ScenarioResponse(BaseModel):
    agent_id: int
    ratings: dict[str, ScenarioRating]  # scenario_id -> rating
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/interview.py backend/tests/interviews/__init__.py backend/tests/interviews/test_models.py
git commit -m "feat(interviews): add pydantic models for instruments and responses"
```

---

### Task 3: YAML instrument loader + validator

**Files:**
- Create: `backend/app/services/interviews/__init__.py`
- Create: `backend/app/services/interviews/instrument_loader.py`
- Create: `backend/scripts/instruments/__init__.py` (empty marker so tests can import path)
- Test: `backend/tests/interviews/test_instrument_loader.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_instrument_loader.py
import pytest
from app.services.interviews.instrument_loader import (
    load_likert_instrument, InstrumentValidationError,
)

def _write(tmp_path, text):
    p = tmp_path / "inst.yaml"
    p.write_text(text, encoding="utf-8")
    return p

def test_loads_valid_likert(tmp_path):
    p = _write(tmp_path, """
name: longitudinal_v1
version: "1.0"
language_default: de
items:
  - item_id: stk_1
    de: "Der westliche Dorschbestand wird sich erholen"
    en: "Western cod stock will recover"
    scale: 5
    family: stocks
""")
    inst = load_likert_instrument(p)
    assert inst.name == "longitudinal_v1"
    assert len(inst.items) == 1

def test_rejects_duplicate_item_id(tmp_path):
    p = _write(tmp_path, """
name: x
items:
  - {item_id: a, de: d, en: e, scale: 5}
  - {item_id: a, de: d, en: e, scale: 5}
""")
    with pytest.raises(InstrumentValidationError):
        load_likert_instrument(p)

def test_rejects_missing_required_field(tmp_path):
    p = _write(tmp_path, """
name: x
items:
  - {item_id: a, de: d, scale: 5}
""")
    with pytest.raises(InstrumentValidationError):
        load_likert_instrument(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_instrument_loader.py -v`
Expected: ImportError.

- [ ] **Step 3: Create loader**

Create `backend/app/services/interviews/__init__.py` (empty), `backend/scripts/instruments/__init__.py` (empty), then `backend/app/services/interviews/instrument_loader.py`:

```python
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import yaml
from pydantic import ValidationError
from app.models.interview import (
    LikertInstrument, QSortInstrument,
)

class InstrumentValidationError(ValueError):
    pass

def _parse_yaml(path: Path) -> dict:
    if not path.exists():
        raise InstrumentValidationError(f"instrument file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise InstrumentValidationError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(data, dict):
        raise InstrumentValidationError(f"top-level YAML must be a mapping in {path}")
    return data

def load_likert_instrument(path: Path) -> LikertInstrument:
    data = _parse_yaml(Path(path))
    try:
        return LikertInstrument(**data)
    except ValidationError as e:
        raise InstrumentValidationError(str(e)) from e

def load_qsort_instrument(path: Path) -> QSortInstrument:
    data = _parse_yaml(Path(path))
    try:
        return QSortInstrument(**data)
    except ValidationError as e:
        raise InstrumentValidationError(str(e)) from e

def instrument_hash(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]

def freeze_snapshot(instruments: dict[str, Path], out_path: Path) -> dict:
    snapshot = {
        name: {
            "path": str(p),
            "hash": instrument_hash(p),
            "content": _parse_yaml(p),
        }
        for name, p in instruments.items()
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_instrument_loader.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interviews/__init__.py backend/app/services/interviews/instrument_loader.py backend/scripts/instruments/__init__.py backend/tests/interviews/test_instrument_loader.py
git commit -m "feat(interviews): YAML instrument loader with pydantic validation and hash freezing"
```

---

### Task 4: LLM stub mode

**Files:**
- Modify: `backend/app/utils/llm_client.py`
- Test: `backend/tests/interviews/test_llm_stub.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_llm_stub.py
import json
from app.utils.llm_client import LLMClient

def test_stub_mode_returns_deterministic_canned_json(monkeypatch):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    from app.config import Config
    Config.LLM_STUB_MODE = True
    client = LLMClient(api_key="x", base_url="x", model="x")
    messages = [
        {"role": "system", "content": "You are persona_42. Return JSON."},
        {"role": "user", "content": "stub_key=longitudinal:item_001"},
    ]
    out1 = client.chat_json(messages=messages, temperature=0.0)
    out2 = client.chat_json(messages=messages, temperature=0.0)
    assert out1 == out2
    assert isinstance(out1, dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_llm_stub.py -v`
Expected: FAIL (real API call attempted or stub absent).

- [ ] **Step 3: Read current `llm_client.py`**

Read the file to locate `chat` and `chat_json` method bodies and where to insert the stub branch.

- [ ] **Step 4: Add stub branch**

At the top of `LLMClient.chat` (before the OpenAI call), insert:
```python
        from app.config import Config
        if getattr(Config, "LLM_STUB_MODE", False):
            return self._stub_response(messages)
```

And at the top of `LLMClient.chat_json` (before delegating), insert the same guard returning a parsed dict via `self._stub_response_json(messages)`.

Add these methods to `LLMClient`:
```python
    def _stub_key(self, messages: list[dict]) -> str:
        user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        # Allow callers to embed an explicit stub_key=... token
        for chunk in user_msg.split():
            if chunk.startswith("stub_key="):
                return chunk[len("stub_key="):]
        import hashlib
        return hashlib.sha256((sys_msg + "|" + user_msg).encode("utf-8")).hexdigest()[:12]

    def _stub_response(self, messages: list[dict]) -> str:
        import json as _json
        return _json.dumps(self._stub_response_json(messages), ensure_ascii=False)

    def _stub_response_json(self, messages: list[dict]) -> dict:
        key = self._stub_key(messages)
        # Deterministic centered Likert + plausible open text
        digit = sum(ord(c) for c in key) % 5 + 1
        return {
            "stub_key": key,
            "responses": {"item_001": digit, "item_002": digit, "item_003": (digit % 5) + 1},
            "confidence": {"item_001": 0.7, "item_002": 0.7, "item_003": 0.6},
            "open_comment": f"stub:{key}",
        }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_llm_stub.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/utils/llm_client.py backend/tests/interviews/test_llm_stub.py
git commit -m "feat(interviews): LLM stub mode for deterministic CI tests"
```

---

### Task 5: StakeholderInterviewer base class

**Files:**
- Create: `backend/app/services/interviews/base.py`
- Test: `backend/tests/interviews/test_base_interviewer.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_base_interviewer.py
import json
import pytest
from app.services.interviews.base import StakeholderInterviewer, MemoryDigest, PersonaRecord

class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        self.calls.append(messages)
        return self.responses.pop(0)

class _FakeMemory:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text=f"digest-for-{agent_id}", available=True)

def test_in_character_prompt_includes_persona_and_memory():
    llm = _FakeLLM([{"x": 1}])
    mem = _FakeMemory()
    interviewer = StakeholderInterviewer(llm=llm, memory=mem)
    persona = PersonaRecord(agent_id=7, name="A", persona="I am a small-scale Baltic fisher.")
    out = interviewer.ask_in_character(persona, user_prompt="Q?", schema_hint="{...}")
    assert out == {"x": 1}
    sys_msg = llm.calls[0][0]["content"]
    assert "small-scale Baltic fisher" in sys_msg
    assert "digest-for-7" in sys_msg

def test_schema_retry_on_first_failure():
    bad_then_good = [{}, {"responses": {"a": 3}}]
    llm = _FakeLLM(bad_then_good)
    mem = _FakeMemory()
    interviewer = StakeholderInterviewer(llm=llm, memory=mem)
    def validator(d): 
        return d if "responses" in d else None
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    out = interviewer.ask_in_character(persona, user_prompt="Q?", schema_hint="x", validate=validator)
    assert out == {"responses": {"a": 3}}
    assert len(llm.calls) == 2

def test_two_failures_raise():
    llm = _FakeLLM([{}, {}])
    mem = _FakeMemory()
    interviewer = StakeholderInterviewer(llm=llm, memory=mem)
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    with pytest.raises(ValueError):
        interviewer.ask_in_character(persona, user_prompt="Q?", schema_hint="x",
                                     validate=lambda d: d if "responses" in d else None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_base_interviewer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement base**

`backend/app/services/interviews/base.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

@dataclass
class PersonaRecord:
    agent_id: int
    name: str
    persona: str
    profession: Optional[str] = None
    bio: Optional[str] = None

@dataclass
class MemoryDigest:
    text: str
    available: bool = True

class MemoryProvider(Protocol):
    def get_digest(self, agent_id: int, max_chars: int = 2000) -> MemoryDigest: ...

class StakeholderInterviewer:
    def __init__(self, llm, memory: MemoryProvider, language: str = "de"):
        self.llm = llm
        self.memory = memory
        self.language = language

    def _system_prompt(self, persona: PersonaRecord, digest: MemoryDigest, schema_hint: str) -> str:
        memory_block = digest.text if digest.available else "[no simulation memory available]"
        lang_note = "Antworte ausschließlich auf Deutsch." if self.language == "de" else "Answer in English."
        return (
            f"You are {persona.name}. {persona.persona}\n\n"
            "You are answering a survey about the future of German fisheries. "
            "Answer strictly in character based on your background, values, and what you experienced "
            "during the simulated social media discourse summarised below.\n\n"
            f"--- simulation memory digest ---\n{memory_block}\n--- end ---\n\n"
            f"{lang_note} Return JSON ONLY matching this schema:\n{schema_hint}"
        )

    def ask_in_character(
        self,
        persona: PersonaRecord,
        user_prompt: str,
        schema_hint: str,
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        validate: Optional[Callable[[dict], Optional[dict]]] = None,
    ) -> dict:
        digest = self.memory.get_digest(persona.agent_id)
        messages = [
            {"role": "system", "content": self._system_prompt(persona, digest, schema_hint)},
            {"role": "user", "content": user_prompt},
        ]
        out = self.llm.chat_json(messages=messages, temperature=temperature, max_tokens=max_tokens)
        if validate is not None:
            validated = validate(out)
            if validated is not None:
                return validated
            messages.append({"role": "assistant", "content": str(out)})
            messages.append({"role": "user", "content":
                "Your previous response did not match the required schema. "
                f"Return ONLY valid JSON matching: {schema_hint}"})
            out = self.llm.chat_json(messages=messages, temperature=0.0, max_tokens=max_tokens)
            validated = validate(out)
            if validated is None:
                raise ValueError(f"agent {persona.agent_id}: schema violation after retry")
            return validated
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_base_interviewer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interviews/base.py backend/tests/interviews/test_base_interviewer.py
git commit -m "feat(interviews): StakeholderInterviewer base with in-character prompting and schema retry"
```

---

## Phase 2 — Subagents

### Task 6: Longitudinal subagent + instrument YAML

**Files:**
- Create: `backend/scripts/instruments/longitudinal_v1.yaml`
- Create: `backend/app/services/interviews/longitudinal.py`
- Test: `backend/tests/interviews/test_longitudinal.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_longitudinal.py
from pathlib import Path
import pytest
from app.models.interview import InterviewPhase
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.longitudinal import LongitudinalSubagent, run_aggregate

class _FakeMem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _CannedLLM:
    def __init__(self): self.n = 0
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        self.n += 1
        return {
            "responses": {"stk_1": 4, "gov_1": 3, "mkt_1": 5, "clm_1": 2},
            "confidence": {"stk_1": 0.8, "gov_1": 0.6, "mkt_1": 0.7, "clm_1": 0.5},
            "open_comment": "test",
        }

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "longitudinal_v1.yaml"

def test_longitudinal_administer_one_agent():
    sub = LongitudinalSubagent(llm=_CannedLLM(), memory=_FakeMem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=3, name="A", persona="p")
    resp = sub.administer(persona, phase=InterviewPhase.T0)
    assert resp.agent_id == 3
    assert resp.phase == InterviewPhase.T0
    assert set(resp.responses.keys()) >= {"stk_1", "gov_1", "mkt_1", "clm_1"}

def test_longitudinal_aggregate_delta():
    from app.models.interview import LikertResponse
    t0 = [LikertResponse(agent_id=i, phase=InterviewPhase.T0,
                         responses={"stk_1": 3, "gov_1": 4},
                         confidence={"stk_1": 0.8, "gov_1": 0.8}) for i in range(5)]
    t1 = [LikertResponse(agent_id=i, phase=InterviewPhase.T1,
                         responses={"stk_1": 4, "gov_1": 4},
                         confidence={"stk_1": 0.8, "gov_1": 0.8}) for i in range(5)]
    agg = run_aggregate(t0, t1)
    assert agg["per_item"]["stk_1"]["mean_delta"] == 1.0
    assert agg["per_item"]["gov_1"]["mean_delta"] == 0.0
    assert agg["n_paired"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_longitudinal.py -v`
Expected: ImportError + missing YAML file.

- [ ] **Step 3: Create instrument YAML**

`backend/scripts/instruments/longitudinal_v1.yaml`:
```yaml
name: longitudinal_v1
version: "1.0"
language_default: de
items:
  # Stock status & recovery
  - {item_id: stk_1, family: stocks, scale: 5,
     de: "Der westliche Dorschbestand wird sich bis 2035 erholen.",
     en: "The Western Baltic cod stock will recover by 2035."}
  - {item_id: stk_2, family: stocks, scale: 5,
     de: "Der Heringsbestand in der westlichen Ostsee ist nicht mehr zu retten.",
     en: "The Western Baltic herring stock can no longer be saved.",
     reverse_coded: true}
  - {item_id: stk_3, family: stocks, scale: 5,
     de: "Wissenschaftliche Bestandsschätzungen sind generell zuverlässig.",
     en: "Scientific stock assessments are generally reliable."}
  # Governance & CFP
  - {item_id: gov_1, family: governance, scale: 5,
     de: "Die Gemeinsame Fischereipolitik der EU scheitert beim Schutz der Ostseefische.",
     en: "The EU Common Fisheries Policy fails to protect Baltic fish.",
     reverse_coded: true}
  - {item_id: gov_2, family: governance, scale: 5,
     de: "Entscheidungen über Fangquoten sollten stärker lokal getroffen werden.",
     en: "Decisions on catch quotas should be taken more locally."}
  - {item_id: gov_3, family: governance, scale: 5,
     de: "Die deutsche Bundesregierung handelt entschlossen bei Fischereifragen.",
     en: "The German federal government acts decisively on fisheries issues."}
  # Market & MSC
  - {item_id: mkt_1, family: market, scale: 5,
     de: "Nur MSC-zertifizierter Fisch sollte verkauft werden dürfen.",
     en: "Only MSC-certified fish should be allowed for sale."}
  - {item_id: mkt_2, family: market, scale: 5,
     de: "Importierter Fisch verdrängt die deutsche Kleinfischerei.",
     en: "Imported fish displaces German small-scale fisheries."}
  - {item_id: mkt_3, family: market, scale: 5,
     de: "Verbraucher zahlen gerne mehr für nachhaltigen Ostseefisch.",
     en: "Consumers gladly pay more for sustainable Baltic fish."}
  # Climate & adaptation
  - {item_id: clm_1, family: climate, scale: 5,
     de: "Der Klimawandel macht traditionelle Ostseefischerei unmöglich.",
     en: "Climate change makes traditional Baltic fisheries impossible.",
     reverse_coded: true}
  - {item_id: clm_2, family: climate, scale: 5,
     de: "Aquakultur ist die Zukunft der deutschen Fischwirtschaft.",
     en: "Aquaculture is the future of the German fishing industry."}
  - {item_id: clm_3, family: climate, scale: 5,
     de: "Die Fischerei muss sich grundlegend an neue Arten anpassen.",
     en: "Fisheries must fundamentally adapt to new species."}
```

- [ ] **Step 4: Implement subagent**

`backend/app/services/interviews/longitudinal.py`:
```python
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Optional
from app.models.interview import (
    LikertInstrument, LikertResponse, InterviewPhase,
)
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord
from app.services.interviews.instrument_loader import load_likert_instrument

class LongitudinalSubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        self.instrument: LikertInstrument = load_likert_instrument(Path(instrument_path))
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.language = language

    def _schema_hint(self) -> str:
        ids = [i.item_id for i in self.instrument.items]
        return json.dumps({
            "responses": {k: "<int 1-5>" for k in ids},
            "confidence": {k: "<float 0-1>" for k in ids},
            "open_comment": "<string, optional>",
        }, ensure_ascii=False)

    def _user_prompt(self) -> str:
        lines = ["Bitte bewerten Sie die folgenden Aussagen auf einer Skala von 1 (lehne stark ab) bis 5 (stimme stark zu)." if self.language == "de"
                 else "Please rate the following statements on a scale from 1 (strongly disagree) to 5 (strongly agree)."]
        for it in self.instrument.items:
            txt = it.de if self.language == "de" else it.en
            lines.append(f"- [{it.item_id}] {txt}")
        return "\n".join(lines)

    def _validator(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict): return None
        resp = raw.get("responses")
        if not isinstance(resp, dict): return None
        required = {it.item_id for it in self.instrument.items}
        if not required.issubset(resp.keys()): return None
        for k, v in resp.items():
            if not isinstance(v, int) or not 1 <= v <= 5: return None
        return raw

    def administer(self, persona: PersonaRecord, phase: InterviewPhase) -> LikertResponse:
        raw = self.interviewer.ask_in_character(
            persona,
            user_prompt=self._user_prompt(),
            schema_hint=self._schema_hint(),
            validate=self._validator,
        )
        return LikertResponse(
            agent_id=persona.agent_id,
            phase=phase,
            responses={k: int(v) for k, v in raw["responses"].items()},
            confidence={k: float(v) for k, v in raw.get("confidence", {}).items()},
            open_comment=raw.get("open_comment"),
        )

def run_aggregate(t0: list[LikertResponse], t1: list[LikertResponse]) -> dict:
    by_t0 = {r.agent_id: r for r in t0}
    by_t1 = {r.agent_id: r for r in t1}
    paired = sorted(set(by_t0) & set(by_t1))
    items: set[str] = set()
    for r in t0 + t1:
        items.update(r.responses.keys())
    per_item: dict[str, dict] = {}
    for it in sorted(items):
        deltas = []
        for aid in paired:
            v0 = by_t0[aid].responses.get(it)
            v1 = by_t1[aid].responses.get(it)
            if v0 is None or v1 is None: continue
            deltas.append(v1 - v0)
        if not deltas:
            per_item[it] = {"mean_delta": None, "n": 0}
            continue
        m = sum(deltas) / len(deltas)
        var = sum((d - m) ** 2 for d in deltas) / max(len(deltas) - 1, 1)
        per_item[it] = {
            "mean_delta": m,
            "sd_delta": math.sqrt(var),
            "n": len(deltas),
            "n_positive": sum(1 for d in deltas if d > 0),
            "n_negative": sum(1 for d in deltas if d < 0),
        }
    per_agent: dict[int, dict] = {}
    for aid in paired:
        r0 = by_t0[aid].responses
        r1 = by_t1[aid].responses
        common = set(r0) & set(r1)
        total = sum(abs(r1[k] - r0[k]) for k in common)
        per_agent[aid] = {"total_abs_drift": total, "n_items": len(common)}
    return {
        "n_paired": len(paired),
        "n_t0_only": len(set(by_t0) - set(by_t1)),
        "n_t1_only": len(set(by_t1) - set(by_t0)),
        "per_item": per_item,
        "per_agent": per_agent,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_longitudinal.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/instruments/longitudinal_v1.yaml backend/app/services/interviews/longitudinal.py backend/tests/interviews/test_longitudinal.py
git commit -m "feat(interviews): longitudinal subagent + 12-item Likert instrument"
```

---

### Task 7: Diversity subagent + Q-sort instrument

**Files:**
- Create: `backend/scripts/instruments/diversity_v1.yaml`
- Create: `backend/app/services/interviews/diversity.py`
- Test: `backend/tests/interviews/test_diversity.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_diversity.py
from pathlib import Path
import numpy as np
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.diversity import (
    DiversitySubagent, run_typology,
)

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _CannedLLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        # Place all 24 statements into legal buckets per the forced distribution
        placements = {}
        buckets = [-3]*2 + [-2]*3 + [-1]*4 + [0]*6 + [1]*4 + [2]*3 + [3]*2
        for i in range(24):
            placements[f"st_{i+1:02d}"] = buckets[i]
        return {
            "placements": placements,
            "likert_axes": {"ax_pres_extr": 5, "ax_loc_eu": 3, "ax_sci_trad": 4,
                            "ax_ind_col": 4, "ax_short_long": 5, "ax_mkt_reg": 3},
        }

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "diversity_v1.yaml"

def test_diversity_administer():
    sub = DiversitySubagent(llm=_CannedLLM(), memory=_Mem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    resp = sub.administer(persona)
    assert len(resp.placements) == 24
    assert set(resp.likert_axes.keys()) == {
        "ax_pres_extr","ax_loc_eu","ax_sci_trad","ax_ind_col","ax_short_long","ax_mkt_reg"
    }

def test_typology_runs_pca_kmeans():
    from app.models.interview import QSortResponse
    rng = np.random.default_rng(42)
    responses = []
    for aid in range(20):
        placements = {f"st_{i+1:02d}": int(rng.integers(-3, 4)) for i in range(24)}
        axes = {f"ax_{j}": int(rng.integers(1, 8)) for j in range(6)}
        responses.append(QSortResponse(agent_id=aid, placements=placements, likert_axes=axes))
    result = run_typology(responses, n_clusters=3)
    assert "clusters" in result
    assert len(result["clusters"]) == 3
    assert "pca" in result
    assert len(result["pca"]["components"]) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_diversity.py -v`
Expected: ImportError.

- [ ] **Step 3: Create instrument YAML**

`backend/scripts/instruments/diversity_v1.yaml`:
```yaml
name: diversity_v1
version: "1.0"
language_default: de
distribution: [2, 3, 4, 6, 4, 3, 2]   # buckets from -3 to +3, total 24
statements:
  - {statement_id: st_01, de: "Die Ostsee gehört den Fischern, die hier seit Generationen leben.", en: "The Baltic belongs to fishers who have lived here for generations."}
  - {statement_id: st_02, de: "MSC-Zertifizierung schützt vor allem große Konzerne.", en: "MSC certification mainly protects large corporations."}
  - {statement_id: st_03, de: "Wissenschaftliche Quoten sind die einzige Grundlage für Politik.", en: "Scientific quotas are the only legitimate basis for policy."}
  - {statement_id: st_04, de: "Aquakultur kann Ostseefischerei ersetzen.", en: "Aquaculture can replace Baltic fisheries."}
  - {statement_id: st_05, de: "Sportfischer schaden den Beständen mehr als die Berufsfischer.", en: "Recreational anglers harm stocks more than commercial fishers."}
  - {statement_id: st_06, de: "Die EU-Fischereipolitik kennt die Ostsee nicht.", en: "EU fisheries policy doesn't understand the Baltic."}
  - {statement_id: st_07, de: "Großtechnische Fischerei ist effizienter und damit nachhaltiger.", en: "Industrial fisheries are more efficient and therefore more sustainable."}
  - {statement_id: st_08, de: "Wer Fisch isst, sollte mehr dafür bezahlen.", en: "Those who eat fish should pay more for it."}
  - {statement_id: st_09, de: "Die Kleinfischerei muss subventioniert werden.", en: "Small-scale fisheries must be subsidised."}
  - {statement_id: st_10, de: "Marine Schutzgebiete sind reine Symbolpolitik.", en: "Marine protected areas are mere symbolism."}
  - {statement_id: st_11, de: "Russlands Krieg ändert alles in der Ostsee.", en: "Russia's war changes everything in the Baltic."}
  - {statement_id: st_12, de: "Nur drastische Reduktion der Fangmengen rettet die Bestände.", en: "Only drastic catch reductions will save the stocks."}
  - {statement_id: st_13, de: "NGOs übertreiben die Krise systematisch.", en: "NGOs systematically exaggerate the crisis."}
  - {statement_id: st_14, de: "Klimawandel ist das eigentliche Problem, nicht die Fischerei.", en: "Climate change is the real problem, not fisheries."}
  - {statement_id: st_15, de: "Tradition zählt mehr als kurzfristige Bestandszahlen.", en: "Tradition matters more than short-term stock numbers."}
  - {statement_id: st_16, de: "Verbraucher entscheiden über die Zukunft des Fisches.", en: "Consumers decide the future of fish."}
  - {statement_id: st_17, de: "Ohne Generalstreik der Fischer ändert sich nichts.", en: "Without a fishers' general strike, nothing will change."}
  - {statement_id: st_18, de: "Die Bundesregierung sollte Kutter aufkaufen und stilllegen.", en: "The federal government should buy out and decommission boats."}
  - {statement_id: st_19, de: "Die Dorschkrise ist Folge gescheiterter Politik.", en: "The cod crisis is the result of policy failure."}
  - {statement_id: st_20, de: "Ostsee-Aquakultur ist ökologisch problematisch.", en: "Baltic aquaculture is ecologically problematic."}
  - {statement_id: st_21, de: "Junge Menschen werden keinen Fischereibetrieb mehr übernehmen.", en: "Young people will no longer take over fishing businesses."}
  - {statement_id: st_22, de: "Markt regelt sich selbst, auch beim Fisch.", en: "The market regulates itself, also for fish."}
  - {statement_id: st_23, de: "Lokale Genossenschaften sind die Lösung.", en: "Local cooperatives are the solution."}
  - {statement_id: st_24, de: "In 20 Jahren gibt es keine deutsche Ostseefischerei mehr.", en: "In 20 years there will be no German Baltic fisheries left."}
likert_axes:
  - {axis_id: ax_pres_extr, scale: 7, de: "Bewahrung (1) vs. Nutzung (7)", en: "Preservation (1) vs. Extraction (7)"}
  - {axis_id: ax_loc_eu,    scale: 7, de: "Lokal (1) vs. EU-zentral (7)",  en: "Local (1) vs. EU-central (7)"}
  - {axis_id: ax_sci_trad,  scale: 7, de: "Wissenschaft (1) vs. Tradition (7)", en: "Science-led (1) vs. Tradition-led (7)"}
  - {axis_id: ax_ind_col,   scale: 7, de: "Individuum (1) vs. Kollektiv (7)", en: "Individual (1) vs. Collective (7)"}
  - {axis_id: ax_short_long,scale: 7, de: "Kurzfristig (1) vs. Langfristig (7)", en: "Short-term (1) vs. Long-term (7)"}
  - {axis_id: ax_mkt_reg,   scale: 7, de: "Markt (1) vs. Regulierung (7)", en: "Market (1) vs. Regulation (7)"}
```

- [ ] **Step 4: Implement subagent**

`backend/app/services/interviews/diversity.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
import numpy as np
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import yaml
from app.models.interview import QSortResponse
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord
from app.services.interviews.instrument_loader import InstrumentValidationError

class DiversitySubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        self.instrument = self._load(Path(instrument_path))
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.language = language

    def _load(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "statements" not in data or "distribution" not in data:
            raise InstrumentValidationError(f"invalid diversity instrument: {path}")
        if sum(data["distribution"]) != len(data["statements"]):
            raise InstrumentValidationError("distribution sum must equal number of statements")
        return data

    def _schema_hint(self) -> str:
        return json.dumps({
            "placements": {s["statement_id"]: "<int in -3..+3>" for s in self.instrument["statements"]},
            "likert_axes": {a["axis_id"]: "<int 1-7>" for a in self.instrument["likert_axes"]},
        }, ensure_ascii=False)

    def _user_prompt(self) -> str:
        dist = self.instrument["distribution"]
        buckets = list(range(-3, 4))
        bucket_desc = ", ".join(f"{b}:{n}" for b, n in zip(buckets, dist))
        lines = [
            ("Ordnen Sie jede Aussage genau einer Box von -3 (lehne stark ab) bis +3 (stimme stark zu) zu. "
             f"Die Verteilung ist erzwungen: {bucket_desc}.") if self.language == "de" else
            ("Place every statement into exactly one box from -3 (strongly disagree) to +3 (strongly agree). "
             f"The distribution is forced: {bucket_desc}."),
            "",
            "Statements:",
        ]
        for s in self.instrument["statements"]:
            txt = s["de"] if self.language == "de" else s["en"]
            lines.append(f"- [{s['statement_id']}] {txt}")
        lines += ["", "Then rate each axis from 1 to 7:"]
        for a in self.instrument["likert_axes"]:
            txt = a["de"] if self.language == "de" else a["en"]
            lines.append(f"- [{a['axis_id']}] {txt}")
        return "\n".join(lines)

    def _validator(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict): return None
        placements = raw.get("placements", {})
        axes = raw.get("likert_axes", {})
        statements = {s["statement_id"] for s in self.instrument["statements"]}
        if set(placements.keys()) != statements: return None
        dist = self.instrument["distribution"]
        target = {b: n for b, n in zip(range(-3, 4), dist)}
        got: dict[int, int] = {}
        for v in placements.values():
            if not isinstance(v, int) or not -3 <= v <= 3: return None
            got[v] = got.get(v, 0) + 1
        if got != target: return None
        for a in self.instrument["likert_axes"]:
            v = axes.get(a["axis_id"])
            if not isinstance(v, int) or not 1 <= v <= 7: return None
        return raw

    def administer(self, persona: PersonaRecord) -> QSortResponse:
        raw = self.interviewer.ask_in_character(
            persona,
            user_prompt=self._user_prompt(),
            schema_hint=self._schema_hint(),
            validate=self._validator,
        )
        return QSortResponse(
            agent_id=persona.agent_id,
            placements={k: int(v) for k, v in raw["placements"].items()},
            likert_axes={k: int(v) for k, v in raw["likert_axes"].items()},
        )

def _vectorize(r: QSortResponse, statements: list[str], axes: list[str]) -> np.ndarray:
    return np.array(
        [r.placements.get(s, 0) for s in statements] +
        [r.likert_axes.get(a, 4) for a in axes],
        dtype=float,
    )

def run_typology(responses: list[QSortResponse], n_clusters: int = 4) -> dict:
    if not responses:
        return {"n": 0, "clusters": [], "pca": {"components": [], "explained_variance": []}}
    statements = sorted({k for r in responses for k in r.placements})
    axes = sorted({k for r in responses for k in r.likert_axes})
    X = np.vstack([_vectorize(r, statements, axes) for r in responses])
    n_clusters = min(n_clusters, len(responses))
    pca = PCA(n_components=min(5, X.shape[1], X.shape[0]))
    pcs = pca.fit_transform(X)
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=0)
    labels = km.fit_predict(X)
    clusters = []
    for c in range(n_clusters):
        members = [responses[i].agent_id for i in range(len(responses)) if labels[i] == c]
        centroid = km.cluster_centers_[c]
        clusters.append({
            "cluster_id": int(c),
            "n": len(members),
            "agent_ids": members,
            "top_loadings": {
                statements[i] if i < len(statements) else axes[i - len(statements)]: float(centroid[i])
                for i in np.argsort(np.abs(centroid))[::-1][:8].tolist()
            },
        })
    return {
        "n": len(responses),
        "clusters": clusters,
        "pca": {
            "components": pcs.tolist(),
            "explained_variance": pca.explained_variance_ratio_.tolist(),
            "agent_ids": [r.agent_id for r in responses],
        },
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_diversity.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/instruments/diversity_v1.yaml backend/app/services/interviews/diversity.py backend/tests/interviews/test_diversity.py
git commit -m "feat(interviews): diversity subagent with Q-sort + 6 Likert axes + PCA/k-means typology"
```

---

### Task 8: Delphi subagent (three rounds)

**Files:**
- Create: `backend/scripts/instruments/delphi_v1.yaml`
- Create: `backend/app/services/interviews/delphi.py`
- Test: `backend/tests/interviews/test_delphi.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_delphi.py
from pathlib import Path
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.delphi import (
    DelphiSubagent, extract_themes, convergence_metrics,
)

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "delphi_v1.yaml"

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _R1LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"answers": {
            "q1": "Klimawandel, Quoten, Generationswechsel",
            "q2": "MSC, Aquakultur",
            "q3": "Russland, EU-Politik",
            "q4": "Verbraucherpreise",
        }}

class _R2LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"ratings": {f"theme_{i}": {"importance": 4, "plausibility": 3} for i in range(5)}}

class _ExtractLLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"themes": [
            {"theme_id": "theme_0", "label": "Klimawandel"},
            {"theme_id": "theme_1", "label": "Quoten"},
            {"theme_id": "theme_2", "label": "MSC"},
            {"theme_id": "theme_3", "label": "EU-Politik"},
            {"theme_id": "theme_4", "label": "Generationswechsel"},
        ]}

def test_delphi_round1_open():
    sub = DelphiSubagent(llm=_R1LLM(), memory=_Mem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=2, name="A", persona="p")
    resp = sub.administer_round1(persona)
    assert resp.round == 1
    assert len(resp.answers) == 4

def test_extract_themes_aggregates():
    from app.models.interview import DelphiOpenResponse
    r1 = [DelphiOpenResponse(agent_id=i, answers={"q1": "Klimawandel", "q2": "MSC"}) for i in range(3)]
    themes = extract_themes(r1, llm=_ExtractLLM())
    assert len(themes) == 5
    assert all("theme_id" in t for t in themes)

def test_convergence_metrics():
    from app.models.interview import DelphiRatingResponse
    r2 = [DelphiRatingResponse(agent_id=i, round=2,
            ratings={"t1": {"importance": 3, "plausibility": 3}}) for i in range(5)]
    r3 = [DelphiRatingResponse(agent_id=i, round=3,
            ratings={"t1": {"importance": 4, "plausibility": 4}}) for i in range(5)]
    conv = convergence_metrics(r2, r3)
    assert "t1" in conv
    assert conv["t1"]["delta_iqr_importance"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_delphi.py -v`
Expected: ImportError.

- [ ] **Step 3: Create instrument YAML**

`backend/scripts/instruments/delphi_v1.yaml`:
```yaml
name: delphi_v1
version: "1.0"
language_default: de
rounds: 3
questions:
  - {question_id: q1, de: "Welche drei Faktoren werden die deutsche Fischerei bis 2040 am stärksten prägen?", en: "Which three factors will most shape German fisheries by 2040?"}
  - {question_id: q2, de: "Welche Akteurinnen und Akteure sind heute entscheidend, werden aber unterschätzt?", en: "Which actors are decisive today but underestimated?"}
  - {question_id: q3, de: "Was sollte sich in den nächsten fünf Jahren ändern, damit die Fischerei eine Zukunft hat?", en: "What should change in the next five years for fisheries to have a future?"}
  - {question_id: q4, de: "Welcher Trend macht Ihnen am meisten Hoffnung – und welcher am meisten Sorge?", en: "Which trend gives you most hope — and which most concern?"}
```

- [ ] **Step 4: Implement subagent**

`backend/app/services/interviews/delphi.py`:
```python
from __future__ import annotations
import json
import statistics
from pathlib import Path
from typing import Optional
import yaml
from app.models.interview import (
    DelphiOpenResponse, DelphiRatingResponse,
)
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord

class DelphiSubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        with Path(instrument_path).open("r", encoding="utf-8") as f:
            self.instrument = yaml.safe_load(f)
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.llm = llm
        self.language = language

    # --- Round 1: open questions ---
    def _r1_schema(self) -> str:
        return json.dumps({
            "answers": {q["question_id"]: "<string>" for q in self.instrument["questions"]}
        }, ensure_ascii=False)

    def _r1_prompt(self) -> str:
        lines = ["Bitte beantworten Sie offen:" if self.language == "de" else "Please answer openly:"]
        for q in self.instrument["questions"]:
            txt = q["de"] if self.language == "de" else q["en"]
            lines.append(f"[{q['question_id']}] {txt}")
        return "\n".join(lines)

    def _r1_validate(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict): return None
        ans = raw.get("answers")
        if not isinstance(ans, dict): return None
        required = {q["question_id"] for q in self.instrument["questions"]}
        if not required.issubset(ans.keys()): return None
        return raw

    def administer_round1(self, persona: PersonaRecord) -> DelphiOpenResponse:
        raw = self.interviewer.ask_in_character(
            persona, user_prompt=self._r1_prompt(),
            schema_hint=self._r1_schema(), validate=self._r1_validate,
        )
        return DelphiOpenResponse(agent_id=persona.agent_id, round=1,
                                  answers={k: str(v) for k, v in raw["answers"].items()})

    # --- Round 2: rate themes ---
    def _r2_schema(self, theme_ids: list[str]) -> str:
        return json.dumps({
            "ratings": {tid: {"importance": "<int 1-5>", "plausibility": "<int 1-5>"} for tid in theme_ids}
        }, ensure_ascii=False)

    def _r2_prompt(self, themes: list[dict]) -> str:
        head = "Bewerten Sie jedes Thema nach Wichtigkeit (1-5) und Plausibilität (1-5):" if self.language == "de" \
               else "Rate each theme on importance (1-5) and plausibility (1-5):"
        body = [f"- [{t['theme_id']}] {t['label']}" for t in themes]
        return head + "\n" + "\n".join(body)

    def _r2_validate(self, theme_ids: list[str]):
        def v(raw: dict) -> Optional[dict]:
            if not isinstance(raw, dict): return None
            ratings = raw.get("ratings", {})
            if set(ratings.keys()) != set(theme_ids): return None
            for tid, r in ratings.items():
                if not isinstance(r, dict): return None
                for key in ("importance", "plausibility"):
                    if not isinstance(r.get(key), int) or not 1 <= r[key] <= 5: return None
            return raw
        return v

    def administer_round2(self, persona: PersonaRecord, themes: list[dict]) -> DelphiRatingResponse:
        theme_ids = [t["theme_id"] for t in themes]
        raw = self.interviewer.ask_in_character(
            persona, user_prompt=self._r2_prompt(themes),
            schema_hint=self._r2_schema(theme_ids), validate=self._r2_validate(theme_ids),
        )
        return DelphiRatingResponse(agent_id=persona.agent_id, round=2,
                                    ratings={k: dict(v) for k, v in raw["ratings"].items()})

    # --- Round 3: revise after seeing group stats ---
    def administer_round3(
        self, persona: PersonaRecord, themes: list[dict], group_stats: dict, own_r2: DelphiRatingResponse
    ) -> DelphiRatingResponse:
        theme_ids = [t["theme_id"] for t in themes]
        head = ("Sie sehen unten die anonymisierten Gruppenwerte (Median, IQR). "
                "Bitte überarbeiten Sie Ihre Bewertungen, wenn Sie möchten, und begründen Sie kurz.") \
               if self.language == "de" else \
               ("Below are the anonymised group values (median, IQR). "
                "Please revise your ratings if you wish and add a short justification.")
        ctx_lines = []
        for t in themes:
            tid = t["theme_id"]
            gs = group_stats.get(tid, {})
            own = own_r2.ratings.get(tid, {})
            ctx_lines.append(
                f"[{tid}] {t['label']} — group importance median={gs.get('imp_median')}, "
                f"IQR={gs.get('imp_iqr')}; plausibility median={gs.get('plaus_median')}, "
                f"IQR={gs.get('plaus_iqr')}. Your R2: imp={own.get('importance')}, plaus={own.get('plausibility')}."
            )
        prompt = head + "\n\n" + "\n".join(ctx_lines)
        schema = json.dumps({
            "ratings": {tid: {"importance": "<int 1-5>", "plausibility": "<int 1-5>"} for tid in theme_ids},
            "justification": "<string>",
        }, ensure_ascii=False)
        def validate(raw):
            if not isinstance(raw, dict): return None
            ratings = raw.get("ratings", {})
            if set(ratings.keys()) != set(theme_ids): return None
            for r in ratings.values():
                if not isinstance(r, dict): return None
                for key in ("importance", "plausibility"):
                    if not isinstance(r.get(key), int) or not 1 <= r[key] <= 5: return None
            return raw
        raw = self.interviewer.ask_in_character(persona, user_prompt=prompt,
                                                schema_hint=schema, validate=validate)
        return DelphiRatingResponse(
            agent_id=persona.agent_id, round=3,
            ratings={k: dict(v) for k, v in raw["ratings"].items()},
            justification=raw.get("justification"),
        )

def extract_themes(round1: list[DelphiOpenResponse], llm) -> list[dict]:
    text_blocks = []
    for r in round1:
        for qid, ans in r.answers.items():
            text_blocks.append(f"[agent {r.agent_id} {qid}] {ans}")
    schema = json.dumps({"themes": [{"theme_id": "<string>", "label": "<short string>"}]}, ensure_ascii=False)
    messages = [
        {"role": "system", "content":
            "You extract distinct thematic codes from open-ended German fisheries survey responses. "
            f"Return JSON ONLY matching: {schema}. Use stable theme_ids of form theme_0, theme_1, …"},
        {"role": "user", "content": "Responses:\n" + "\n".join(text_blocks) + "\n\nReturn up to 12 distinct themes."},
    ]
    raw = llm.chat_json(messages=messages, temperature=0.0)
    themes = raw.get("themes", []) if isinstance(raw, dict) else []
    out = []
    for i, t in enumerate(themes):
        if isinstance(t, dict) and "label" in t:
            out.append({"theme_id": t.get("theme_id") or f"theme_{i}", "label": str(t["label"])})
    return out

def _iqr(xs: list[float]) -> float:
    if not xs: return 0.0
    xs = sorted(xs)
    q1 = statistics.quantiles(xs, n=4)[0] if len(xs) >= 4 else xs[0]
    q3 = statistics.quantiles(xs, n=4)[2] if len(xs) >= 4 else xs[-1]
    return q3 - q1

def convergence_metrics(r2: list[DelphiRatingResponse], r3: list[DelphiRatingResponse]) -> dict:
    by_r2 = {r.agent_id: r for r in r2}
    by_r3 = {r.agent_id: r for r in r3}
    themes: set[str] = set()
    for r in r2 + r3:
        themes.update(r.ratings.keys())
    out: dict[str, dict] = {}
    for t in sorted(themes):
        imp_r2 = [by_r2[a].ratings[t]["importance"] for a in by_r2 if t in by_r2[a].ratings]
        imp_r3 = [by_r3[a].ratings[t]["importance"] for a in by_r3 if t in by_r3[a].ratings]
        plaus_r2 = [by_r2[a].ratings[t]["plausibility"] for a in by_r2 if t in by_r2[a].ratings]
        plaus_r3 = [by_r3[a].ratings[t]["plausibility"] for a in by_r3 if t in by_r3[a].ratings]
        out[t] = {
            "imp_median_r2": statistics.median(imp_r2) if imp_r2 else None,
            "imp_median_r3": statistics.median(imp_r3) if imp_r3 else None,
            "imp_iqr_r2": _iqr(imp_r2),
            "imp_iqr_r3": _iqr(imp_r3),
            "delta_iqr_importance": _iqr(imp_r3) - _iqr(imp_r2),
            "plaus_iqr_r2": _iqr(plaus_r2),
            "plaus_iqr_r3": _iqr(plaus_r3),
            "delta_iqr_plausibility": _iqr(plaus_r3) - _iqr(plaus_r2),
        }
    return out

def group_stats_from_r2(r2: list[DelphiRatingResponse]) -> dict:
    themes: set[str] = set()
    for r in r2: themes.update(r.ratings.keys())
    stats: dict[str, dict] = {}
    for t in themes:
        imps = [r.ratings[t]["importance"] for r in r2 if t in r.ratings]
        plauss = [r.ratings[t]["plausibility"] for r in r2 if t in r.ratings]
        stats[t] = {
            "imp_median": statistics.median(imps) if imps else None,
            "imp_iqr": _iqr(imps),
            "plaus_median": statistics.median(plauss) if plauss else None,
            "plaus_iqr": _iqr(plauss),
        }
    return stats
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_delphi.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/instruments/delphi_v1.yaml backend/app/services/interviews/delphi.py backend/tests/interviews/test_delphi.py
git commit -m "feat(interviews): Delphi subagent (3 rounds: open, rate, revise) + convergence metrics"
```

---

### Task 9: Scenario subagent

**Files:**
- Create: `backend/scripts/instruments/scenario_v1.yaml`
- Create: `backend/app/services/interviews/scenario.py`
- Test: `backend/tests/interviews/test_scenario.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_scenario.py
from pathlib import Path
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interviews.scenario import ScenarioSubagent, polarity_matrix

INSTRUMENT = Path(__file__).resolve().parents[2] / "scripts" / "instruments" / "scenario_v1.yaml"

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        return {"ratings": {sid: {
            "desirability": 4, "plausibility": 3, "impact_on_my_group": 5, "fairness": 3,
            "if_woke_up_response": f"act-on-{sid}",
        } for sid in ("S1", "S2", "S3", "S4")}}

def test_scenario_administer():
    sub = ScenarioSubagent(llm=_LLM(), memory=_Mem(), instrument_path=INSTRUMENT)
    persona = PersonaRecord(agent_id=1, name="A", persona="p")
    resp = sub.administer(persona)
    assert set(resp.ratings.keys()) == {"S1", "S2", "S3", "S4"}
    assert resp.ratings["S1"].desirability == 4

def test_polarity_matrix():
    from app.models.interview import ScenarioResponse, ScenarioRating
    responses = [ScenarioResponse(agent_id=i, ratings={
        "S1": ScenarioRating(desirability=5, plausibility=4, impact_on_my_group=5, fairness=4,
                              if_woke_up_response="x"),
    }) for i in range(3)]
    m = polarity_matrix(responses)
    assert "S1" in m
    assert m["S1"]["mean_desirability"] == 5
    assert m["S1"]["n"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_scenario.py -v`
Expected: ImportError.

- [ ] **Step 3: Create instrument YAML**

`backend/scripts/instruments/scenario_v1.yaml`:
```yaml
name: scenario_v1
version: "1.0"
language_default: de
scenarios:
  - scenario_id: S1
    label_de: "Erholung 2040"
    label_en: "Recovery 2040"
    description_de: |
      Bis 2040 haben sich Dorsch- und Heringsbestände in der westlichen Ostsee
      deutlich erholt. MSC-Zertifizierung ist branchenweit Standard. Die kleine
      Küstenfischerei hat sich stabilisiert; die Politik gilt als erfolgreich.
    description_en: |
      By 2040, Western Baltic cod and herring stocks have substantially recovered.
      MSC certification is industry-wide standard. Small-scale coastal fisheries
      have stabilised; policy is regarded as successful.
  - scenario_id: S2
    label_de: "Kollaps 2040"
    label_en: "Collapse 2040"
    description_de: |
      Bis 2040 sind Dorsch- und Heringsbestände zusammengebrochen. Die Flotte
      ist halbiert, Aquakultur dominiert den Markt, Häfen veröden.
    description_en: |
      By 2040, cod and herring stocks have collapsed. The fleet is halved,
      aquaculture dominates the market, harbour towns decline.
  - scenario_id: S3
    label_de: "Festung Europa 2040"
    label_en: "Fortress Europe 2040"
    description_de: |
      Bis 2040 verfolgt die EU eine protektionistische Politik mit hohen Importzöllen,
      Meeresschutzgebiete bedecken 30% der Ostsee, Sportfischerei ist stark eingeschränkt.
    description_en: |
      By 2040, the EU pursues a protectionist policy with high import tariffs,
      MPAs cover 30% of the Baltic, recreational fishing is strongly curtailed.
  - scenario_id: S4
    label_de: "Privatisierung 2040"
    label_en: "Privatisation 2040"
    description_de: |
      Bis 2040 sind Fangrechte als handelbare Quoten (ITQs) etabliert. Die Branche
      hat sich konsolidiert; nur große, kapitalstarke Unternehmen sind übrig.
    description_en: |
      By 2040, fishing rights are tradable quotas (ITQs). The industry has
      consolidated; only large, well-capitalised firms remain.
dimensions:
  - {dimension_id: desirability, scale: 7,
     de: "Wie wünschenswert ist dieses Szenario?", en: "How desirable is this scenario?"}
  - {dimension_id: plausibility, scale: 7,
     de: "Wie plausibel ist dieses Szenario?",   en: "How plausible is this scenario?"}
  - {dimension_id: impact_on_my_group, scale: 7,
     de: "Wie stark trifft es Ihre Gruppe?",     en: "How strongly does it affect your group?"}
  - {dimension_id: fairness, scale: 7,
     de: "Wie fair ist dieses Szenario?",        en: "How fair is this scenario?"}
```

- [ ] **Step 4: Implement subagent**

`backend/app/services/interviews/scenario.py`:
```python
from __future__ import annotations
import json
import statistics
from pathlib import Path
from typing import Optional
import yaml
from app.models.interview import ScenarioRating, ScenarioResponse
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord

class ScenarioSubagent:
    def __init__(self, llm, memory, instrument_path: Path, language: str = "de"):
        with Path(instrument_path).open("r", encoding="utf-8") as f:
            self.instrument = yaml.safe_load(f)
        self.interviewer = StakeholderInterviewer(llm=llm, memory=memory, language=language)
        self.language = language

    def _schema_hint(self) -> str:
        sids = [s["scenario_id"] for s in self.instrument["scenarios"]]
        return json.dumps({
            "ratings": {sid: {
                "desirability": "<int 1-7>",
                "plausibility": "<int 1-7>",
                "impact_on_my_group": "<int 1-7>",
                "fairness": "<int 1-7>",
                "if_woke_up_response": "<string>",
            } for sid in sids}
        }, ensure_ascii=False)

    def _user_prompt(self) -> str:
        head = ("Bewerten Sie jedes der folgenden Szenarien auf vier Dimensionen (1-7) "
                "und beantworten Sie kurz, was Sie tun würden, wenn Sie in dieser Welt aufwachten.") \
               if self.language == "de" else \
               ("Rate each of the following scenarios on four dimensions (1-7) "
                "and briefly answer what you would do if you woke up in this world.")
        blocks = []
        for s in self.instrument["scenarios"]:
            label = s["label_de"] if self.language == "de" else s["label_en"]
            desc = s["description_de"] if self.language == "de" else s["description_en"]
            blocks.append(f"--- {s['scenario_id']}: {label} ---\n{desc}")
        return head + "\n\n" + "\n\n".join(blocks)

    def _validate(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict): return None
        sids = {s["scenario_id"] for s in self.instrument["scenarios"]}
        ratings = raw.get("ratings", {})
        if set(ratings.keys()) != sids: return None
        for v in ratings.values():
            if not isinstance(v, dict): return None
            for k in ("desirability", "plausibility", "impact_on_my_group", "fairness"):
                if not isinstance(v.get(k), int) or not 1 <= v[k] <= 7: return None
            if not isinstance(v.get("if_woke_up_response", ""), str): return None
        return raw

    def administer(self, persona: PersonaRecord) -> ScenarioResponse:
        raw = self.interviewer.ask_in_character(
            persona, user_prompt=self._user_prompt(),
            schema_hint=self._schema_hint(), validate=self._validate,
        )
        ratings = {sid: ScenarioRating(**v) for sid, v in raw["ratings"].items()}
        return ScenarioResponse(agent_id=persona.agent_id, ratings=ratings)

def polarity_matrix(responses: list[ScenarioResponse]) -> dict:
    matrix: dict[str, dict] = {}
    sids: set[str] = set()
    for r in responses: sids.update(r.ratings.keys())
    for sid in sorted(sids):
        vals = [r.ratings[sid] for r in responses if sid in r.ratings]
        if not vals:
            matrix[sid] = {"n": 0}
            continue
        matrix[sid] = {
            "n": len(vals),
            "mean_desirability": statistics.mean(v.desirability for v in vals),
            "mean_plausibility": statistics.mean(v.plausibility for v in vals),
            "mean_impact": statistics.mean(v.impact_on_my_group for v in vals),
            "mean_fairness": statistics.mean(v.fairness for v in vals),
            "sd_desirability": statistics.pstdev([v.desirability for v in vals]) if len(vals) > 1 else 0.0,
            "sd_plausibility": statistics.pstdev([v.plausibility for v in vals]) if len(vals) > 1 else 0.0,
        }
    return matrix
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_scenario.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/instruments/scenario_v1.yaml backend/app/services/interviews/scenario.py backend/tests/interviews/test_scenario.py
git commit -m "feat(interviews): scenario subagent with 4 futures × 4 dimensions + polarity matrix"
```

---

## Phase 3 — Storage and Zep

### Task 10: Interview storage layout writer

**Files:**
- Create: `backend/app/services/interviews/storage.py`
- Test: `backend/tests/interviews/test_storage.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_storage.py
import json
from pathlib import Path
from app.models.interview import (
    LikertResponse, InterviewPhase, SubagentKind,
)
from app.services.interviews.storage import InterviewStore

def test_run_directory_layout(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T0, subagent=SubagentKind.LONGITUDINAL)
    assert run_dir.exists()
    assert run_dir.parent.name == "longitudinal"
    assert run_dir.parent.parent.name == "T0"

def test_append_response(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T0, subagent=SubagentKind.LONGITUDINAL)
    r = LikertResponse(agent_id=1, phase=InterviewPhase.T0,
                       responses={"a": 3}, confidence={"a": 0.5})
    store.append_response(run_dir, r)
    contents = (run_dir / "responses.jsonl").read_text()
    assert json.loads(contents.splitlines()[0])["agent_id"] == 1

def test_write_aggregate_and_latest_pointer(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T1, subagent=SubagentKind.SCENARIO)
    store.write_aggregate(run_dir, {"k": 1})
    store.mark_latest(run_dir)
    latest = (run_dir.parent / "latest.json").read_text()
    assert json.loads(latest)["run_dir"].endswith(run_dir.name)

def test_audit_log_append(tmp_path):
    store = InterviewStore(root=tmp_path, sim_id="sim42")
    run_dir = store.start_run(phase=InterviewPhase.T0, subagent=SubagentKind.DELPHI)
    store.audit(run_dir, agent_id=7, event="schema_violation", detail="missing key x")
    audit = (run_dir / "audit.jsonl").read_text()
    assert "schema_violation" in audit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_storage.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement storage**

`backend/app/services/interviews/storage.py`:
```python
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any
from pydantic import BaseModel
from app.models.interview import InterviewPhase, SubagentKind

class InterviewStore:
    def __init__(self, root: Path, sim_id: str):
        self.base = Path(root) / "simulations" / sim_id / "interviews"
        self.base.mkdir(parents=True, exist_ok=True)

    def start_run(self, phase: InterviewPhase, subagent: SubagentKind) -> Path:
        run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = self.base / phase.value / subagent.value / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {"run_id": run_id, "phase": phase.value, "subagent": subagent.value,
                "created_at": time.time()}
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return run_dir

    def append_response(self, run_dir: Path, model: BaseModel) -> None:
        path = run_dir / "responses.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(model.model_dump_json() + "\n")

    def append_jsonl(self, run_dir: Path, filename: str, payload: dict | BaseModel) -> None:
        path = run_dir / filename
        with path.open("a", encoding="utf-8") as f:
            if isinstance(payload, BaseModel):
                f.write(payload.model_dump_json() + "\n")
            else:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_responses(self, run_dir: Path, filename: str = "responses.jsonl") -> list[dict]:
        path = run_dir / filename
        if not path.exists(): return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_aggregate(self, run_dir: Path, payload: dict) -> None:
        (run_dir / "aggregate.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_named(self, run_dir: Path, name: str, payload: Any) -> None:
        (run_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def audit(self, run_dir: Path, agent_id: int | None, event: str, detail: str = "") -> None:
        entry = {"ts": time.time(), "agent_id": agent_id, "event": event, "detail": detail}
        with (run_dir / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def mark_latest(self, run_dir: Path) -> None:
        pointer = run_dir.parent / "latest.json"
        pointer.write_text(json.dumps({
            "run_dir": str(run_dir.relative_to(self.base)),
        }), encoding="utf-8")

    def latest_run(self, phase: InterviewPhase, subagent: SubagentKind) -> Path | None:
        pointer = self.base / phase.value / subagent.value / "latest.json"
        if not pointer.exists(): return None
        rel = json.loads(pointer.read_text())["run_dir"]
        path = self.base / rel
        return path if path.exists() else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_storage.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interviews/storage.py backend/tests/interviews/test_storage.py
git commit -m "feat(interviews): JSONL/JSON storage layout with run_id directories and latest pointer"
```

---

### Task 11: Zep episode writer for interviews

**Files:**
- Create: `backend/app/services/interviews/zep_writer.py`
- Test: `backend/tests/interviews/test_zep_writer.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_zep_writer.py
from app.models.interview import (
    LikertResponse, InterviewPhase, SubagentKind,
)
from app.services.interviews.zep_writer import InterviewZepWriter

class _FakeMemoryUpdater:
    def __init__(self):
        self.events = []
    def add_activity(self, activity):
        self.events.append(activity)
    def add_text_episode(self, graph_id, text):
        self.events.append({"graph_id": graph_id, "text": text})

def test_per_agent_episode_text():
    upd = _FakeMemoryUpdater()
    w = InterviewZepWriter(memory_updater=upd, graph_id="g1")
    r = LikertResponse(agent_id=42, phase=InterviewPhase.T1,
                       responses={"stk_1": 4, "gov_1": 3},
                       confidence={"stk_1": 0.8, "gov_1": 0.7})
    w.write_per_agent(SubagentKind.LONGITUDINAL, r, agent_name="Fischer Müller")
    assert any("Fischer Müller" in str(e) for e in upd.events)
    assert any("longitudinal/T1" in str(e) for e in upd.events)

def test_aggregate_episode():
    upd = _FakeMemoryUpdater()
    w = InterviewZepWriter(memory_updater=upd, graph_id="g1")
    w.write_aggregate(SubagentKind.SCENARIO, summary="S1 mean desirability 5.2; S2 mean 2.1")
    assert any("S1 mean" in str(e) for e in upd.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_zep_writer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement writer**

`backend/app/services/interviews/zep_writer.py`:
```python
from __future__ import annotations
from typing import Any, Optional
from app.models.interview import (
    LikertResponse, QSortResponse, DelphiRatingResponse, ScenarioResponse, SubagentKind,
)

class InterviewZepWriter:
    """Mirrors `ZepGraphMemoryUpdater.add_activity` usage but for interview episodes.

    The real `ZepGraphMemoryUpdater` may expose `add_activity` (preferred) or a lower-level
    text-episode method; this writer adapts to either via duck typing.
    """
    def __init__(self, memory_updater, graph_id: str):
        self.updater = memory_updater
        self.graph_id = graph_id

    def _emit(self, text: str) -> None:
        if hasattr(self.updater, "add_text_episode"):
            self.updater.add_text_episode(self.graph_id, text)
        elif hasattr(self.updater, "add_activity"):
            self.updater.add_activity({"graph_id": self.graph_id, "text": text})
        else:
            raise RuntimeError("memory_updater has neither add_text_episode nor add_activity")

    def _summarize_likert(self, r: LikertResponse) -> str:
        mean_v = sum(r.responses.values()) / max(len(r.responses), 1)
        top = sorted(r.responses.items(), key=lambda kv: -kv[1])[:3]
        bot = sorted(r.responses.items(), key=lambda kv: kv[1])[:3]
        return (f"mean={mean_v:.2f}; agrees with {[k for k,_ in top]}; "
                f"disagrees with {[k for k,_ in bot]}")

    def _summarize_qsort(self, r: QSortResponse) -> str:
        plus = [k for k, v in r.placements.items() if v >= 2]
        minus = [k for k, v in r.placements.items() if v <= -2]
        return f"+strongly:{plus}; -strongly:{minus}"

    def _summarize_scenario(self, r: ScenarioResponse) -> str:
        parts = [f"{sid}: des={rt.desirability} plaus={rt.plausibility}"
                 for sid, rt in r.ratings.items()]
        return "; ".join(parts)

    def write_per_agent(
        self, subagent: SubagentKind, response: Any, agent_name: str,
        phase: Optional[str] = None,
    ) -> None:
        if isinstance(response, LikertResponse):
            phase = phase or response.phase.value
            summary = self._summarize_likert(response)
        elif isinstance(response, QSortResponse):
            phase = phase or "T1"
            summary = self._summarize_qsort(response)
        elif isinstance(response, ScenarioResponse):
            phase = phase or "T1"
            summary = self._summarize_scenario(response)
        elif isinstance(response, DelphiRatingResponse):
            phase = phase or f"T1/R{response.round}"
            summary = f"round={response.round}; {len(response.ratings)} themes rated"
        else:
            phase = phase or "T1"
            summary = str(response)[:200]
        text = f"Agent {agent_name} (interview/{subagent.value}/{phase}): {summary}"
        self._emit(text)

    def write_aggregate(self, subagent: SubagentKind, summary: str) -> None:
        self._emit(f"Interview aggregate ({subagent.value}): {summary}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_zep_writer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interviews/zep_writer.py backend/tests/interviews/test_zep_writer.py
git commit -m "feat(interviews): Zep writer adapts add_activity/add_text_episode for per-agent + aggregate episodes"
```

---

## Phase 4 — Orchestrator, lifecycle, synthesiser

### Task 12: InterviewOrchestrator (parallel fan-out)

**Files:**
- Create: `backend/app/services/interview_orchestrator.py`
- Test: `backend/tests/interviews/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_orchestrator.py
from pathlib import Path
import pytest
from app.models.interview import InterviewPhase, SubagentKind
from app.services.interviews.base import PersonaRecord, MemoryDigest
from app.services.interview_orchestrator import (
    InterviewOrchestrator, PersonaProvider,
)

INST_DIR = Path(__file__).resolve().parents[2] / "scripts" / "instruments"

class _Mem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text="x", available=True)

class _LLM:
    def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
        sys_text = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "longitudinal" in sys_text or "stk_" in (messages[-1].get("content") or ""):
            return {
                "responses": {k: 3 for k in ("stk_1","stk_2","stk_3","gov_1","gov_2","gov_3",
                                             "mkt_1","mkt_2","mkt_3","clm_1","clm_2","clm_3")},
                "confidence": {}, "open_comment": "ok",
            }
        return {}

class _Personas(PersonaProvider):
    def __init__(self, n=3):
        self._items = [PersonaRecord(agent_id=i, name=f"A{i}", persona="p") for i in range(n)]
    def all(self): return list(self._items)

class _NoopZep:
    def write_per_agent(self, *a, **kw): pass
    def write_aggregate(self, *a, **kw): pass

def test_pre_phase_runs_longitudinal_only(tmp_path):
    orch = InterviewOrchestrator(
        llm=_LLM(), memory=_Mem(), personas=_Personas(3),
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="sim1",
        zep_writer=_NoopZep(), max_workers=2,
    )
    result = orch.run_pre()
    assert result["longitudinal"]["n_responded"] == 3
    assert "diversity" not in result  # only longitudinal in pre-phase

def test_partial_failure_does_not_kill_run(tmp_path):
    class _FlakyLLM:
        def __init__(self): self.n = 0
        def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
            self.n += 1
            if self.n % 2 == 0:
                raise RuntimeError("simulated LLM 5xx")
            return {
                "responses": {k: 3 for k in ("stk_1","stk_2","stk_3","gov_1","gov_2","gov_3",
                                             "mkt_1","mkt_2","mkt_3","clm_1","clm_2","clm_3")},
                "confidence": {}, "open_comment": "ok",
            }
    orch = InterviewOrchestrator(
        llm=_FlakyLLM(), memory=_Mem(), personas=_Personas(4),
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="sim2",
        zep_writer=_NoopZep(), max_workers=1,
    )
    result = orch.run_pre()
    assert result["longitudinal"]["n_responded"] < 4
    assert result["longitudinal"]["n_failed"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_orchestrator.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement orchestrator**

`backend/app/services/interview_orchestrator.py`:
```python
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol
from app.models.interview import (
    InterviewPhase, SubagentKind, LikertResponse, QSortResponse,
    DelphiOpenResponse, DelphiRatingResponse, ScenarioResponse,
)
from app.services.interviews.base import PersonaRecord
from app.services.interviews.longitudinal import LongitudinalSubagent, run_aggregate as longitudinal_aggregate
from app.services.interviews.diversity import DiversitySubagent, run_typology
from app.services.interviews.delphi import (
    DelphiSubagent, extract_themes, convergence_metrics, group_stats_from_r2,
)
from app.services.interviews.scenario import ScenarioSubagent, polarity_matrix
from app.services.interviews.storage import InterviewStore
from app.services.interviews.instrument_loader import freeze_snapshot

class PersonaProvider(Protocol):
    def all(self) -> list[PersonaRecord]: ...

class InterviewOrchestrator:
    def __init__(
        self, llm, memory, personas: PersonaProvider,
        instrument_dir: Path, store_root: Path, sim_id: str,
        zep_writer, max_workers: int = 8, language: str = "de",
    ):
        self.llm = llm
        self.memory = memory
        self.personas = personas
        self.instrument_dir = Path(instrument_dir)
        self.store = InterviewStore(root=store_root, sim_id=sim_id)
        self.zep_writer = zep_writer
        self.max_workers = max_workers
        self.language = language
        # Freeze snapshot once per orchestrator lifetime
        freeze_snapshot(
            instruments={
                "longitudinal": self.instrument_dir / "longitudinal_v1.yaml",
                "diversity":    self.instrument_dir / "diversity_v1.yaml",
                "delphi":       self.instrument_dir / "delphi_v1.yaml",
                "scenario":     self.instrument_dir / "scenario_v1.yaml",
            },
            out_path=self.store.base / "instruments_used.json",
        )

    # --- Generic per-agent runner ---
    def _fan_out(self, run_dir, agent_fn, personas, audit_label):
        ok: list = []
        failed: list[int] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(agent_fn, p): p for p in personas}
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    out = fut.result()
                    ok.append(out)
                    self.store.append_response(run_dir, out)
                except Exception as e:
                    failed.append(p.agent_id)
                    self.store.audit(run_dir, agent_id=p.agent_id,
                                     event="agent_failed", detail=f"{audit_label}: {e!r}")
        return ok, failed

    # --- Pre-phase (T0) ---
    def run_pre(self) -> dict:
        sub = LongitudinalSubagent(self.llm, self.memory,
                                   self.instrument_dir / "longitudinal_v1.yaml",
                                   language=self.language)
        run_dir = self.store.start_run(InterviewPhase.T0, SubagentKind.LONGITUDINAL)
        ok, failed = self._fan_out(
            run_dir, lambda p: sub.administer(p, phase=InterviewPhase.T0),
            self.personas.all(), audit_label="longitudinal_T0",
        )
        for r in ok:
            persona = next(p for p in self.personas.all() if p.agent_id == r.agent_id)
            try: self.zep_writer.write_per_agent(SubagentKind.LONGITUDINAL, r, persona.name)
            except Exception: pass
        self.store.mark_latest(run_dir)
        return {"longitudinal": {"n_responded": len(ok), "n_failed": len(failed),
                                 "run_dir": str(run_dir)}}

    # --- Post-phase (T1) ---
    def run_post(self) -> dict:
        personas = self.personas.all()
        out: dict = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                "longitudinal": pool.submit(self._post_longitudinal, personas),
                "diversity":    pool.submit(self._post_diversity, personas),
                "scenario":     pool.submit(self._post_scenario, personas),
            }
            for name, fut in futures.items():
                try: out[name] = fut.result()
                except Exception as e: out[name] = {"error": repr(e)}
        # Delphi runs sequentially (R1 → R2 → R3) and uses the LLM for theme extraction
        try: out["delphi"] = self._post_delphi(personas)
        except Exception as e: out["delphi"] = {"error": repr(e)}
        return out

    def _post_longitudinal(self, personas) -> dict:
        sub = LongitudinalSubagent(self.llm, self.memory,
                                   self.instrument_dir / "longitudinal_v1.yaml",
                                   language=self.language)
        run_dir = self.store.start_run(InterviewPhase.T1, SubagentKind.LONGITUDINAL)
        ok, failed = self._fan_out(
            run_dir, lambda p: sub.administer(p, phase=InterviewPhase.T1),
            personas, audit_label="longitudinal_T1",
        )
        # Aggregate using T0 + T1
        t0_path = self.store.latest_run(InterviewPhase.T0, SubagentKind.LONGITUDINAL)
        t0_raw = self.store.read_responses(t0_path) if t0_path else []
        t0 = [LikertResponse(**d) for d in t0_raw]
        agg = longitudinal_aggregate(t0, ok)
        self.store.write_aggregate(run_dir, agg)
        for r in ok:
            persona = next(p for p in personas if p.agent_id == r.agent_id)
            try: self.zep_writer.write_per_agent(SubagentKind.LONGITUDINAL, r, persona.name)
            except Exception: pass
        try: self.zep_writer.write_aggregate(SubagentKind.LONGITUDINAL,
                                             f"n_paired={agg['n_paired']}")
        except Exception: pass
        self.store.mark_latest(run_dir)
        return {"n_responded": len(ok), "n_failed": len(failed), "run_dir": str(run_dir)}

    def _post_diversity(self, personas) -> dict:
        sub = DiversitySubagent(self.llm, self.memory,
                                self.instrument_dir / "diversity_v1.yaml",
                                language=self.language)
        run_dir = self.store.start_run(InterviewPhase.T1, SubagentKind.DIVERSITY)
        ok, failed = self._fan_out(
            run_dir, lambda p: sub.administer(p), personas, audit_label="diversity",
        )
        typology = run_typology(ok)
        self.store.write_named(run_dir, "typology.json", typology)
        self.store.write_aggregate(run_dir, {"n": len(ok), "n_failed": len(failed),
                                             "clusters": typology["clusters"]})
        for r in ok:
            persona = next(p for p in personas if p.agent_id == r.agent_id)
            try: self.zep_writer.write_per_agent(SubagentKind.DIVERSITY, r, persona.name)
            except Exception: pass
        self.store.mark_latest(run_dir)
        return {"n_responded": len(ok), "n_failed": len(failed), "run_dir": str(run_dir)}

    def _post_scenario(self, personas) -> dict:
        sub = ScenarioSubagent(self.llm, self.memory,
                               self.instrument_dir / "scenario_v1.yaml",
                               language=self.language)
        run_dir = self.store.start_run(InterviewPhase.T1, SubagentKind.SCENARIO)
        ok, failed = self._fan_out(
            run_dir, lambda p: sub.administer(p), personas, audit_label="scenario",
        )
        matrix = polarity_matrix(ok)
        self.store.write_named(run_dir, "polarity_matrix.json", matrix)
        self.store.write_aggregate(run_dir, {"n": len(ok), "n_failed": len(failed),
                                             "polarity": matrix})
        for r in ok:
            persona = next(p for p in personas if p.agent_id == r.agent_id)
            try: self.zep_writer.write_per_agent(SubagentKind.SCENARIO, r, persona.name)
            except Exception: pass
        self.store.mark_latest(run_dir)
        return {"n_responded": len(ok), "n_failed": len(failed), "run_dir": str(run_dir)}

    def _post_delphi(self, personas) -> dict:
        sub = DelphiSubagent(self.llm, self.memory,
                             self.instrument_dir / "delphi_v1.yaml",
                             language=self.language)
        run_dir = self.store.start_run(InterviewPhase.T1, SubagentKind.DELPHI)
        # Round 1
        r1_ok, r1_failed = self._fan_out(
            run_dir, lambda p: sub.administer_round1(p), personas, audit_label="delphi_r1",
        )
        # Move all R1 responses into a dedicated file
        for r in r1_ok: self.store.append_jsonl(run_dir, "round1_themes.jsonl", r)
        # Extract themes from R1
        themes = extract_themes(r1_ok, llm=self.llm)
        self.store.write_named(run_dir, "themes.json", {"themes": themes})
        # Round 2
        r2_ok, r2_failed = self._fan_out(
            run_dir, lambda p: sub.administer_round2(p, themes),
            [p for p in personas if p.agent_id in {r.agent_id for r in r1_ok}],
            audit_label="delphi_r2",
        )
        for r in r2_ok: self.store.append_jsonl(run_dir, "round2_ratings.jsonl", r)
        gstats = group_stats_from_r2(r2_ok)
        # Round 3
        r2_by = {r.agent_id: r for r in r2_ok}
        r3_personas = [p for p in personas if p.agent_id in r2_by]
        def r3_call(p): return sub.administer_round3(p, themes, gstats, r2_by[p.agent_id])
        r3_ok, r3_failed = self._fan_out(run_dir, r3_call, r3_personas, audit_label="delphi_r3")
        for r in r3_ok: self.store.append_jsonl(run_dir, "round3_revisions.jsonl", r)
        # Convergence
        conv = convergence_metrics(r2_ok, r3_ok)
        self.store.write_named(run_dir, "convergence.json", conv)
        self.store.write_aggregate(run_dir, {
            "n_r1": len(r1_ok), "n_r2": len(r2_ok), "n_r3": len(r3_ok),
            "n_failed_r1": len(r1_failed), "n_failed_r2": len(r2_failed), "n_failed_r3": len(r3_failed),
            "themes": themes,
        })
        for r in r3_ok:
            persona = next(p for p in personas if p.agent_id == r.agent_id)
            try: self.zep_writer.write_per_agent(SubagentKind.DELPHI, r, persona.name)
            except Exception: pass
        self.store.mark_latest(run_dir)
        return {"n_r1": len(r1_ok), "n_r2": len(r2_ok), "n_r3": len(r3_ok),
                "run_dir": str(run_dir)}

    # --- Re-run a single subagent ---
    def rerun(self, subagent: SubagentKind) -> dict:
        personas = self.personas.all()
        if subagent == SubagentKind.LONGITUDINAL: return {"longitudinal": self._post_longitudinal(personas)}
        if subagent == SubagentKind.DIVERSITY:    return {"diversity":    self._post_diversity(personas)}
        if subagent == SubagentKind.SCENARIO:     return {"scenario":     self._post_scenario(personas)}
        if subagent == SubagentKind.DELPHI:       return {"delphi":       self._post_delphi(personas)}
        raise ValueError(f"unknown subagent {subagent}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_orchestrator.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interview_orchestrator.py backend/tests/interviews/test_orchestrator.py
git commit -m "feat(interviews): orchestrator with two-phase lifecycle, parallel fan-out, isolated failures"
```

---

### Task 13: Simulation manager lifecycle hooks

**Files:**
- Modify: `backend/app/services/simulation_manager.py`
- Test: `backend/tests/interviews/test_simulation_hooks.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_simulation_hooks.py
from app.services.simulation_manager import SimulationManager, SimulationState

def test_register_post_ready_hook_invoked(monkeypatch):
    called = []
    mgr = SimulationManager()
    mgr.register_on_ready(lambda state: called.append(("ready", state.sim_id)))
    state = SimulationState(sim_id="abc", status="ready")
    mgr._notify_on_ready(state)
    assert called == [("ready", "abc")]

def test_register_post_completed_hook_invoked():
    called = []
    mgr = SimulationManager()
    mgr.register_on_completed(lambda state: called.append(("done", state.sim_id)))
    state = SimulationState(sim_id="abc", status="completed")
    mgr._notify_on_completed(state)
    assert called == [("done", "abc")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_simulation_hooks.py -v`
Expected: AttributeError on `register_on_ready` / `register_on_completed`.

- [ ] **Step 3: Add hook registry to SimulationManager**

In `backend/app/services/simulation_manager.py`, find the `SimulationManager` class. Add to `__init__` (preserving existing init):
```python
        self._on_ready_hooks: list = []
        self._on_completed_hooks: list = []
```

Add methods to the class:
```python
    def register_on_ready(self, fn) -> None:
        self._on_ready_hooks.append(fn)

    def register_on_completed(self, fn) -> None:
        self._on_completed_hooks.append(fn)

    def _notify_on_ready(self, state) -> None:
        for fn in list(self._on_ready_hooks):
            try: fn(state)
            except Exception as e:
                from app.utils.logger import get_logger
                get_logger(__name__).warning(f"on_ready hook failed: {e!r}")

    def _notify_on_completed(self, state) -> None:
        for fn in list(self._on_completed_hooks):
            try: fn(state)
            except Exception as e:
                from app.utils.logger import get_logger
                get_logger(__name__).warning(f"on_completed hook failed: {e!r}")
```

Locate the existing code that transitions state to `ready` (after `prepare_simulation` completes) and to `completed` (after simulation finishes). Insert calls to `self._notify_on_ready(state)` and `self._notify_on_completed(state)` immediately after each transition. If `SimulationState` is not a simple dataclass with `sim_id` and `status` attributes, adjust the test fixture to match the actual class shape (read the file first).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_simulation_hooks.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/simulation_manager.py backend/tests/interviews/test_simulation_hooks.py
git commit -m "feat(interviews): on_ready / on_completed hook registry on SimulationManager"
```

---

### Task 14: InterviewSynthesizer

**Files:**
- Create: `backend/app/services/interview_synthesizer.py`
- Test: `backend/tests/interviews/test_synthesizer.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_synthesizer.py
import json
from pathlib import Path
from app.services.interviews.storage import InterviewStore
from app.models.interview import InterviewPhase, SubagentKind, LikertResponse
from app.services.interview_synthesizer import InterviewSynthesizer

def _seed_minimal(tmp_path: Path) -> InterviewStore:
    store = InterviewStore(root=tmp_path, sim_id="s1")
    rd = store.start_run(InterviewPhase.T0, SubagentKind.LONGITUDINAL)
    for i in range(3):
        store.append_response(rd, LikertResponse(
            agent_id=i, phase=InterviewPhase.T0,
            responses={"stk_1": 3, "gov_1": 3}, confidence={"stk_1": 0.5, "gov_1": 0.5},
        ))
    store.write_aggregate(rd, {"per_item": {}, "n_paired": 0})
    store.mark_latest(rd)
    return store

def test_synthesizer_runs_with_partial_data(tmp_path):
    store = _seed_minimal(tmp_path)
    synth = InterviewSynthesizer(store=store)
    report = synth.run()
    assert "limitations" in report.lower()
    assert "stub mode" in report.lower() or "n_responded" in report.lower()

def test_synthesizer_writes_files(tmp_path):
    store = _seed_minimal(tmp_path)
    synth = InterviewSynthesizer(store=store)
    synth.run()
    files = list((store.base / "synthesis").iterdir())
    names = {f.name for f in files}
    assert "report.md" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_synthesizer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement synthesiser**

`backend/app/services/interview_synthesizer.py`:
```python
from __future__ import annotations
import csv
import json
from pathlib import Path
from app.models.interview import InterviewPhase, SubagentKind
from app.services.interviews.storage import InterviewStore

class InterviewSynthesizer:
    def __init__(self, store: InterviewStore):
        self.store = store

    def _maybe(self, phase: InterviewPhase, sub: SubagentKind) -> dict | None:
        run = self.store.latest_run(phase, sub)
        if run is None: return None
        agg = run / "aggregate.json"
        if not agg.exists(): return None
        return {"run_dir": str(run), "aggregate": json.loads(agg.read_text(encoding="utf-8"))}

    def _instrument_hashes(self) -> dict:
        snap = self.store.base / "instruments_used.json"
        if not snap.exists(): return {}
        try: data = json.loads(snap.read_text(encoding="utf-8"))
        except Exception: return {}
        return {k: v.get("hash") for k, v in data.items()}

    def _limitations_text(self, present: dict[str, bool]) -> str:
        lines = [
            "## Limitations",
            "- **Simulated, not real stakeholders.** Responses reflect how the seed-document discourse "
            "and the LLM jointly encode each stakeholder type, not what an actual fisher or NGO "
            "staffer would say. The instrument measures the *model of the stakeholder*, not the stakeholder.",
            "- **Memory digest is lossy.** Each agent's experience of OASIS is summarised to bounded length; "
            "agents do not have full episodic recall.",
            "- **LLM acquiescence and centrality bias.** Likert scales with LLM respondents skew toward 3–4 "
            "of 5; check per-item distribution shape before drawing conclusions.",
            "- **N is what it is.** `n_responded` and `n_failed` are printed verbatim per subagent; no smoothing.",
            "- **Instrument provenance.** Hashes of frozen instruments are listed below; an identical run "
            "is reproducible from these snapshots.",
        ]
        for k, ok in present.items():
            if not ok:
                lines.append(f"- *{k}* subagent results are missing for this run.")
        return "\n".join(lines)

    def run(self) -> str:
        sections: list[str] = []
        sections.append("# Stakeholder Interview Synthesis\n")

        long_t0 = self._maybe(InterviewPhase.T0, SubagentKind.LONGITUDINAL)
        long_t1 = self._maybe(InterviewPhase.T1, SubagentKind.LONGITUDINAL)
        if long_t1:
            agg = long_t1["aggregate"]
            sections.append("## Longitudinal opinion drift (T0 → T1)")
            sections.append(f"- N paired: {agg.get('n_paired', 'NA')}")
            per_item = agg.get("per_item", {})
            top = sorted(per_item.items(),
                         key=lambda kv: abs(kv[1].get("mean_delta") or 0), reverse=True)[:5]
            sections.append("- Largest mean shifts:")
            for k, v in top:
                sections.append(f"  - `{k}`: Δ̄ = {v.get('mean_delta'):+0.2f}  (n={v.get('n')})")

        diversity = self._maybe(InterviewPhase.T1, SubagentKind.DIVERSITY)
        if diversity:
            clusters = diversity["aggregate"].get("clusters", [])
            sections.append("## Stakeholder typology")
            sections.append(f"- N agents: {diversity['aggregate'].get('n', 'NA')}")
            sections.append(f"- Clusters: {len(clusters)}")
            for c in clusters:
                sections.append(f"  - cluster {c['cluster_id']}: n={c['n']}, "
                                f"top loadings = {list(c['top_loadings'].keys())[:5]}")

        delphi = self._maybe(InterviewPhase.T1, SubagentKind.DELPHI)
        if delphi:
            agg = delphi["aggregate"]
            sections.append("## Delphi consensus")
            sections.append(f"- Rounds completed: R1={agg.get('n_r1')}, R2={agg.get('n_r2')}, R3={agg.get('n_r3')}")
            themes = agg.get("themes", [])
            sections.append(f"- Themes: {[t.get('label') for t in themes]}")

        scenario = self._maybe(InterviewPhase.T1, SubagentKind.SCENARIO)
        if scenario:
            pol = scenario["aggregate"].get("polarity", {})
            sections.append("## Scenario evaluation")
            for sid in sorted(pol):
                v = pol[sid]
                if v.get("n", 0) == 0: continue
                sections.append(
                    f"- **{sid}**: n={v['n']}, desirability {v['mean_desirability']:.2f}, "
                    f"plausibility {v['mean_plausibility']:.2f}, impact {v['mean_impact']:.2f}, "
                    f"fairness {v['mean_fairness']:.2f}")

        sections.append("")
        sections.append(self._limitations_text({
            "longitudinal": bool(long_t1),
            "diversity":    bool(diversity),
            "delphi":       bool(delphi),
            "scenario":     bool(scenario),
        }))
        sections.append("")
        sections.append("### Instrument provenance")
        for name, h in self._instrument_hashes().items():
            sections.append(f"- `{name}`: hash `{h}`")

        report = "\n\n".join(sections)
        out_dir = self.store.base / "synthesis"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.md").write_text(report, encoding="utf-8")
        self._write_tidy_csv(out_dir / "exports" / "all_responses.csv")
        return report

    def _write_tidy_csv(self, csv_path: Path) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict] = []
        for phase in (InterviewPhase.T0, InterviewPhase.T1):
            for sub in SubagentKind:
                run = self.store.latest_run(phase, sub)
                if run is None: continue
                files = ["responses.jsonl", "round1_themes.jsonl",
                         "round2_ratings.jsonl", "round3_revisions.jsonl"]
                for fname in files:
                    for rec in self.store.read_responses(run, fname):
                        flat = self._flatten(rec, phase=phase.value, subagent=sub.value)
                        rows.extend(flat)
        if not rows:
            csv_path.write_text("phase,subagent,agent_id,key,value\n", encoding="utf-8")
            return
        fieldnames = sorted({k for r in rows for k in r.keys()})
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows: w.writerow(r)

    def _flatten(self, rec: dict, *, phase: str, subagent: str) -> list[dict]:
        out: list[dict] = []
        aid = rec.get("agent_id")
        for key, val in rec.items():
            if key == "agent_id": continue
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    if isinstance(v2, dict):
                        for k3, v3 in v2.items():
                            out.append({"phase": phase, "subagent": subagent, "agent_id": aid,
                                        "key": f"{key}.{k2}.{k3}", "value": v3})
                    else:
                        out.append({"phase": phase, "subagent": subagent, "agent_id": aid,
                                    "key": f"{key}.{k2}", "value": v2})
            else:
                out.append({"phase": phase, "subagent": subagent, "agent_id": aid,
                            "key": key, "value": val})
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_synthesizer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interview_synthesizer.py backend/tests/interviews/test_synthesizer.py
git commit -m "feat(interviews): synthesiser emits cross-method report + tidy CSV + limitations section"
```

---

## Phase 5 — Adapters and API

### Task 15: Persona + memory adapters

**Files:**
- Create: `backend/app/services/interviews/adapters.py`
- Test: `backend/tests/interviews/test_adapters.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_adapters.py
import csv
import json
from pathlib import Path
from app.services.interviews.adapters import (
    FileSystemPersonaProvider, ZepMemoryProvider,
)

def _write_reddit_profiles(tmp_path: Path):
    data = [
        {"user_id": 0, "user_name": "fischer1", "name": "Fischer Müller",
         "persona": "I am a small-scale Baltic fisher.", "profession": "fisher", "bio": ""},
        {"user_id": 1, "user_name": "ngo1", "name": "Ines NGO",
         "persona": "I work for an environmental NGO.", "profession": "ngo_staff", "bio": ""},
    ]
    p = tmp_path / "reddit_profiles.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p

def test_file_system_persona_provider_reads_reddit_json(tmp_path):
    p = _write_reddit_profiles(tmp_path)
    provider = FileSystemPersonaProvider(reddit_path=p, twitter_path=None)
    personas = provider.all()
    assert len(personas) == 2
    assert personas[0].name == "Fischer Müller"
    assert personas[0].agent_id == 0

def test_zep_memory_provider_returns_empty_when_unavailable():
    class _BrokenReader:
        def get_entity_with_context(self, *a, **kw):
            raise RuntimeError("offline")
    prov = ZepMemoryProvider(entity_reader=_BrokenReader(), graph_id="g1",
                             agent_to_entity={0: "uuid-zero"})
    d = prov.get_digest(0)
    assert d.available is False
    assert d.text != ""

def test_zep_memory_provider_truncates_to_max_chars():
    class _R:
        def get_entity_with_context(self, *a, **kw):
            class _Ctx:
                name = "X"; summary = "Y"
                related_edges = [{"fact": "very long fact " * 200}]
            return _Ctx()
    prov = ZepMemoryProvider(entity_reader=_R(), graph_id="g1",
                             agent_to_entity={5: "uuid-five"})
    d = prov.get_digest(5, max_chars=300)
    assert d.available is True
    assert len(d.text) <= 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_adapters.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement adapters**

`backend/app/services/interviews/adapters.py`:
```python
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Optional
from app.services.interviews.base import PersonaRecord, MemoryDigest

class FileSystemPersonaProvider:
    """Reads OASIS profiles from the simulation's `reddit_profiles.json` and/or `twitter_profiles.csv`.

    If both are present, agents from `reddit_profiles.json` take precedence; twitter-only agents are appended.
    """
    def __init__(self, reddit_path: Optional[Path], twitter_path: Optional[Path]):
        self.reddit_path = Path(reddit_path) if reddit_path else None
        self.twitter_path = Path(twitter_path) if twitter_path else None

    def _load_reddit(self) -> list[PersonaRecord]:
        if not self.reddit_path or not self.reddit_path.exists(): return []
        data = json.loads(self.reddit_path.read_text(encoding="utf-8"))
        out = []
        for row in data:
            out.append(PersonaRecord(
                agent_id=int(row.get("user_id")),
                name=str(row.get("name") or row.get("user_name") or f"agent_{row.get('user_id')}"),
                persona=str(row.get("persona") or row.get("bio") or ""),
                profession=row.get("profession"),
                bio=row.get("bio"),
            ))
        return out

    def _load_twitter(self) -> list[PersonaRecord]:
        if not self.twitter_path or not self.twitter_path.exists(): return []
        out = []
        with self.twitter_path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if not row.get("user_id"): continue
                out.append(PersonaRecord(
                    agent_id=int(row["user_id"]),
                    name=str(row.get("name") or row.get("user_name") or f"agent_{row['user_id']}"),
                    persona=str(row.get("persona") or row.get("bio") or ""),
                    profession=row.get("profession"),
                    bio=row.get("bio"),
                ))
        return out

    def all(self) -> list[PersonaRecord]:
        reddit = self._load_reddit()
        seen = {p.agent_id for p in reddit}
        twitter = [p for p in self._load_twitter() if p.agent_id not in seen]
        return reddit + twitter

class ZepMemoryProvider:
    """Builds a bounded memory digest per agent from Zep entity context.

    Maps `agent_id` (OASIS user_id) to a Zep entity UUID; falls back to the agent_id as a string.
    """
    def __init__(self, entity_reader, graph_id: str, agent_to_entity: dict[int, str] | None = None):
        self.reader = entity_reader
        self.graph_id = graph_id
        self.map = dict(agent_to_entity or {})

    def get_digest(self, agent_id: int, max_chars: int = 2000) -> MemoryDigest:
        entity_uuid = self.map.get(agent_id) or str(agent_id)
        try:
            ctx = self.reader.get_entity_with_context(self.graph_id, entity_uuid)
        except Exception:
            return MemoryDigest(text=f"[no memory for agent {agent_id}]", available=False)
        parts: list[str] = []
        name = getattr(ctx, "name", None)
        summary = getattr(ctx, "summary", None)
        if name: parts.append(f"Name: {name}")
        if summary: parts.append(f"Summary: {summary}")
        edges = getattr(ctx, "related_edges", []) or []
        for e in edges[:20]:
            fact = e.get("fact") if isinstance(e, dict) else getattr(e, "fact", None)
            if fact: parts.append(f"- {fact}")
        text = "\n".join(parts)
        if len(text) > max_chars: text = text[: max_chars - 1] + "…"
        return MemoryDigest(text=text or f"[empty memory for agent {agent_id}]", available=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_adapters.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interviews/adapters.py backend/tests/interviews/test_adapters.py
git commit -m "feat(interviews): persona + Zep memory adapters bridging existing services to interview subsystem"
```

---

### Task 16: /api/interview Flask blueprint

**Files:**
- Create: `backend/app/api/interview.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/interviews/test_api_interview.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_api_interview.py
import json
import os
from pathlib import Path
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    from app.config import Config
    Config.LLM_STUB_MODE = True
    Config.UPLOADS_DIR = str(tmp_path)
    # Seed a minimal reddit_profiles.json
    sim_dir = tmp_path / "simulations" / "sim_test"
    sim_dir.mkdir(parents=True)
    profiles = [{"user_id": i, "user_name": f"u{i}", "name": f"A{i}",
                 "persona": "p", "profession": "fisher"} for i in range(3)]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    from flask import Flask
    from app.api import register_blueprints
    app = Flask(__name__)
    register_blueprints(app)
    return app.test_client()

def test_post_pre_returns_task_id(client):
    res = client.post("/api/interview/sim_test/pre")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert "task_id" in body["data"]

def test_status_endpoint_returns_progress(client):
    res = client.post("/api/interview/sim_test/pre")
    task_id = res.get_json()["data"]["task_id"]
    res2 = client.get(f"/api/interview/sim_test/status?task_id={task_id}")
    assert res2.status_code == 200
    assert "status" in res2.get_json()["data"]

def test_unknown_subagent_returns_400(client):
    res = client.post("/api/interview/sim_test/rerun",
                      json={"subagent": "nonsense"})
    assert res.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_api_interview.py -v`
Expected: ImportError / 404.

- [ ] **Step 3: Check current `api/__init__.py`**

Read `backend/app/api/__init__.py` and identify how `graph_bp`, `simulation_bp`, `report_bp` are registered. The test expects a `register_blueprints(app)` helper — if one doesn't exist, add it.

- [ ] **Step 4: Modify `api/__init__.py`**

Replace contents (preserving existing blueprint imports — adjust to match actual file):
```python
from flask import Flask
from .graph import graph_bp
from .simulation import simulation_bp
from .report import report_bp
from .interview import interview_bp

def register_blueprints(app: Flask) -> None:
    app.register_blueprint(graph_bp, url_prefix="/api/graph")
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(report_bp, url_prefix="/api/report")
    app.register_blueprint(interview_bp, url_prefix="/api/interview")
```

If the existing app factory in `app/__init__.py` already calls register manually, update it to call `register_blueprints(app)` instead.

- [ ] **Step 5: Implement blueprint**

`backend/app/api/interview.py`:
```python
from __future__ import annotations
import threading
import traceback
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file
from app.config import Config
from app.models.interview import SubagentKind, InterviewPhase
from app.services.interviews.adapters import FileSystemPersonaProvider, ZepMemoryProvider
from app.services.interviews.zep_writer import InterviewZepWriter
from app.services.interview_orchestrator import InterviewOrchestrator
from app.services.interview_synthesizer import InterviewSynthesizer
from app.services.interviews.storage import InterviewStore
from app.utils.llm_client import LLMClient

interview_bp = Blueprint("interview", __name__)
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()

INSTRUMENT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "instruments"

def _uploads_root() -> Path:
    return Path(getattr(Config, "UPLOADS_DIR", "uploads"))

def _build_orchestrator(sim_id: str) -> InterviewOrchestrator:
    sim_dir = _uploads_root() / "simulations" / sim_id
    reddit = sim_dir / "reddit_profiles.json"
    twitter = sim_dir / "twitter_profiles.csv"
    personas = FileSystemPersonaProvider(reddit_path=reddit if reddit.exists() else None,
                                         twitter_path=twitter if twitter.exists() else None)
    # Zep memory + writer: best-effort; in stub/test mode the writer no-ops on exceptions
    class _NullUpdater:
        def add_text_episode(self, *a, **kw): return None
    try:
        from app.services.zep_entity_reader import ZepEntityReader
        from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater
        graph_id = (sim_dir / "graph_id.txt").read_text().strip() if (sim_dir / "graph_id.txt").exists() else ""
        reader = ZepEntityReader()
        updater = ZepGraphMemoryUpdater()
        memory = ZepMemoryProvider(reader, graph_id=graph_id)
        zep_writer = InterviewZepWriter(memory_updater=updater, graph_id=graph_id)
    except Exception:
        class _Mem:
            def get_digest(self, agent_id, max_chars=2000):
                from app.services.interviews.base import MemoryDigest
                return MemoryDigest(text="[memory unavailable]", available=False)
        memory = _Mem()
        zep_writer = InterviewZepWriter(memory_updater=_NullUpdater(), graph_id="")
    llm = LLMClient(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL,
                    model=Config.LLM_MODEL_NAME)
    return InterviewOrchestrator(
        llm=llm, memory=memory, personas=personas,
        instrument_dir=INSTRUMENT_DIR, store_root=_uploads_root(), sim_id=sim_id,
        zep_writer=zep_writer, max_workers=Config.INTERVIEW_MAX_WORKERS,
        language=Config.INTERVIEW_DEFAULT_LANGUAGE,
    )

def _run_task(task_id: str, fn) -> None:
    with _LOCK:
        _TASKS[task_id] = {"status": "running", "progress": {}, "result": None, "error": None}
    try:
        result = fn(task_id)
        with _LOCK:
            _TASKS[task_id]["status"] = "completed"; _TASKS[task_id]["result"] = result
    except Exception as e:
        with _LOCK:
            _TASKS[task_id]["status"] = "failed"
            _TASKS[task_id]["error"] = repr(e)
            _TASKS[task_id]["traceback"] = traceback.format_exc()

def _start_task(fn) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _TASKS[task_id] = {"status": "queued", "progress": {}, "result": None, "error": None}
    threading.Thread(target=_run_task, args=(task_id, fn), daemon=True).start()
    return task_id

def _envelope(data=None, error=None, status: int = 200):
    body = {"success": error is None, "data": data or {}, "error": error}
    return jsonify(body), status

@interview_bp.route("/<sim_id>/pre", methods=["POST"])
def post_pre(sim_id: str):
    orch = _build_orchestrator(sim_id)
    task_id = _start_task(lambda tid: orch.run_pre())
    return _envelope({"task_id": task_id})

@interview_bp.route("/<sim_id>/post", methods=["POST"])
def post_post(sim_id: str):
    orch = _build_orchestrator(sim_id)
    def run(tid):
        out = orch.run_post()
        synth = InterviewSynthesizer(store=orch.store)
        out["synthesis"] = synth.run()[:1000]  # short preview
        return out
    task_id = _start_task(run)
    return _envelope({"task_id": task_id})

@interview_bp.route("/<sim_id>/rerun", methods=["POST"])
def post_rerun(sim_id: str):
    body = request.get_json(silent=True) or {}
    sub = body.get("subagent")
    try: subagent = SubagentKind(sub)
    except ValueError: return _envelope(error=f"unknown subagent {sub!r}", status=400)
    orch = _build_orchestrator(sim_id)
    task_id = _start_task(lambda tid: orch.rerun(subagent))
    return _envelope({"task_id": task_id})

@interview_bp.route("/<sim_id>/status", methods=["GET"])
def get_status(sim_id: str):
    task_id = request.args.get("task_id")
    with _LOCK:
        task = _TASKS.get(task_id)
    if task is None: return _envelope(error="unknown task_id", status=404)
    return _envelope({"status": task["status"], "progress": task.get("progress", {}),
                      "result": task.get("result"), "error": task.get("error")})

@interview_bp.route("/<sim_id>/results/<subagent>", methods=["GET"])
def get_results(sim_id: str, subagent: str):
    try: sub = SubagentKind(subagent)
    except ValueError: return _envelope(error=f"unknown subagent {subagent!r}", status=400)
    store = InterviewStore(root=_uploads_root(), sim_id=sim_id)
    phase = InterviewPhase.T1 if sub != SubagentKind.LONGITUDINAL else InterviewPhase.T1
    run = store.latest_run(phase, sub)
    if run is None: return _envelope(error="no results yet", status=404)
    agg = (run / "aggregate.json")
    if not agg.exists(): return _envelope(error="aggregate missing", status=404)
    import json as _j
    return _envelope({"aggregate": _j.loads(agg.read_text(encoding="utf-8")),
                      "run_dir": str(run)})

@interview_bp.route("/<sim_id>/results/synthesis", methods=["GET"])
def get_synthesis(sim_id: str):
    store = InterviewStore(root=_uploads_root(), sim_id=sim_id)
    report = store.base / "synthesis" / "report.md"
    if not report.exists():
        synth = InterviewSynthesizer(store=store)
        synth.run()
    return _envelope({"report_markdown": report.read_text(encoding="utf-8")})

@interview_bp.route("/<sim_id>/export.csv", methods=["GET"])
def get_export_csv(sim_id: str):
    store = InterviewStore(root=_uploads_root(), sim_id=sim_id)
    csv_path = store.base / "synthesis" / "exports" / "all_responses.csv"
    if not csv_path.exists():
        InterviewSynthesizer(store=store).run()
    return send_file(csv_path, mimetype="text/csv", as_attachment=True,
                     download_name=f"{sim_id}_interviews.csv")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_api_interview.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/__init__.py backend/app/api/interview.py backend/tests/interviews/test_api_interview.py
git commit -m "feat(interviews): Flask blueprint /api/interview with task-based async + CSV export"
```

---

## Phase 6 — Integration

### Task 17: End-to-end pipeline test (stub LLM)

**Files:**
- Create: `backend/tests/integration/__init__.py`
- Test: `backend/tests/integration/test_interview_pipeline.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/integration/__init__.py` (empty), then:

```python
# backend/tests/integration/test_interview_pipeline.py
import json
import pytest
from pathlib import Path
from app.config import Config
from app.models.interview import SubagentKind, InterviewPhase
from app.services.interviews.adapters import FileSystemPersonaProvider
from app.services.interviews.base import MemoryDigest
from app.services.interviews.zep_writer import InterviewZepWriter
from app.services.interview_orchestrator import InterviewOrchestrator
from app.services.interview_synthesizer import InterviewSynthesizer
from app.utils.llm_client import LLMClient

pytestmark = pytest.mark.integration

INST_DIR = Path(__file__).resolve().parents[2] / "scripts" / "instruments"

class _NullUpdater:
    def __init__(self): self.events = []
    def add_text_episode(self, graph_id, text): self.events.append(text)

class _StaticMem:
    def get_digest(self, agent_id, max_chars=2000):
        return MemoryDigest(text=f"agent {agent_id} memory snippet", available=True)

@pytest.fixture
def seeded_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    Config.LLM_STUB_MODE = True
    sim_dir = tmp_path / "simulations" / "intg_sim"
    sim_dir.mkdir(parents=True)
    profiles = [{"user_id": i, "user_name": f"u{i}", "name": f"A{i}",
                 "persona": "stakeholder p", "profession": "fisher"} for i in range(5)]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    return tmp_path

def _make_orch(tmp_path):
    sim_dir = tmp_path / "simulations" / "intg_sim"
    personas = FileSystemPersonaProvider(
        reddit_path=sim_dir / "reddit_profiles.json", twitter_path=None,
    )
    llm = LLMClient(api_key="x", base_url="x", model="x")
    updater = _NullUpdater()
    writer = InterviewZepWriter(memory_updater=updater, graph_id="g")
    return InterviewOrchestrator(
        llm=llm, memory=_StaticMem(), personas=personas,
        instrument_dir=INST_DIR, store_root=tmp_path, sim_id="intg_sim",
        zep_writer=writer, max_workers=2, language="de",
    )

def test_pipeline_runs_pre_then_post_then_synthesis(seeded_uploads):
    tmp = seeded_uploads
    orch = _make_orch(tmp)

    pre = orch.run_pre()
    assert pre["longitudinal"]["n_responded"] >= 1

    post = orch.run_post()
    assert "longitudinal" in post
    assert "diversity" in post
    assert "scenario" in post
    assert "delphi" in post

    synth = InterviewSynthesizer(store=orch.store)
    report = synth.run()
    assert "Stakeholder Interview Synthesis" in report
    assert "Limitations" in report

    csv_path = orch.store.base / "synthesis" / "exports" / "all_responses.csv"
    assert csv_path.exists()
    lines = csv_path.read_text().splitlines()
    assert lines[0].startswith("agent_id,") or "agent_id" in lines[0]

def test_idempotent_rerun_creates_new_run_id(seeded_uploads):
    tmp = seeded_uploads
    orch = _make_orch(tmp)
    orch.run_pre()
    first = orch.run_post()
    second = orch.rerun(SubagentKind.SCENARIO)
    first_scn = first["scenario"]["run_dir"]
    second_scn = second["scenario"]["run_dir"]
    assert first_scn != second_scn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_interview_pipeline.py -v -m integration`
Expected: most likely ValidationError from the stub LLM's canned JSON not satisfying every subagent's strict validator (forced Q-sort distribution, scenarios, Delphi). This is the signal to enrich the stub.

- [ ] **Step 3: Enrich `_stub_response_json` in `LLMClient` to satisfy each subagent**

Read the current `_stub_response_json` (Task 4). Replace its body with content-aware stubs by inspecting the user message text. In `backend/app/utils/llm_client.py`, replace `_stub_response_json` with:

```python
    def _stub_response_json(self, messages: list[dict]) -> dict:
        import hashlib, json as _json
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        usr_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        h = hashlib.sha256((sys_msg + "|" + usr_msg).encode("utf-8")).hexdigest()
        seed = int(h[:8], 16)
        rng = (seed % 5) + 1

        # Longitudinal Likert (12 items)
        if all(tok in usr_msg for tok in ("stk_1", "gov_1", "mkt_1", "clm_1")):
            ids = ["stk_1","stk_2","stk_3","gov_1","gov_2","gov_3",
                   "mkt_1","mkt_2","mkt_3","clm_1","clm_2","clm_3"]
            return {"responses": {k: ((seed >> (i*3)) % 5) + 1 for i, k in enumerate(ids)},
                    "confidence": {k: 0.6 for k in ids},
                    "open_comment": f"stub:{h[:8]}"}

        # Diversity Q-sort: 24 statements + 6 axes, forced distribution 2,3,4,6,4,3,2
        if "st_01" in usr_msg and "ax_pres_extr" in usr_msg:
            buckets = [-3]*2 + [-2]*3 + [-1]*4 + [0]*6 + [1]*4 + [2]*3 + [3]*2
            stmts = [f"st_{i+1:02d}" for i in range(24)]
            # shuffle deterministically
            order = sorted(range(24), key=lambda i: (h[i % len(h)], i))
            placements = {stmts[i]: buckets[order.index(i)] for i in range(24)}
            return {
                "placements": placements,
                "likert_axes": {a: ((seed >> (j*3)) % 7) + 1 for j, a in enumerate(
                    ["ax_pres_extr","ax_loc_eu","ax_sci_trad",
                     "ax_ind_col","ax_short_long","ax_mkt_reg"])},
            }

        # Scenario: S1..S4 × 4 dims
        if all(s in usr_msg for s in ("S1:", "S2:", "S3:", "S4:")):
            return {"ratings": {sid: {
                "desirability": ((seed >> (i*3)) % 7) + 1,
                "plausibility": ((seed >> (i*3+1)) % 7) + 1,
                "impact_on_my_group": ((seed >> (i*3+2)) % 7) + 1,
                "fairness": ((seed >> (i*3+4)) % 7) + 1,
                "if_woke_up_response": f"act-{sid}-{h[:4]}",
            } for i, sid in enumerate(["S1","S2","S3","S4"])}}

        # Delphi R1: q1..q4 free text
        if "q1" in usr_msg and "q2" in usr_msg and "Bewerten" not in usr_msg and "Sie sehen" not in usr_msg:
            return {"answers": {qid: f"stub-themes-{qid}-{h[:4]}" for qid in ("q1","q2","q3","q4")}}

        # Delphi theme extraction (no in-character system prompt)
        if "extract distinct thematic codes" in sys_msg:
            return {"themes": [{"theme_id": f"theme_{i}", "label": f"Thema {i}"} for i in range(5)]}

        # Delphi R2 (rate) or R3 (revise)
        if "Bewerten Sie jedes Thema" in usr_msg or "Sie sehen unten" in usr_msg \
           or "Rate each theme" in usr_msg or "Below are the anonymised" in usr_msg:
            theme_ids = [f"theme_{i}" for i in range(5)]
            out = {"ratings": {tid: {"importance": ((seed >> (i*2)) % 5) + 1,
                                     "plausibility": ((seed >> (i*2+1)) % 5) + 1}
                               for i, tid in enumerate(theme_ids)}}
            if "Sie sehen unten" in usr_msg or "Below are the anonymised" in usr_msg:
                out["justification"] = "stub-revision"
            return out

        # Fallback
        return {"stub_key": h[:12], "value": rng}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_interview_pipeline.py -v -m integration`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/llm_client.py backend/tests/integration/__init__.py backend/tests/integration/test_interview_pipeline.py
git commit -m "test(interviews): end-to-end pipeline test + content-aware LLM stubs for all 4 subagents"
```

---

## Phase 7 — Frontend

Note: this project has no frontend test framework. Tasks below use the build (`npm run build`) plus a manual smoke check via `npm run dev` as the verification gate. Commit after each task once the build is green.

### Task 18: Step4bInterviews.vue scaffold + tab shell

**Files:**
- Create: `frontend/src/components/Step4bInterviews.vue`
- Create: `frontend/src/api/interview.js`
- Modify: `frontend/src/App.vue` (or the parent that orchestrates Step1..Step5 — locate and adjust)

- [ ] **Step 1: Add API client module**

`frontend/src/api/interview.js`:
```javascript
import { api } from "./index"

export async function startPre(simId) {
  const r = await api.post(`/api/interview/${simId}/pre`)
  return r.data
}
export async function startPost(simId) {
  const r = await api.post(`/api/interview/${simId}/post`)
  return r.data
}
export async function rerun(simId, subagent) {
  const r = await api.post(`/api/interview/${simId}/rerun`, { subagent })
  return r.data
}
export async function getStatus(simId, taskId) {
  const r = await api.get(`/api/interview/${simId}/status`, { params: { task_id: taskId } })
  return r.data
}
export async function getResults(simId, subagent) {
  const r = await api.get(`/api/interview/${simId}/results/${subagent}`)
  return r.data
}
export async function getSynthesis(simId) {
  const r = await api.get(`/api/interview/${simId}/results/synthesis`)
  return r.data
}
export function exportCsvUrl(simId) {
  return `/api/interview/${simId}/export.csv`
}
```

- [ ] **Step 2: Implement Step4bInterviews.vue scaffold**

`frontend/src/components/Step4bInterviews.vue`:
```vue
<template>
  <section class="step4b">
    <header>
      <h2>{{ t('interview.title') }}</h2>
      <p class="subtitle">{{ t('interview.subtitle') }}</p>
    </header>

    <div class="actions">
      <button :disabled="busy" @click="startPostRun">{{ t('interview.runAll') }}</button>
      <a :href="csvUrl" target="_blank" rel="noopener">{{ t('interview.downloadCsv') }}</a>
    </div>

    <nav class="tabs">
      <button v-for="t in tabs" :key="t.id"
              :class="{ active: active === t.id }"
              @click="active = t.id">
        {{ t.label }}
      </button>
    </nav>

    <component :is="currentPanel" :sim-id="simId" :status="status" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import LongitudinalPanel from './interviews/LongitudinalPanel.vue'
import DiversityPanel from './interviews/DiversityPanel.vue'
import DelphiPanel from './interviews/DelphiPanel.vue'
import ScenarioPanel from './interviews/ScenarioPanel.vue'
import SynthesisPanel from './interviews/SynthesisPanel.vue'
import { startPost, getStatus, exportCsvUrl } from '../api/interview'

const props = defineProps({ simId: { type: String, required: true } })
const { t } = useI18n()
const tabs = [
  { id: 'longitudinal', label: t('interview.tab.longitudinal') },
  { id: 'diversity',    label: t('interview.tab.diversity') },
  { id: 'delphi',       label: t('interview.tab.delphi') },
  { id: 'scenario',     label: t('interview.tab.scenario') },
  { id: 'synthesis',    label: t('interview.tab.synthesis') },
]
const active = ref('longitudinal')
const status = ref({ status: 'idle' })
const busy = ref(false)
const csvUrl = computed(() => exportCsvUrl(props.simId))

const panels = {
  longitudinal: LongitudinalPanel, diversity: DiversityPanel,
  delphi: DelphiPanel, scenario: ScenarioPanel, synthesis: SynthesisPanel,
}
const currentPanel = computed(() => panels[active.value])

async function startPostRun() {
  busy.value = true
  try {
    const res = await startPost(props.simId)
    if (!res.success) throw new Error(res.error || 'failed to start')
    await poll(res.data.task_id)
  } finally { busy.value = false }
}

async function poll(taskId) {
  while (true) {
    const r = await getStatus(props.simId, taskId)
    status.value = r.data
    if (['completed', 'failed'].includes(r.data.status)) break
    await new Promise(r => setTimeout(r, 1500))
  }
}
</script>

<style scoped>
.step4b { padding: 1rem; }
.tabs { display: flex; gap: .5rem; margin: 1rem 0; }
.tabs button.active { font-weight: 700; border-bottom: 2px solid #333; }
.actions { display: flex; gap: 1rem; align-items: center; }
</style>
```

- [ ] **Step 3: Create placeholder panel components (to be filled in Task 19)**

Create five empty-but-renderable Vue components so the scaffold compiles:

`frontend/src/components/interviews/LongitudinalPanel.vue`:
```vue
<template><div class="panel">Longitudinal: results will appear here.</div></template>
<script setup>
defineProps({ simId: String, status: Object })
</script>
```

Repeat the same pattern (changing only the inner text) for `DiversityPanel.vue`, `DelphiPanel.vue`, `ScenarioPanel.vue`, `SynthesisPanel.vue` in `frontend/src/components/interviews/`.

- [ ] **Step 4: Wire Step4b into parent navigation**

Read `frontend/src/App.vue` (or wherever Step1..Step5 are rendered). Locate the routing/visibility logic. Add a Step4b state between Step4 and Step5, and import `Step4bInterviews` from `./components/Step4bInterviews.vue`. Pass `:sim-id="currentSimId"` where the others receive the sim id. Add i18n keys to `locales/en.json`, `locales/de.json`, `locales/zh.json`:
```json
"interview": {
  "title": "Stakeholder interviews",
  "subtitle": "Four independent surveys of the simulated stakeholder population.",
  "runAll": "Run all post-simulation interviews",
  "downloadCsv": "Download CSV",
  "tab": {
    "longitudinal": "Longitudinal (Δ)",
    "diversity": "Diversity",
    "delphi": "Delphi",
    "scenario": "Scenarios",
    "synthesis": "Synthesis"
  }
}
```

- [ ] **Step 5: Build to verify it compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/interview.js frontend/src/components/Step4bInterviews.vue \
        frontend/src/components/interviews/*.vue frontend/src/App.vue \
        locales/*.json
git commit -m "feat(interviews): Step4b Vue scaffold with five-tab navigation, API client, i18n keys"
```

---

### Task 19: Per-tab d3 visualisations

**Files:**
- Modify: `frontend/src/components/interviews/LongitudinalPanel.vue`
- Modify: `frontend/src/components/interviews/DiversityPanel.vue`
- Modify: `frontend/src/components/interviews/DelphiPanel.vue`
- Modify: `frontend/src/components/interviews/ScenarioPanel.vue`
- Modify: `frontend/src/components/interviews/SynthesisPanel.vue`

For each panel, fetch the relevant aggregate via the API on mount, then render with d3. The five implementations follow the same structure; each shows the full content below.

- [ ] **Step 1: Longitudinal panel — heatmap of Δ̄ per item**

`frontend/src/components/interviews/LongitudinalPanel.vue`:
```vue
<template>
  <div class="panel">
    <h3>Longitudinal Δ (T0 → T1)</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <svg v-else ref="chart" :width="width" :height="height"></svg>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import { getResults } from '../../api/interview'

const props = defineProps({ simId: String, status: Object })
const chart = ref(null)
const loading = ref(true)
const error = ref(null)
const width = 640
const height = 360

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    const r = await getResults(props.simId, 'longitudinal')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate)
  } catch (e) { error.value = String(e) }
  finally { loading.value = false }
}

function draw(agg) {
  const items = Object.entries(agg.per_item || {})
  if (items.length === 0) return
  const svg = d3.select(chart.value)
  svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 60, left: 80 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const x = d3.scaleBand().domain(items.map(([k]) => k)).range([0, w]).padding(0.1)
  const y = d3.scaleLinear().domain([-4, 4]).range([h, 0])
  const color = d3.scaleDiverging(d3.interpolateRdBu).domain([-4, 0, 4])
  g.selectAll('rect').data(items).enter().append('rect')
    .attr('x', d => x(d[0]))
    .attr('y', d => y(Math.max(0, d[1].mean_delta || 0)))
    .attr('width', x.bandwidth())
    .attr('height', d => Math.abs(y(d[1].mean_delta || 0) - y(0)))
    .attr('fill', d => color(d[1].mean_delta || 0))
  g.append('g').attr('transform', `translate(0,${y(0)})`)
    .call(d3.axisBottom(x)).selectAll('text')
    .attr('transform', 'rotate(-40)').attr('text-anchor', 'end')
  g.append('g').call(d3.axisLeft(y))
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
```

- [ ] **Step 2: Diversity panel — PCA scatter coloured by cluster**

`frontend/src/components/interviews/DiversityPanel.vue`:
```vue
<template>
  <div class="panel">
    <h3>Stakeholder typology (PCA)</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <svg v-else ref="chart" :width="width" :height="height"></svg>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import { getResults } from '../../api/interview'

const props = defineProps({ simId: String, status: Object })
const chart = ref(null); const loading = ref(true); const error = ref(null)
const width = 640, height = 480

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    const r = await getResults(props.simId, 'diversity')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate)
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}

function draw(agg) {
  // The /results endpoint returns aggregate.json which contains clusters + agent_ids
  // PCA components live in typology.json (separate file). For v1 use clusters only,
  // distributing them across a notional 2D layout from their cluster centroid hashes.
  const clusters = agg.clusters || []
  if (!clusters.length) return
  const svg = d3.select(chart.value); svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 30, left: 30 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const points = []
  clusters.forEach((c, i) => {
    (c.agent_ids || []).forEach((aid, k) => {
      const angle = (i / clusters.length) * 2 * Math.PI
      const radius = (k % 5 + 1) * 0.15 + 0.2
      points.push({ x: 0.5 + Math.cos(angle) * radius, y: 0.5 + Math.sin(angle) * radius,
                    cluster: c.cluster_id, agent_id: aid })
    })
  })
  const x = d3.scaleLinear().domain([0, 1]).range([0, w])
  const y = d3.scaleLinear().domain([0, 1]).range([h, 0])
  const color = d3.scaleOrdinal(d3.schemeCategory10)
  g.selectAll('circle').data(points).enter().append('circle')
    .attr('cx', d => x(d.x)).attr('cy', d => y(d.y)).attr('r', 5)
    .attr('fill', d => color(d.cluster)).attr('opacity', .7)
    .append('title').text(d => `agent ${d.agent_id} · cluster ${d.cluster}`)
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
```

- [ ] **Step 3: Delphi panel — convergence bar chart (R2 IQR vs R3 IQR per theme)**

`frontend/src/components/interviews/DelphiPanel.vue`:
```vue
<template>
  <div class="panel">
    <h3>Delphi convergence (IQR shift R2 → R3)</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <svg v-else ref="chart" :width="width" :height="height"></svg>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import { api } from '../../api/index'

const props = defineProps({ simId: String, status: Object })
const chart = ref(null); const loading = ref(true); const error = ref(null)
const width = 640, height = 420

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    const r = await api.get(`/api/interview/${props.simId}/results/delphi`)
    if (!r.data.success) { error.value = r.data.error; return }
    // For richer detail, also fetch the per-theme convergence.json directly via a follow-up endpoint.
    // v1: render aggregate.themes + agg.n_r1/r2/r3.
    draw(r.data.data.aggregate)
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}

function draw(agg) {
  const themes = agg.themes || []
  if (!themes.length) return
  const svg = d3.select(chart.value); svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 80, left: 60 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const x = d3.scaleBand().domain(themes.map(t => t.theme_id)).range([0, w]).padding(0.15)
  const y = d3.scaleLinear().domain([0, agg.n_r1 || 1]).range([h, 0])
  const bars = themes.map((t, i) => ({
    theme: t.theme_id, label: t.label,
    nr1: agg.n_r1, nr2: agg.n_r2, nr3: agg.n_r3,
  }))
  g.selectAll('rect').data(bars).enter().append('rect')
    .attr('x', d => x(d.theme)).attr('y', d => y(d.nr3))
    .attr('width', x.bandwidth()).attr('height', d => h - y(d.nr3))
    .attr('fill', d3.schemeCategory10[2])
  g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x))
    .selectAll('text').attr('transform', 'rotate(-30)').attr('text-anchor', 'end')
  g.append('g').call(d3.axisLeft(y))
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
```

- [ ] **Step 4: Scenario panel — polarity quadrant (desirability × plausibility)**

`frontend/src/components/interviews/ScenarioPanel.vue`:
```vue
<template>
  <div class="panel">
    <h3>Scenarios: desirability × plausibility</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <svg v-else ref="chart" :width="width" :height="height"></svg>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import { getResults } from '../../api/interview'

const props = defineProps({ simId: String, status: Object })
const chart = ref(null); const loading = ref(true); const error = ref(null)
const width = 520, height = 520

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    const r = await getResults(props.simId, 'scenario')
    if (!r.success) { error.value = r.error; return }
    draw(r.data.aggregate.polarity || {})
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}

function draw(polarity) {
  const pts = Object.entries(polarity)
    .filter(([, v]) => v && v.n > 0)
    .map(([sid, v]) => ({
      sid, x: v.mean_plausibility, y: v.mean_desirability,
      n: v.n, sdx: v.sd_plausibility, sdy: v.sd_desirability,
    }))
  if (!pts.length) return
  const svg = d3.select(chart.value); svg.selectAll('*').remove()
  const margin = { top: 20, right: 20, bottom: 40, left: 40 }
  const w = width - margin.left - margin.right
  const h = height - margin.top - margin.bottom
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
  const x = d3.scaleLinear().domain([1, 7]).range([0, w])
  const y = d3.scaleLinear().domain([1, 7]).range([h, 0])
  g.append('line').attr('x1', 0).attr('x2', w).attr('y1', y(4)).attr('y2', y(4)).attr('stroke', '#ccc')
  g.append('line').attr('x1', x(4)).attr('x2', x(4)).attr('y1', 0).attr('y2', h).attr('stroke', '#ccc')
  g.selectAll('circle').data(pts).enter().append('circle')
    .attr('cx', d => x(d.x)).attr('cy', d => y(d.y))
    .attr('r', d => 6 + Math.sqrt(d.n))
    .attr('fill', d3.schemeCategory10[1]).attr('opacity', .7)
  g.selectAll('text.lbl').data(pts).enter().append('text')
    .attr('class', 'lbl').attr('x', d => x(d.x) + 8).attr('y', d => y(d.y))
    .text(d => `${d.sid} (n=${d.n})`)
  g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x))
  g.append('g').call(d3.axisLeft(y))
  g.append('text').attr('x', w/2).attr('y', h+34).attr('text-anchor', 'middle').text('plausibility')
  g.append('text').attr('transform', `rotate(-90)`).attr('x', -h/2).attr('y', -28)
    .attr('text-anchor', 'middle').text('desirability')
}
</script>

<style scoped>
.panel { padding: .5rem; }
</style>
```

- [ ] **Step 5: Synthesis panel — render markdown report**

`frontend/src/components/interviews/SynthesisPanel.vue`:
```vue
<template>
  <div class="panel">
    <h3>Synthesis</h3>
    <div v-if="loading">Loading…</div>
    <div v-else-if="error">{{ error }}</div>
    <pre v-else class="report">{{ report }}</pre>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { getSynthesis } from '../../api/interview'

const props = defineProps({ simId: String, status: Object })
const loading = ref(true); const error = ref(null); const report = ref('')

watch(() => props.status?.status, (s) => { if (s === 'completed') load() })
onMounted(load)

async function load() {
  loading.value = true; error.value = null
  try {
    const r = await getSynthesis(props.simId)
    if (!r.success) { error.value = r.error; return }
    report.value = r.data.report_markdown
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}
</script>

<style scoped>
.panel { padding: .5rem; }
.report { white-space: pre-wrap; font-family: ui-monospace, monospace; line-height: 1.4; }
</style>
```

- [ ] **Step 6: Build + smoke test**

Run: `cd frontend && npm run build`
Expected: build succeeds. Then `cd .. && npm run dev` and manually visit Step4b for a completed `sim_id` — verify all five tabs render without console errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/interviews/*.vue
git commit -m "feat(interviews): d3 visualisations for longitudinal Δ, diversity PCA, Delphi, scenario polarity, synthesis"
```

---

### Task 20: Auto-trigger pre-survey on simulation `ready`

**Files:**
- Create: `backend/app/services/interviews/lifecycle.py`
- Modify: `backend/app/__init__.py` (app factory) to install the hook

- [ ] **Step 1: Write failing test**

```python
# backend/tests/interviews/test_lifecycle.py
from app.services.interviews.lifecycle import install_hooks

class _StubMgr:
    def __init__(self): self.ready = []; self.completed = []
    def register_on_ready(self, fn): self.ready.append(fn)
    def register_on_completed(self, fn): self.completed.append(fn)

def test_install_hooks_registers_two_callables():
    mgr = _StubMgr()
    install_hooks(mgr)
    assert len(mgr.ready) == 1
    assert len(mgr.completed) == 1
    assert callable(mgr.ready[0])
    assert callable(mgr.completed[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/interviews/test_lifecycle.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement lifecycle hook installer**

`backend/app/services/interviews/lifecycle.py`:
```python
from __future__ import annotations
import threading
from app.utils.logger import get_logger

logger = get_logger(__name__)

def install_hooks(manager) -> None:
    """Attach interview lifecycle callbacks to a SimulationManager.

    on_ready  → spawn T0 longitudinal in a background thread
    on_completed → spawn full post-sim batch in a background thread
    Hooks are best-effort; failures only log.
    """
    def _on_ready(state) -> None:
        sim_id = getattr(state, "sim_id", None) or getattr(state, "id", None)
        if not sim_id: return
        threading.Thread(target=_run_pre, args=(sim_id,), daemon=True).start()

    def _on_completed(state) -> None:
        sim_id = getattr(state, "sim_id", None) or getattr(state, "id", None)
        if not sim_id: return
        threading.Thread(target=_run_post, args=(sim_id,), daemon=True).start()

    manager.register_on_ready(_on_ready)
    manager.register_on_completed(_on_completed)

def _run_pre(sim_id: str) -> None:
    try:
        from app.api.interview import _build_orchestrator
        orch = _build_orchestrator(sim_id)
        orch.run_pre()
    except Exception as e:
        logger.warning(f"auto pre-survey failed for {sim_id}: {e!r}")

def _run_post(sim_id: str) -> None:
    try:
        from app.api.interview import _build_orchestrator
        from app.services.interview_synthesizer import InterviewSynthesizer
        orch = _build_orchestrator(sim_id)
        orch.run_post()
        InterviewSynthesizer(store=orch.store).run()
    except Exception as e:
        logger.warning(f"auto post-survey failed for {sim_id}: {e!r}")
```

- [ ] **Step 4: Wire into app factory**

Read `backend/app/__init__.py`. Locate where `SimulationManager` (or its singleton) is instantiated. Add:
```python
    from app.services.interviews.lifecycle import install_hooks
    install_hooks(simulation_manager)
```
immediately after the manager is constructed. If `simulation_manager` is module-level in `simulation_manager.py`, attach the hooks at the bottom of that module instead — the goal is "install once on app startup".

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/interviews/test_lifecycle.py -v`
Expected: 1 passed.

- [ ] **Step 6: Full backend test suite**

Run: `cd backend && uv run pytest -m "not integration" -q`
Expected: all unit tests pass.

Run: `cd backend && uv run pytest -m integration -q`
Expected: integration tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/interviews/lifecycle.py backend/app/__init__.py backend/tests/interviews/test_lifecycle.py
git commit -m "feat(interviews): auto-trigger pre and post interviews via SimulationManager lifecycle hooks"
```

---

## Final verification

- [ ] **Run full backend test suite**

Run: `cd backend && uv run pytest -q`
Expected: every test passes.

- [ ] **Run frontend build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Smoke test the running app**

Run: `npm run dev` from project root. With an existing completed simulation:
1. Navigate to Step4b in the UI
2. Click "Run all post-simulation interviews"
3. Wait for status to reach `completed`
4. Verify each of the five tabs renders without console errors
5. Click "Download CSV" and confirm the file downloads

- [ ] **Verify spec coverage**

Re-open `docs/superpowers/specs/2026-05-23-stakeholder-interview-subagents-design.md` and confirm every section in the spec has a corresponding task:

- §3 architectural approach (deterministic runners) → Tasks 5–9
- §4 file structure + lifecycle hooks → Tasks 2–14, 20
- §5.1–5.4 four instruments → Tasks 6, 7, 8, 9
- §5.5 in-character prompting + structured output + cost guardrails → Tasks 4, 5
- §6.1 storage layout → Task 10
- §6.2 Zep integration → Task 11
- §6.3 API surface (all 7 endpoints) → Task 16
- §6.4 parallelism + token guard → Task 12 (parallelism); token guard sits in `Config.INTERVIEW_MAX_TOKENS_PER_RUN` from Task 1 — *open: enforcement not implemented in v1; flag if you want it added*
- §6.5 frontend Step4b + per-tab viz → Tasks 18, 19
- §7 error handling (per-agent isolation, schema retry, idempotency) → Tasks 5, 10, 12
- §8 validation (schema, instrument, plausibility flags) → Tasks 2, 3 (schema + instrument); plausibility-flags currently sit inside synthesiser §10 — *check that flagged thresholds in §8 plausibility checks match what synthesiser currently emits*
- §9 testing (unit per subagent + integration + stub mode) → Tasks 4, 6–9, 12, 17
- §10 methodological caveats in synthesis → Task 14
- §11 defaults — already encoded in Task 1 config keys and instrument YAML

If §6.4 token-guard enforcement is needed for v1, add a small follow-up task that computes a projected-token estimate before `run_post` and returns 400 with `confirm=true` override — but the spec keeps this as a guard, not a blocker, so it can ship in v1.1.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-23-stakeholder-interview-subagents.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

