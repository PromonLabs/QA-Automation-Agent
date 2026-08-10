#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic terminal flow runner — reads any flow JSON from flows/json-flow/,
resolves ${VAR} placeholders from .env, plans with the LLM (Claude API if
LLM_PROVIDER=claude, otherwise Ollama/direct-parse fallback), and executes
it with a real (visible) browser via BrowserAgent. Bypasses the web UI entirely.

Usage (from the backend/ directory with venv active):
    python tests/run_flow.py "Tusass-TopUp-Talk"
    python tests/run_flow.py "Tusass-TopUp-Talk" --headless
"""
import asyncio
import io
import json
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
_env = BACKEND_DIR / ".env"
if _env.exists():
    load_dotenv(_env, override=True)

from app.agents.llm_client import llm_client
from app.agents.browser_agent import BrowserAgent
from app.agents.orchestrator import _extract_steps_from_task
from app.core.config import settings

FLOWS_DIR = BACKEND_DIR.parent / "flows" / "json-flow"


def _resolve_flow_path(name: str) -> Path:
    direct = FLOWS_DIR / f"{name}.json"
    if direct.exists():
        return direct
    norm = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    for f in FLOWS_DIR.glob("*.json"):
        if f.stem.lower().replace(" ", "").replace("-", "").replace("_", "") == norm:
            return f
    raise FileNotFoundError(f"No flow file matching {name!r} in {FLOWS_DIR}")


async def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tests/run_flow.py <flow-name> [--headless]")
        available = ", ".join(f.stem for f in FLOWS_DIR.glob("*.json"))
        print(f"Available flows: {available}")
        return 1

    flow_name = sys.argv[1]
    headless = "--headless" in sys.argv[2:]

    flow_path = _resolve_flow_path(flow_name)
    raw_task = flow_path.read_text(encoding="utf-8")

    steps_list = _extract_steps_from_task(raw_task)
    if len(steps_list) < 2:
        print(f"Could not extract steps from {flow_path}")
        return 1

    task_text = "\n".join(f"- {s}" for s in steps_list)

    banner = "=" * 64
    print(banner)
    print(f"  Flow          : {flow_path.stem}")
    print(f"  LLM provider  : {settings.LLM_PROVIDER}  (USE_FLOW_AGENT={settings.USE_FLOW_AGENT})")
    print(f"  Headless      : {headless}")
    print(f"  Steps parsed  : {len(steps_list)}")
    print(banner)
    for i, s in enumerate(steps_list, 1):
        print(f"  {i:2d}. {s}")
    print(banner)

    print("\nPlanning...")
    plan = await llm_client.generate_plan(task_text)
    print(f"Plan ready: {len(plan.get('steps', []))} steps")
    if plan.get("reasoning"):
        print(f"Reasoning: {plan['reasoning'][:200]}")

    exec_id = f"termrun_{flow_path.stem}_{int(time.time())}"

    async def on_log(log):
        print(f"[{log.level.upper():7s}] {log.message}")

    agent = BrowserAgent(
        exec_id=exec_id,
        headless=headless,
        log_callback=on_log,
        screenshot_mode="all",
    )

    t0 = time.monotonic()
    try:
        result = await agent.run(plan)
    except Exception as exc:
        print(f"EXCEPTION: {exc}")
        return 1
    duration = time.monotonic() - t0

    print(f"\n{banner}")
    print(f"  RESULT: {result['status'].upper()}")
    print(f"  Steps  : {result['steps_completed']}/{result['steps_total']}")
    print(f"  Time   : {duration:.1f}s")
    print(f"  Summary: {result.get('summary', '')}")
    if result.get("stop_reason"):
        print(f"  Stopped: {result['stop_reason']}")
    print(f"  Screenshots: {BACKEND_DIR / 'artifacts' / 'screenshots' / exec_id}")
    print(banner)

    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
