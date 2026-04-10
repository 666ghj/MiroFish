"""
Quick test: MiroFish LLMClient → LM Studio via Prompture
"""
import sys, os

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override env vars for LM Studio before Config loads
os.environ["LLM_MODEL_NAME"] = "lmstudio/deepseek/deepseek-r1-0528-qwen3-8b"
os.environ["LLM_BASE_URL"] = "http://localhost:1234/v1"
os.environ["LLM_API_KEY"] = "lm-studio"
# Provide a dummy ZEP key so Config.validate() won't complain
os.environ.setdefault("ZEP_API_KEY", "dummy")

from app.utils.llm_client import LLMClient

def test_basic_chat():
    print("=== Test 1: Basic chat ===")
    client = LLMClient()
    from app.utils.llm_client import _HAS_PROMPTURE
    print(f"  Backend: Prompture={_HAS_PROMPTURE}")
    print(f"  Model:   {client.model}")
    response = client.chat([
        {"role": "system", "content": "You are a helpful assistant. Reply in one sentence."},
        {"role": "user", "content": "What is social media simulation?"},
    ], temperature=0.5, max_tokens=256)
    print(f"  Response: {response[:300]}")
    print()

def test_json_chat():
    print("=== Test 2: JSON response ===")
    client = LLMClient()
    result = client.chat_json([
        {"role": "system", "content": "You are a JSON-only assistant. Always respond with valid JSON."},
        {"role": "user", "content": 'Return a JSON object with keys "platform" and "agents" (an integer). Example: {"platform":"twitter","agents":5}'},
    ], temperature=0.2, max_tokens=256)
    print(f"  Parsed JSON: {result}")
    print(f"  Type: {type(result)}")
    print()

def test_multi_turn():
    print("=== Test 3: Multi-turn conversation ===")
    client = LLMClient()
    r1 = client.chat([
        {"role": "user", "content": "My name is MiroFish. Remember it."},
    ], max_tokens=128)
    print(f"  Turn 1: {r1[:200]}")

    r2 = client.chat([
        {"role": "user", "content": "My name is MiroFish. Remember it."},
        {"role": "assistant", "content": r1},
        {"role": "user", "content": "What is my name?"},
    ], max_tokens=128)
    print(f"  Turn 2: {r2[:200]}")
    print()

if __name__ == "__main__":
    print(f"Prompture installed: True")
    print(f"LM Studio endpoint: http://localhost:1234/v1\n")
    try:
        test_basic_chat()
        test_json_chat()
        test_multi_turn()
        print("All tests passed!")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
