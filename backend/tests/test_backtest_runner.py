"""
历史回测（Historical Backtesting）测试

覆盖 app/services/backtest_runner.py：
- create_backtest 的输入校验（source 二选一、来源必须存在且已成功完成、
  prediction 字段类型/范围校验）
- record_ground_truth：一次性、不可变、必须与 prediction 有可比较字段
- 单 case 指标计算：event_occurrence/brier、direction、sentiment、
  distribution_distance——只计算双方都提供了的字段
- 套件级聚合：direction/sentiment/occurrence 命中率、calibration error
  （expected calibration error）、rank correlation（Spearman），样本不足
  时诚实返回 None 而不是编造数字
"""

import json
import os

import pytest

from app.services.backtest_runner import BacktestCase, BacktestRunner
from app.services.ensemble_runner import EnsembleRecord, EnsembleMemberRecord, EnsembleRunner
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState
from app.utils.state_machine import atomic_write_json


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    simulations_dir = tmp_path / "simulations"
    ensembles_dir = tmp_path / "ensembles"
    backtests_dir = tmp_path / "backtests"
    simulations_dir.mkdir()

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations_dir))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(simulations_dir))
    monkeypatch.setattr(EnsembleRunner, "ENSEMBLE_DATA_DIR", str(ensembles_dir))
    monkeypatch.setattr(BacktestRunner, "BACKTEST_DATA_DIR", str(backtests_dir))

    monkeypatch.setattr(SimulationRunner, "_run_states", {})

    yield


def _make_completed_simulation(
    simulation_id="sim_source12345",
    owner_id="user-1",
    project_id="proj_test1234",
):
    manager = SimulationManager()
    state = SimulationState(
        simulation_id=simulation_id,
        project_id=project_id,
        graph_id="graph-test-1",
        status=SimulationStatus.COMPLETED,
        profiles_generated=True,
        config_generated=True,
        owner_id=owner_id,
    )
    manager._save_simulation_state(state)
    SimulationRunner._save_run_state(
        SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.COMPLETED)
    )
    return state


def _make_running_simulation(simulation_id="sim_running1234", owner_id="user-1"):
    manager = SimulationManager()
    state = SimulationState(
        simulation_id=simulation_id,
        project_id="proj_test1234",
        graph_id="graph-test-1",
        status=SimulationStatus.RUNNING,
        owner_id=owner_id,
    )
    manager._save_simulation_state(state)
    SimulationRunner._save_run_state(
        SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.RUNNING)
    )
    return state


def _make_completed_ensemble(
    ensemble_id="ens_source1234",
    owner_id="user-1",
    project_id="proj_test1234",
    member_count=2,
    member_statuses=None,
):
    """Constructed by hand (bypassing the launch machinery) since these
    tests only need a *completed* ensemble to reference as a backtest
    source, not the launch/aggregation behavior itself (covered in
    test_ensemble_runner.py). member_statuses, if given, is a list of
    RunnerStatus values (one per member index) overriding the default
    COMPLETED for that member."""
    _RUNNER_TO_SIMULATION_STATUS = {
        RunnerStatus.COMPLETED: SimulationStatus.COMPLETED,
        RunnerStatus.RUNNING: SimulationStatus.RUNNING,
        RunnerStatus.FAILED: SimulationStatus.FAILED,
        RunnerStatus.STOPPED: SimulationStatus.STOPPED,
    }
    manager = SimulationManager()
    members = []
    for index in range(member_count):
        member_id = f"{ensemble_id}_m{index}"
        status = (
            member_statuses[index]
            if member_statuses and index < len(member_statuses)
            else RunnerStatus.COMPLETED
        )
        SimulationRunner._save_run_state(
            SimulationRunState(simulation_id=member_id, runner_status=status)
        )
        manager._save_simulation_state(SimulationState(
            simulation_id=member_id,
            project_id=project_id,
            graph_id="graph-test-1",
            status=_RUNNER_TO_SIMULATION_STATUS.get(status, SimulationStatus.CREATED),
        ))
        members.append(EnsembleMemberRecord(simulation_id=member_id, index=index))

    record = EnsembleRecord(
        ensemble_id=ensemble_id,
        source_simulation_id="sim_source12345",
        project_id=project_id,
        graph_id="graph-test-1",
        platform="reddit",
        max_rounds=None,
        run_count=member_count,
        members=members,
        created_at="2024-01-01T00:00:00",
        owner_id=owner_id,
    )
    atomic_write_json(EnsembleRunner._ensemble_path(ensemble_id), record.to_dict())
    return record


class TestCreateBacktestValidation:
    def test_neither_source_provided_rejected(self):
        with pytest.raises(ValueError, match="source_simulation_id"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
            )

    def test_both_sources_provided_rejected(self):
        _make_completed_simulation()
        _make_completed_ensemble()
        with pytest.raises(ValueError, match="source_simulation_id"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
                source_ensemble_id="ens_source1234",
            )

    def test_empty_string_simulation_id_treated_as_absent_uses_ensemble(self):
        # An empty-string source_simulation_id alongside a real
        # source_ensemble_id must resolve to "use the ensemble", not be
        # treated as a present-but-invalid simulation id (which would
        # incorrectly reject a perfectly valid request).
        _make_completed_ensemble()
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_simulation_id="",
            source_ensemble_id="ens_source1234",
        )
        assert case.source_ensemble_id == "ens_source1234"
        assert case.source_simulation_id is None

    def test_empty_string_ensemble_id_does_not_get_persisted(self):
        # A real source_simulation_id alongside an empty-string
        # source_ensemble_id must not leave a stray non-None
        # source_ensemble_id="" in the persisted record.
        _make_completed_simulation()
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_simulation_id="sim_source12345",
            source_ensemble_id="",
        )
        assert case.source_simulation_id == "sim_source12345"
        assert case.source_ensemble_id is None

    def test_non_string_falsy_source_id_is_rejected_not_silently_absent(self):
        # Only the literal "" is normalized to "not provided". Other falsy
        # values (0, False, []) are not valid ids and must not be erased by
        # normalization -- they should still cause a rejection (whether via
        # the exclusive-source check or downstream identifier validation),
        # not be silently treated as "absent" and let a malformed request
        # through.
        _make_completed_ensemble()
        with pytest.raises(ValueError):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id=0,
                source_ensemble_id="ens_source1234",
            )

    def test_missing_scenario_description_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="scenario_description"):
            BacktestRunner.create_backtest(
                scenario_description="", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
            )

    def test_missing_t0_cutoff_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="t0_cutoff"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
            )

    def test_whitespace_only_scenario_description_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="scenario_description"):
            BacktestRunner.create_backtest(
                scenario_description="   \t\n  ", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
            )

    def test_whitespace_only_t0_cutoff_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="t0_cutoff"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="   ",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
            )

    def test_whitespace_only_direction_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="direction"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"direction": "   "},
                source_simulation_id="sim_source12345",
            )

    def test_whitespace_only_sentiment_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="sentiment"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"sentiment": ""},
                source_simulation_id="sim_source12345",
            )

    def test_missing_source_simulation_rejected(self):
        with pytest.raises(ValueError, match="不存在"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_doesnotexist",
            )

    def test_incomplete_source_simulation_rejected(self):
        _make_running_simulation()
        with pytest.raises(ValueError, match="尚未成功完成"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_running1234",
            )

    def test_missing_source_ensemble_rejected(self):
        with pytest.raises(ValueError, match="不存在"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_ensemble_id="ens_doesnotexist",
            )

    def test_empty_prediction_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="prediction"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={},
                source_simulation_id="sim_source12345",
            )

    def test_probability_out_of_range_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="probability"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"probability": 1.5},
                source_simulation_id="sim_source12345",
            )

    def test_non_numeric_probability_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="probability"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"probability": "high"},
                source_simulation_id="sim_source12345",
            )

    def test_boolean_probability_rejected(self):
        # isinstance(True, int) is True in Python; must be explicitly excluded.
        _make_completed_simulation()
        with pytest.raises(ValueError, match="probability"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"probability": True},
                source_simulation_id="sim_source12345",
            )

    def test_non_string_direction_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="direction"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"direction": 1},
                source_simulation_id="sim_source12345",
            )

    def test_empty_distribution_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {}},
                source_simulation_id="sim_source12345",
            )

    def test_negative_distribution_value_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {"a": -0.5, "b": 1.5}},
                source_simulation_id="sim_source12345",
            )

    def test_zero_sum_distribution_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {"a": 0, "b": 0}},
                source_simulation_id="sim_source12345",
            )

    def test_unknown_prediction_field_rejected(self):
        # A typo (e.g. "direciton" instead of "direction") must be
        # rejected up front, not silently dropped by from_dict's .get(...)
        # -- which would leave the intended field as None with no error.
        _make_completed_simulation()
        with pytest.raises(ValueError, match="无法识别"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True, "direciton": "up"},
                source_simulation_id="sim_source12345",
            )

    def test_unknown_ground_truth_field_rejected_before_consuming_claim(self):
        # Even more important than the prediction-side case: ground truth
        # is one-shot and immutable, so a typo here would otherwise be
        # permanently unrecoverable. Must be rejected before the exclusive
        # claim is created, so a corrected retry is still possible.
        _make_completed_simulation()
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True, "direction": "up"},
            source_simulation_id="sim_source12345",
        )
        with pytest.raises(ValueError, match="无法识别"):
            BacktestRunner.record_ground_truth(
                case.backtest_id, {"occurred": True, "direciton": "up"}
            )

        # The claim must not have been consumed -- a corrected resubmission
        # still succeeds.
        result = BacktestRunner.record_ground_truth(
            case.backtest_id, {"occurred": True, "direction": "up"}
        )
        assert result.metrics["direction_correct"] is True

    def test_nan_rank_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="rank"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"rank": float("nan")},
                source_simulation_id="sim_source12345",
            )

    def test_infinite_rank_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="rank"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"rank": float("inf")},
                source_simulation_id="sim_source12345",
            )

    def test_nan_distribution_value_rejected(self):
        # nan < 0 is False in Python, so a naive non-negativity check alone
        # would silently accept this.
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {"a": float("nan"), "b": 1.0}},
                source_simulation_id="sim_source12345",
            )

    def test_infinite_distribution_value_rejected(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {"a": float("inf"), "b": 1.0}},
                source_simulation_id="sim_source12345",
            )

    def test_oversized_integer_rank_rejected_not_500(self):
        # math.isfinite() raises OverflowError (not returns False) when
        # converting an arbitrary-precision Python int this large to a
        # float; a naive isfinite check would let this propagate as an
        # unhandled 500 instead of a clean validation error.
        _make_completed_simulation()
        with pytest.raises(ValueError, match="rank"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"rank": 10 ** 400},
                source_simulation_id="sim_source12345",
            )

    def test_oversized_integer_probability_rejected_not_500(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="probability"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"probability": 10 ** 400},
                source_simulation_id="sim_source12345",
            )

    def test_oversized_integer_distribution_value_rejected_not_500(self):
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {"a": 10 ** 400, "b": 1.0}},
                source_simulation_id="sim_source12345",
            )

    def test_distribution_with_overflowing_sum_rejected(self):
        # Each value is individually finite, but 1e308 + 1e308 overflows to
        # inf when summed -- a naive `total <= 0` check wouldn't catch this
        # (inf <= 0 is False), and normalizing against an infinite total
        # would silently produce a degenerate all-zero distribution.
        _make_completed_simulation()
        with pytest.raises(ValueError, match="distribution"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"distribution": {"a": 1e308, "b": 1e308}},
                source_simulation_id="sim_source12345",
            )


class TestCreateBacktestHappyPath:
    def test_creates_backtest_from_completed_simulation(self):
        _make_completed_simulation(owner_id="alice", project_id="proj_abc12345")
        case = BacktestRunner.create_backtest(
            scenario_description="Will sentiment turn negative?",
            t0_cutoff="2024-01-01T00:00:00",
            prediction={"occurred": True, "probability": 0.7, "direction": "up"},
            source_simulation_id="sim_source12345",
            owner_id="alice",
        )
        assert case.source_simulation_id == "sim_source12345"
        assert case.source_ensemble_id is None
        assert case.project_id == "proj_abc12345"
        assert case.owner_id == "alice"
        assert case.prediction.occurred is True
        assert case.prediction.probability == 0.7
        assert case.ground_truth is None
        assert case.metrics is None

        reloaded = BacktestRunner.get_backtest(case.backtest_id)
        assert reloaded is not None
        assert reloaded.prediction.direction == "up"

    def test_creates_backtest_from_completed_ensemble(self):
        _make_completed_ensemble(owner_id="bob", project_id="proj_xyz98765")
        case = BacktestRunner.create_backtest(
            scenario_description="Distribution of outcomes",
            t0_cutoff="2024-01-01",
            prediction={"distribution": {"a": 0.6, "b": 0.4}},
            source_ensemble_id="ens_source1234",
            owner_id="bob",
        )
        assert case.source_ensemble_id == "ens_source1234"
        assert case.source_simulation_id is None
        assert case.project_id == "proj_xyz98765"
        assert case.owner_id == "bob"
        assert case.prediction.distribution == {"a": 0.6, "b": 0.4}

    def test_owner_id_is_caller_supplied_not_inherited_from_a_legacy_unowned_source(self):
        # A source with owner_id=None represents a resource created before
        # authentication existed; any authenticated user may read it. The
        # backtest derived from it must NOT also end up owner_id=None
        # (which would make it a public resource anyone could later submit
        # a one-shot ground truth against) -- it must be stamped with
        # whoever actually made this request (the API layer passes this
        # in from the current authenticated user; the service never
        # infers it from the source).
        _make_completed_simulation(owner_id=None, project_id="proj_abc12345")
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_simulation_id="sim_source12345",
            owner_id="alice",
        )
        assert case.owner_id == "alice"

    def test_source_run_snapshot_pins_simulation_started_at(self):
        _make_completed_simulation()
        run_state = SimulationRunner.get_run_state("sim_source12345")
        run_state.started_at = "2024-06-01T12:00:00"
        SimulationRunner._save_run_state(run_state)

        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_simulation_id="sim_source12345",
        )
        assert case.source_run_snapshot_at == "2024-06-01T12:00:00"

        # If the source simulation is later rerun (same simulation_id, new
        # started_at), the pinned snapshot on the already-created backtest
        # stays frozen at the original value -- the mismatch is exactly
        # what lets an auditor detect the source has since changed.
        run_state.started_at = "2024-07-01T00:00:00"
        SimulationRunner._save_run_state(run_state)
        reloaded = BacktestRunner.get_backtest(case.backtest_id)
        assert reloaded.source_run_snapshot_at == "2024-06-01T12:00:00"

    def test_source_run_snapshot_fingerprints_every_completed_member(self):
        # EnsembleRecord.created_at alone can't detect a member being
        # restarted in place after the fact (each member is an ordinary,
        # restartable SimulationRunner simulation from SimulationRunner's
        # point of view) -- the snapshot must be built from each member's
        # own started_at instead.
        _make_completed_ensemble(member_count=2)
        for i, started_at in enumerate(["2024-01-01T00:00:00", "2024-01-02T00:00:00"]):
            member_id = f"ens_source1234_m{i}"
            member_state = SimulationRunner.get_run_state(member_id)
            member_state.started_at = started_at
            SimulationRunner._save_run_state(member_state)

        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_ensemble_id="ens_source1234",
        )
        assert case.source_run_snapshot_at == (
            "ens_source1234_m0:2024-01-01T00:00:00|"
            "ens_source1234_m1:2024-01-02T00:00:00"
        )

        # If a member is later restarted (started_at changes), the pinned
        # snapshot on the already-created backtest stays frozen, and a
        # freshly recomputed fingerprint for the current state would no
        # longer match it -- that mismatch is the detectable signal.
        member_0 = SimulationRunner.get_run_state("ens_source1234_m0")
        member_0.started_at = "2024-06-01T00:00:00"
        SimulationRunner._save_run_state(member_0)
        reloaded = BacktestRunner.get_backtest(case.backtest_id)
        assert reloaded.source_run_snapshot_at != (
            "ens_source1234_m0:2024-06-01T00:00:00|"
            "ens_source1234_m1:2024-01-02T00:00:00"
        )
        assert reloaded.source_run_snapshot_at == case.source_run_snapshot_at

    def test_source_run_snapshot_uses_force_reload_not_stale_cache(self):
        # Regression test: get_run_state's in-process cache must be
        # bypassed for this permanent, evidence-locking decision -- a
        # cached COMPLETED status must not let create_backtest snapshot a
        # source that has actually since moved on to a new run.
        _make_completed_simulation()
        # Prime the process-local cache with a stale COMPLETED entry, then
        # overwrite the on-disk state to RUNNING without going through
        # _save_run_state's normal cache-updating path (simulating another
        # worker process writing to the shared uploads directory).
        SimulationRunner.get_run_state("sim_source12345")  # populates the cache
        import json as _json
        state_path = os.path.join(
            SimulationRunner._get_sim_dir("sim_source12345"), "run_state.json"
        )
        with open(state_path, "r", encoding="utf-8") as f:
            on_disk = _json.load(f)
        on_disk["runner_status"] = "running"
        with open(state_path, "w", encoding="utf-8") as f:
            _json.dump(on_disk, f)

        with pytest.raises(ValueError, match="尚未成功完成"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
            )

    def test_reprepared_source_simulation_rejected_despite_stale_completed_run_state(self):
        # Regression test: /api/simulation/prepare with force_regenerate=True
        # can regenerate a COMPLETED simulation's profiles/config in place,
        # moving SimulationState.status to PREPARING/READY -- but it never
        # touches run_state.json, which still shows the previous run's
        # COMPLETED status. run_state alone can't detect this; the
        # SimulationState.status check must catch it.
        _make_completed_simulation()
        state = SimulationManager().get_simulation("sim_source12345")
        state.status = SimulationStatus.READY
        SimulationManager()._save_simulation_state(state)

        with pytest.raises(ValueError, match="尚未成功完成"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_simulation_id="sim_source12345",
            )

    def test_reprepared_ensemble_member_rejected_despite_stale_completed_run_state(self):
        _make_completed_ensemble(member_count=1)
        member_state = SimulationManager().get_simulation("ens_source1234_m0")
        member_state.status = SimulationStatus.PREPARING
        SimulationManager()._save_simulation_state(member_state)

        with pytest.raises(ValueError, match="尚未成功完成"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_ensemble_id="ens_source1234",
            )

    def test_ensemble_member_restarted_after_stale_summary_is_rejected(self):
        # Regression test: get_ensemble_summary() checks each member's
        # status via the default (possibly stale-cached) get_run_state
        # path, so it can still report "completed" after another worker
        # restarted one member in place. The force_reload=True re-check on
        # each member inside create_backtest's own loop must catch this
        # and reject the whole request -- not silently include the
        # restarted member's new started_at in the fingerprint while still
        # creating the backtest.
        _make_completed_ensemble(member_count=2)
        # Populate the cache with COMPLETED for both members (mirrors what
        # get_ensemble_summary's own default-path read would have primed),
        # then move member 0 to RUNNING only on disk -- simulating another
        # worker process restarting it without this process's cache ever
        # being told.
        SimulationRunner.get_run_state("ens_source1234_m0")
        SimulationRunner.get_run_state("ens_source1234_m1")
        state_path = os.path.join(
            SimulationRunner._get_sim_dir("ens_source1234_m0"), "run_state.json"
        )
        with open(state_path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        on_disk["runner_status"] = "running"
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(on_disk, f)

        with pytest.raises(ValueError, match="尚未成功完成"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_ensemble_id="ens_source1234",
            )

    def test_ensemble_with_some_failed_members_still_creatable(self):
        # A member that genuinely FAILED (not restarted -- just never
        # succeeded) must not block backtest creation: it was never part
        # of EnsembleRunner's aggregate/prediction basis in the first
        # place (see TASK 8's _compute_aggregate), so its status is
        # irrelevant to this backtest's provenance.
        _make_completed_ensemble(
            member_count=2,
            member_statuses=[RunnerStatus.COMPLETED, RunnerStatus.FAILED],
        )

        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_ensemble_id="ens_source1234",
        )
        assert "ens_source1234_m0" in case.source_run_snapshot_at
        assert "ens_source1234_m1" not in case.source_run_snapshot_at

    def test_genuinely_incomplete_ensemble_rejected(self):
        _make_completed_ensemble(
            member_count=2,
            member_statuses=[RunnerStatus.COMPLETED, RunnerStatus.RUNNING],
        )
        with pytest.raises(ValueError, match="尚未成功完成"):
            BacktestRunner.create_backtest(
                scenario_description="x", t0_cutoff="2024-01-01",
                prediction={"occurred": True},
                source_ensemble_id="ens_source1234",
            )

    def test_ensemble_still_creatable_when_this_workers_cache_is_stale_running(self):
        # Regression test for the flawed "cheap early exit": a cache-based
        # pre-check must not reject an ensemble just because *this*
        # process happened to cache an earlier RUNNING snapshot for a
        # member that has genuinely completed since (e.g. on another
        # worker). Eligibility must be decided solely by the
        # force_reload=True loop.
        _make_completed_ensemble(member_count=2)
        # Prime this process's cache with a stale RUNNING entry for
        # member 0 (simulating this worker having observed it earlier,
        # before it finished), while the on-disk state is already the
        # real COMPLETED written by _make_completed_ensemble above.
        from app.services.simulation_runner import SimulationRunState as _SRS

        SimulationRunner._run_states["ens_source1234_m0"] = _SRS(
            simulation_id="ens_source1234_m0", runner_status=RunnerStatus.RUNNING
        )

        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_ensemble_id="ens_source1234",
        )
        assert "ens_source1234_m0" in case.source_run_snapshot_at
        assert "ens_source1234_m1" in case.source_run_snapshot_at

    def test_cancelled_after_crash_provisional_member_does_not_block_creation(self):
        # Regression test matching TASK 8's crash-then-cancel scenario
        # (see EnsembleRunner.get_ensemble_summary): a member the launch
        # loop never reached before the whole worker crashed has no
        # start_error and no run_state, but a subsequent stop_ensemble
        # call durably marked the ensemble record cancelled=True.
        # get_ensemble_summary() classifies that placeholder as a
        # terminal failure (not "unknown"), and this code must agree
        # instead of treating the missing run_state as an anomaly to
        # reject outright.
        record = _make_completed_ensemble(member_count=1)
        never_started = EnsembleMemberRecord(
            simulation_id="ens_source1234_m1", index=1
        )
        cancelled_record = EnsembleRecord(
            ensemble_id=record.ensemble_id,
            source_simulation_id=record.source_simulation_id,
            project_id=record.project_id,
            graph_id=record.graph_id,
            platform=record.platform,
            max_rounds=record.max_rounds,
            run_count=2,
            members=list(record.members) + [never_started],
            created_at=record.created_at,
            owner_id=record.owner_id,
            cancelled=True,
        )
        atomic_write_json(
            EnsembleRunner._ensemble_path(record.ensemble_id), cancelled_record.to_dict()
        )

        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True},
            source_ensemble_id=record.ensemble_id,
        )
        assert "ens_source1234_m0" in case.source_run_snapshot_at
        assert "ens_source1234_m1" not in case.source_run_snapshot_at


class TestRecordGroundTruth:
    def _create_case(self, prediction):
        _make_completed_simulation()
        return BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction=prediction,
            source_simulation_id="sim_source12345",
        )

    def test_missing_backtest_rejected(self):
        with pytest.raises(ValueError, match="不存在"):
            BacktestRunner.record_ground_truth("bt_doesnotexist", {"occurred": True})

    def test_probing_nonexistent_ids_creates_no_claim_file_or_directory(self):
        # Regression test for the original unbounded-growth concern under
        # the old threading.Lock-based design: existence is checked before
        # any exclusive-create claim file is touched, so probing with
        # distinct nonexistent ids leaves nothing behind on disk.
        for i in range(20):
            with pytest.raises(ValueError, match="不存在"):
                BacktestRunner.record_ground_truth(f"bt_doesnotexist{i:03d}", {"occurred": True})
        assert not os.path.exists(BacktestRunner.BACKTEST_DATA_DIR) or not os.listdir(
            BacktestRunner.BACKTEST_DATA_DIR
        )

    def test_recording_creates_a_claim_file_for_cross_process_exclusion(self):
        case = self._create_case({"occurred": True})
        BacktestRunner.record_ground_truth(case.backtest_id, {"occurred": True})
        claim_path = BacktestRunner._ground_truth_claim_path(case.backtest_id)
        assert os.path.exists(claim_path)

    def test_recording_twice_rejected(self):
        case = self._create_case({"occurred": True})
        BacktestRunner.record_ground_truth(case.backtest_id, {"occurred": True})
        with pytest.raises(ValueError, match="已经登记过"):
            BacktestRunner.record_ground_truth(case.backtest_id, {"occurred": False})

    def test_no_comparable_fields_rejected(self):
        case = self._create_case({"direction": "up"})
        with pytest.raises(ValueError, match="没有任何可比较"):
            BacktestRunner.record_ground_truth(case.backtest_id, {"sentiment": "positive"})

    def test_validation_failure_does_not_consume_the_one_shot_claim(self):
        # Input validation (_parse_ground_truth/_ensure_scorable) happens
        # before the exclusive claim file is created, specifically so a
        # single malformed/mismatched request can't permanently brick a
        # case's ability to ever record ground truth. A bad first attempt
        # must still allow a valid follow-up to succeed.
        case = self._create_case({"occurred": True})
        with pytest.raises(ValueError, match="没有任何可比较"):
            BacktestRunner.record_ground_truth(case.backtest_id, {"sentiment": "positive"})

        result = BacktestRunner.record_ground_truth(case.backtest_id, {"occurred": True})
        assert result.metrics["event_occurrence_correct"] is True

    def test_rank_only_overlap_is_scorable(self):
        # rank has no per-case metric of its own (it only feeds suite-level
        # rank correlation), but it must still count as "comparable" so a
        # case built purely for ranking doesn't get rejected.
        case = self._create_case({"rank": 1.0})
        result = BacktestRunner.record_ground_truth(case.backtest_id, {"rank": 2.0})
        assert result.metrics == {}
        assert result.ground_truth.rank == 2.0

    def test_ground_truth_becomes_immutable_after_recording(self):
        case = self._create_case({"occurred": True})
        BacktestRunner.record_ground_truth(case.backtest_id, {"occurred": True})
        reloaded = BacktestRunner.get_backtest(case.backtest_id)
        assert reloaded.ground_truth is not None
        assert reloaded.ground_truth_recorded_at is not None
        assert reloaded.metrics is not None

    def test_concurrent_record_calls_never_both_succeed(self, monkeypatch):
        # Regression test for the read-check-write race, now guarded by an
        # O_CREAT|O_EXCL claim file instead of a threading.Lock (which only
        # ever protected a single process -- see the module docstring and
        # record_ground_truth's own docstring for why that wasn't enough).
        # Widen the window between t1 claiming and t1 actually writing the
        # scored result, so t2's concurrent attempt reliably lands while
        # t1's claim already exists but its write hasn't landed yet.
        import threading
        from app.services import backtest_runner as backtest_runner_module

        case = self._create_case({"occurred": True})

        real_write = backtest_runner_module.atomic_write_json
        entered_write = threading.Event()
        release_write = threading.Event()
        first_writer_seen = {"done": False}

        def slow_write(path, data):
            if not first_writer_seen["done"]:
                first_writer_seen["done"] = True
                entered_write.set()
                release_write.wait(timeout=5)
            real_write(path, data)

        monkeypatch.setattr(backtest_runner_module, "atomic_write_json", slow_write)

        results = {}

        def submit(occurred, key):
            try:
                results[key] = BacktestRunner.record_ground_truth(
                    case.backtest_id, {"occurred": occurred}
                )
            except ValueError as error:
                results[key] = error

        t1 = threading.Thread(target=submit, args=(True, "first"))
        t1.start()
        assert entered_write.wait(timeout=5)  # t1 already holds the claim, mid-write

        t2 = threading.Thread(target=submit, args=(False, "second"))
        t2.start()
        t2.join(timeout=5)  # t2's os.open(O_EXCL) fails fast -- no blocking involved
        assert not t2.is_alive()

        release_write.set()
        t1.join(timeout=5)

        outcomes = list(results.values())
        successes = [r for r in outcomes if isinstance(r, BacktestCase)]
        errors = [r for r in outcomes if isinstance(r, ValueError)]
        assert len(successes) == 1
        assert len(errors) == 1
        assert "已经登记过" in str(errors[0])

        reloaded = BacktestRunner.get_backtest(case.backtest_id)
        assert reloaded.ground_truth.occurred == successes[0].ground_truth.occurred


class TestScoringMetrics:
    def _score(self, prediction, ground_truth):
        _make_completed_simulation()
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction=prediction, source_simulation_id="sim_source12345",
        )
        return BacktestRunner.record_ground_truth(case.backtest_id, ground_truth)

    def test_event_occurrence_correct_when_matching(self):
        result = self._score({"occurred": True}, {"occurred": True})
        assert result.metrics["event_occurrence_correct"] is True

    def test_event_occurrence_incorrect_when_mismatched(self):
        result = self._score({"occurred": True}, {"occurred": False})
        assert result.metrics["event_occurrence_correct"] is False

    def test_brier_score_computed_when_probability_and_occurred_present(self):
        result = self._score({"occurred": True, "probability": 0.8}, {"occurred": True})
        assert result.metrics["brier_score"] == pytest.approx((0.8 - 1.0) ** 2)

    def test_brier_score_absent_without_probability(self):
        result = self._score({"occurred": True}, {"occurred": True})
        assert "brier_score" not in result.metrics

    def test_probability_only_prediction_is_scorable_against_occurred(self):
        # A prediction with ONLY a probability (no point occurred guess) is
        # a perfectly valid probabilistic forecast -- it must not be
        # rejected as "unscorable" just because it doesn't also overlap on
        # the occurred field, and it must still yield a brier_score.
        result = self._score({"probability": 0.7}, {"occurred": True})
        assert "event_occurrence_correct" not in result.metrics
        assert result.metrics["brier_score"] == pytest.approx((0.7 - 1.0) ** 2)

    def test_direction_correct_is_case_and_whitespace_insensitive(self):
        result = self._score({"direction": " Up "}, {"direction": "up"})
        assert result.metrics["direction_correct"] is True

    def test_blank_ground_truth_direction_rejected_not_falsely_matched(self):
        # Regression test: a blank/whitespace-only direction must be
        # rejected outright, not normalized to "" and falsely matched
        # against another blank value (which would report a successful
        # direction_correct=True and inflate suite accuracy).
        _make_completed_simulation()
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"direction": "up"}, source_simulation_id="sim_source12345",
        )
        with pytest.raises(ValueError, match="direction"):
            BacktestRunner.record_ground_truth(case.backtest_id, {"direction": "  "})

    def test_sentiment_incorrect_when_mismatched(self):
        result = self._score({"sentiment": "positive"}, {"sentiment": "negative"})
        assert result.metrics["sentiment_correct"] is False

    def test_distribution_distance_known_value(self):
        # Total variation distance between {a:0.6,b:0.4} and {a:0.5,b:0.5}
        # (already normalized) is 0.5 * (0.1 + 0.1) = 0.1.
        result = self._score(
            {"distribution": {"a": 0.6, "b": 0.4}},
            {"distribution": {"a": 0.5, "b": 0.5}},
        )
        assert result.metrics["distribution_distance"] == pytest.approx(0.1)

    def test_distribution_distance_normalizes_unnormalized_inputs(self):
        # {a:60,b:40} normalizes to the same distribution as {a:0.6,b:0.4}.
        result = self._score(
            {"distribution": {"a": 60, "b": 40}},
            {"distribution": {"a": 0.5, "b": 0.5}},
        )
        assert result.metrics["distribution_distance"] == pytest.approx(0.1)

    def test_only_overlapping_fields_are_scored(self):
        result = self._score(
            {"occurred": True, "direction": "up"}, {"occurred": True, "sentiment": "positive"}
        )
        assert "event_occurrence_correct" in result.metrics
        assert "direction_correct" not in result.metrics
        assert "sentiment_correct" not in result.metrics


class TestListAndGetBacktest:
    def test_get_missing_returns_none(self):
        assert BacktestRunner.get_backtest("bt_doesnotexist") is None

    def test_list_filters_by_project_id(self):
        _make_completed_simulation(simulation_id="sim_p1", project_id="proj_p1_abcdef")
        _make_completed_simulation(simulation_id="sim_p2", project_id="proj_p2_abcdef")
        BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"occurred": True}, source_simulation_id="sim_p1",
        )
        BacktestRunner.create_backtest(
            scenario_description="y", t0_cutoff="2024-01-01",
            prediction={"occurred": True}, source_simulation_id="sim_p2",
        )
        cases = BacktestRunner.list_backtests(project_id="proj_p1_abcdef")
        assert len(cases) == 1
        assert cases[0].source_simulation_id == "sim_p1"


class TestSuiteSummary:
    def _completed_case(self, index, occurred, probability=None, direction=None, rank=None, sentiment=None):
        sim_id = f"sim_case{index}"
        _make_completed_simulation(simulation_id=sim_id, project_id="proj_suite123")
        prediction = {}
        if probability is not None:
            prediction["probability"] = probability
            prediction["occurred"] = occurred
        if direction is not None:
            prediction["direction"] = direction
        if sentiment is not None:
            prediction["sentiment"] = sentiment
        if rank is not None:
            prediction["rank"] = rank
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction=prediction, source_simulation_id=sim_id,
        )
        ground_truth = {}
        if probability is not None:
            ground_truth["occurred"] = occurred
        if direction is not None:
            ground_truth["direction"] = direction
        if sentiment is not None:
            ground_truth["sentiment"] = sentiment
        if rank is not None:
            ground_truth["rank"] = rank
        return BacktestRunner.record_ground_truth(case.backtest_id, ground_truth)

    def test_empty_suite_returns_honest_nones(self):
        summary = BacktestRunner.get_suite_summary()
        assert summary["scored_case_count"] == 0
        assert summary["direction_accuracy"] is None
        assert summary["calibration_error"]["expected_calibration_error"] is None
        assert summary["rank_correlation"]["spearman_rho"] is None

    def test_direction_accuracy_across_cases(self):
        self._completed_case(0, occurred=True, direction="up")
        # second case: prediction "up", ground truth "down" -> incorrect
        sim_id = "sim_case1"
        _make_completed_simulation(simulation_id=sim_id, project_id="proj_suite123")
        case = BacktestRunner.create_backtest(
            scenario_description="x", t0_cutoff="2024-01-01",
            prediction={"direction": "up"}, source_simulation_id=sim_id,
        )
        BacktestRunner.record_ground_truth(case.backtest_id, {"direction": "down"})

        summary = BacktestRunner.get_suite_summary(project_id="proj_suite123")
        assert summary["direction_accuracy"]["count"] == 2
        assert summary["direction_accuracy"]["correct"] == 1
        assert summary["direction_accuracy"]["accuracy"] == 0.5

    def test_calibration_error_needs_at_least_two_samples(self):
        self._completed_case(0, occurred=True, probability=0.9)
        summary = BacktestRunner.get_suite_summary(project_id="proj_suite123")
        assert summary["calibration_error"]["sample_count"] == 1
        assert summary["calibration_error"]["expected_calibration_error"] is None

    def test_calibration_error_computed_with_enough_samples(self):
        self._completed_case(0, occurred=True, probability=0.9)
        self._completed_case(1, occurred=False, probability=0.9)
        summary = BacktestRunner.get_suite_summary(project_id="proj_suite123")
        calibration = summary["calibration_error"]
        assert calibration["sample_count"] == 2
        # Both land in the 0.9-1.0 bucket: mean predicted 0.9, actual rate 0.5.
        assert calibration["expected_calibration_error"] == pytest.approx(0.4)

    def test_rank_correlation_needs_at_least_three_pairs(self):
        self._completed_case(0, occurred=True, rank=1.0)
        self._completed_case(1, occurred=True, rank=2.0)
        summary = BacktestRunner.get_suite_summary(project_id="proj_suite123")
        assert summary["rank_correlation"]["sample_count"] == 2
        assert summary["rank_correlation"]["spearman_rho"] is None

    def test_rank_correlation_perfect_monotonic_relationship(self):
        for i, rank in enumerate([1.0, 2.0, 3.0]):
            self._completed_case(i, occurred=True, rank=rank)
        # Ground truth ranks assigned in the same order as prediction ranks
        # above (see _completed_case: ground_truth["rank"] = rank param).
        summary = BacktestRunner.get_suite_summary(project_id="proj_suite123")
        assert summary["rank_correlation"]["sample_count"] == 3
        assert summary["rank_correlation"]["spearman_rho"] == pytest.approx(1.0)
