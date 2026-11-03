"""Apply the requested output language before OASIS agents start interacting."""

import os


def apply_output_language(agent_graph):
    language = os.environ.get('MIROFISH_OUTPUT_LANGUAGE', '').strip()
    if language:
        # CAMEL's setter refreshes the system message and resets conversation
        # memory, so call it only on a freshly created agent graph.
        for _, agent in agent_graph.get_agents():
            agent.output_language = language


def interview_prompt(prompt: str) -> str:
    """OASIS interviews rebuild their system prompt, so repeat the language here."""
    language = os.environ.get('MIROFISH_OUTPUT_LANGUAGE', '').strip()
    return f'{prompt}\n\nRespond in {language}.' if language else prompt
