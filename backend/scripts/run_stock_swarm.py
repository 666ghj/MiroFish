#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
SQL_DIR = SCRIPT_DIR.parent / "sql"

CompleteFn = Callable[[str], Awaitable[dict[str, Any]]]


def env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val if val not in (None, "") else default


def sanitize_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = parts.hostname
    if not host:
        return None
    out = f"{parts.scheme}://{host}"
    if parts.port:
        out += f":{parts.port}"
    return out


@dataclass
class SwarmConfig:
    agents: int = 8
    rounds: int = 2
    peers: int = 2
    concurrency: int = 4
    max_tokens: int = 512
    seed: int = 1337
    limit: int = 50
    max_retries: int = 3
    base_delay: float = 0.5
    reasoning_effort: str = "none"
    opinion_words: int = 80
    include_hosts: bool = False
    dry_run: bool = False
    output: str = "stock_swarm_result.json"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_name: str | None = None
    clickhouse_url: str | None = None
    clickhouse_user: str | None = None
    clickhouse_password: str | None = None
    clickhouse_database: str | None = None


@dataclass
class CallResult:
    ok: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    content: str | None = None
    error: str | None = None


def validate_config(cfg: SwarmConfig) -> None:
    positive = {
        "agents": cfg.agents,
        "rounds": cfg.rounds,
        "concurrency": cfg.concurrency,
        "max_tokens": cfg.max_tokens,
        "limit": cfg.limit,
        "opinion_words": cfg.opinion_words,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if cfg.peers < 0:
        invalid.append("peers")
    if cfg.max_retries < 0:
        invalid.append("max_retries")
    if cfg.base_delay < 0:
        invalid.append("base_delay")
    if invalid:
        raise ValueError(f"Invalid non-positive configuration: {', '.join(invalid)}")


class RetryableHTTP(Exception):
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError,)):
        return True
    if isinstance(exc, RetryableHTTP):
        return True
    sc = getattr(exc, "status_code", None)
    if sc in (429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__
    if name in ("APITimeoutError", "ConnectError", "ConnectTimeout",
                "ReadTimeout", "RemoteProtocolError"):
        return True
    return False


def percentile(sorted_xs: list[float], q: float) -> float | None:
    if not sorted_xs:
        return None
    k = max(0, math.ceil(q / 100 * len(sorted_xs)) - 1)
    return round(sorted_xs[min(k, len(sorted_xs) - 1)], 3)


def is_valid_opinion(opinion: dict | None) -> bool:
    return bool(opinion and "parse_error" not in opinion and opinion.get("view"))


def summarize(results: list[CallResult], wall_time_s: float,
              opinions: list[dict | None] | None = None) -> dict[str, Any]:
    lat = sorted(r.latency_ms for r in results)
    requests = len(results)
    transport_successes = sum(1 for r in results if r.ok)
    transport_failures = requests - transport_successes
    valid_opinions = (
        sum(1 for opinion in opinions if is_valid_opinion(opinion))
        if opinions is not None else transport_successes
    )
    invalid_opinions = requests - valid_opinions
    prompt_tokens = sum(r.prompt_tokens for r in results)
    completion_tokens = sum(r.completion_tokens for r in results)
    total_tokens = sum(r.total_tokens for r in results)
    wall = wall_time_s if wall_time_s and wall_time_s > 0 else 0.0
    return {
        "requests": requests,
        "successes": valid_opinions,
        "failures": invalid_opinions,
        "transport_successes": transport_successes,
        "transport_failures": transport_failures,
        "valid_opinions": valid_opinions,
        "invalid_opinions": invalid_opinions,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "wall_time_s": round(wall_time_s, 4),
        "input_tokens_per_sec": round(prompt_tokens / wall, 2) if wall else 0.0,
        "output_tokens_per_sec": round(completion_tokens / wall, 2) if wall else 0.0,
        "latency_ms": {
            "p50": percentile(lat, 50),
            "p95": percentile(lat, 95),
            "p99": percentile(lat, 99),
        },
    }


def build_topology(n: int, peers: int, seed: int) -> dict[int, list[int]]:
    if n <= 1:
        return {i: [] for i in range(n)}
    k = min(peers, n - 1)
    rng = random.Random(seed)
    topo: dict[int, list[int]] = {}
    for i in range(n):
        others = [j for j in range(n) if j != i]
        rng.shuffle(others)
        topo[i] = sorted(others[:k])
    return topo


def round1_prompt(ticker: str, dossier_json: str, opinion_words: int) -> str:
    return (
        "You are a stock analyst agent. Ticker: "
        f"{ticker}.\nDossier (JSON):\n{dossier_json}\n"
        "Form an independent opinion. Respond ONLY with valid JSON, no markdown. "
        f"Make analysis approximately {opinion_words} words:\n"
        '{"ticker": "<ticker>", "view": "bullish|bearish|neutral", '
        '"score": 0.0-1.0, "confidence": 0.0-1.0, "thesis": "<one sentence>", '
        '"drivers": ["<driver>", "<driver>", "<driver>"], '
        '"risks": ["<risk>", "<risk>"], "analysis": "<synthesis>"}'
    )


def roundN_prompt(ticker: str, dossier_json: str, own_opinion: dict | None,
                  peers: list[dict], opinion_words: int) -> str:
    own_block = json.dumps(own_opinion, separators=(",", ":"))
    peer_block = json.dumps(peers, separators=(",", ":"))
    return (
        "You are a stock analyst agent. Ticker: "
        f"{ticker}.\nDossier (JSON):\n{dossier_json}\n"
        "Your previous opinion:\n"
        f"{own_block}\n"
        "Your peers' opinions from the previous round:\n"
        f"{peer_block}\n"
        "Revise your opinion considering peers. Respond ONLY with valid JSON, no markdown. "
        f"Make analysis approximately {opinion_words} words:\n"
        '{"ticker": "<ticker>", "view": "bullish|bearish|neutral", '
        '"score": 0.0-1.0, "confidence": 0.0-1.0, "thesis": "<one sentence>", '
        '"drivers": ["<driver>", "<driver>", "<driver>"], '
        '"risks": ["<risk>", "<risk>"], "analysis": "<synthesis>", '
        '"changed": true|false, "revision_note": "<short>"}'
    )


def parse_opinion(content: str | None) -> dict | None:
    if not content:
        return None
    s = content.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j == -1 or j < i:
        return {"parse_error": "no json object", "raw": s[:200]}
    try:
        return json.loads(s[i:j + 1])
    except json.JSONDecodeError as e:
        return {"parse_error": str(e), "raw": s[i:j + 1][:200]}


def load_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def ch_query(sql: str, params: dict[str, Any],
             cfg: SwarmConfig | None = None) -> list[dict]:
    configured_url = cfg.clickhouse_url if cfg else env("CLICKHOUSE_URL")
    if not configured_url:
        raise RuntimeError("CLICKHOUSE_URL is required")
    url = configured_url.rstrip("/") + "/"
    database = (
        cfg.clickhouse_database if cfg and cfg.clickhouse_database
        else env("CLICKHOUSE_DATABASE", "default")
    )
    qs: dict[str, str] = {
        "database": database or "default",
        "default_format": "JSON",
    }
    for k, v in params.items():
        qs[f"param_{k}"] = str(v)
    full = url + "?" + urllib.parse.urlencode(qs)
    user = (
        cfg.clickhouse_user if cfg and cfg.clickhouse_user
        else env("CLICKHOUSE_USER", "default")
    ) or "default"
    password = (
        cfg.clickhouse_password if cfg and cfg.clickhouse_password is not None
        else env("CLICKHOUSE_PASSWORD", "")
    ) or ""
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(
        full, data=sql.encode("utf-8"), method="POST",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ClickHouse HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"ClickHouse unreachable: {e}") from e
    return json.loads(body).get("data", [])


def fetch_ticker_universe(limit: int, cfg: SwarmConfig | None = None) -> list[dict]:
    rows = ch_query(load_sql("ticker_universe.sql"), {"limit": limit}, cfg)
    return [
        {
            "ticker": r["ticker"],
            "name": r.get("name"),
            "sector": r.get("sector"),
            "scale_marketcap": r.get("scale_marketcap"),
        }
        for r in rows
    ]


def fetch_holding_quarter(cfg: SwarmConfig | None = None) -> str:
    rows = ch_query(load_sql("holding_quarter.sql"), {}, cfg)
    if not rows:
        raise RuntimeError("ClickHouse has no fully filed 13F quarter")
    return rows[0]["calendardate"]


def fetch_dossier(ticker: str, holding_quarter: str,
                  cfg: SwarmConfig | None = None) -> dict:
    rows = ch_query(
        load_sql("dossier.sql"),
        {"ticker": ticker, "holding_quarter": holding_quarter},
        cfg,
    )
    if not rows or not rows[0].get("latest_annual_date"):
        raise RuntimeError(f"No fundamentals dossier for {ticker}")
    return rows[0]


async def fetch_live_universe(cfg: SwarmConfig) -> tuple[list[dict], dict[str, Any]]:
    started = time.perf_counter()
    universe_limit = max(cfg.limit, cfg.agents)
    universe_raw, holding_quarter = await asyncio.gather(
        asyncio.to_thread(fetch_ticker_universe, universe_limit, cfg),
        asyncio.to_thread(fetch_holding_quarter, cfg),
    )
    if len(universe_raw) < cfg.agents:
        raise RuntimeError(
            f"Requested {cfg.agents} agents but ClickHouse returned {len(universe_raw)} tickers"
        )
    selected = universe_raw[:cfg.agents]
    ch_sem = asyncio.Semaphore(min(cfg.concurrency, 16))

    async def load(row: dict) -> dict:
        async with ch_sem:
            dossier = await asyncio.to_thread(
                fetch_dossier, row["ticker"], holding_quarter, cfg
            )
        return {**row, "dossier": dossier}

    universe = await asyncio.gather(*(load(row) for row in selected))
    return universe, {
        "wall_time_s": round(time.perf_counter() - started, 4),
        "holding_quarter": holding_quarter,
        "dossiers": len(universe),
    }


def synthetic_universe(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    sectors = ["Tech", "Health", "Energy", "Finance", "Consumer"]
    out = []
    for i in range(n):
        ticker = f"SYNTH{seed % 100:02d}{i:02d}"
        dossier = {
            "ticker": ticker,
            "revenue_annual": round(rng.uniform(1e9, 5e10), 0),
            "netinc_annual": round(rng.uniform(-1e9, 8e9), 0),
            "equity_annual": round(rng.uniform(2e9, 3e10), 0),
            "roe": round(rng.uniform(-0.1, 0.4), 4),
            "roe_percentile": round(rng.random(), 4),
            "holder_count": rng.randint(50, 1200),
            "synthetic": True,
        }
        out.append({"ticker": ticker, "name": f"Synthetic Co {i}",
                    "sector": rng.choice(sectors), "dossier": dossier})
    return out


class FakeLLM:

    def __init__(self, seed: int, fail_first: int = 0, delay: float = 0.0):
        self.seed = seed
        self.fail_first = fail_first
        self.delay = delay
        self.calls = 0

    async def complete(self, prompt: str) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RetryableHTTP(429, "dry-run forced 429")
        if self.delay:
            await asyncio.sleep(self.delay)
        h = hashlib.sha256(f"{self.seed}:{prompt}".encode()).hexdigest()
        views = ["bullish", "bearish", "neutral"]
        view = views[int(h[:2], 16) % 3]
        score = (int(h[2:4], 16) % 100) / 100
        conf = (int(h[4:6], 16) % 100) / 100
        changed = "Your previous opinion:" in prompt
        obj = {
            "view": view, "score": round(score, 3),
            "confidence": round(conf, 3), "thesis": "synthetic thesis",
            "changed": changed,
            "revision_note": "peer-adjusted" if changed else "initial",
        }
        prompt_tokens = 40 + len(prompt) % 60
        completion_tokens = 60 + int(h[:2], 16) % 40
        return {
            "content": json.dumps(obj, separators=(",", ":")),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }


def build_complete_fn(cfg: SwarmConfig) -> CompleteFn:
    if cfg.dry_run:
        return FakeLLM(cfg.seed).complete
    if not (cfg.llm_api_key and cfg.llm_base_url and cfg.llm_model_name):
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME required when not --dry-run")
    client = AsyncOpenAI(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        max_retries=0,
        timeout=120.0,
    )
    model = cfg.llm_model_name
    max_tokens = cfg.max_tokens
    effort = cfg.reasoning_effort.strip() if cfg.reasoning_effort else ""

    async def real_complete(prompt: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if effort:
            kwargs["reasoning_effort"] = effort
        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0] if resp.choices else None
        message = choice.message if choice else None
        content = (message.content if message else None) or ""
        if not content and message:
            content = (message.model_extra or {}).get("reasoning_content", "")
        usage = resp.usage
        return {
            "content": content,
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }

    return real_complete


async def invoke(complete_fn: CompleteFn, prompt: str, sem: asyncio.Semaphore,
                 max_retries: int, base_delay: float) -> CallResult:
    start = time.perf_counter()
    async with sem:
        last_err: str | None = None
        for attempt in range(max_retries + 1):
            try:
                res = await complete_fn(prompt)
                latency = (time.perf_counter() - start) * 1000
                return CallResult(
                    ok=True, latency_ms=latency,
                    prompt_tokens=int(res.get("prompt_tokens", 0)),
                    completion_tokens=int(res.get("completion_tokens", 0)),
                    total_tokens=int(res.get("total_tokens", 0)),
                    content=res.get("content"),
                )
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if not is_retryable(e) or attempt == max_retries:
                    latency = (time.perf_counter() - start) * 1000
                    return CallResult(ok=False, latency_ms=latency, error=last_err)
                delay = base_delay * (2 ** attempt)
                if delay:
                    await asyncio.sleep(delay + random.uniform(0, max(delay * 0.25, 0.01)))
        latency = (time.perf_counter() - start) * 1000
        return CallResult(ok=False, latency_ms=latency, error=last_err or "unknown")


async def run_agent(idx: int, ticker_info: dict, rnd: int,
                    opinions_prev: dict[int, dict], complete_fn: CompleteFn,
                    topology: dict[int, list[int]], ticker_info_by_idx: list[dict],
                    cfg: SwarmConfig,
                    sem: asyncio.Semaphore) -> tuple[int, CallResult, dict | None]:
    ticker = ticker_info["ticker"]
    dossier = ticker_info.get("dossier", {})
    if rnd == 1:
        prompt = round1_prompt(
            ticker, json.dumps(dossier, separators=(",", ":")), cfg.opinion_words
        )
    else:
        peer_idxs = topology[idx]
        peers = [
            {
                "peer_ticker": ticker_info_by_idx[j]["ticker"],
                "opinion": opinions_prev[j],
            }
            for j in peer_idxs
            if j in opinions_prev
        ]
        prompt = roundN_prompt(
            ticker,
            json.dumps(dossier, separators=(",", ":")),
            opinions_prev.get(idx),
            peers,
            cfg.opinion_words,
        )
    cr = await invoke(complete_fn, prompt, sem, cfg.max_retries, cfg.base_delay)
    opinion = parse_opinion(cr.content) if cr.ok else None
    return idx, cr, opinion


async def run_swarm(cfg: SwarmConfig) -> dict[str, Any]:
    return await run_swarm_with_complete(cfg, build_complete_fn(cfg))


async def run_swarm_with_complete(cfg: SwarmConfig, complete_fn: CompleteFn) -> dict[str, Any]:
    validate_config(cfg)
    if cfg.dry_run:
        setup_started = time.perf_counter()
        universe = synthetic_universe(cfg.agents, cfg.seed)
        setup = {
            "wall_time_s": round(time.perf_counter() - setup_started, 4),
            "holding_quarter": None,
            "dossiers": len(universe),
        }
    else:
        universe, setup = await fetch_live_universe(cfg)
    tickers = universe[:cfg.agents]
    n = len(tickers)
    topology = build_topology(n, cfg.peers, cfg.seed)
    sem = asyncio.Semaphore(cfg.concurrency)

    rounds_out: list[dict] = []
    round_metrics: list[dict] = []
    all_results: list[CallResult] = []
    all_opinions: list[dict | None] = []
    errors: list[dict] = []
    opinions_prev: dict[int, dict] = {}
    overall_start = time.perf_counter()

    for rnd in range(1, cfg.rounds + 1):
        opinions_input = opinions_prev.copy()
        rstart = time.perf_counter()
        tasks = [
            asyncio.create_task(run_agent(i, tickers[i], rnd, opinions_input,
                                          complete_fn, topology, tickers, cfg, sem))
            for i in range(n)
        ]
        results = await asyncio.gather(*tasks)
        wall = time.perf_counter() - rstart
        round_results = [cr for _, cr, _ in results]
        round_opinions = [opinion for _, _, opinion in results]
        all_results.extend(round_results)
        all_opinions.extend(round_opinions)
        round_metrics.append(summarize(round_results, wall, round_opinions))
        agents_out = []
        for idx, cr, opinion in results:
            opinion_ok = cr.ok and is_valid_opinion(opinion)
            peer_opinions_received = sum(
                1 for peer_idx in topology[idx] if peer_idx in opinions_input
            ) if rnd > 1 else 0
            entry = {
                "agent_id": idx,
                "ticker": tickers[idx]["ticker"],
                "ok": opinion_ok,
                "request_ok": cr.ok,
                "opinion_ok": opinion_ok,
                "peer_opinions_received": peer_opinions_received,
                "latency_ms": round(cr.latency_ms, 3),
                "prompt_tokens": cr.prompt_tokens,
                "completion_tokens": cr.completion_tokens,
                "total_tokens": cr.total_tokens,
                "opinion": opinion,
                "error": cr.error,
            }
            agents_out.append(entry)
            if opinion_ok:
                opinions_prev[idx] = opinion
            if not cr.ok:
                errors.append({
                    "round": rnd,
                    "agent_id": idx,
                    "ticker": tickers[idx]["ticker"],
                    "kind": "request",
                    "error": cr.error,
                })
            elif not opinion_ok:
                errors.append({
                    "round": rnd,
                    "agent_id": idx,
                    "ticker": tickers[idx]["ticker"],
                    "kind": "opinion_parse",
                    "error": (opinion or {}).get("parse_error", "missing view"),
                })
        rounds_out.append({"round": rnd, "wall_time_s": round(wall, 4), "agents": agents_out})

    total_wall = time.perf_counter() - overall_start
    return {
        "config": {
            "mode": "dry-run" if cfg.dry_run else "live",
            "model_name": cfg.llm_model_name,
            "reasoning_effort": cfg.reasoning_effort,
            "agents": n,
            "rounds": cfg.rounds,
            "peers": cfg.peers,
            "concurrency": cfg.concurrency,
            "max_tokens": cfg.max_tokens,
            "opinion_words": cfg.opinion_words,
            "seed": cfg.seed,
            "limit": cfg.limit,
            "max_retries": cfg.max_retries,
            "llm_base_url": sanitize_url(cfg.llm_base_url) if cfg.include_hosts else None,
            "clickhouse_url": sanitize_url(cfg.clickhouse_url) if cfg.include_hosts else None,
        },
        "topology": [
            {
                "agent_id": idx,
                "ticker": tickers[idx]["ticker"],
                "peers": [tickers[j]["ticker"] for j in topology[idx]],
            }
            for idx in range(n)
        ],
        "metrics": {
            "setup": setup,
            "total": summarize(all_results, total_wall, all_opinions),
            "rounds": round_metrics,
        },
        "rounds": rounds_out,
        "errors": errors,
    }


def build_config_from_env(args: argparse.Namespace) -> SwarmConfig:
    cfg = SwarmConfig(
        agents=args.agents, rounds=args.rounds, peers=args.peers,
        concurrency=args.concurrency, max_tokens=args.max_tokens,
        seed=args.seed, limit=args.limit, max_retries=args.max_retries,
        base_delay=args.base_delay, reasoning_effort=args.reasoning_effort,
        opinion_words=args.opinion_words, include_hosts=args.include_hosts,
        dry_run=args.dry_run, output=args.output,
        llm_base_url=env("LLM_BASE_URL"), llm_api_key=env("LLM_API_KEY"),
        llm_model_name=env("LLM_MODEL_NAME"),
        clickhouse_url=env("CLICKHOUSE_URL"), clickhouse_user=env("CLICKHOUSE_USER"),
        clickhouse_password=env("CLICKHOUSE_PASSWORD"),
        clickhouse_database=env("CLICKHOUSE_DATABASE"),
    )
    if not cfg.dry_run:
        missing = [k for k, v in {
            "CLICKHOUSE_URL": cfg.clickhouse_url,
            "LLM_BASE_URL": cfg.llm_base_url,
            "LLM_API_KEY": cfg.llm_api_key,
            "LLM_MODEL_NAME": cfg.llm_model_name,
        }.items() if not v]
        if missing:
            raise SystemExit(f"Missing required env (not --dry-run): {', '.join(missing)}")
    return cfg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stock-agent P2P throughput PoC")
    p.add_argument("--agents", type=int, default=8)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--peers", type=int, default=2)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--limit", type=int, default=50, help="universe fetch cap")
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--base-delay", type=float, default=0.5)
    p.add_argument("--reasoning-effort", default="none",
                   help="none|low|medium|high; empty string to omit the param")
    p.add_argument("--opinion-words", type=int, default=80)
    p.add_argument("--include-hosts", action="store_true")
    p.add_argument("--output", default="stock_swarm_result.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    cfg = build_config_from_env(args)
    try:
        validate_config(cfg)
    except ValueError as exc:
        p.error(str(exc))
    output = asyncio.run(run_swarm(cfg))
    output_path = Path(cfg.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    total = output["metrics"]["total"]
    print(f"agents={output['config']['agents']} rounds={cfg.rounds} "
          f"requests={total['requests']} ok={total['successes']} "
          f"fail={total['failures']} total_tokens={total['total_tokens']} "
          f"in_tok/s={total['input_tokens_per_sec']} "
          f"out_tok/s={total['output_tokens_per_sec']} "
          f"p50={total['latency_ms']['p50']}ms p95={total['latency_ms']['p95']}ms "
          f"-> {cfg.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
