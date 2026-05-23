from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
import numpy as np
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import yaml
from app.models.interview import QSortResponse
from app.services.interviews.base import StakeholderInterviewer, PersonaRecord, coerce_int
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
        if not isinstance(raw, dict):
            return None
        placements = raw.get("placements", {})
        axes = raw.get("likert_axes", {})
        statements = {s["statement_id"] for s in self.instrument["statements"]}
        if set(placements.keys()) != statements:
            return None
        dist = self.instrument["distribution"]
        target = {b: n for b, n in zip(range(-3, 4), dist)}
        got: dict[int, int] = {}
        coerced_p: dict[str, int] = {}
        for k, v in placements.items():
            iv = coerce_int(v)
            if iv is None or not -3 <= iv <= 3:
                return None
            coerced_p[k] = iv
            got[iv] = got.get(iv, 0) + 1
        if got != target:
            return None
        coerced_a: dict[str, int] = {}
        for a in self.instrument["likert_axes"]:
            iv = coerce_int(axes.get(a["axis_id"]))
            if iv is None or not 1 <= iv <= 7:
                return None
            coerced_a[a["axis_id"]] = iv
        raw["placements"] = coerced_p
        raw["likert_axes"] = coerced_a
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
