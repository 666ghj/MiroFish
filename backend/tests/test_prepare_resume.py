import json
import threading
from types import SimpleNamespace

import pytest

from app import create_app
from app.config import Config
from app.services.oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.utils.codex_transport import CodexProviderError


def entities():
    return [EntityNode(str(i), f'Person {i}', ['Person'], 'summary', {}) for i in range(3)]


def profile(entity, user_id):
    return OasisAgentProfile(user_id, f'user{user_id}', entity.name, 'bio', 'long persona',
                             source_entity_uuid=entity.uuid, follower_count=912,
                             profession='Engineer', interested_topics=['science'])


def generator(monkeypatch, generate):
    instance = object.__new__(OasisProfileGenerator)
    instance.graph_id = 'graph'
    monkeypatch.setattr(instance, 'generate_profile_from_entity', generate)
    monkeypatch.setattr(instance, '_print_generated_profile', lambda *args: None)
    return instance


def test_retry_only_generates_failed_entities_and_retains_parallel_success(tmp_path, monkeypatch):
    barrier = threading.Barrier(3)
    def generate(entity, user_id, **kwargs):
        barrier.wait(timeout=5)
        if entity.uuid == '0':
            raise CodexProviderError('provider offline')
        import time
        time.sleep(0.02)
        return profile(entity, user_id)
    path = tmp_path / 'reddit_profiles.json'
    first = generator(monkeypatch, generate)
    with pytest.raises(CodexProviderError):
        first.generate_profiles_from_entities(entities(), realtime_output_path=str(path), parallel_count=3)
    calls = []
    def retry(entity, user_id, **kwargs):
        calls.append(entity.uuid)
        return profile(entity, user_id)
    resumed = generator(monkeypatch, retry).generate_profiles_from_entities(
        list(reversed(entities())), realtime_output_path=str(path), parallel_count=1)
    assert calls == ['0']
    assert [(p.source_entity_uuid, p.user_id) for p in resumed] == [('0', 0), ('1', 1), ('2', 2)]
    assert resumed[1].follower_count == 912
    assert resumed[1].profession == 'Engineer'


def test_legacy_partial_personas_are_reused(tmp_path, monkeypatch):
    path = tmp_path / 'reddit_profiles.json'
    path.write_text(json.dumps([profile(entities()[1], 1).to_reddit_format()]))
    calls = []
    def generate(entity, user_id, **kwargs):
        calls.append(entity.uuid)
        return profile(entity, user_id)
    results = generator(monkeypatch, generate).generate_profiles_from_entities(
        entities(), realtime_output_path=str(path), parallel_count=1)
    assert calls == ['0', '2']
    assert results[1].persona == 'long persona'


def test_changed_inputs_require_explicit_regeneration(tmp_path, monkeypatch):
    path = tmp_path / 'reddit_profiles.json'
    gen = generator(monkeypatch, lambda entity, user_id, **kw: profile(entity, user_id))
    gen.generate_profiles_from_entities(entities(), realtime_output_path=str(path))
    changed = entities()
    changed[0].summary = 'changed'
    with pytest.raises(ValueError, match='force_regenerate'):
        gen.generate_profiles_from_entities(changed, realtime_output_path=str(path))


def test_status_restores_failed_and_interrupted_preparation(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    manager = SimulationManager()
    app = create_app()
    for status in (SimulationStatus.FAILED, SimulationStatus.PREPARING):
        state = SimulationState('sim_status', 'project', 'graph', status=status, error='provider offline')
        manager._save_simulation_state(state)
        response = app.test_client().post('/api/simulation/prepare/status', json={'simulation_id':state.simulation_id})
        assert response.status_code == 200
        assert response.json['data']['status'] == 'failed'
        assert response.json['data']['resumable'] is True
        assert SimulationManager().get_simulation(state.simulation_id).status == SimulationStatus.FAILED


def test_manager_resumes_saved_entities_and_reuses_completed_config(tmp_path, monkeypatch):
    from app.services import simulation_manager as module
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    counts = {'read': 0, 'profiles': 0, 'config': 0}
    class Reader:
        def filter_defined_entities(self, **kwargs):
            counts['read'] += 1
            return module.FilteredEntities(entities(), {'Person'}, 3, 3)
    class Generator(OasisProfileGenerator):
        def __init__(self, graph_id):
            self.graph_id = graph_id
        def generate_profile_from_entity(self, entity, user_id, **kwargs):
            counts['profiles'] += 1
            return profile(entity, user_id)
        def _print_generated_profile(self, *args):
            pass
    class ConfigGenerator:
        def generate_config(self, **kwargs):
            counts['config'] += 1
            if counts['config'] == 1:
                raise CodexProviderError('config unavailable')
            return SimpleNamespace(to_json=lambda: json.dumps({'simulation_id':'sim_resume', 'generation_reasoning':'saved'}),
                                   generation_reasoning='saved')
    monkeypatch.setattr(module, 'ZepEntityReader', Reader)
    monkeypatch.setattr(module, 'OasisProfileGenerator', Generator)
    monkeypatch.setattr(module, 'SimulationConfigGenerator', ConfigGenerator)
    manager = SimulationManager()
    manager._save_simulation_state(SimulationState('sim_resume', 'project', 'graph'))
    with pytest.raises(CodexProviderError):
        manager.prepare_simulation('sim_resume', 'requirement', 'document')
    resumed = SimulationManager().prepare_simulation('sim_resume', 'requirement', 'document')
    assert resumed.status == SimulationStatus.READY
    assert counts == {'read': 1, 'profiles': 3, 'config': 2}
    SimulationManager().prepare_simulation('sim_resume', 'requirement', 'document')
    assert counts == {'read': 1, 'profiles': 3, 'config': 2}
    SimulationManager().prepare_simulation('sim_resume', 'requirement', 'document', force_regenerate=True)
    assert counts == {'read': 2, 'profiles': 6, 'config': 3}


def test_prepare_repeated_click_reuses_task_and_clears_error(tmp_path, monkeypatch):
    import app.api.simulation as api
    from app.models.project import ProjectManager
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    manager = SimulationManager()
    manager._save_simulation_state(SimulationState('sim_click', 'project', 'graph', status=SimulationStatus.FAILED, error='old error'))
    monkeypatch.setattr(ProjectManager, 'get_project', lambda _: SimpleNamespace(simulation_requirement='requirement', graph_provider='zep'))
    monkeypatch.setattr(ProjectManager, 'get_extracted_text', lambda _: 'document')
    monkeypatch.setattr(api, 'ZepEntityReader', lambda: SimpleNamespace(filter_defined_entities=lambda **kw: SimpleNamespace(filtered_count=3, entity_types={'Person'})))
    started = []
    monkeypatch.setattr(threading.Thread, 'start', lambda thread: started.append(thread))
    client = create_app().test_client()
    first = client.post('/api/simulation/prepare', json={'simulation_id':'sim_click'})
    second = client.post('/api/simulation/prepare', json={'simulation_id':'sim_click'})
    assert first.status_code == second.status_code == 200
    assert first.json['data']['task_id'] == second.json['data']['task_id']
    assert len(started) == 1
    assert SimulationManager().get_simulation('sim_click').error is None
    status = client.post('/api/simulation/prepare/status', json={'simulation_id':'sim_click'})
    assert status.json['data']['task_id'] == first.json['data']['task_id']
    assert status.json['data']['status'] in ('pending', 'processing', 'preparing')


def test_concurrent_prepare_requests_and_refresh_share_one_worker(tmp_path, monkeypatch):
    import concurrent.futures
    from app.models.project import ProjectManager
    from app.models.task import TaskManager
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    SimulationManager()._save_simulation_state(SimulationState('sim_concurrent', 'project', 'graph'))
    monkeypatch.setattr(ProjectManager, 'get_project', lambda _: SimpleNamespace(simulation_requirement='requirement', graph_provider='zep'))
    monkeypatch.setattr(ProjectManager, 'get_extracted_text', lambda _: 'document')
    release = threading.Event()
    exited = threading.Event()
    calls = []
    def prepare(manager, **kwargs):
        calls.append(kwargs['simulation_id'])
        try:
            assert release.wait(timeout=5)
            return manager.get_simulation(kwargs['simulation_id'])
        finally:
            exited.set()
    monkeypatch.setattr(SimulationManager, 'prepare_simulation', prepare)
    app = create_app()
    def submit(_):
        with app.test_client() as client:
            return client.post('/api/simulation/prepare', json={'simulation_id':'sim_concurrent'})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            responses = list(executor.map(submit, range(5)))
        assert {response.status_code for response in responses} == {200}
        assert len({response.json['data']['task_id'] for response in responses}) == 1
        assert calls == ['sim_concurrent']
        task_id = responses[0].json['data']['task_id']
        # Simulate routing the refresh to a process without the in-memory Task.
        monkeypatch.setattr(TaskManager, 'get_task', lambda *args: None)
        response = app.test_client().post('/api/simulation/prepare/status', json={'simulation_id':'sim_concurrent'})
        assert response.json['data']['task_id'] == task_id
    finally:
        monkeypatch.undo()
        release.set()
        assert exited.wait(timeout=5)
