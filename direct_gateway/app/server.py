from openai import OpenAI

from .api import create_app
from .config import DirectConfig
from .fallback import DeepSeekProvider
from .oauth import DeviceCodeClient
from .provider import ProviderRouter
from .responses_client import ResponsesClient
from .runtime import TokenManager
from .token_store import TokenStore
from .device_sessions import DeviceLoginManager

config = DirectConfig.from_env()
store = TokenStore(config.credentials_path)
manager = TokenManager(store, DeviceCodeClient(config=config))
direct = ResponsesClient(endpoint=config.codex_endpoint, model=config.model, token_manager=manager, timeout=config.request_timeout_seconds)
fallback = None
if __import__("os").environ.get("FALLBACK_LLM_API_KEY"):
    client = OpenAI(api_key=__import__("os").environ["FALLBACK_LLM_API_KEY"], base_url=__import__("os").environ.get("FALLBACK_LLM_BASE_URL"))
    fallback = DeepSeekProvider(client=client, model=__import__("os").environ.get("FALLBACK_LLM_MODEL", "deepseek-chat"))
device_logins = DeviceLoginManager(DeviceCodeClient(config=config), store)
app = create_app(router=ProviderRouter(direct, fallback), config=config, account_reader=store.status, device_logins=device_logins, logout=store.clear)
