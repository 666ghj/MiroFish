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


def test_diversity_accepts_string_likert_values():
    """Diversity placements + axes should accept stringified ints."""
    from app.services.interviews.base import PersonaRecord, MemoryDigest
    from app.services.interviews.diversity import DiversitySubagent
    from pathlib import Path as _P

    class _Mem:
        def get_digest(self, agent_id, max_chars=2000):
            return MemoryDigest(text="x", available=True)

    buckets = [-3]*2 + [-2]*3 + [-1]*4 + [0]*6 + [1]*4 + [2]*3 + [3]*2

    class _StringLLM:
        def chat_json(self, messages, temperature=0.0, max_tokens=None, **kw):
            return {
                "placements": {f"st_{i+1:02d}": str(buckets[i]) for i in range(24)},
                "likert_axes": {a: "4" for a in (
                    "ax_pres_extr","ax_loc_eu","ax_sci_trad",
                    "ax_ind_col","ax_short_long","ax_mkt_reg")},
            }

    inst = _P(__file__).resolve().parents[2] / "scripts" / "instruments" / "diversity_v1.yaml"
    sub = DiversitySubagent(llm=_StringLLM(), memory=_Mem(), instrument_path=inst)
    persona = PersonaRecord(agent_id=7, name="A", persona="p")
    resp = sub.administer(persona)
    assert isinstance(resp.placements["st_01"], int)
    assert isinstance(resp.likert_axes["ax_pres_extr"], int)
    assert resp.likert_axes["ax_pres_extr"] == 4
