#!/usr/bin/env python3
"""Concurrency benchmark for the Promon AI Gateway (LiteLLM).

Simulates N concurrent "users" hitting the OpenAI-compatible /chat/completions
endpoint for a fixed duration, then reports latency distributions, error rate,
and throughput per model. No pass/fail thresholds — just what happened.

Cloud models (claude-general/gpt-general/gemini-general) cost real money per
call, so they're excluded unless you explicitly pass --include-cloud.

Usage:
    pip install httpx

    python3 scripts/benchmark_gateway.py \
        --base-url https://ai-gateway.promon.co.in \
        --api-key sk-... \
        --cacert fetched-certs/ai-gateway.promon.co.in.crt \
        --concurrency 20 --duration 300

    # include cloud models too (real cost — see the printed warning)
    python3 scripts/benchmark_gateway.py ... --include-cloud
"""
import argparse
import asyncio
import csv
import random
import statistics
import string
import sys
import time
from dataclasses import dataclass, field

import httpx

LOCAL_MODELS = ["local-qwen25"]

CLOUD_MODELS = ["claude-general", "gpt-general", "gemini-general"]

# A couple of fixed prompts (repeated across users — exercises the Valkey
# cache) plus a template for unique prompts (a random nonce defeats the
# cache, giving you an uncached-latency baseline to compare against).
FIXED_PROMPTS = [
    "In one sentence, what is the capital of France?",
    "Summarize the purpose of a load balancer in 2 sentences.",
]
UNIQUE_PROMPT_TEMPLATE = "Nonce {nonce}: write one sentence about {topic}."
TOPICS = ["databases", "networking", "kubernetes", "compilers", "caching", "DNS"]


@dataclass
class Result:
    model: str
    latency_ms: float
    status_code: int
    error: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cacheable: bool = False


@dataclass
class Args:
    base_url: str
    api_key: str
    cacert: str | None
    concurrency: int
    duration: float
    think_time: float
    max_tokens: int
    models: list[str]
    output: str


def pick_prompt(rng: random.Random) -> tuple[str, bool]:
    # ~30% of requests reuse a fixed prompt (cacheable); rest are unique.
    if rng.random() < 0.3:
        return rng.choice(FIXED_PROMPTS), True
    nonce = "".join(rng.choices(string.ascii_lowercase + string.digits, k=8))
    return UNIQUE_PROMPT_TEMPLATE.format(nonce=nonce, topic=rng.choice(TOPICS)), False


async def user_loop(
    user_id: int,
    client: httpx.AsyncClient,
    args: Args,
    stop_at: float,
    results: list[Result],
) -> None:
    rng = random.Random(user_id * 7919)
    while time.monotonic() < stop_at:
        model = rng.choice(args.models)
        prompt, cacheable = pick_prompt(rng)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": args.max_tokens,
        }
        start = time.monotonic()
        try:
            resp = await client.post("/v1/chat/completions", json=payload, timeout=60.0)
            latency_ms = (time.monotonic() - start) * 1000
            usage = {}
            error = ""
            if resp.status_code == 200:
                try:
                    usage = resp.json().get("usage", {})
                except ValueError:
                    error = "non-JSON 200 response"
            else:
                error = resp.text[:200]
            results.append(
                Result(
                    model=model,
                    latency_ms=latency_ms,
                    status_code=resp.status_code,
                    error=error,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    cacheable=cacheable,
                )
            )
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            results.append(
                Result(model=model, latency_ms=latency_ms, status_code=0, error=str(exc), cacheable=cacheable)
            )

        if args.think_time > 0:
            await asyncio.sleep(rng.uniform(0.5, 1.5) * args.think_time)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def print_report(results: list[Result], wall_seconds: float) -> None:
    if not results:
        print("No requests completed — check connectivity/auth before reading anything else into this.")
        return

    by_model: dict[str, list[Result]] = {}
    for r in results:
        by_model.setdefault(r.model, []).append(r)

    print(f"\n{'=' * 72}\nBENCHMARK REPORT — {len(results)} requests over {wall_seconds:.1f}s wall time\n{'=' * 72}")
    for model, rs in sorted(by_model.items()):
        ok = [r for r in rs if r.status_code == 200]
        err = [r for r in rs if r.status_code != 200]
        lat = [r.latency_ms for r in ok]
        cached_lat = [r.latency_ms for r in ok if r.cacheable]
        uncached_lat = [r.latency_ms for r in ok if not r.cacheable]
        print(f"\n--- {model} ---")
        print(f"  requests: {len(rs)}   ok: {len(ok)}   errors: {len(err)}   error_rate: {len(err)/len(rs):.1%}")
        print(f"  throughput: {len(ok)/wall_seconds:.2f} req/s")
        if lat:
            print(
                f"  latency ms  mean={statistics.mean(lat):.0f}  p50={percentile(lat,0.5):.0f}"
                f"  p95={percentile(lat,0.95):.0f}  p99={percentile(lat,0.99):.0f}  max={max(lat):.0f}"
            )
        if cached_lat and uncached_lat:
            print(
                f"  cache signal: repeated-prompt p50={percentile(cached_lat,0.5):.0f}ms"
                f"  vs unique-prompt p50={percentile(uncached_lat,0.5):.0f}ms"
                f"  (lower repeated-prompt latency suggests the Valkey cache is helping)"
            )
        if err:
            sample = err[0].error[:150]
            print(f"  sample error: {sample!r}")

    total_ok = sum(1 for r in results if r.status_code == 200)
    total_tokens = sum(r.completion_tokens for r in results)
    print(f"\n--- overall ---")
    print(f"  total requests: {len(results)}   overall throughput: {total_ok/wall_seconds:.2f} req/s")
    print(f"  total completion tokens generated: {total_tokens}")
    print(f"{'=' * 72}\n")


def write_csv(results: list[Result], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "latency_ms", "status_code", "error", "prompt_tokens", "completion_tokens", "cacheable"])
        for r in results:
            w.writerow([r.model, f"{r.latency_ms:.1f}", r.status_code, r.error, r.prompt_tokens, r.completion_tokens, r.cacheable])
    print(f"Raw per-request data written to {path}")


async def main_async(args: Args) -> None:
    verify: str | bool = args.cacert if args.cacert else True
    headers = {"Authorization": f"Bearer {args.api_key}"}
    async with httpx.AsyncClient(base_url=args.base_url, headers=headers, verify=verify) as client:
        stop_at = time.monotonic() + args.duration
        results: list[Result] = []
        wall_start = time.monotonic()
        await asyncio.gather(
            *[user_loop(i, client, args, stop_at, results) for i in range(args.concurrency)]
        )
        wall_seconds = time.monotonic() - wall_start

    print_report(results, wall_seconds)
    write_csv(results, args.output)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="e.g. https://ai-gateway.promon.co.in")
    p.add_argument("--api-key", required=True, help="a LiteLLM virtual key (prefer a scoped test key over the master key)")
    p.add_argument("--cacert", default=None, help="path to the self-signed CA cert (fetched-certs/...)")
    p.add_argument("--concurrency", type=int, default=20, help="simulated concurrent users (default: 20)")
    p.add_argument("--duration", type=float, default=300, help="test duration in seconds (default: 300)")
    p.add_argument("--think-time", type=float, default=2.0, help="avg seconds between a user's requests (default: 2.0; use 0 for a pure burst/stress test)")
    p.add_argument("--max-tokens", type=int, default=150, help="cap response length (default: 150)")
    p.add_argument("--include-cloud", action="store_true", help="also hit claude-general/gpt-general/gemini-general — REAL API COST")
    p.add_argument("--output", default="benchmark_results.csv")
    ns = p.parse_args()

    models = list(LOCAL_MODELS)
    if ns.include_cloud:
        models += CLOUD_MODELS
        print(
            "WARNING: --include-cloud is set. This run WILL make real, billed calls to "
            f"Anthropic/OpenAI/Gemini for the duration of the test ({ns.duration:.0f}s at "
            f"{ns.concurrency} concurrent users). Ctrl+C now if that's not intended.\n"
        )
        time.sleep(3)

    args = Args(
        base_url=ns.base_url,
        api_key=ns.api_key,
        cacert=ns.cacert,
        concurrency=ns.concurrency,
        duration=ns.duration,
        think_time=ns.think_time,
        max_tokens=ns.max_tokens,
        models=models,
        output=ns.output,
    )
    print(f"Starting: {args.concurrency} users, {args.duration:.0f}s, models={models}")
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
