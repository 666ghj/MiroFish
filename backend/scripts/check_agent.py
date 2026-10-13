"""Validate a CLI provider; add --live to consume account allowance for smoke tests."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def check_oasis(provider, directory):
    import oasis
    from app.utils.agent_model import AgentModel
    from app.utils.simulation_env import CodexSimulationEnv

    graph = oasis.AgentGraph()
    agents = []
    for index, name in enumerate(['Alice', 'Bob']):
        agent = oasis.SocialAgent(
            agent_id=index,
            user_info=oasis.UserInfo(user_name=name.lower(), name=name, recsys_type='reddit'),
            agent_graph=graph, model=AgentModel(provider),
            available_actions=[oasis.ActionType.CREATE_POST], max_iteration=1,
        )
        graph.add_agent(agent)
        agents.append(agent)
    database = str(Path(directory) / 'simulation.db')
    env = CodexSimulationEnv(agent_graph=graph, platform=oasis.DefaultPlatformType.REDDIT,
                             database_path=database, semaphore=2)
    await env.reset()
    try:
        await env.step({agent: oasis.LLMAction() for agent in agents})
        with sqlite3.connect(database) as connection:
            rows = connection.execute('SELECT user_id, content FROM post').fetchall()
        if len({row[0] for row in rows}) != 2 or any(not row[1] for row in rows):
            raise RuntimeError('OASIS did not record a post from each agent.')
        print('PASS: OASIS recorded posts from two agents.')
    finally:
        await env.close()


def main():
    # Load once before importing app.config (which has the same root .env policy).
    from app.config import Config
    from research_agents import PROVIDERS, ProviderError, get_provider, validate_provider, run_agent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', default=Config.LLM_PROVIDER, help='One of: ' + ', '.join(PROVIDERS))
    parser.add_argument('--live', action='store_true', help='Run text, JSON, tool and graph-envelope checks')
    parser.add_argument('--oasis', action='store_true', help='Also run a two-agent local simulation (requires --live)')
    args = parser.parse_args()
    if args.oasis and not args.live:
        parser.error('--oasis requires --live')
    try:
        provider = get_provider(args.provider).id
        validate_provider(provider)
        print(f'PASS: {provider} configuration and executable found. Authentication has not been checked.', flush=True)
        if not args.live:
            print('No inference was run. Add --live to check your account and CLI compatibility.')
            return
        from app.utils.agent_provider import AgentClient
        client = AgentClient(provider)
        result = client.create(messages=[{'role': 'user', 'content': 'Reply with the single word READY.'}])
        if result.choices[0].message.content.strip() != 'READY':
            raise ProviderError('Unexpected text response.')
        print('PASS: text completion.', flush=True)
        result = client.create(messages=[{'role': 'user', 'content': 'Return a JSON object with ready set to true.'}],
                               response_format={'type': 'json_object'})
        if json.loads(result.choices[0].message.content).get('ready') is not True:
            raise ProviderError('Unexpected JSON response.')
        print('PASS: JSON completion.', flush=True)
        result = client.create(
            messages=[{'role': 'user', 'content': 'Call ready with ready=true.'}], tool_choice='required',
            tools=[{'type': 'function', 'function': {'name': 'ready', 'parameters': {
                'type': 'object', 'properties': {'ready': {'type': 'boolean', 'const': True}},
                'required': ['ready'], 'additionalProperties': False}}}],
        )
        if not result.choices[0].message.tool_calls:
            raise ProviderError('No simulation action returned.')
        print('PASS: validated simulation action (not executed).', flush=True)
        result, _ = run_agent('Return an envelope whose json string encodes {"ready":true}.', {
            'type': 'object', 'properties': {'json': {'type': 'string'}},
            'required': ['json'], 'additionalProperties': False,
        }, provider=provider)
        if json.loads(result['json']).get('ready') is not True:
            raise ProviderError('Unexpected graph extraction envelope.')
        print('PASS: graph extraction envelope (no database required).', flush=True)
        if args.oasis:
            previous = os.getcwd()
            with tempfile.TemporaryDirectory(prefix='mirofish-agent-check-') as directory:
                try:
                    os.chdir(directory)
                    asyncio.run(check_oasis(provider, directory))
                finally:
                    os.chdir(previous)
    except (ProviderError, ValueError) as error:
        parser.exit(1, f'FAIL: {error}\n')


if __name__ == '__main__':
    main()
