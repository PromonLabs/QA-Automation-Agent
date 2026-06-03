"""
Standalone flow runner — no server, no UI required.
Usage:
    python run.py
    python run.py path/to/flow.json
"""
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)

from app.agents.browser_agent import BrowserAgent
from app.agents.llm_client import _steps_from_task
from app.agents.orchestrator import _extract_steps_from_task, _substitute_captured, _reload_dotenv
from app.agents.pdf_reporter import generate_pdf
from app.core.config import settings
from app.models.schemas import ExecutionResult, ExecutionLog, ExecutionStatus

DEFAULT_FLOW = Path(__file__).parent.parent / "flows" / "json-flow" / "Tusass-TopUp-Talk.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main():
    _reload_dotenv()

    flow_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FLOW
    if not flow_path.exists():
        print(f"Flow file not found: {flow_path}")
        sys.exit(1)

    flow_data  = json.loads(flow_path.read_text(encoding="utf-8"))
    flow_name  = flow_data.get("name", flow_path.stem).strip()
    raw_task   = json.dumps(flow_data)

    # Extract steps and report note — no LLM call
    steps_list = _extract_steps_from_task(raw_task)
    report_note = ""
    for s in steps_list:
        if re.match(r"^give\s+the\s+report\b", s.lower()):
            report_note = re.sub(
                r"^give\s+the\s+report\s*[-–:]\s*", "", s, flags=re.IGNORECASE
            ).strip()
            break

    task_text = "\n".join(f"- {s}" for s in steps_list)
    steps     = _steps_from_task(task_text)
    plan      = {"steps": steps, "expected_outcome": report_note or "Complete all steps"}

    print(f"\n  {flow_name}")
    print(f"  {len(steps)} steps  |  headless  |  no LLM")
    print("  " + "-" * 44)

    exec_id      = str(uuid.uuid4())
    screenshots: list = []
    logs:        list = []
    start        = datetime.now(timezone.utc)

    async def on_log(log: ExecutionLog):
        logs.append(log)
        msg = log.message.strip()
        if msg:
            print(f"  {msg}")
        if log.screenshot and log.screenshot not in screenshots:
            screenshots.append(log.screenshot)

    agent  = BrowserAgent(exec_id=exec_id, headless=True, log_callback=on_log)
    result = await agent.run(plan)

    end      = datetime.now(timezone.utc)
    duration = (end - start).total_seconds()
    status   = ExecutionStatus.SUCCESS if result["status"] == "success" else ExecutionStatus.FAILED
    m, s     = divmod(int(duration), 60)

    captured   = result.get("captured_vars", {})
    final_note = _substitute_captured(report_note, captured) if report_note else result.get("summary", "")

    print("  " + "-" * 44)
    icon = "PASS" if status == ExecutionStatus.SUCCESS else "FAIL"
    print(f"  {icon}  -  {result['steps_completed']}/{result['steps_total']} steps  in  {m}m {s}s\n")

    exec_result = ExecutionResult(
        id=exec_id,
        flow_id=str(uuid.uuid4()),
        flow_name=flow_name,
        status=status,
        started_at=start.isoformat(),
        finished_at=end.isoformat(),
        duration_seconds=round(duration, 2),
        logs=logs,
        screenshots=screenshots,
        result_summary=final_note,
        steps_completed=result["steps_completed"],
        steps_total=result["steps_total"],
    )

    safe     = re.sub(r"[^\w\-]", "_", flow_name).strip("_")
    safe     = re.sub(r"_+", "_", safe)
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    report_p = settings.REPORTS_DIR / f"{safe}_{ts}.pdf"
    generate_pdf(exec_result, report_p)
    print(f"  Report -> {report_p}\n")


if __name__ == "__main__":
    asyncio.run(main())
