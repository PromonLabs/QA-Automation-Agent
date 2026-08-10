"""
Quick concurrency benchmark: local Ollama vs the Promon AI Gateway,
same model family (qwen2.5:7b), at concurrency=1 and concurrency=5.

Small scale on purpose (a handful of requests per level) — this hits the
shared gateway, not just your machine, so it stays light rather than a
full load test.

Usage:
    python scripts/benchmark_gateway.py
"""
import asyncio
import time
import statistics
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.config import settings  # noqa: E402

PROMPT = "In one short sentence, what is 17 + 25?"
CONCURRENCY_LEVELS = [1, 5]


async def _call_ollama(client: httpx.AsyncClient) -> float:
    start = time.perf_counter()
    resp = await client.post(
        f"{settings.OLLAMA_HOST}/api/chat",
        json={
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": PROMPT}],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=120,
    )
    resp.raise_for_status()
    resp.json()
    return time.perf_counter() - start


async def _call_gateway(client: httpx.AsyncClient) -> float:
    start = time.perf_counter()
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.GATEWAY_API_KEY}"},
        json={
            "model": settings.GATEWAY_MODEL,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 100,
            "temperature": 0.1,
        },
        timeout=120,
    )
    resp.raise_for_status()
    resp.json()
    return time.perf_counter() - start


async def _run_level(label: str, call_fn, client: httpx.AsyncClient, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)

    async def _one():
        async with sem:
            return await call_fn(client)

    wall_start = time.perf_counter()
    latencies = await asyncio.gather(*[_one() for _ in range(concurrency)])
    wall_time = time.perf_counter() - wall_start

    return {
        "label": label,
        "concurrency": concurrency,
        "wall_time": wall_time,
        "latencies": latencies,
        "avg_latency": statistics.mean(latencies),
        "min_latency": min(latencies),
        "max_latency": max(latencies),
    }


async def main():
    print(f"Local model:   {settings.LLM_MODEL} @ {settings.OLLAMA_HOST}")
    print(f"Gateway model: {settings.GATEWAY_MODEL} @ {settings.GATEWAY_BASE_URL}")
    print(f"Prompt: {PROMPT!r}\n")

    verify = settings.GATEWAY_CACERT if settings.GATEWAY_CACERT else True
    results = []

    async with httpx.AsyncClient() as ollama_client, \
               httpx.AsyncClient(base_url=settings.GATEWAY_BASE_URL, verify=verify) as gateway_client:

        for concurrency in CONCURRENCY_LEVELS:
            print(f"--- concurrency={concurrency} ---")

            r = await _run_level("local", _call_ollama, ollama_client, concurrency)
            results.append(r)
            print(f"  local   wall={r['wall_time']:6.2f}s  avg={r['avg_latency']:6.2f}s  "
                  f"min={r['min_latency']:6.2f}s  max={r['max_latency']:6.2f}s")

            try:
                r = await _run_level("gateway", _call_gateway, gateway_client, concurrency)
                results.append(r)
                print(f"  gateway wall={r['wall_time']:6.2f}s  avg={r['avg_latency']:6.2f}s  "
                      f"min={r['min_latency']:6.2f}s  max={r['max_latency']:6.2f}s")
            except Exception as exc:
                print(f"  gateway FAILED: {exc}")
            print()

    print("=== Summary ===")
    print(f"{'target':<8} {'concurrency':<12} {'wall_time':<12} {'avg_latency':<12}")
    for r in results:
        print(f"{r['label']:<8} {r['concurrency']:<12} {r['wall_time']:<12.2f} {r['avg_latency']:<12.2f}")


if __name__ == "__main__":
    asyncio.run(main())
