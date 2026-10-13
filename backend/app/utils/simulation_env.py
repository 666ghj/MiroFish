"""Preserve provider failures that OASIS otherwise returns as action results."""

import os

import oasis
from oasis.environment.env import OasisEnv


class CodexSimulationEnv(OasisEnv):
    async def _perform_llm_action(self, agent):
        result = await super()._perform_llm_action(agent)
        if isinstance(result, Exception):
            raise result
        return result


def make_simulation_env(*args, **kwargs):
    if os.environ.get('LLM_PROVIDER', 'openai').strip().lower() == 'codex':
        return CodexSimulationEnv(*args, **kwargs)
    return oasis.make(*args, **kwargs)
