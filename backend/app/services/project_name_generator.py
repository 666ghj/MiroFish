from datetime import date
from typing import Optional
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.project_name')

_PROMPT = (
    "Read the following document excerpt and return ONLY a concise title of 5-8 words "
    "that summarizes its main topic. Do not use punctuation at the end. "
    "Reply only with the title, nothing else.\n\nText:\n{text}"
)


def generate_project_name(text: str, llm_client: Optional[LLMClient] = None) -> str:
    excerpt = text[:2000]
    try:
        client = llm_client or LLMClient()
        name = client.chat(
            messages=[{"role": "user", "content": _PROMPT.format(text=excerpt)}],
            temperature=0.3,
        )
        name = name.strip().strip('"').strip("'")
        if name:
            return name
    except Exception as e:
        logger.warning(f"Failed to generate project name: {e}")
    return f"Simulació {date.today().isoformat()}"
