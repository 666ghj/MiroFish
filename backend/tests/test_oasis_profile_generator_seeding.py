"""
OasisProfileGenerator 随机种子测试

覆盖 TASK 6 的一处修复：最初实现曾在 prepare_simulation 中重新播种进程
全局的 random 模块，当多个模拟并行准备（各自在自己的线程池中生成
Profile）时会相互踩踏彼此的随机序列，使记录在可复现性清单里的种子失真。
现在改为每个实体使用一个独立、由 (random_seed, entity_uuid) 派生的
random.Random 实例，不触碰任何共享的可变状态。
"""

import concurrent.futures

import pytest

from app.services.oasis_profile_generator import OasisProfileGenerator


def _generator(seed):
    # api_key 只是为了满足构造函数校验；这些测试从不发起真实的 LLM 调用。
    return OasisProfileGenerator(api_key="fake-key", random_seed=seed)


class TestEntityRngDeterminism:
    def test_same_seed_and_entity_yields_same_sequence(self):
        gen = _generator(42)
        a = gen._entity_rng("entity-1")
        b = gen._entity_rng("entity-1")
        assert [a.randint(0, 10**9) for _ in range(20)] == [
            b.randint(0, 10**9) for _ in range(20)
        ]

    def test_different_entities_get_different_streams(self):
        gen = _generator(42)
        a = gen._entity_rng("entity-1").randint(0, 10**9)
        b = gen._entity_rng("entity-2").randint(0, 10**9)
        assert a != b

    def test_different_seeds_get_different_streams_for_same_entity(self):
        a = _generator(1)._entity_rng("entity-1").randint(0, 10**9)
        b = _generator(2)._entity_rng("entity-1").randint(0, 10**9)
        assert a != b

    def test_generate_username_deterministic_for_same_seed(self):
        gen = _generator(7)
        name_a = gen._generate_username("Alice", gen._entity_rng("entity-1"))
        name_b = gen._generate_username("Alice", gen._entity_rng("entity-1"))
        assert name_a == name_b

    def test_generate_profile_rule_based_deterministic_for_same_seed(self):
        gen = _generator(7)
        kwargs = dict(
            entity_name="Bob",
            entity_type="Student",
            entity_summary="A student",
            entity_attributes={},
        )
        first = gen._generate_profile_rule_based(**kwargs, rng=gen._entity_rng("entity-1"))
        second = gen._generate_profile_rule_based(**kwargs, rng=gen._entity_rng("entity-1"))
        assert first["age"] == second["age"]
        assert first["gender"] == second["gender"]
        assert first["mbti"] == second["mbti"]
        assert first["country"] == second["country"]

    def test_missing_rng_falls_back_to_global_random_without_raising(self):
        gen = _generator(None)
        # No rng passed -- must not raise, must still produce a valid profile.
        result = gen._generate_profile_rule_based(
            entity_name="Carol",
            entity_type="Student",
            entity_summary="",
            entity_attributes={},
        )
        assert isinstance(result["age"], int)

    def test_no_seed_preserves_original_nondeterministic_behavior(self):
        # Regression test: a generator with no random_seed (e.g. the
        # /generate-profiles endpoint, which never passes one) must keep
        # producing genuinely different values across repeated calls for the
        # same entity -- it must not treat the literal string "None" as a
        # real seed and become artificially deterministic.
        gen = _generator(None)
        suffixes = {
            gen._generate_username("Alice", gen._entity_rng("entity-1"))
            for _ in range(30)
        }
        assert len(suffixes) > 1

    def test_entity_rng_is_the_global_random_module_when_unseeded(self):
        gen = _generator(None)
        import random as random_module

        assert gen._entity_rng("entity-1") is random_module


class TestConcurrentSimulationsDoNotInterfere:
    """
    直接针对 Codex 发现的 [P1] 问题的回归测试：两个模拟并行准备时，
    各自的随机序列不应互相干扰或依赖线程调度顺序。
    """

    def test_two_simulations_concurrent_generation_matches_sequential_baseline(self):
        gen_a = _generator(111)
        gen_b = _generator(222)
        entity_ids = [f"entity-{i}" for i in range(50)]

        expected_a = [gen_a._entity_rng(eid).randint(0, 10**9) for eid in entity_ids]
        expected_b = [gen_b._entity_rng(eid).randint(0, 10**9) for eid in entity_ids]

        results_a = [None] * len(entity_ids)
        results_b = [None] * len(entity_ids)

        def work_a(i, eid):
            results_a[i] = gen_a._entity_rng(eid).randint(0, 10**9)

        def work_b(i, eid):
            results_b[i] = gen_b._entity_rng(eid).randint(0, 10**9)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for i, eid in enumerate(entity_ids):
                futures.append(executor.submit(work_a, i, eid))
                futures.append(executor.submit(work_b, i, eid))
            for f in futures:
                f.result()

        assert results_a == expected_a
        assert results_b == expected_b

    def test_repeated_concurrent_runs_are_stable(self):
        """Run the interleaved generation multiple times; a shared-global-RNG
        bug would make results flaky across repetitions."""
        gen = _generator(999)
        entity_ids = [f"entity-{i}" for i in range(30)]
        baseline = [gen._entity_rng(eid).randint(0, 10**9) for eid in entity_ids]

        for _ in range(5):
            results = [None] * len(entity_ids)

            def work(i, eid):
                results[i] = gen._entity_rng(eid).randint(0, 10**9)

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda args: work(*args), enumerate(entity_ids)))

            assert results == baseline
