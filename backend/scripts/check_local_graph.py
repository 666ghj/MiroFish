"""Check local readiness; --live runs/resumes a small real end-to-end research project."""
import argparse
import json
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = '''Alice Chen and Bob Tan co-founded Northstar Research in 2025.
Alice Chen is its research director. She supports publishing an open research tool,
with transparent evidence and reproducible results. Bob Tan is its engineering director.
He supports a small pilot before launch, with privacy checks and a clear maintenance plan.
The two founders are deciding whether to release their tool publicly next month.
Alice proposes inviting independent reviewers. Bob wants to limit the initial release
to ten testers and publish known limitations. Both agree not to promise reliable predictions.
'''
REQUIREMENT = '''Simulate a short English discussion between Alice Chen and Bob Tan about
releasing Northstar Research's open research tool. Use only these two people as agents,
one Reddit round, and a tiny pilot. Produce a concise report explaining their positions,
likely agreement, and limitations. This is synthetic test data, not a real forecast.'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Uses the configured inference provider and creates a retained demo project')
    parser.add_argument('--state', type=Path, default=ROOT / 'backend/uploads/local-graph-smoke.json')
    args = parser.parse_args()
    client = httpx.Client(base_url='http://127.0.0.1:5001', timeout=900, trust_env=False,
                          headers={'Accept-Language': 'en'})

    def api(path, payload=None, **kwargs):
        response = client.request('POST' if payload is not None or kwargs else 'GET', '/api/' + path,
                                  json=payload, **kwargs)
        result = response.json()
        if response.is_error or result.get('success') is False:
            raise RuntimeError(f'{path}: {response.status_code} {result.get("error", result)}')
        return result.get('data', result)

    status = api('system/status')
    print(json.dumps(status), flush=True)
    if status['graph_provider'] != 'graphiti' or status['graph']['status'] != 'ready':
        raise RuntimeError('Local graph platform is not ready')
    if not args.live:
        return
    state = json.loads(args.state.read_text()) if args.state.exists() else {}

    def save(**updates):
        state.update(updates)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2) + '\n')
        print(json.dumps(updates), flush=True)

    def wait(fetch, status_key='status'):
        deadline = time.monotonic() + 7200
        previous = None
        while time.monotonic() < deadline:
            result = fetch()
            summary = {k: result[k] for k in [status_key, 'progress', 'message', 'error', 'current_round'] if k in result}
            if summary != previous:
                print(json.dumps(summary), flush=True)
                previous = summary
            status = result.get(status_key)
            if status in {'completed', 'ready'}:
                return result
            if status in {'failed', 'stopped'}:
                raise RuntimeError(json.dumps(result))
            time.sleep(3)
        raise TimeoutError('Workflow step did not finish in two hours; state retained for inspection')

    if 'project_id' not in state:
        result = api('graph/ontology/generate', files={'files': ('northstar.txt', DOCUMENT, 'text/plain')},
                     data={'simulation_requirement': REQUIREMENT, 'project_name': 'My Own Researcher — Local Demo'})
        save(project_id=result['project_id'])
    pid = state['project_id']
    if 'graph_task' not in state:
        save(graph_task=api('graph/build', {'project_id': pid})['task_id'])
    if 'graph_id' not in state:
        wait(lambda: api('graph/task/' + state['graph_task']))
        project = api('graph/project/' + pid)
        save(graph_id=project['graph_id'])
    graph = api('graph/data/' + state['graph_id'])
    print(json.dumps({'nodes': len(graph['nodes']), 'edges': len(graph['edges']),
                      'labels': {n['name']: n.get('labels') for n in graph['nodes']}}), flush=True)
    if 'simulation_id' not in state:
        save(simulation_id=api('simulation/create', {'project_id': pid, 'enable_twitter': False,
                                                    'enable_reddit': True})['simulation_id'])
    sid = state['simulation_id']
    if 'prepare_task' not in state:
        result = api('simulation/prepare', {'simulation_id': sid, 'use_llm_for_profiles': True,
                    'parallel_profile_count': 1, 'entity_types': sorted({label for n in graph['nodes']
                    if n['name'] in {'Alice Chen', 'Bob Tan'} for label in n.get('labels', []) if label != 'Entity'})})
        save(prepare_task=result.get('task_id'))
    if not state.get('prepared'):
        wait(lambda: api('simulation/prepare/status', {'simulation_id': sid, 'task_id': state['prepare_task']}))
        save(prepared=True)
    if not state.get('started'):
        # Deterministic activity scheduling for this synthetic demo only. A single
        # midnight round otherwise often selects nobody from daytime profiles.
        config_path = ROOT / 'backend/uploads/simulations' / sid / 'simulation_config.json'
        config = json.loads(config_path.read_text())
        config['time_config'].update(agents_per_hour_min=2, agents_per_hour_max=2,
                                    peak_hours=[], off_peak_hours=[])
        for agent in config['agent_configs']:
            agent.update(active_hours=list(range(24)), activity_level=1.0)
        config_path.write_text(json.dumps(config, indent=2) + '\n')
        api('simulation/start', {'simulation_id': sid, 'platform': 'reddit', 'max_rounds': 1,
                                'enable_graph_memory_update': True, 'force': True})
        save(started=True)
    if not state.get('simulation_complete'):
        result = wait(lambda: api('simulation/' + sid + '/run-status'), 'runner_status')
        save(simulation_complete=True, run_result=result)
    if 'interview' not in state:
        save(interview=api('simulation/interview', {'simulation_id': sid, 'agent_id': 0, 'platform': 'reddit',
            'prompt': 'What should the team do before releasing the research tool? Answer briefly in English.', 'timeout': 300}))
    if 'report_task' not in state:
        save(report_task=api('report/generate', {'simulation_id': sid}).get('task_id'))
    if 'report_id' not in state:
        result = wait(lambda: api('report/generate/status', {'task_id': state['report_task']}
                                  if state.get('report_task') else {'simulation_id': sid}))
        save(report_id=result.get('report_id') or result['result']['report_id'])
    report = api('report/' + state['report_id'])
    assert report['status'] == 'completed', report
    log_path = ROOT / 'backend/uploads/reports' / state['report_id'] / 'agent_log.jsonl'
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert any(event.get('action') == 'tool_call' for event in events), 'Report completed without retrieving evidence'
    assert any(event.get('action') == 'tool_result' and 'Alice Chen' in event['details'].get('result', '')
               and 'Bob Tan' in event['details'].get('result', '') for event in events), 'Report did not retrieve the demo evidence'
    assert state['interview'].get('success'), 'Interview failed'
    print('PASS: document → typed graph → profiles → simulation + graph memory → interview → report', flush=True)
    print('Demo state: ' + str(args.state), flush=True)


if __name__ == '__main__':
    main()
