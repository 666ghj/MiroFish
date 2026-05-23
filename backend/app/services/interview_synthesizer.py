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
        if run is None:
            return None
        agg = run / "aggregate.json"
        if not agg.exists():
            return None
        return {"run_dir": str(run), "aggregate": json.loads(agg.read_text(encoding="utf-8"))}

    def _instrument_hashes(self) -> dict:
        snap = self.store.base / "instruments_used.json"
        if not snap.exists():
            return {}
        try:
            data = json.loads(snap.read_text(encoding="utf-8"))
        except Exception:
            return {}
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
                if v.get("n", 0) == 0:
                    continue
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
                if run is None:
                    continue
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
            for r in rows:
                w.writerow(r)

    def _flatten(self, rec: dict, *, phase: str, subagent: str) -> list[dict]:
        out: list[dict] = []
        aid = rec.get("agent_id")
        for key, val in rec.items():
            if key == "agent_id":
                continue
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
