"""
Execution Orchestrator — coordinates LLM planning + browser execution + artifact storage.
"""
import asyncio
import json
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Set, List

from app.agents.llm_client import llm_client
from app.agents.browser_agent import BrowserAgent
from app.agents.pdf_reporter import generate_pdf
from app.models.schemas import ExecutionStatus, ExecutionLog, ExecutionResult, FlowResponse
from app.storage import artifact_store
from app.core.config import settings

_active_executions: Set[str] = set()
_cancelled_executions: Set[str] = set()

# Path to .env file (backend root)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


def _load_flow_env_file(flow_name: str) -> dict:
    """
    Load per-flow .env from DISK_FLOWS_DIR/env/<stem>.env.
    Matches by normalizing both the filename stem and the flow name
    (strips spaces/hyphens/underscores, case-insensitive) so
    'Mobile-Data-Add.env' matches flow name 'Mobile Data Add'.
    """
    from app.core.config import settings
    env_dir = settings.DISK_FLOWS_DIR / "env"
    if not env_dir.exists():
        return {}
    norm_name = re.sub(r'[\s_\-]+', '', flow_name.strip().lower())
    try:
        for env_file in sorted(env_dir.glob("*.env")):
            if re.sub(r'[\s_\-]+', '', env_file.stem.lower()) == norm_name:
                result = {}
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        if k.strip() and " " not in k.strip():
                            result[k.strip().upper()] = v.strip()
                return result
    except Exception:
        pass
    return {}


def _substitute_captured(text: str, captured: dict) -> str:
    """Replace ${VAR} placeholders with values extracted during the run."""
    for k, v in captured.items():
        text = text.replace(f"${{{k}}}", v)
    # Replace any remaining unresolved placeholders so the report never shows raw ${...}
    text = re.sub(r'\$\{[^}]+\}', 'N/A', text)
    return text


def _reload_dotenv() -> None:
    """
    Reload .env into os.environ with override=True so that:
    - Any edits to .env take effect on the NEXT execution without restarting the server
    - SCREENSHOT_MODE, BROWSER_HEADLESS, credentials, URLs are always up-to-date
    """
    if not _ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=True)
        # Sync settings object so BrowserAgent picks up new values
        settings.BROWSER_HEADLESS            = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"
        settings.BROWSER_SLOW_MO             = int(os.environ.get("BROWSER_SLOW_MO", "0"))
        settings.SCREENSHOT_MODE             = os.environ.get("SCREENSHOT_MODE", "none").lower()
        settings.BROWSER_NAVIGATION_TIMEOUT  = int(os.environ.get("BROWSER_NAVIGATION_TIMEOUT", "180000"))
    except Exception:
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _substitute_env_vars(text: str, flow_env: Optional[dict] = None) -> str:
    """
    Replace env variable references inside a flow step with actual env values.

    Priority order for value lookup:
      1. flow_env  — per-flow credentials saved in the flow record (highest)
      2. os.environ — global env / .env file loaded at startup
      3. .env file  — read fresh from disk on each execution

    Substitution passes (in order):
      1. ${VAR_NAME}     — standard template syntax
      2. raw_key =       — generic alias before = with no value
      3. = raw_key       — value reference after = sign
      4. bare raw_key    — alias at end-of-line or after value keywords
    """
    if not text:
        return text

    # ── Raw key → env var (original casing/spacing preserved for regex) ──────
    # Each entry: (display_name_lowercase, env_var)
    # Only GENERIC aliases — no brand/product-specific names.
    # Flow steps should use ${VAR_NAME} syntax or these generic labels.
    _RAW = [
        ("portal url",          "PORTAL_URL"),
        ("portalurl",           "PORTAL_URL"),
        ("app url",             "PORTAL_URL"),
        ("appurl",              "PORTAL_URL"),
        ("site url",            "PORTAL_URL"),
        ("siteurl",             "PORTAL_URL"),
        ("base url",            "PORTAL_URL"),
        ("baseurl",             "PORTAL_URL"),
        ("admin url",           "ADMIN_URL"),
        ("adminurl",            "ADMIN_URL"),
        ("admin user",          "ADMIN_USER"),
        ("admin username",      "ADMIN_USER"),
        ("adminuser",           "ADMIN_USER"),
        ("adminusername",       "ADMIN_USER"),
        ("admin pass",          "ADMIN_PASS"),
        ("admin password",      "ADMIN_PASS"),
        ("adminpass",           "ADMIN_PASS"),
        ("adminpassword",       "ADMIN_PASS"),
        ("phone number",        "PHONE_NUMBER"),
        ("phonenumber",         "PHONE_NUMBER"),
        ("card number",         "CARD_NUMBER"),
        ("cardnumber",          "CARD_NUMBER"),
        ("card month",          "CARD_MONTH"),
        ("card expiry month",   "CARD_MONTH"),
        ("cardmonth",           "CARD_MONTH"),
        ("card year",           "CARD_YEAR"),
        ("card expiry year",    "CARD_YEAR"),
        ("cardyear",            "CARD_YEAR"),
        ("card cvv",            "CARD_CVV"),
        ("cardcvv",             "CARD_CVV"),
    ]

    # Normalise: lowercase, strip spaces/underscores/hyphens
    def _norm(s: str) -> str:
        return re.sub(r"[\s_\-]", "", s.lower())

    # Build a lookup dict: norm(key) → env_var
    _NORM_MAP = {_norm(k): v for k, v in _RAW}

    # Read the .env file values directly (always fresh, no server restart needed)
    _dotenv_vals: dict = {}
    if _ENV_FILE.exists():
        try:
            for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip()
                    if k and " " not in k:          # skip keys with spaces (invalid)
                        _dotenv_vals[k.upper()] = v
        except Exception:
            pass

    def _env_get(var_name: str) -> Optional[str]:
        """
        Get env var value using priority order:
          1. flow_env (per-flow credentials saved in the flow record)
          2. os.environ (global / .env loaded at startup)
          3. .env file values read fresh from disk
        """
        key_upper = var_name.strip().upper()
        if flow_env:
            val = flow_env.get(key_upper) or flow_env.get(var_name.strip())
            if val:
                return val
        return os.environ.get(key_upper) or _dotenv_vals.get(key_upper)

    def _lookup(raw: str) -> Optional[str]:
        env_var = _NORM_MAP.get(_norm(raw))
        if env_var:
            val = _env_get(env_var)
            if val:
                return val
        direct = raw.strip().upper().replace(" ", "_").replace("-", "_")
        return _env_get(direct)

    def _key_pattern(display: str) -> str:
        """Build a regex fragment that matches the display name flexibly."""
        # escape then allow any combo of space/underscore/hyphen between words
        parts = re.split(r"[\s_\-]", display)
        return r"[\s_\-]*".join(re.escape(p) for p in parts if p)

    # ── Pass 1: ${VAR_NAME} ───────────────────────────────────────────────────
    text = re.sub(
        r"\$\{([^}]+)\}",
        lambda m: _env_get(m.group(1).strip()) or m.group(0),
        text,
    )

    # ── Pass 2: "raw_key =" — key is BEFORE the equals, value is empty ────────
    # e.g. "Navigate to  portal url = " → "Navigate to https://..."
    # Also handles "key = key" (redundant): "phone number = phone number" → the actual value
    for display, env_var in _RAW:
        val = _env_get(env_var) or ""
        if not val:
            continue
        try:
            kp = _key_pattern(display)
            # First, collapse "key = key" into just the value (avoids trailing alias words)
            pat_self = re.compile(
                r"\b" + kp + r"\s*=\s*" + kp + r"\b",
                re.IGNORECASE,
            )
            text = pat_self.sub(val, text)
            # Then handle the plain "key = " form (no value after it)
            pat = re.compile(
                r"\b" + kp + r"\s*=\s*",
                re.IGNORECASE,
            )
            text = pat.sub(val + " ", text)
        except re.error:
            pass

    # ── Pass 3: "= raw_key" — value reference after = sign ───────────────────
    # e.g. "type = phone number" → "type <value from PHONE_NUMBER>"
    def _eq_repl(m: re.Match) -> str:
        val = _lookup(m.group(1).strip())
        return val if val else m.group(0)

    text = re.sub(
        r"=\s+([a-zA-Z][a-zA-Z0-9 _\-]{1,40}?)(?=\s*$|\s*,|\s*\.\s*$|\s+and\b|\s+then\b|\s+again\b)",
        _eq_repl,
        text,
        flags=re.IGNORECASE,
    )

    # ── Pass 4: bare raw_key at end or after value keywords ──────────────────
    # e.g. "Fill username field with admin username" → "…with the value from ADMIN_USER"
    _VALUE_KW = r"(?:with|type|for|navigate\s+to|use|number)\s+"
    for display, env_var in _RAW:
        val = _env_get(env_var) or ""
        if not val or val in text:
            continue
        try:
            pat_flex = _key_pattern(display)
            # end-of-line
            text = re.sub(
                r"(?i)" + pat_flex + r"\s*$",
                val,
                text,
            )
            # after value keyword
            text = re.sub(
                r"(?i)(" + _VALUE_KW + r")" + pat_flex + r"\b",
                lambda m2, v=val: m2.group(1) + v,
                text,
            )
        except re.error:
            pass

    return text.strip()


def _clean_step_line(line: str) -> str:
    """
    Clean a single line that may still have JSON formatting:
      "Click the button labeled Submit",  →  Click the button labeled Submit
    """
    line = line.strip().rstrip(",").strip()
    # Strip surrounding JSON string quotes (properly unescape)
    if line.startswith('"') and line.endswith('"'):
        try:
            line = json.loads(line)   # handles \n \t \" etc.
        except Exception:
            line = line[1:-1]         # bare strip as fallback
    return line.strip()


def _is_screenshot_step(step: str) -> bool:
    """
    Return True only for steps that do nothing useful beyond taking a screenshot
    AND whose screenshot is NOT needed in the PDF report.
    - "SS" bare steps → always keep (saved as ss_NNN.png for the PDF)
    - "save as X.png" steps → always keep (named screenshot for the PDF)
    - Generic "take a screenshot" with no filename → drop (redundant)
    """
    lo = step.lower().strip()
    lo_j = lo.replace("screen shot", "screenshot")

    # Always keep SS steps and named-save steps
    if lo_j == "ss":
        return False
    if "save" in lo_j and (".png" in lo_j or ".jpg" in lo_j):
        return False

    return (
        lo_j.startswith("take a screenshot") or
        lo_j.startswith("screenshot") or
        (lo_j.startswith("take") and "screenshot" in lo_j)
    )


def _extract_steps_from_task(raw_task: str, flow_env: Optional[dict] = None) -> List[str]:
    """
    Extract a list of step strings from ANY task format and apply env var substitution.
    Formats handled:
    - Full JSON flow file : {"name":..., "task": {"steps": [...]}}
    - Flat JSON steps     : {"steps": [...]}
    - Plain JSON array    : ["step1", "step2"]
    - Raw quoted lines    : "Navigate to...",\n"Click...",
    - Natural language    : one step per line
    After extraction, each step has ${ENV_VAR} and alias references resolved using
    flow_env (per-flow credentials) with highest priority.
    """
    raw_steps: List[str] = []

    # ── Try JSON parse first ───────────────────────────────────────────────
    try:
        parsed = json.loads(raw_task)
        if isinstance(parsed, dict):
            inner = parsed.get("task", {})
            if isinstance(inner, dict) and "steps" in inner:
                steps = inner["steps"]
                if isinstance(steps, list) and steps:
                    raw_steps = [str(s) for s in steps]
            if not raw_steps and "steps" in parsed:
                steps = parsed["steps"]
                if isinstance(steps, list) and steps:
                    raw_steps = [str(s) for s in steps]
        elif isinstance(parsed, list) and parsed:
            raw_steps = [str(s) for s in parsed]
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Wrap-in-array retry ────────────────────────────────────────────────
    if not raw_steps:
        try:
            wrapped = "[" + raw_task.strip().rstrip(",") + "]"
            parsed = json.loads(wrapped)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], str):
                raw_steps = [str(s) for s in parsed]
        except Exception:
            pass

    # ── Line-by-line fallback ──────────────────────────────────────────────
    if not raw_steps:
        skip_prefixes = ("{", "}", "[", "]", '"name"', '"description"',
                         '"format"', '"tags"', '"task"', '"steps"')
        for raw_line in raw_task.splitlines():
            l = raw_line.strip()
            if not l or any(l.startswith(p) for p in skip_prefixes):
                continue
            cleaned = _clean_step_line(l)
            if cleaned and len(cleaned) > 3:
                raw_steps.append(cleaned)

    # ── Apply env var substitution + drop pure screenshot steps ───────────
    result = []
    for step in raw_steps:
        step = _substitute_env_vars(step, flow_env=flow_env)
        # Strip trailing parenthetical annotations like "(all digits, do not truncate)"
        # so they are never typed literally into browser fields.
        step = re.sub(r'\s*\([^)]{3,120}\)\s*$', '', step).strip()
        if _is_screenshot_step(step):
            continue   # dropped — no screenshots; final state captured automatically
        if step and (len(step) > 3 or step.strip().upper() == "SS"):
            result.append(step)

    return result


class Orchestrator:
    def __init__(
        self,
        flow: FlowResponse,
        exec_id: str,
        headless: Optional[bool] = None,
        ws_broadcast: Optional[Callable] = None,
        shared_browser=None,
        shared_context=None,
        already_in_proactor_loop: bool = False,
    ):
        self.flow = flow
        self.shared_browser = shared_browser
        self.shared_context = shared_context
        self.already_in_proactor_loop = already_in_proactor_loop
        self.exec_id = exec_id
        self.headless = headless
        self.ws_broadcast = ws_broadcast

    async def _emit(self, type_: str, data: dict):
        if self.ws_broadcast:
            try:
                await self.ws_broadcast(self.exec_id, {"type": type_, "data": data})
            except Exception:
                pass

    async def _emit_log(self, log: ExecutionLog):
        artifact_store.append_log(self.exec_id, log)
        await self._emit("log", log.dict())

    async def _log(self, level: str, message: str):
        await self._emit_log(ExecutionLog(
            timestamp=_now(), level=level, message=message,
        ))

    async def run(self) -> Optional[ExecutionResult]:
        if self.exec_id in _active_executions:
            return artifact_store.get_execution(self.exec_id)
        _active_executions.add(self.exec_id)

        # ── Reload .env every execution so changes take effect immediately ────
        # This means you never need to restart the server after editing .env
        _reload_dotenv()

        start_time = datetime.now(timezone.utc)
        artifact_store.update_execution(self.exec_id, {
            "status": ExecutionStatus.RUNNING,
            "started_at": _now(),
        })
        await self._emit("status", {"status": "running", "exec_id": self.exec_id})

        try:
            if self.exec_id in _cancelled_executions:
                raise RuntimeError("Execution cancelled before start")

            # ── Extract task steps (handles ALL JSON formats + natural language) ──
            raw_task = self.flow.task
            # Explicit per-flow credentials saved in the flow record (UI-entered, highest priority)
            flow_env = dict(self.flow.env_vars) if self.flow.env_vars else {}
            # Load per-flow .env file — overrides global .env, explicit env_vars win over file
            file_env = _load_flow_env_file(self.flow.name)
            if file_env:
                await self._log("info", f"📂 Per-flow env: {self.flow.name}.env ({len(file_env)} var(s))")
                flow_env = {**file_env, **flow_env}
            elif flow_env:
                await self._log("info", f"🔑 Using flow-level credentials ({len(flow_env)} var(s))")
            steps_list = _extract_steps_from_task(raw_task, flow_env=flow_env)

            # Extract custom report note from any "Give the report" step
            report_note = ""
            for _s in steps_list:
                if re.match(r"^give\s+the\s+report\b", _s.lower()):
                    report_note = re.sub(
                        r"^give\s+the\s+report\s*[-–:]\s*", "", _s, flags=re.IGNORECASE
                    ).strip()
                    break

            await self._log("info", f"📝 Task extracted: {len(steps_list)} steps")

            if len(steps_list) < 2:
                # Show first 200 chars of what was stored for debugging
                preview = raw_task[:200].replace("\n", " ")
                raise RuntimeError(
                    f"Could not extract browser steps from the stored task "
                    f"({len(steps_list)} step found). "
                    f"Stored task preview: {preview!r}\n\n"
                    "➜ Solution: Go to New Flow, add at least 2 steps, then click Save & Run."
                )

            # Convert to plain text for LLM
            task_text = "\n".join(f"- {s}" for s in steps_list)
            await self._log("info", f"  Step 1: {steps_list[0][:80]}")
            await self._log("info", f"  Step {len(steps_list)}: {steps_list[-1][:80]}")

            # ── LLM Planning ───────────────────────────────────────────
            if settings.USE_FLOW_AGENT:
                await self._log("info", f"🤖 Sending task to {llm_client.active_model} ({llm_client.provider})…")
            else:
                await self._log("info", "⚡ Flow agent disabled — running steps directly")
            plan = await llm_client.generate_plan(task_text)
            total_steps = len(plan.get("steps", []))

            await self._log("info", f"📋 Plan ready: {total_steps} steps")
            if plan.get("reasoning"):
                await self._log("info", f"💭 {plan['reasoning'][:200]}")

            artifact_store.update_execution(self.exec_id, {"steps_total": total_steps})

            # ── Browser execution ─────────────────────────────────────
            async def on_log(log: ExecutionLog):
                await self._emit_log(log)
                if log.screenshot:
                    artifact_store.add_screenshot(self.exec_id, log.screenshot)
                    await self._emit("screenshot", {
                        "filename": log.screenshot,
                        "exec_id": self.exec_id,
                    })
                artifact_store.update_execution(self.exec_id, {
                    "steps_completed": log.step or 0,
                })

            async def on_frame(b64_jpeg: str):
                await self._emit("live_frame", {"b64": b64_jpeg})

            if self.exec_id in _cancelled_executions:
                raise RuntimeError("Execution cancelled")

            agent = BrowserAgent(
                exec_id=self.exec_id,
                headless=self.headless,
                log_callback=on_log,
                frame_callback=on_frame,
            )
            agent._shared_browser = self.shared_browser
            agent._shared_context = self.shared_context
            agent._already_in_proactor_loop = self.already_in_proactor_loop
            agent._flow_env = flow_env   # pass bulk-run per-item vars to agent for fallbacks
            result = await agent.run(plan)

            # ── Finalize ──────────────────────────────────────────────
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            final_status = (
                ExecutionStatus.SUCCESS if result["status"] == "success"
                else ExecutionStatus.FAILED
            )
            # Merge: flow env vars (lowest priority) < captured runtime vars (highest priority)
            # This ensures ${MISTIN_ID} etc. in report templates get substituted even if
            # the agent couldn't extract the value from the page.
            merged_vars = {**flow_env, **result.get("captured_vars", {})}
            skipped_unreachable = result.get("skipped_unreachable", 0)
            summary = report_note or result.get("summary", "")
            if final_status == ExecutionStatus.FAILED and skipped_unreachable:
                summary = result.get("stop_reason", summary)
            exec_result = artifact_store.update_execution(self.exec_id, {
                "status": final_status,
                "finished_at": _now(),
                "duration_seconds": round(duration, 2),
                "steps_completed": result["steps_completed"],
                "steps_total": result["steps_total"],
                "result_summary": _substitute_captured(summary, merged_vars),
            })

            icon = "✅" if final_status == ExecutionStatus.SUCCESS else "❌"
            await self._log(
                "success" if final_status == ExecutionStatus.SUCCESS else "error",
                f"{icon} {'COMPLETED' if final_status == ExecutionStatus.SUCCESS else 'FAILED'}"
                f" — {result['steps_completed']}/{result['steps_total']} steps in {duration:.1f}s",
            )

            # ── Clean up captured vars from .env after successful run ─────────
            # Variables like SUBSCRIBER_EXTERNAL_ID / ICC_ID are captured fresh
            # each run — remove stale entries so they don't bleed into other flows.
            if final_status == ExecutionStatus.SUCCESS:
                captured = result.get("captured_vars", {})
                if captured and _ENV_FILE.exists():
                    try:
                        lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
                        cleaned = [
                            ln for ln in lines
                            if not any(
                                ln.strip().upper().startswith(k.upper() + "=")
                                for k in captured
                            )
                        ]
                        if len(cleaned) != len(lines):
                            _ENV_FILE.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
                            removed = [k for k in captured if any(
                                ln.strip().upper().startswith(k.upper() + "=")
                                for ln in lines
                            )]
                            await self._log("info", f"🧹 Removed from .env: {', '.join(removed)}")
                    except Exception:
                        pass

            # ── Generate PDF report ────────────────────────────────────────
            if exec_result:
                try:
                    safe_name = re.sub(r"[^\w\-]", "_", self.flow.name.strip()).strip("_")
                    safe_name = re.sub(r"_+", "_", safe_name)
                    timestamp  = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
                    report_stem = f"{safe_name}_{timestamp}"
                    report_path = settings.REPORTS_DIR / f"{report_stem}.pdf"
                    pdf_ok = generate_pdf(exec_result, report_path)
                    ext = "pdf" if pdf_ok else "txt"
                    report_name = f"{report_stem}.{ext}"
                    await self._log("info", f"📄 Report: {report_name}")
                    artifact_store.update_execution(self.exec_id, {
                        "report_file": report_name,
                    })
                except Exception as pdf_err:
                    await self._log("info", f"ℹ️  Report generation skipped: {pdf_err}")

            await self._emit("status", {"status": final_status.value})
            await self._emit("complete", exec_result.dict() if exec_result else {})
            return exec_result

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            error_msg = str(e)
            tb = traceback.format_exc()

            artifact_store.update_execution(self.exec_id, {
                "status": ExecutionStatus.FAILED,
                "finished_at": _now(),
                "duration_seconds": round(duration, 2),
                "error": error_msg,
            })
            await self._log("error", f"❌ Error: {error_msg}")
            # Show last 4 traceback lines for diagnosis
            tb_lines = [l.strip() for l in tb.splitlines() if l.strip()]
            for line in tb_lines[-4:]:
                await self._log("error", f"   {line}")
            await self._emit("status", {"status": "failed"})
            return artifact_store.get_execution(self.exec_id)

        finally:
            _active_executions.discard(self.exec_id)
            _cancelled_executions.discard(self.exec_id)


def cancel_execution(exec_id: str) -> bool:
    if exec_id in _active_executions:
        _cancelled_executions.add(exec_id)
        return True
    return False


def is_active(exec_id: str) -> bool:
    return exec_id in _active_executions
