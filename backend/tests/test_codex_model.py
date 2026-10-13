import asyncio
import importlib
import json

import pytest
from pydantic import BaseModel

from test_codex_provider import fake_codex


def test_camel_model_supports_sync_and_async_completions(fake_codex):
    from app.utils.codex_model import CodexModel
    model = CodexModel()
    messages = [{'role': 'user', 'content': 'Say hello'}]
    assert model.run(messages).choices[0].message.content == 'Hello'
    assert asyncio.run(model.arun(messages)).choices[0].message.content == 'Hello'
    assert model.token_limit == 32768
    assert model.token_counter.count_tokens_from_messages(messages) > 0


def test_camel_schema_output_is_parsed(fake_codex):
    from app.utils.codex_model import CodexModel

    class Answer(BaseModel):
        count: int

    fake_codex.write_text(json.dumps({'content': '{"count":3}'}))
    response = CodexModel().run([{'role': 'user', 'content': 'Count'}], response_format=Answer)
    assert response.choices[0].message.parsed.count == 3


def test_camel_chat_agent_executes_returned_function(fake_codex, monkeypatch):
    from app.utils.codex_model import CodexModel
    from camel.agents import ChatAgent
    from camel.toolkits import FunctionTool

    posts = []

    def create_post(content: str) -> str:
        """Create a simulated post.

        Args:
            content: The post text.
        """
        posts.append(content)
        fake_codex.write_text(json.dumps({'content': 'Posted.'}))
        return 'created'

    fake_codex.write_text(json.dumps({'content': '', 'tool_calls': [
        {'name': 'create_post', 'arguments': '{"content":"Hello simulation"}'}]}))
    agent = ChatAgent('You are Alice.', model=CodexModel(), tools=[FunctionTool(create_post)])
    response = agent.step('Create a greeting post.')
    assert posts == ['Hello simulation']
    assert response.msgs[0].content == 'Posted.'


@pytest.mark.parametrize('runner', ['twitter', 'reddit', 'parallel', 'parallel_boost'])
def test_every_runner_selects_codex_without_api_key(monkeypatch, runner):
    from app.utils.codex_model import CodexModel
    monkeypatch.setenv('LLM_PROVIDER', 'codex')
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('LLM_BOOST_API_KEY', 'ignored-boost')
    if runner.startswith('parallel'):
        module = importlib.import_module('scripts.run_parallel_simulation')
        model = module.create_model({}, use_boost=runner.endswith('boost'))
    else:
        module = importlib.import_module(f'scripts.run_{runner}_simulation')
        cls = getattr(module, f'{runner.title()}SimulationRunner')
        instance = object.__new__(cls)
        instance.config = {}
        model = instance._create_model()
    assert isinstance(model, CodexModel)


def test_cancelled_async_request_kills_codex_process(fake_codex, tmp_path):
    import os
    from app.utils.codex_model import CodexModel
    pid_file = tmp_path / 'pid'
    fake_codex.write_text(json.dumps({'sleep': 3, 'pid_file': str(pid_file)}))

    async def scenario():
        task = asyncio.create_task(CodexModel().arun([{'role': 'user', 'content': 'Hello'}]))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.02)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    asyncio.run(scenario())


def test_simulation_propagates_errors_returned_by_oasis(monkeypatch):
    from types import SimpleNamespace
    from app.utils.codex_transport import CodexProviderError
    from app.utils.simulation_env import CodexSimulationEnv

    async def failed_action():
        return CodexProviderError('Codex usage limit reached')

    env = object.__new__(CodexSimulationEnv)
    env.llm_semaphore = asyncio.Semaphore(1)
    agent = SimpleNamespace(perform_action_by_llm=failed_action)
    with pytest.raises(CodexProviderError, match='usage limit'):
        asyncio.run(env._perform_llm_action(agent))
