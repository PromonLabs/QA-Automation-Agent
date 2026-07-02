#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tusass TopUp Talk -- direct browser test (bypasses LLM, uses BrowserAgent directly).

Runs the full 25-step flow N times and prints a summary.

Usage (from the backend/ directory with venv active):
    python tests/test_tusass_topup.py

Env overrides:
    set PHONE_NUMBER=236619
    set TOPUP_AMOUNT=50
    set HEADLESS=false
    set MAX_RUNS=10
    python tests/test_tusass_topup.py
"""
import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows so emojis/unicode don't crash
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Resolve paths ────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(BACKEND_DIR))

# Load .env BEFORE importing app modules (settings reads env at import time)
from dotenv import load_dotenv

_env = BACKEND_DIR / ".env"
if _env.exists():
    load_dotenv(_env, override=True)

# ── Test configuration (from .env with fallbacks) ────────────────────────────
PORTAL_URL   = os.getenv("PORTAL_URL",   "https://test.tusass.lab.gl/test")
COS_URL      = os.getenv("COS_URL",      "https://msitcos.lab.gl/")
ADMIN_USER   = os.getenv("ADMIN_USER",   "admin@telepost.gl")
ADMIN_PASS   = os.getenv("ADMIN_PASS",   "test1234")
MISTIN_ID    = os.getenv("MISTIN_ID",    "236619")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "236619")
TOPUP_AMOUNT = os.getenv("TOPUP_AMOUNT", "50")
CARD_NUMBER  = os.getenv("CARD_NUMBER",  "1000000000000008")
CARD_MONTH   = os.getenv("CARD_MONTH",   "01")
CARD_YEAR    = os.getenv("CARD_YEAR",    "06")
CARD_EXPIRY  = f"{CARD_MONTH}/{CARD_YEAR}"
CARD_CVC     = os.getenv("CARD_CVV",     os.getenv("CARD_CVC", "123"))
HEADLESS     = os.getenv("HEADLESS",     "false").lower() == "true"
MAX_RUNS     = int(os.getenv("MAX_RUNS", "10"))

SCREENSHOTS_ROOT = BACKEND_DIR / "test-screenshots"
SCREENSHOTS_ROOT.mkdir(parents=True, exist_ok=True)


# ── Build the browser plan ───────────────────────────────────────────────────

def _make_plan(run_num: int) -> dict:
    """
    Construct the full Tusass TopUp Talk automation plan as a BrowserAgent-ready dict.
    Steps:
      Part 1  (steps  1-8)  — COS admin login + record initial balance
      Part 2  (steps  9-15) — Tusass portal TopUp Talk + phone entry + amount select
      Part 3  (steps 16-21) — Payment card + Pay + receipt
      Part 4  (steps 22-25) — Return to COS + verify updated balance
    """
    steps = [
        # ── Part 1: COS Admin Portal — login & note current balance ──────────
        {
            "step_number": 1,
            "action": "navigate",
            "target": COS_URL,
            "description": "Open COS Admin Portal",
        },
        {
            "step_number": 2,
            "action": "press_key",
            "target": "Escape",
            "description": "Dismiss Microsoft SSO popup if present",
            "optional": True,
        },
        {
            "step_number": 3,
            "action": "click",
            "target": "Login with password",
            "alternatives": ["Sign in with password", "Use password", "login with password"],
            "description": "Click 'Login with password' to reveal the credential form",
            "optional": True,
        },
        {
            "step_number": 4,
            "action": "type",
            "target": "Username",
            "value": ADMIN_USER,
            "description": f"Enter admin username: {ADMIN_USER}",
        },
        {
            "step_number": 5,
            "action": "type",
            "target": "Password",
            "value": ADMIN_PASS,
            "description": "Enter admin password",
        },
        {
            "step_number": 6,
            "action": "click",
            "target": "Log in",
            "alternatives": ["Login", "Sign in", "Submit"],
            "description": "Click Log in button",
        },
        {
            "step_number": 7,
            "action": "search",
            "target": "search",
            "value": MISTIN_ID,
            "description": f"Search for customer {MISTIN_ID}",
        },
        {
            "step_number": 8,
            "action": "screenshot",
            "target": "search-result.png",
            "description": "Screenshot: initial balance (before TopUp)",
        },

        # ── Part 2: Tusass TopUp Portal — TopUp Talk flow ─────────────────────
        {
            "step_number": 9,
            "action": "navigate",
            "target": PORTAL_URL,
            "description": "Open Tusass TopUp Portal",
        },
        {
            "step_number": 10,
            "action": "wait",
            "target": "2000",
            "description": "Wait for portal menu to fully render",
        },
        {
            "step_number": 11,
            "action": "click",
            "target": "Topup talk",
            "alternatives": ["TopUp Talk", "Top Up Talk", "Talk", "TopUp"],
            "description": "Click the Topup talk button",
        },
        {
            "step_number": 12,
            "action": "wait",
            "target": "4000",
            "description": "Wait for SPA to navigate to phone entry form",
        },
        {
            "step_number": 13,
            "action": "screenshot",
            "target": "after-topup-click.png",
            "description": "Screenshot: page state after clicking Topup talk",
        },
        {
            "step_number": 14,
            "action": "type",
            "target": "mobile number",
            "value": PHONE_NUMBER,
            "description": f"Enter mobile number: {PHONE_NUMBER}",
        },
        {
            "step_number": 15,
            "action": "type",
            "target": "mobile number",
            "value": PHONE_NUMBER,
            "description": f"Enter mobile number again (confirmation field if present)",
            "optional": True,
        },
        {
            "step_number": 16,
            "action": "click",
            "target": "Continue",
            "alternatives": ["Next", "Proceed", "Naja"],
            "description": "Click Continue after entering phone number",
        },
        {
            "step_number": 17,
            "action": "wait",
            "target": "2000",
            "description": "Wait for amount selection page",
        },
        {
            "step_number": 18,
            "action": "screenshot",
            "target": "amount-selection.png",
            "description": "Screenshot: amount selection page",
        },
        {
            "step_number": 19,
            "action": "click",
            "target": TOPUP_AMOUNT,
            "alternatives": [f"{TOPUP_AMOUNT} DKK", f"DKK {TOPUP_AMOUNT}", f"{TOPUP_AMOUNT} kr", "50"],
            "description": f"Select TopUp amount: {TOPUP_AMOUNT}",
        },
        {
            "step_number": 20,
            "action": "click",
            "target": "Continue",
            "alternatives": ["Next", "Proceed", "Confirm"],
            "description": "Click Continue on amount selection page",
        },

        # ── Part 3: Payment — enter card details and pay ──────────────────────
        {
            "step_number": 21,
            "action": "wait",
            "target": "2000",
            "description": "Wait for payment form to render",
        },
        {
            "step_number": 22,
            "action": "screenshot",
            "target": "payment-page.png",
            "description": "Screenshot: payment page",
        },
        {
            "step_number": 23,
            "action": "type",
            "target": "card number",
            "value": CARD_NUMBER,
            "description": f"Enter card number: {CARD_NUMBER}",
        },
        {
            "step_number": 24,
            "action": "type",
            "target": "MM",
            "value": CARD_MONTH,
            "description": f"Enter card expiry month: {CARD_MONTH}",
        },
        {
            "step_number": 25,
            "action": "type",
            "target": "YY",
            "value": CARD_YEAR,
            "description": f"Enter card expiry year: {CARD_YEAR}",
        },
        {
            "step_number": 26,
            "action": "type",
            "target": "cvv",
            "value": CARD_CVC,
            "description": f"Enter CVV: {CARD_CVC}",
        },
        {
            "step_number": 27,
            "action": "click",
            "target": "Pay",
            "alternatives": ["Submit", "Complete Payment", "Confirm Payment", "Pay now"],
            "description": "Click Pay button",
        },
        {
            "step_number": 28,
            "action": "wait",
            "target": "3000",
            "description": "Wait for payment to process",
        },
        {
            "step_number": 29,
            "action": "click",
            "target": "No, thanks",
            "alternatives": ["Cancel", "Close", "Skip", "Dismiss", "No thanks"],
            "description": "Dismiss save-card dialog if it appears",
            "optional": True,
        },
        {
            "step_number": 30,
            "action": "screenshot",
            "target": "receipt.png",
            "description": "Screenshot: payment receipt page",
        },

        # ── Part 4: Return to COS — verify updated balance ────────────────────
        {
            "step_number": 31,
            "action": "navigate",
            "target": COS_URL,
            "description": "Return to COS Admin Portal to verify balance",
        },
        {
            "step_number": 32,
            "action": "search",
            "target": "search",
            "value": MISTIN_ID,
            "description": f"Search for customer {MISTIN_ID} (post-TopUp verification)",
        },
        {
            "step_number": 33,
            "action": "screenshot",
            "target": "updated-balance.png",
            "description": "Screenshot: updated balance after TopUp",
        },
        {
            "step_number": 34,
            "action": "verify",
            "target": MISTIN_ID,
            "description": f"Verify customer {MISTIN_ID} is visible on balance page",
        },
    ]

    return {
        "reasoning": (
            f"Tusass TopUp Talk automated test — Run {run_num}/{MAX_RUNS}. "
            f"Phone: {PHONE_NUMBER}, Amount: {TOPUP_AMOUNT}, "
            f"Card: ****{CARD_NUMBER[-4:]}"
        ),
        "steps": steps,
        "expected_outcome": (
            f"Customer {MISTIN_ID} successfully topped up with {TOPUP_AMOUNT} "
            f"and balance is updated in the COS admin portal."
        ),
    }


# ── Run a single iteration ───────────────────────────────────────────────────

async def run_once(run_num: int) -> dict:
    """Execute the full flow once and return a result summary dict."""
    from app.agents.browser_agent import BrowserAgent

    exec_id  = f"test_run_{run_num:02d}_{int(time.time())}"
    plan     = _make_plan(run_num)
    log_lines: list[str] = []

    async def on_log(log):
        line = f"[{log.level.upper():7s}] {log.message}"
        log_lines.append(line)
        print(line)

    agent = BrowserAgent(
        exec_id=exec_id,
        headless=HEADLESS,
        log_callback=on_log,
        screenshot_mode="all",
    )

    t0 = time.monotonic()
    try:
        result = await agent.run(plan)
    except Exception as exc:
        result = {
            "status": "failed",
            "steps_completed": 0,
            "steps_total": len(plan["steps"]),
            "failed_steps": [],
            "stop_reason": str(exc),
            "success_rate": 0.0,
            "summary": f"Exception during run: {exc}",
        }
    duration = time.monotonic() - t0

    # ── Copy screenshots to test-screenshots/run_NN/ ─────────────────────────
    src_dir  = BACKEND_DIR / "artifacts" / "screenshots" / exec_id
    run_dir  = SCREENSHOTS_ROOT / f"run_{run_num:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    shot_count = 0
    if src_dir.exists():
        for png in sorted(src_dir.glob("*.png")):
            dst = run_dir / png.name
            dst.write_bytes(png.read_bytes())
            shot_count += 1

    return {
        "run":             run_num,
        "exec_id":         exec_id,
        "status":          result["status"],
        "steps_completed": result["steps_completed"],
        "steps_total":     result["steps_total"],
        "duration_s":      round(duration, 1),
        "success_rate":    round(result.get("success_rate", 0.0), 1),
        "stop_reason":     result.get("stop_reason", ""),
        "summary":         result.get("summary", ""),
        "screenshots":     shot_count,
        "last_logs":       log_lines[-6:],
    }


# ── Entry point ──────────────────────────────────────────────────────────────

async def main() -> int:
    banner = "=" * 64
    print(banner)
    print(f"  Tusass TopUp Talk -- {MAX_RUNS}-Run Test Suite")
    print(banner)
    print(f"  Portal URL    : {PORTAL_URL}")
    print(f"  Admin URL     : {COS_URL}")
    print(f"  Phone / ID    : {PHONE_NUMBER} / {MISTIN_ID}")
    print(f"  TopUp Amount  : {TOPUP_AMOUNT}")
    print(f"  Card          : ****{CARD_NUMBER[-4:]}  exp {CARD_EXPIRY}  cvv ***")
    print(f"  Headless      : {HEADLESS}")
    print(f"  Screenshots   : {SCREENSHOTS_ROOT}")
    print(banner)

    all_results: list[dict] = []

    for i in range(1, MAX_RUNS + 1):
        sep = "-" * 64
        print(f"\n{sep}")
        print(f"  RUN {i}/{MAX_RUNS}  --  {datetime.now().strftime('%H:%M:%S')}")
        print(sep)

        res = await run_once(i)
        all_results.append(res)

        icon = "✅" if res["status"] == "success" else (
               "⚠️ " if res["status"] == "partial" else "❌")
        print(f"\n  {icon} Run {i}: {res['status'].upper()} — "
              f"{res['steps_completed']}/{res['steps_total']} steps  "
              f"({res['duration_s']}s)  "
              f"📸 {res['screenshots']} shots")
        if res["stop_reason"] and res["status"] != "success":
            print(f"     Stopped: {res['stop_reason'][:120]}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{banner}")
    print(f"  FINAL SUMMARY — {MAX_RUNS} Runs Completed")
    print(banner)

    passed  = sum(1 for r in all_results if r["status"] == "success")
    partial = sum(1 for r in all_results if r["status"] == "partial")
    failed  = sum(1 for r in all_results if r["status"] == "failed")
    avg_dur  = sum(r["duration_s"]   for r in all_results) / len(all_results)
    avg_rate = sum(r["success_rate"] for r in all_results) / len(all_results)

    print(f"  ✅ Passed  : {passed}/{MAX_RUNS}")
    print(f"  ⚠️  Partial : {partial}/{MAX_RUNS}")
    print(f"  ❌ Failed  : {failed}/{MAX_RUNS}")
    print(f"  ⏱  Avg time : {avg_dur:.1f}s per run")
    print(f"  📊 Avg steps: {avg_rate:.0f}% success rate")
    print()
    print("  Per-run detail:")
    for r in all_results:
        icon = "✅" if r["status"] == "success" else (
               "⚠️ " if r["status"] == "partial" else "❌")
        print(f"    Run {r['run']:2d}: {icon} {r['status']:<8}  "
              f"{r['steps_completed']:2d}/{r['steps_total']:<2d} steps  "
              f"{r['duration_s']:6.1f}s  "
              f"📸 {r['screenshots']} shots")

    # Save JSON report
    report = {
        "generated_at": datetime.now().isoformat(),
        "config": {
            "portal_url":   PORTAL_URL,
            "cos_url":      COS_URL,
            "phone_number": PHONE_NUMBER,
            "mistin_id":    MISTIN_ID,
            "topup_amount": TOPUP_AMOUNT,
            "max_runs":     MAX_RUNS,
            "headless":     HEADLESS,
        },
        "summary": {
            "passed":            passed,
            "partial":           partial,
            "failed":            failed,
            "avg_duration_s":    round(avg_dur, 1),
            "avg_success_rate":  round(avg_rate, 1),
        },
        "runs": all_results,
    }
    report_path = SCREENSHOTS_ROOT / "report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\n  Report saved : {report_path}")
    print(f"  Screenshots  : {SCREENSHOTS_ROOT}")
    print(banner)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
