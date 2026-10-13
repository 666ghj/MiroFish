"""The monitor must ingest each committed simulation action exactly once."""
import asyncio
import importlib
import json
import sqlite3
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('platform', ['twitter', 'reddit'])
def test_initial_posts_are_logged_once_after_commit(monkeypatch, tmp_path, platform):
    module = importlib.import_module('scripts.run_parallel_simulation')
    agent = object()
    graph = SimpleNamespace(get_agents=lambda: [(0, agent)], get_agent=lambda _: agent)
    async def generate(**kwargs): return graph
    monkeypatch.setattr(module, f'generate_{platform}_agent_graph', generate)
    monkeypatch.setattr(module, 'create_model', lambda *a, **kw: object())
    monkeypatch.setattr(module, '_shutdown_event', None)
    monkeypatch.setattr(module, 'get_active_agents_for_round', lambda *a: [(0, agent)])
    database = tmp_path / f'{platform}_simulation.db'
    class Environment:
        agent_graph = graph
        steps = 0
        async def reset(self):
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE trace (user_id INTEGER, action TEXT, info TEXT)')
        async def step(self, actions):
            self.steps += 1
            with sqlite3.connect(database) as db:
                db.execute('INSERT INTO trace VALUES (0, ?, ?)', ('create_post', json.dumps({'content': f'Post {self.steps}'})))
    monkeypatch.setattr(module, 'make_simulation_env', lambda **kw: Environment())
    (tmp_path / ('reddit_profiles.json' if platform == 'reddit' else 'twitter_profiles.csv')).write_text('')
    config = {'event_config': {'initial_posts': [{'poster_agent_id': 0, 'content': 'Post 1'}]},
              'time_config': {'total_simulation_hours': 1, 'minutes_per_round': 60},
              'agent_configs': [{'agent_id': 0, 'entity_name': 'Alice'}]}
    logger = module.PlatformActionLogger(platform, str(tmp_path))
    result = asyncio.run(getattr(module, f'run_{platform}_simulation')(config, str(tmp_path), logger, max_rounds=1))
    rows = [json.loads(line) for line in (tmp_path / platform / 'actions.jsonl').read_text().splitlines()]
    actions = [row for row in rows if 'agent_id' in row]
    assert [(row['round'], row['action_args']['content']) for row in actions] == [(0, 'Post 1'), (1, 'Post 2')]
    assert result.total_actions == 2
