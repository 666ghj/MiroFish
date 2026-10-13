"""Adapt schema-constrained agent output to MiroFish/CAMEL completions.

Tool decisions are validated data, not native CLI tool execution. CAMEL owns
the action loop and supplies tool results in the next request's history.
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

import jsonschema
from openai.types.chat import ChatCompletion

from research_agents import ProviderError, get_provider, model_name, run_agent


def _envelope_schema(names: list[str]) -> dict:
    name_schema = {'type': 'string'}
    if names:
        name_schema['enum'] = names
    return {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'content': {'type': 'string'},
            'tool_calls': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'name': name_schema, 'arguments': {'type': 'string'}},
                'required': ['name', 'arguments'],
            }},
        },
        'required': ['content', 'tool_calls'],
    }


class AgentClient:
    """Small Chat Completions-compatible surface; no network API client."""

    def __init__(self, provider=None):
        self.provider = get_provider(provider).id
        self.chat = SimpleNamespace(completions=self)

    def _infer(self, prompt, schema, cancel_event=None):
        return run_agent(prompt, schema, cancel_event=cancel_event, provider=self.provider)

    def create(self, *, messages: list[dict], model: str | None = None,
               tools: list[dict] | None = None, tool_choice=None,
               response_format: dict | None = None, stream: bool = False,
               temperature=None, max_tokens=None, max_completion_tokens=None,
               parallel_tool_calls: bool = True, n: int = 1,
               _cancel_event=None, **kwargs) -> ChatCompletion:
        if stream:
            raise ValueError('Agent provider does not support streaming Chat Completions.')
        if n != 1 or kwargs:
            raise ValueError('Unsupported Agent completion options: ' + ', '.join(kwargs or ['n']))
        if not messages or any(not isinstance(m, dict) for m in messages):
            raise ValueError('Agent requires a nonempty conversation.')
        available = {}
        for tool in tools or []:
            if tool.get('type') != 'function':
                raise ValueError('Agent provider only supports simulation function tools.')
            function = tool['function']
            name = function['name']
            if name in available:
                raise ValueError('Duplicate simulation function name.')
            jsonschema.Draft202012Validator.check_schema(function.get('parameters', {}))
            available[name] = function
        forced = None
        if isinstance(tool_choice, dict):
            forced = tool_choice.get('function', {}).get('name')
            if tool_choice.get('type') != 'function' or forced not in available:
                raise ValueError('Unknown forced simulation function.')
        elif tool_choice not in (None, 'auto', 'none', 'required'):
            raise ValueError('Unsupported tool_choice.')
        if tool_choice == 'required' and not available:
            raise ValueError('tool_choice requires simulation tools.')
        format_type = (response_format or {}).get('type', 'text')
        if format_type not in ('text', 'json_object', 'json_schema'):
            raise ValueError('Unsupported response_format.')
        content_schema = None
        if format_type == 'json_schema':
            content_schema = response_format['json_schema']['schema']
            jsonschema.Draft202012Validator.check_schema(content_schema)

        allowed_names = [] if tool_choice == 'none' else ([forced] if forced else list(available))
        schema = _envelope_schema(allowed_names)
        prompt = (
            'Generate the next assistant response for this conversation. Preserve the persona '
            'and obey its system/developer messages. Prior assistant tool_calls and tool results '
            'are conversation history, not new actions. Return a JSON envelope with content '
            '(assistant text) and tool_calls (array of name and JSON-encoded arguments strings). '
            'If choosing actions, put them in tool_calls; the simulation will execute them. '
            'Never execute actions yourself. If responding with text, use tool_calls=[].\n'
            + 'Conversation: ' + json.dumps(messages, ensure_ascii=False)
            + '\nContent response format: ' + json.dumps(response_format or {'type': 'text'})
        )
        if available:
            prompt += (
                '\nAvailable simulation functions: ' + json.dumps(list(available.values()), ensure_ascii=False)
                + '\nAllowed function names: ' + json.dumps(allowed_names)
                + '\nTool choice: ' + json.dumps(tool_choice or 'auto')
                + '\nAllow multiple actions: ' + json.dumps(parallel_tool_calls)
            )
        else:
            prompt += (
                '\nSet the envelope tool_calls array to []. The conversation may define a '
                'TEXT protocol for the host application, such as <tool_call> JSON blocks. '
                'When requested, write those blocks literally inside content; the host '
                'application dispatches those requests and supplies observations next turn. '
                'Those text protocol tools are available exactly as described in the '
                'conversation, independently of native CLI or structured function tools. '
                'Do not execute anything yourself or invent observations.'
            )
        if format_type != 'text':
            prompt += '\nThe content STRING must itself encode valid JSON matching the requested format.'
        result, usage = self._infer(prompt, schema, cancel_event=_cancel_event)
        try:
            jsonschema.validate(result, schema)
        except (jsonschema.ValidationError, TypeError):
            raise ProviderError('Agent returned an invalid response envelope.') from None
        calls = result['tool_calls']
        if not parallel_tool_calls and len(calls) > 1:
            raise ProviderError('Agent returned multiple actions when only one was allowed.')
        if (tool_choice == 'required' or forced) and not calls:
            raise ProviderError('Agent did not return the required simulation action.')
        converted = []
        for call in calls:
            name = call['name']
            if name not in allowed_names:
                raise ProviderError('Agent selected an unavailable simulation action.')
            try:
                arguments = json.loads(call['arguments'])
                if not isinstance(arguments, dict):
                    raise ValueError('Function arguments must be an object.')
                jsonschema.validate(arguments, available[name].get('parameters', {}))
            except (ValueError, jsonschema.ValidationError):
                raise ProviderError('Agent returned invalid simulation action arguments.') from None
            converted.append({
                'id': 'call_' + uuid.uuid4().hex, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)},
            })
        content = result['content']
        if not converted:
            if not content.strip():
                raise ProviderError('Agent returned an empty response.')
            if format_type != 'text':
                try:
                    parsed = json.loads(content)
                    if format_type == 'json_object' and not isinstance(parsed, dict):
                        raise ValueError('Expected an object')
                    if content_schema is not None:
                        jsonschema.validate(parsed, content_schema)
                except (ValueError, jsonschema.ValidationError):
                    raise ProviderError('Agent returned invalid JSON object or schema output.') from None
        try:
            prompt_tokens = int(usage.get('input_tokens', 0))
            completion_tokens = int(usage.get('output_tokens', 0))
            if prompt_tokens < 0 or completion_tokens < 0:
                raise ValueError()
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise ProviderError('Agent returned invalid token usage.') from None
        return ChatCompletion(
            id='chatcmpl-' + self.provider + '-' + uuid.uuid4().hex, object='chat.completion',
            created=int(time.time()), model=model_name(self.provider),
            choices=[{'index': 0, 'finish_reason': 'tool_calls' if converted else 'stop',
                      'message': {'role': 'assistant', 'content': content or None,
                                  'tool_calls': converted or None}}],
            usage={'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                   'total_tokens': prompt_tokens + completion_tokens},
        )
