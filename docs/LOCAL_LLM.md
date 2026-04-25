# Running MiroFish with a Local LLM

MiroFish talks to any **OpenAI-compatible** chat endpoint, so you can swap the cloud provider for a local runtime such as **LM Studio**, **Ollama**, or **llama.cpp server**. This document covers the moving parts.

> Zep Cloud is still required for the memory graph — only the LLM call path can be replaced. See [Limitations](#limitations) below.

## TL;DR

```env
# .env
LLM_API_KEY=local-anything       # any non-empty string
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL_NAME=<the model id your runtime exposes>
LLM_JSON_MODE=none               # IMPORTANT for LM Studio / llama.cpp
ZEP_API_KEY=<your zep cloud key>
```

The single critical knob is **`LLM_JSON_MODE=none`**. Cloud providers accept `response_format={"type":"json_object"}`, but most local runtimes reject it with HTTP 400. Setting `LLM_JSON_MODE=none` makes MiroFish skip that parameter and rely on prompt-driven JSON output, which the existing parser handles robustly.

## Provider quick reference

| Runtime | `LLM_BASE_URL` | `LLM_JSON_MODE` | Notes |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `json_object` (default) | Strict JSON via `response_format` |
| Anthropic (OpenAI-compat) | `https://api.anthropic.com/v1/` | `none` | Trailing slash matters; rejects `json_object` |
| Qwen / Dashscope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `json_object` | Project default |
| Ollama | `http://localhost:11434/v1` | `json_object` | Ollama mostly accepts it |
| **LM Studio** | `http://localhost:1234/v1` | **`none`** | Returns 400 if `response_format` is sent |
| llama.cpp server | `http://localhost:8080/v1` | `none` | Same constraint as LM Studio |
| vLLM | depends on deploy | `json_object` | Generally OpenAI-faithful |

## Recipe: LM Studio (recommended on Apple Silicon)

LM Studio ships an OpenAI-compatible server backed by an MLX runtime that is currently the most reliable option on **macOS Tahoe + Apple Silicon (M1–M5)**. See [Apple Silicon caveats](#apple-silicon-caveats) for why Ollama is not recommended on that combination right now.

```bash
# 1. Install (Homebrew cask, or download from https://lmstudio.ai)
brew install --cask lm-studio

# 2. Open LM Studio once to complete the first-run flow.
#    The CLI is bootstrapped at ~/.lmstudio/bin/lms after that.

# 3. Make `lms` available in your shell
export PATH="$HOME/.lmstudio/bin:$PATH"

# 4. Pull a chat-tuned model in MLX format. Examples:
lms get qwen/qwen3-4b-2507 --mlx -y          # ~2.3 GB, fast, instruction-tuned
# lms get qwen/qwen3-coder-30b --mlx -y      # only if you have the RAM

# 5. Start the server with CORS enabled
lms server start --cors

# 6. Load the model with a generous context window
lms load qwen/qwen3-4b-2507 --gpu max --context-length 32768 -y
```

Then in `.env`:

```env
LLM_API_KEY=lm-studio-local
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL_NAME=qwen/qwen3-4b-2507
LLM_JSON_MODE=none
```

Smoke-test the endpoint before starting MiroFish:

```bash
curl -sS http://localhost:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3-4b-2507","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":10}'
```

If you see a normal completion, you're good. Now run `npm run dev` from the repo root.

### Why `--context-length 32768`?

Ontology generation feeds **all** of your uploaded documents into a single prompt. With four medium-sized PDFs (~30 KB extracted text) you'll need ~8k tokens of input, plus headroom for the model's response. The default 4k context window will fail with `The number of tokens to keep from the initial prompt is greater than the context length`. 32k is a safe choice on a 16 GB Mac; raise it on machines with more RAM if you're loading more documents.

## Recipe: Ollama

```bash
ollama pull qwen2.5:7b-instruct
ollama serve
```

```env
LLM_API_KEY=ollama-local
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:7b-instruct
LLM_JSON_MODE=json_object   # Ollama accepts the param
```

## Apple Silicon caveats

If you're on **macOS 26 (Tahoe)** with an **M3/M4/M5** chip, Ollama versions ≤ 0.21 fail to compile their Metal shaders against the updated `MetalPerformancePrimitives` framework, terminating every model load with `static_assert failed [bfloat/half] ... panic: unable to create llama context`. Tracked upstream in [ollama/ollama#15748](https://github.com/ollama/ollama/issues/15748) and [#15594](https://github.com/ollama/ollama/issues/15594).

Until that's resolved, prefer **LM Studio** on those machines. Its MLX runtime side-steps the broken Metal path.

## Memory & throughput expectations

A typical MiroFish simulation (200–500 agents × 30 rounds × 2 platforms) issues thousands of LLM calls. On a 16 GB MacBook with a local 4B model:

- A single round can take **5–15 minutes** when the model is the bottleneck.
- A full simulation can run for **hours** and may exhaust RAM (`backend` Python + `LM Studio` model + `frontend` Node + `Zep` cache).
- Concurrent requests can crash the MLX runtime under memory pressure, surfaced as `The model has crashed without additional information`.

If you need 200+ agents over many rounds, a cloud LLM (Claude Haiku, GPT-4o-mini, Qwen-plus) is dramatically cheaper in wall-clock time and frees RAM for everything else.

For first-time validation, **start with a 20-agent / 3-round smoke test** to confirm the pipeline before committing to a long run.

## Limitations

- **Zep Cloud is still required.** MiroFish hardcodes the `zep_cloud` SDK in several services (`zep_tools.py`, `graph_builder.py`, `zep_graph_memory_updater.py`, `zep_entity_reader.py`). There is no `ZEP_BASE_URL` knob today, so Zep self-hosting requires a code patch. The free Zep tier (5 req/min) is enough for small simulations; busier ones will benefit from a paid tier.
- **Embeddings are handled by Zep**, not the local LLM. Your local runtime does not need an embeddings endpoint.
- **MiroFish prompts are written in Chinese internally.** Local models with weaker multilingual coverage may inject Chinese phrases into otherwise English/Portuguese outputs. Cloud models handle this gracefully.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `400 - 'response_format.type' must be 'json_schema' or 'text'` | Runtime rejects `json_object` | Set `LLM_JSON_MODE=none` |
| `400 - The number of tokens to keep from the initial prompt is greater than the context length` | Context window too small for combined seed documents | Reload model with `--context-length 32768` (or higher) |
| `The model has crashed without additional information` | MLX runtime OOM under concurrency | Reduce agent count, lower context length, or switch to a cloud LLM |
| `panic: unable to create llama context` (Ollama) | macOS Tahoe + Apple Silicon Metal bug | Use LM Studio instead — see [Apple Silicon caveats](#apple-silicon-caveats) |
| Zep `429 Rate limit exceeded for FREE plan` | Free tier is 5 req/min | Reduce simulation size, or upgrade Zep, or close the UI tab to stop graph polling |
