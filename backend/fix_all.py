"""
fix_all.py — Patch EVERY flow in the database:
  - Replace all env-key references with real values from .env
  - Drop screenshot steps
  - Works with the OLD running server (no restart needed)
Run:  python fix_all.py
"""
import sys, os, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# ── Read .env values ──────────────────────────────────────────────────────────
ENV = {}
env_path = Path(__file__).parent / ".env"
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        k = k.strip()
        if k and " " not in k:
            ENV[k.upper()] = v.strip()

PORTAL_URL   = ENV["PORTAL_URL"]
ADMIN_URL    = ENV["ADMIN_URL"]
ADMIN_USER   = ENV["ADMIN_USER"]
ADMIN_PASS   = ENV["ADMIN_PASS"]
PHONE_NUMBER = ENV["PHONE_NUMBER"]
CARD_NUMBER  = ENV["CARD_NUMBER"]
CARD_MONTH   = ENV["CARD_MONTH"]
CARD_YEAR    = ENV["CARD_YEAR"]
CARD_CVV     = ENV["CARD_CVV"]

print(f"PORTAL_URL   = {PORTAL_URL}")
print(f"ADMIN_URL    = {ADMIN_URL}")
print(f"ADMIN_USER   = {ADMIN_USER}")
print(f"PHONE_NUMBER = {PHONE_NUMBER}")
print(f"CARD_NUMBER  = {CARD_NUMBER}")
print(f"CARD_MONTH/YEAR/CVV = {CARD_MONTH}/{CARD_YEAR}/{CARD_CVV}")
print()

# ── Substitution pairs: (regex_pattern, replacement) ─────────────────────────
# Order matters: longer/more-specific patterns first
SUBS = [
    # ${VAR_NAME} format
    (r"\$\{PORTAL_URL\}",   PORTAL_URL),
    (r"\$\{ADMIN_URL\}",    ADMIN_URL),
    (r"\$\{ADMIN_USER\}",   ADMIN_USER),
    (r"\$\{ADMIN_PASS\}",   ADMIN_PASS),
    (r"\$\{PHONE_NUMBER\}", PHONE_NUMBER),
    (r"\$\{CARD_NUMBER\}",  CARD_NUMBER),
    (r"\$\{CARD_MONTH\}",   CARD_MONTH),
    (r"\$\{CARD_YEAR\}",    CARD_YEAR),
    (r"\$\{CARD_CVV\}",     CARD_CVV),

    # "key =" format — generic aliases only
    (r"portal\s+url\s*=\s*",                PORTAL_URL + " "),
    (r"app\s+url\s*=\s*",                   PORTAL_URL + " "),
    (r"site\s+url\s*=\s*",                  PORTAL_URL + " "),
    (r"admin\s+url\s*=\s*",                 ADMIN_URL  + " "),
    (r"admin[_\s]+user(?:name)?\s*=\s*",    ADMIN_USER + " "),
    (r"admin[_\s]+pass(?:word)?\s*=\s*",    ADMIN_PASS + " "),
    (r"phone\s+number\s*=\s*",             PHONE_NUMBER + " "),
    (r"card\s+number\s*=\s*",              CARD_NUMBER + " "),
    (r"card\s+expiry\s+month\s*=\s*",      CARD_MONTH + " "),
    (r"card\s+month\s*=\s*",               CARD_MONTH + " "),
    (r"card\s+expiry\s+year\s*=\s*",       CARD_YEAR + " "),
    (r"card\s+year\s*=\s*",                CARD_YEAR + " "),
    (r"card\s+cvv\s*=\s*",                 CARD_CVV + " "),

    # "= key_name" format (value after =)
    (r"=\s*portal\s*url\b",                PORTAL_URL),
    (r"=\s*app\s*url\b",                   PORTAL_URL),
    (r"=\s*admin\s*url\b",                 ADMIN_URL),
    (r"=\s*admin[_\s]*user(?:name)?\b",    ADMIN_USER),
    (r"=\s*admin[_\s]*pass(?:word)?\b",    ADMIN_PASS),
    (r"=\s*phone\s*number\b",              PHONE_NUMBER),
    (r"=\s*card\s*number\b",               CARD_NUMBER),
    (r"=\s*card\s*expiry\s*month\b",       CARD_MONTH),
    (r"=\s*card\s*month\b",                CARD_MONTH),
    (r"=\s*card\s*expiry\s*year\b",        CARD_YEAR),
    (r"=\s*card\s*year\b",                 CARD_YEAR),
    (r"=\s*card\s*cvv\b",                  CARD_CVV),

    # Fix card values that may be wrong (hardcoded old values)
    (r"(?i)(expiry\s+year\s+with\s+)\d+",     r"\g<1>" + CARD_YEAR),
    (r"(?i)(expiry\s+month\s+with\s+)\d+",    r"\g<1>" + CARD_MONTH),
    (r"(?i)(cvv\s+with\s+)\d+",               r"\g<1>" + CARD_CVV),
    (r"(?i)(card\s+number\s+(?:field\s+)?with\s+)[\d\s]+", r"\g<1>" + CARD_NUMBER),
]


def is_screenshot_step(s):
    lo = s.lower().strip()
    return (lo.startswith("take a screenshot") or
            lo.startswith("screenshot") or
            (lo.startswith("take") and "screenshot" in lo))


def fix_step(s):
    if is_screenshot_step(s):
        return None  # drop
    orig = s
    for pat, repl in SUBS:
        try:
            s = re.sub(pat, repl, s, flags=re.IGNORECASE)
        except Exception:
            pass
    return s.strip()


# ── Process all flows ─────────────────────────────────────────────────────────
flows_dir = Path(__file__).parent / "artifacts" / "flows"
fixed = 0
skipped = 0

for flow_file in sorted(flows_dir.glob("*.json")):
    data = json.loads(flow_file.read_text(encoding="utf-8"))
    task_raw = data.get("task", "")

    # Try to find steps — handle multiple nesting levels AND raw formats
    steps = []
    steps_location = None
    parsed_outer = None

    def extract_steps_from_parsed(p):
        """Return (steps_list, location_key) or (None, None)."""
        if isinstance(p, list):
            # Each element may be a string or an object
            flat = []
            for item in p:
                if isinstance(item, str):
                    flat.append(item)
                elif isinstance(item, dict):
                    # Try to pull a readable description from structured step objects
                    desc = (item.get("description") or item.get("action") or
                            item.get("text") or item.get("step") or str(item))
                    url = item.get("url", "")
                    val = item.get("value", "")
                    if url:
                        desc = f"{desc} {url}"
                    elif val:
                        desc = f"{desc} {val}"
                    flat.append(desc.strip())
            return flat, "list"
        if isinstance(p, dict):
            # Direct: {"steps": [...]}
            if "steps" in p and isinstance(p["steps"], list):
                flat, _ = extract_steps_from_parsed(p["steps"])
                return flat, "direct"
            # Nested: {"task": {"steps": [...]}, ...}
            if "task" in p:
                inner = p["task"]
                if isinstance(inner, dict) and "steps" in inner:
                    flat, _ = extract_steps_from_parsed(inner["steps"])
                    return flat, "nested"
                if isinstance(inner, list):
                    flat, _ = extract_steps_from_parsed(inner)
                    return flat, "nested_list"
        return None, None

    try:
        parsed_outer = json.loads(task_raw)
        steps, steps_location = extract_steps_from_parsed(parsed_outer)
        if not steps:
            steps, steps_location = None, None
    except Exception:
        parsed_outer = None

    # Fallback: task is raw comma-separated quoted strings without outer brackets
    if not steps and task_raw and task_raw.strip().startswith('"'):
        try:
            wrapped = "[" + task_raw + "]"
            parsed_outer = json.loads(wrapped)
            steps = [str(s) for s in parsed_outer if isinstance(s, str)]
            if steps:
                steps_location = "raw_list"
        except Exception:
            pass

    # Last-resort: extract all quoted strings via regex
    if not steps and task_raw:
        raw_strings = re.findall(r'"((?:[^"\\]|\\.)*)"', task_raw)
        if len(raw_strings) >= 3:
            steps = raw_strings
            steps_location = "regex"

    if not steps:
        skipped += 1
        continue

    new_steps = []
    changed = False
    for s in steps:
        result = fix_step(s)
        if result is None:
            changed = True   # dropped
            continue
        new_steps.append(result)
        if result != s:
            changed = True

    if not changed:
        skipped += 1
        continue

    # Write back — always store as clean {"steps": [...]} JSON string
    data["task"] = json.dumps({"steps": new_steps}, ensure_ascii=False, indent=2)

    flow_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    fixed += 1
    name = data.get("name", flow_file.stem)
    print(f"Fixed [{fixed}]: {name}  ({len(steps)} -> {len(new_steps)} steps)")
    if new_steps:
        print(f"  Step 1: {new_steps[0]}")
        print(f"  Step 2: {new_steps[1] if len(new_steps)>1 else ''}")

print()
print(f"Fixed: {fixed}   Skipped (clean): {skipped}")
