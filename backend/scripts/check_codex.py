"""Explicit live smoke check: consumes a few requests from your Codex plan.

Run from backend: uv run python scripts/check_codex.py --live
Add --oasis to verify two agents creating posts in a temporary Reddit database.
No Zep credentials, real documents, or external social-media accounts are used.
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def check_oasis(directory):
    import oasis
    from app.utils.codex_model import CodexModel
    from app.utils.simulation_env import CodexSimulationEnv

    graph = oasis.AgentGraph()
    agents = []
    for index, name in enumerate(['Alice', 'Bob']):
        agent = oasis.SocialAgent(
            agent_id=index,
            user_info=oasis.UserInfo(user_name=name.lower(), name=name, recsys_type='reddit'),
            agent_graph=graph, model=CodexModel(),
            available_actions=[oasis.ActionType.CREATE_POST], max_iteration=1,
        )
        graph.add_agent(agent)
        agents.append(agent)
    database = str(Path(directory) / 'simulation.db')
    env = CodexSimulationEnv(
        agent_graph=graph, platform=oasis.DefaultPlatformType.REDDIT,
        database_path=database, semaphore=2,
    )
    await env.reset()
    try:
        await env.step({agent: oasis.LLMAction() for agent in agents})
        with sqlite3.connect(database) as connection:
            rows = connection.execute('SELECT user_id, content FROM post').fetchall()
        if len({row[0] for row in rows}) != 2 or any(not row[1] for row in rows):
            raise RuntimeError('OASIS did not record a post from each Codex-powered agent.')
        print(f'PASS: OASIS recorded {len(rows)} posts from two Codex-powered agents.')
    finally:
        await env.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Run requests using your Codex allowance')
    parser.add_argument('--oasis', action='store_true', help='Also run a tiny local social simulation')
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live to run checks that consume your Codex subscription allowance.')
    from app.utils.codex_provider import CodexClient

    client = CodexClient()
    response = client.create(messages=[{'role': 'user', 'content': 'Reply with the single word READY.'}])
    if response.choices[0].message.content.strip() != 'READY':
        raise RuntimeError('Unexpected text response.')
    print('PASS: text completion using the local Codex login.', flush=True)
    response = client.create(
        messages=[{'role': 'user', 'content': 'Return a JSON object with ready set to true.'}],
        response_format={'type': 'json_object'},
    )
    if json.loads(response.choices[0].message.content).get('ready') is not True:
        raise RuntimeError('Unexpected JSON response.')
    print('PASS: structured JSON completion.', flush=True)
    if args.oasis:
        previous = os.getcwd()
        with tempfile.TemporaryDirectory(prefix='mirofish-oasis-check-') as directory:
            try:
                # OASIS writes relative log files on import; keep them temporary.
                os.chdir(directory)
                asyncio.run(check_oasis(directory))
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    main()
