"""
evaluate.py
===========
Evaluate whether the fine-tuned model has learned your automation workflows.

Tests:
  1. JSON validity      — does the model output valid JSON?
  2. Schema compliance  — does it have 'name' and 'steps' keys?
  3. Action coverage    — does it use the right action verbs?
  4. Variable recall    — does it remember to use ${VAR} placeholders?
  5. Step ordering      — are steps in a logical sequence?
  6. Prompt variety     — test with unseen descriptions (not in training set)

Usage:
  # Test via Ollama (after export):
  python evaluate.py --mode ollama --model automation-agent

  # Test via HuggingFace (before export):
  python evaluate.py --mode hf --model_path ./output/lora_adapter \
                                --base_model Qwen/Qwen2.5-7B-Instruct
"""

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Callable


# ── Test prompts — these should NOT be in your training set ──────────────────
TEST_CASES = [
    {
        "name": "topup_generation",
        "prompt": (
            "Create a browser automation flow to top up a customer's talk credit. "
            "Use ${COS_URL} for the COS portal, ${PORTAL_URL} for the payment portal, "
            "${PHONE_NUMBER} for the customer, and ${TOPUP_AMOUNT} for the amount. "
            "Include card payment with ${CARD_NUMBER}, ${CARD_MONTH}, ${CARD_YEAR}, ${CARD_CVV}. "
            "Take screenshots before and after payment. Output JSON only."
        ),
        "expected_variables": ["COS_URL", "PORTAL_URL", "PHONE_NUMBER", "TOPUP_AMOUNT",
                               "CARD_NUMBER", "CARD_MONTH", "CARD_YEAR", "CARD_CVV"],
        "expected_actions": ["navigate", "click", "type", "select", "screenshot"],
        "min_steps": 15,
    },
    {
        "name": "login_flow",
        "prompt": (
            "Generate a browser automation flow that logs into COS at ${COS_URL} "
            "using ${ADMIN_USER} and ${ADMIN_PASS}, then searches for customer ${MISTIN_ID}."
        ),
        "expected_variables": ["COS_URL", "ADMIN_USER", "ADMIN_PASS", "MISTIN_ID"],
        "expected_actions": ["navigate", "click", "type"],
        "min_steps": 6,
    },
    {
        "name": "screenshot_evidence",
        "prompt": (
            "Create an automation flow that navigates to ${PORTAL_URL}, "
            "clicks a button, waits 3 seconds, then takes a screenshot "
            "saved as 'result.png' for evidence."
        ),
        "expected_variables": ["PORTAL_URL"],
        "expected_actions": ["navigate", "click", "wait"],
        "must_contain_strings": ["result.png", "screenshot", "save it as"],
        "min_steps": 4,
    },
    {
        "name": "data_topup",
        "prompt": (
            "Write a flow to add data to a customer. Navigate to ${COS_URL}, login, "
            "find customer ${MISTIN_ID}, then go to ${PORTAL_URL} to purchase "
            "${DATA_AMOUNT} using card payment."
        ),
        "expected_variables": ["COS_URL", "PORTAL_URL", "MISTIN_ID", "DATA_AMOUNT"],
        "min_steps": 10,
    },
    {
        "name": "new_account",
        "prompt": (
            "Create a flow for new SIM account creation that: "
            "logs into the ICC inventory system at ${ICC_URL} to get an ICCID, "
            "then goes to ${MSITCOS_URL} to create the service for account ${ACCOUNT_NUMBER}."
        ),
        "expected_variables": ["ICC_URL", "MSITCOS_URL", "ACCOUNT_NUMBER"],
        "expected_actions": ["navigate", "select", "click"],
        "min_steps": 12,
    },
]

ACTION_KEYWORDS = {
    "navigate": [r"navigate to", r"^navigate"],
    "click":    [r"^click", r"click the"],
    "type":     [r"enter .+ in", r"in .+ enter", r"type "],
    "select":   [r"^select "],
    "wait":     [r"^wait \d+", r"^wait for"],
    "screenshot": [r"screenshot", r"save it as", r"^ss$"],
}


def detect_action(step: str) -> str:
    lo = step.lower().strip()
    for action, patterns in ACTION_KEYWORDS.items():
        if any(re.search(p, lo) for p in patterns):
            return action
    return "click"


@dataclass
class TestResult:
    name: str
    passed: bool
    score: float        # 0.0 – 1.0
    details: list[str] = field(default_factory=list)
    raw_output: str = ""


def evaluate_output(test: dict, raw_output: str) -> TestResult:
    result = TestResult(name=test["name"], passed=False, score=0.0, raw_output=raw_output)
    checks_passed = 0
    checks_total  = 0

    # ── 1. JSON validity ─────────────────────────────────────────────────────
    checks_total += 1
    parsed = None
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", raw_output).strip()
        cleaned = re.sub(r"```\s*", "", cleaned).strip()
        # Find the outermost JSON object
        depth, start = 0, None
        for i, ch in enumerate(cleaned):
            if ch == "{":
                if depth == 0: start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    parsed = json.loads(cleaned[start:i+1])
                    break
        if parsed:
            checks_passed += 1
            result.details.append("✅ Valid JSON")
        else:
            result.details.append("❌ Could not parse JSON from output")
    except Exception as e:
        result.details.append(f"❌ JSON parse error: {e}")

    if parsed is None:
        result.score = 0.0
        return result

    # ── 2. Schema compliance ─────────────────────────────────────────────────
    checks_total += 1
    steps = parsed.get("steps") or []
    if "name" in parsed and isinstance(steps, list) and len(steps) > 0:
        checks_passed += 1
        result.details.append(f"✅ Schema valid (name + {len(steps)} steps)")
    else:
        result.details.append(f"❌ Schema invalid: name={('name' in parsed)}, steps={len(steps)}")

    # ── 3. Minimum step count ─────────────────────────────────────────────────
    min_steps = test.get("min_steps", 3)
    checks_total += 1
    if len(steps) >= min_steps:
        checks_passed += 1
        result.details.append(f"✅ Step count: {len(steps)} ≥ {min_steps}")
    else:
        result.details.append(f"❌ Too few steps: {len(steps)} < {min_steps}")

    # ── 4. Variable recall ───────────────────────────────────────────────────
    expected_vars = test.get("expected_variables", [])
    if expected_vars:
        all_text  = "\n".join(str(s) for s in steps)
        found_vars = [v for v in expected_vars
                      if f"${{{v}}}" in all_text or v in all_text]
        recall = len(found_vars) / len(expected_vars)
        checks_total += 1
        if recall >= 0.8:
            checks_passed += 1
            result.details.append(f"✅ Variable recall: {len(found_vars)}/{len(expected_vars)} vars used")
        else:
            missing = [v for v in expected_vars if v not in found_vars]
            result.details.append(f"⚠️  Variable recall: {recall:.0%} — missing: {missing}")

    # ── 5. Action diversity ───────────────────────────────────────────────────
    expected_actions = test.get("expected_actions", [])
    if expected_actions:
        found_actions = {detect_action(str(s)) for s in steps}
        checks_total += 1
        covered = [a for a in expected_actions if a in found_actions]
        if len(covered) == len(expected_actions):
            checks_passed += 1
            result.details.append(f"✅ Actions: {', '.join(covered)}")
        else:
            missing = [a for a in expected_actions if a not in found_actions]
            result.details.append(f"⚠️  Missing actions: {missing}")

    # ── 6. Must-contain strings ───────────────────────────────────────────────
    must_contain = test.get("must_contain_strings", [])
    if must_contain:
        all_text = "\n".join(str(s) for s in steps).lower()
        checks_total += 1
        found_all = all(s.lower() in all_text for s in must_contain)
        if found_all:
            checks_passed += 1
            result.details.append(f"✅ Required strings found: {must_contain}")
        else:
            missing = [s for s in must_contain if s.lower() not in all_text]
            result.details.append(f"❌ Missing required strings: {missing}")

    # ── 7. Step ordering sanity ───────────────────────────────────────────────
    checks_total += 1
    step_strs = [str(s).lower() for s in steps]
    nav_indices  = [i for i, s in enumerate(step_strs) if s.startswith("navigate")]
    click_indices = [i for i, s in enumerate(step_strs) if s.startswith("click")]
    if nav_indices and click_indices:
        if nav_indices[0] < click_indices[-1]:
            checks_passed += 1
            result.details.append("✅ Step order: navigate before click (logical)")
        else:
            result.details.append("⚠️  Step order: suspicious (clicking before navigating)")
    else:
        checks_passed += 1
        result.details.append("✅ Step order: n/a")

    result.score  = checks_passed / checks_total if checks_total > 0 else 0.0
    result.passed = result.score >= 0.75   # 75% checks must pass
    return result


# ── Model backends ────────────────────────────────────────────────────────────

def query_ollama(model_name: str, prompt: str, system: str) -> str:
    import httpx
    payload = {
        "model": model_name,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.05, "num_predict": 2000},
    }
    resp = httpx.post("http://localhost:11434/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "")


def query_hf(model_path: str, base_model: str, prompt: str, system: str) -> str:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

    if not hasattr(query_hf, "_pipe"):
        print("  Loading model for evaluation (one-time)…")
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        base = AutoModelForCausalLM.from_pretrained(
            base_model,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(base, model_path)
        model = model.merge_and_unload()
        query_hf._pipe = pipeline(
            "text-generation", model=model, tokenizer=tokenizer,
            max_new_tokens=2000, temperature=0.05, do_sample=False,
        )

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]
    output = query_hf._pipe(messages)[0]["generated_text"]
    # Extract the last assistant turn
    if isinstance(output, list):
        return output[-1].get("content", "")
    return str(output)


SYSTEM_PROMPT = """You are a browser automation expert. Generate browser automation flows as JSON.
Always output valid JSON with 'name' and 'steps' fields. Use ${VAR_NAME} for dynamic values."""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode",       choices=["ollama", "hf"], default="ollama")
    p.add_argument("--model",      default="automation-agent",
                   help="Ollama model name (for --mode ollama)")
    p.add_argument("--model_path", default="./output/lora_adapter",
                   help="HF adapter path (for --mode hf)")
    p.add_argument("--base_model", default="Qwen/Qwen2.5-7B-Instruct",
                   help="HF base model (for --mode hf)")
    p.add_argument("--verbose",    action="store_true")
    args = p.parse_args()

    print(f"\n{'='*60}")
    print(f" Evaluating: {args.model if args.mode == 'ollama' else args.model_path}")
    print(f" Mode: {args.mode}")
    print(f" Tests: {len(TEST_CASES)}")
    print(f"{'='*60}\n")

    results: list[TestResult] = []

    for test in TEST_CASES:
        print(f"Testing: {test['name']}…", end=" ", flush=True)
        try:
            if args.mode == "ollama":
                raw = query_ollama(args.model, test["prompt"], SYSTEM_PROMPT)
            else:
                raw = query_hf(args.model_path, args.base_model, test["prompt"], SYSTEM_PROMPT)

            result = evaluate_output(test, raw)
            results.append(result)

            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{status}  (score: {result.score:.0%})")

            if args.verbose or not result.passed:
                for detail in result.details:
                    print(f"    {detail}")
                if not result.passed:
                    print(f"\n  Raw output (first 500 chars):")
                    print(textwrap.indent(raw[:500], "    "))
                print()

        except Exception as e:
            print(f"❌ ERROR: {e}")
            results.append(TestResult(name=test["name"], passed=False, score=0.0,
                                      details=[f"Error: {e}"]))

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r.passed)
    avg_score = sum(r.score for r in results) / len(results) if results else 0

    print(f"\n{'='*60}")
    print(f" Results: {passed}/{len(results)} tests passed")
    print(f" Average score: {avg_score:.0%}")
    print(f"{'='*60}")

    if avg_score >= 0.85:
        print(" 🎉 Excellent! The model has learned your workflows well.")
    elif avg_score >= 0.65:
        print(" ⚠️  Acceptable. Consider 1–2 more training epochs or adding more data.")
    else:
        print(" ❌ Poor. Check your dataset quality, increase epochs, or lower learning rate.")

    print()
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
