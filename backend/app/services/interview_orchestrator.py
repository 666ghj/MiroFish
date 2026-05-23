from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol
from app.models.interview import (
    InterviewPhase, SubagentKind, LikertResponse, QSortResponse,
    DelphiOpenResponse, DelphiRatingResponse, ScenarioResponse,
)
from app.services.interviews.base import PersonaRecord, SchemaValidationFailure
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
                except SchemaValidationFailure as e:
                    failed.append(p.agent_id)
                    self.store.audit(run_dir, agent_id=p.agent_id,
                                     event="schema_validation_failure",
                                     detail={"label": audit_label, "attempts": e.attempts})
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
