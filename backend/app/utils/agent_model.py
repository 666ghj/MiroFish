"""CAMEL model backend using the same Agent transport as MiroFish services."""

import asyncio
import threading

from camel.models import BaseModelBackend
from camel.types import ModelType, UnifiedModelType
from camel.utils import OpenAITokenCounter

from .agent_provider import AgentClient
from research_agents import model_name


class AgentModel(BaseModelBackend):
    def __init__(self, provider=None):
        super().__init__(model_name(provider), {})
        self.client = AgentClient(provider)

    @property
    def token_counter(self):
        # Approximation for CAMEL's history budgeting, not a billing estimate.
        if self._token_counter is None:
            self._token_counter = OpenAITokenCounter(UnifiedModelType(ModelType.GPT_4O))
        return self._token_counter

    @property
    def token_limit(self):
        # Conservative history budget; leaves room for Agent instructions/tools.
        return 32768

    def _run(self, messages, response_format=None, tools=None, *, _cancel_event=None):
        format_dict = None
        if response_format is not None:
            format_dict = {'type': 'json_schema', 'json_schema': {
                'name': response_format.__name__, 'schema': response_format.model_json_schema(),
            }}
        response = self.client.chat.completions.create(
            model=str(self.model_type), messages=messages, tools=tools,
            response_format=format_dict, _cancel_event=_cancel_event,
        )
        if response_format is not None and not response.choices[0].message.tool_calls:
            message = response.choices[0].message
            message.parsed = response_format.model_validate_json(message.content)
        return response

    async def _arun(self, messages, response_format=None, tools=None):
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(
            self._run, messages, response_format, tools, _cancel_event=cancelled,
        ))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            raise
