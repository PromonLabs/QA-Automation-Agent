"""
prepare_dataset.py
==================
Converts your JSON workflow files into JSONL training data for LLM fine-tuning.

Each workflow generates MULTIPLE training examples to teach different skills:
  1. Flow generation     — NL description → full JSON flow
  2. Step explanation    — what does this flow do?
  3. Step extension      — add a step to this flow
  4. Variable extraction — what variables does this flow use?
  5. Action recognition  — classify a step's action type
  6. Flow comparison     — how do these two flows differ?

Usage:
  python prepare_dataset.py --flows_dir ../flows/json-flow \
                             --output_dir ./data \
                             --split 0.9
"""

import json
import random
import re
from pathlib import Path
from typing import Any
import argparse


SYSTEM_PROMPT = """You are a browser automation expert. You understand web UI automation workflows
written as ordered JSON step lists. You can:
- Generate new automation flows from natural language descriptions
- Explain what a flow does
- Extend existing flows with new steps
- Identify variables and their purpose
- Convert between natural language and structured JSON automation steps

Always produce valid JSON when asked for a flow. Use ${VAR_NAME} syntax for dynamic values."""


# ── Action vocabulary (parsed from steps) ──────────────────────────────────
ACTION_PATTERNS = [
    (r"^Navigate to",                      "navigate"),
    (r"^Click",                            "click"),
    (r"^Enter .+ in .+ box",              "type"),
    (r"^In .+ field.* enter",             "type"),
    (r"^In .+ enter",                     "type"),
    (r"^Type ",                            "type"),
    (r"^Select ",                          "select"),
    (r"^Wait \d+ms",                       "wait"),
    (r"^Wait for ",                        "wait_for"),
    (r"^Verify|^Check|^Assert|^Confirm",  "verify"),
    (r"^SS$",                              "screenshot"),
    (r"screenshot|save it as",            "screenshot"),
    (r"^Note the ",                        "extract"),
    (r"Extract the",                       "extract"),
    (r"^Refresh",                          "refresh_until"),
    (r"^Press ",                           "press_key"),
    (r"^Scroll",                           "scroll"),
    (r"^Give the report",                  "report"),
]


def classify_action(step: str) -> str:
    lo = step.strip()
    for pattern, action in ACTION_PATTERNS:
        if re.search(pattern, lo, re.IGNORECASE):
            return action
    return "click"


def extract_variables(steps: list[str]) -> list[str]:
    """Return sorted unique ${VAR} names found in all steps."""
    vars_found = sorted(set(re.findall(r"\$\{([^}]+)\}", "\n".join(steps))))
    return vars_found


def flow_summary(name: str, steps: list[str]) -> str:
    """Generate a plain-English description of what a flow does."""
    name_clean = name.strip()
    nav_steps   = [s for s in steps if re.match(r"^Navigate to", s, re.IGNORECASE)]
    click_steps = [s for s in steps if re.match(r"^Click", s, re.IGNORECASE)]
    ss_steps    = [s for s in steps if "screenshot" in s.lower() or s.strip().upper() == "SS"]
    variables   = extract_variables(steps)
    urls        = [re.search(r"\$\{[^}]+\}", s).group() if re.search(r"\$\{[^}]+\}", s) else s
                   for s in nav_steps]

    lines = [
        f"The '{name_clean}' workflow has {len(steps)} steps.",
        f"It navigates to {len(nav_steps)} URL(s): {', '.join(urls[:3])}.",
        f"It performs {len(click_steps)} click action(s).",
        f"It captures {len(ss_steps)} screenshot(s) as evidence.",
    ]
    if variables:
        lines.append(f"Dynamic variables used: {', '.join(f'${{{v}}}' for v in variables)}.")
    return " ".join(lines)


def make_chat(system: str, user: str, assistant: str) -> dict:
    return {
        "messages": [
            {"role": "system",    "content": system},
            {"role": "user",      "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


# ── Per-flow example generators ────────────────────────────────────────────

def example_generate_flow(name: str, steps: list[str]) -> dict:
    """Task: produce the full JSON flow from a description."""
    summary = flow_summary(name, steps)
    variables = extract_variables(steps)
    var_list = ", ".join(f"${{{v}}}" for v in variables) if variables else "none"

    user = (
        f"Create a browser automation flow called '{name.strip()}'. "
        f"It should: {summary} "
        f"Use these environment variables: {var_list}. "
        "Output the complete flow as JSON."
    )
    assistant = json.dumps({"name": name.strip(), "steps": steps}, indent=2)
    return make_chat(SYSTEM_PROMPT, user, assistant)


def example_explain_flow(name: str, steps: list[str]) -> dict:
    """Task: explain what the flow does in plain English."""
    flow_json = json.dumps({"name": name.strip(), "steps": steps}, indent=2)
    user = f"Explain what this browser automation flow does:\n\n{flow_json}"
    variables = extract_variables(steps)
    nav = [s for s in steps if re.match(r"Navigate to", s, re.IGNORECASE)]

    assistant_lines = [
        f"This is the '{name.strip()}' automation workflow with {len(steps)} steps.\n",
        f"**What it does:**",
    ]
    if nav:
        assistant_lines.append(f"- Navigates to {len(nav)} site(s): " +
                                ", ".join(re.sub(r"Navigate to\s*", "", s) for s in nav[:3]))

    action_counts: dict[str, int] = {}
    for step in steps:
        action = classify_action(step)
        action_counts[action] = action_counts.get(action, 0) + 1

    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        assistant_lines.append(f"- Performs {count} '{action}' action(s)")

    if variables:
        assistant_lines.append(f"\n**Variables used:** {', '.join(f'${{{v}}}' for v in variables)}")
        assistant_lines.append("These are substituted at runtime from your .env configuration.")

    ss_steps = [s for s in steps if "save it as" in s.lower() and ".png" in s.lower()]
    if ss_steps:
        names = [re.search(r"save it as\s*-\s*([a-zA-Z0-9_\-]+\.png)", s) for s in ss_steps]
        fnames = [m.group(1) for m in names if m]
        if fnames:
            assistant_lines.append(f"\n**Evidence screenshots:** {', '.join(fnames)}")

    report = next((s for s in steps if s.lower().startswith("give the report")), None)
    if report:
        msg = re.sub(r"^Give the report\s*[-–:]\s*", "", report, flags=re.IGNORECASE)
        assistant_lines.append(f"\n**Success condition:** {msg}")

    return make_chat(SYSTEM_PROMPT, user, "\n".join(assistant_lines))


def example_add_step(name: str, steps: list[str]) -> dict:
    """Task: extend the flow with an additional verification step."""
    # Show the first half of the flow, ask model to add a verification
    half = steps[:len(steps)//2]
    partial_flow = json.dumps({"name": name.strip(), "steps": half}, indent=2)
    variables = extract_variables(steps)

    user = (
        f"Given this partial automation flow:\n\n{partial_flow}\n\n"
        "Add a step after the last step to verify the action was successful "
        "and take a screenshot as evidence."
    )
    # The 'correct' answer is the next step in the real flow
    next_step = steps[len(steps)//2] if len(steps) > 1 else "SS"
    extended = half + [next_step]
    assistant = json.dumps({"name": name.strip(), "steps": extended}, indent=2)
    return make_chat(SYSTEM_PROMPT, user, assistant)


def example_variables(name: str, steps: list[str]) -> dict:
    """Task: list and explain all variables in the flow."""
    flow_json = json.dumps({"name": name.strip(), "steps": steps}, indent=2)
    variables = extract_variables(steps)

    if not variables:
        return None

    user = (
        f"List and explain all environment variables used in this flow:\n\n{flow_json}"
    )

    var_descriptions = {
        "COS_URL":               "URL of the Customer Operations System (COS) portal",
        "PORTAL_URL":            "URL of the customer self-service portal (e.g. Tusass)",
        "ADMIN_USER":            "Admin username / email for COS login",
        "ADMIN_PASS":            "Admin password for COS login",
        "MISTIN_ID":             "Customer MISTIN identifier used for search",
        "PHONE_NUMBER":          "Customer phone/mobile number for top-up",
        "MOBILE_NUMBER":         "Customer mobile number (same as PHONE_NUMBER in most flows)",
        "TOPUP_AMOUNT":          "Amount to top up in local currency",
        "CARD_NUMBER":           "Payment card number (16 digits)",
        "CARD_MONTH":            "Card expiry month (MM format)",
        "CARD_YEAR":             "Card expiry year (YY format)",
        "CARD_CVV":              "Card CVV/CVC security code",
        "DATA_AMOUNT":           "Data package amount and description (e.g. '3GB data 150 kr')",
        "ICC_URL":               "URL of the ICC inventory system",
        "ICC_ID":                "Extracted ICCID (SIM card identifier) from inventory",
        "ICC_ROW":               "Row number in inventory table to extract ICCID from",
        "MSITCOS_URL":           "URL of the MSITCOS portal",
        "CSR_USER":              "CSR system username",
        "CSR_PASSWORD":          "CSR system password",
        "ACCOUNT_NUMBER":        "Customer account number",
        "PHONE_ROW":             "Row number in phone number selection list",
        "COS_URL":               "URL of the COS portal",
        "COS_OPERATION_URL":     "URL of the operations service process list",
        "OPERATIONS_USER":       "Operations portal username",
        "OPERATIONS_PASS":       "Operations portal password",
        "SUBSCRIBER_EXTERNAL_ID":"Extracted subscriber external ID from the COS page",
        "OLD_BALANCE":           "Balance captured before the top-up operation",
        "NEW_BALANCE":           "Balance captured after the top-up operation",
    }

    lines = [f"The '{name.strip()}' flow uses {len(variables)} variable(s):\n"]
    for var in variables:
        desc = var_descriptions.get(var, "Flow-specific configuration value")
        lines.append(f"- `${{{var}}}` — {desc}")

    lines.append("\nThese are loaded from a `.env` file at runtime and substituted "
                 "before each step is executed.")
    return make_chat(SYSTEM_PROMPT, user, "\n".join(lines))


def example_classify_steps(name: str, steps: list[str]) -> dict:
    """Task: given a list of steps, label each with its action type."""
    sample_steps = steps[:10]  # keep examples short
    user = (
        "For each of the following browser automation steps, identify the action type "
        "(navigate, click, type, select, wait, screenshot, extract, verify, press_key, "
        "scroll, report):\n\n"
        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(sample_steps))
    )
    labelled = [f"{i+1}. [{classify_action(s).upper()}] {s}"
                for i, s in enumerate(sample_steps)]
    return make_chat(SYSTEM_PROMPT, user, "\n".join(labelled))


def example_create_variant(name: str, steps: list[str]) -> dict:
    """Task: create a flow variant with a different variable value."""
    variables = extract_variables(steps)
    if not variables:
        return None

    var = variables[0]
    flow_json = json.dumps({"name": name.strip(), "steps": steps}, indent=2)
    user = (
        f"Given this flow:\n\n{flow_json}\n\n"
        f"Create a variant of this flow that also accepts `${{{var}}}` as a parameter "
        "but adds a verification step at the end to confirm the operation succeeded."
    )
    verify_step = f"Verify the operation completed successfully for ${{{var}}}"
    ss_step = "Take the screenshot of that page and save it as - final-verify.png -"
    variant_steps = steps + [verify_step, ss_step]
    assistant = json.dumps(
        {"name": f"{name.strip()} (with verify)", "steps": variant_steps}, indent=2
    )
    return make_chat(SYSTEM_PROMPT, user, assistant)


def example_from_nl(name: str, steps: list[str]) -> dict:
    """Task: convert natural language description to structured steps."""
    # Pick a 5-step window from the flow
    start = random.randint(0, max(0, len(steps) - 5))
    window = steps[start:start + 5]

    nl_descriptions = []
    for step in window:
        action = classify_action(step)
        if action == "navigate":
            url = re.sub(r"Navigate to\s*", "", step, flags=re.IGNORECASE)
            nl_descriptions.append(f"Open the page at {url}")
        elif action == "click":
            target = re.sub(r"^Click\s+(the\s+)?(-\s+)?", "", step, flags=re.IGNORECASE)
            nl_descriptions.append(f"Press the {target} button")
        elif action == "type":
            nl_descriptions.append(f"Fill in: {step}")
        elif action == "wait":
            ms_m = re.search(r"(\d+)ms", step)
            if ms_m:
                nl_descriptions.append(f"Pause for {int(ms_m.group(1))//1000} second(s)")
        else:
            nl_descriptions.append(step)

    user = (
        "Convert these natural language instructions into browser automation steps "
        "using the JSON format with action steps:\n\n"
        + "\n".join(f"- {d}" for d in nl_descriptions)
    )
    assistant = json.dumps({"name": "Generated Flow", "steps": window}, indent=2)
    return make_chat(SYSTEM_PROMPT, user, assistant)


# ── Main conversion ─────────────────────────────────────────────────────────

GENERATORS = [
    example_generate_flow,
    example_explain_flow,
    example_add_step,
    example_variables,
    example_classify_steps,
    example_create_variant,
    example_from_nl,
]


def load_flow(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        name  = data.get("name", path.stem).strip()
        steps_raw = (
            data.get("steps")
            or (data.get("task") or {}).get("steps")
            or []
        )
        steps = [str(s).strip() for s in steps_raw if str(s).strip()]
        if len(steps) < 3:
            print(f"  [skip] {path.name} — too few steps ({len(steps)})")
            return None
        return {"name": name, "steps": steps, "source": path.name}
    except Exception as e:
        print(f"  [error] {path.name}: {e}")
        return None


def convert(flows_dir: str, output_dir: str, split: float = 0.9, seed: int = 42):
    random.seed(seed)
    flows_path  = Path(flows_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_files = list(flows_path.rglob("*.json"))
    print(f"Found {len(json_files)} JSON file(s) in {flows_path}")

    all_examples: list[dict] = []

    for path in json_files:
        flow = load_flow(path)
        if not flow:
            continue
        print(f"  Processing: {flow['name']} ({len(flow['steps'])} steps)")

        for gen_fn in GENERATORS:
            try:
                example = gen_fn(flow["name"], flow["steps"])
                if example:
                    all_examples.append(example)
            except Exception as e:
                print(f"    [warn] {gen_fn.__name__} failed: {e}")

    random.shuffle(all_examples)

    split_idx = int(len(all_examples) * split)
    train_examples = all_examples[:split_idx]
    val_examples   = all_examples[split_idx:]

    train_path = output_path / "train.jsonl"
    val_path   = output_path / "val.jsonl"

    for path, examples in [(train_path, train_examples), (val_path, val_examples)]:
        with open(path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\nDataset written:")
    print(f"  Train: {len(train_examples)} examples -> {train_path}")
    print(f"  Val:   {len(val_examples)} examples -> {val_path}")
    print(f"  Total: {len(all_examples)} examples from {len(json_files)} flow(s)")
    print(f"\nWith hundreds of flows this will produce {len(GENERATORS)*2}xN examples.")
    return train_path, val_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--flows_dir",  default="../flows/json-flow")
    parser.add_argument("--output_dir", default="./data")
    parser.add_argument("--split",      type=float, default=0.9)
    parser.add_argument("--seed",       type=int,   default=42)
    args = parser.parse_args()

    convert(args.flows_dir, args.output_dir, args.split, args.seed)
