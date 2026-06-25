"""
Bulk execution — run a flow for a list of numbers/IDs in parallel.

Execution env = bulk_env (base) merged with per-item env_vars.
Two input modes:
  1. subscribers — each item carries its own env_vars dict (data mode)
  2. numbers     — one variable changes per row; bulk_env provides the rest (file mode)
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.storage import artifact_store

router = APIRouter(prefix="/bulk", tags=["bulk"])

_BULK_DIR     = settings.ARTIFACTS_DIR / "bulk"
_BULK_ENV_FILE = _BULK_DIR / "bulk_env.json"
_DATA_FILE    = settings.ARTIFACTS_DIR / "data" / "tusass_subscribers.json"

_BULK_DIR.mkdir(parents=True, exist_ok=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _bulk_path(bulk_id: str) -> Path:
    return _BULK_DIR / f"{bulk_id}.json"

def _save(run: dict):
    _bulk_path(run["id"]).write_text(json.dumps(run, indent=2), encoding="utf-8")

def _load(bulk_id: str) -> Optional[dict]:
    p = _bulk_path(bulk_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def _load_bulk_env() -> Dict[str, str]:
    if _BULK_ENV_FILE.exists():
        return json.loads(_BULK_ENV_FILE.read_text(encoding="utf-8"))
    return {}

def _save_bulk_env(env: Dict[str, str]):
    _BULK_ENV_FILE.write_text(json.dumps(env, indent=2), encoding="utf-8")


# ── models ────────────────────────────────────────────────────────────────────

class BulkEnvUpdate(BaseModel):
    env_vars: Dict[str, str]

class BulkSubscriberInput(BaseModel):
    env_vars: Dict[str, str]
    label: str = ""

class BulkRunRequest(BaseModel):
    flow_id: str
    # data mode
    subscribers: Optional[List[BulkSubscriberInput]] = None
    # file mode — each number replaces exactly one variable; bulk_env fills the rest
    numbers: Optional[List[str]] = None
    variable_name: str = "ACCOUNT_NUMBER"   # the single variable that changes per row
    max_parallel: int = 3


# ── bulk env endpoints ────────────────────────────────────────────────────────

@router.get("/env")
async def get_bulk_env(user: str = Depends(get_current_user)):
    return _load_bulk_env()

@router.put("/env")
async def save_bulk_env(body: BulkEnvUpdate, user: str = Depends(get_current_user)):
    _save_bulk_env(body.env_vars)
    return {"ok": True}


# ── subscribers data endpoint ─────────────────────────────────────────────────

@router.get("/subscribers")
async def get_subscribers(user: str = Depends(get_current_user)):
    if not _DATA_FILE.exists():
        return []
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return data.get("subscribers", [])


# ── run ───────────────────────────────────────────────────────────────────────

@router.post("/run")
async def start_bulk_run(
    req: BulkRunRequest,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
):
    from app.api.routes.disk_flows import _load_disk_flow_content
    result = _load_disk_flow_content(req.flow_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Flow not found: {req.flow_id}")

    flow_name, _, _ = result
    bulk_id = str(uuid.uuid4())

    if req.subscribers:
        items = [
            {
                "number": s.env_vars.get("ACCOUNT_NUMBER", s.label or str(i)),
                "label": s.label or s.env_vars.get("plan", ""),
                "env_vars": s.env_vars,
                "execution_id": None,
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "error": None,
            }
            for i, s in enumerate(req.subscribers)
        ]
    else:
        numbers = [n.strip() for n in (req.numbers or []) if n.strip()]
        items = [
            {
                "number": n,
                "label": n,
                # only the one changing variable; bulk_env merged at execution time
                "env_vars": {req.variable_name: n},
                "execution_id": None,
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "error": None,
            }
            for n in numbers
        ]

    if not items:
        raise HTTPException(status_code=400, detail="No numbers or subscribers provided")

    run = {
        "id": bulk_id,
        "flow_id": req.flow_id,
        "flow_name": flow_name,
        "variable_name": req.variable_name,
        "max_parallel": req.max_parallel,
        "total": len(items),
        "completed": 0,
        "success": 0,
        "failed": 0,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "items": items,
    }
    _save(run)
    background_tasks.add_task(_execute_bulk, bulk_id)
    return run


# ── execution ─────────────────────────────────────────────────────────────────

async def _run_one_item(bulk_id: str, idx: int, shared_browser=None, shared_context=None):
    """Execute a single bulk item. Reuses shared_browser/shared_context if provided."""
    from app.api.routes.disk_flows import _load_disk_flow_content
    from app.agents.orchestrator import Orchestrator
    from app.api.routes.execution import manager, _running

    run = _load(bulk_id)
    item = run["items"][idx]
    run["items"][idx]["status"] = "running"
    run["items"][idx]["started_at"] = _now()
    _save(run)

    status, duration, error, exec_id = "failed", None, None, None
    try:
        result = _load_disk_flow_content(run["flow_id"])
        if not result:
            raise Exception("Flow not found")
        name, task_content, fmt = result

        bulk_env = _load_bulk_env()
        env_vars = {**bulk_env, **item.get("env_vars", {})}
        # Each bulk item gets a different ICC and phone row so repeated runs don't
        # hit "reserved" errors on the same ID/number. Row = 1-based item index.
        _ORDINALS = ["first", "second", "third", "fourth", "fifth",
                     "sixth", "seventh", "eighth", "ninth", "tenth"]
        if "ICC_ROW" not in env_vars:
            env_vars["ICC_ROW"] = str(idx + 1)
        if "PHONE_ROW" not in env_vars:
            env_vars["PHONE_ROW"] = _ORDINALS[min(idx, len(_ORDINALS) - 1)]
        label = item.get("label") or item["number"]

        payload = {
            "name": f"{name} [{label}]",
            "description": f"Bulk run for {label}",
            "format": fmt,
            "task": task_content,
            "tags": ["bulk"],
            "env_vars": env_vars,
        }
        flow = artifact_store.create_flow(payload)
        exec_record = artifact_store.create_execution(flow)
        exec_id = exec_record.id

        run = _load(bulk_id)
        run["items"][idx]["execution_id"] = exec_id
        _save(run)

        _running.add(exec_id)
        try:
            orch = Orchestrator(
                flow=flow,
                exec_id=exec_id,
                headless=settings.BROWSER_HEADLESS,
                ws_broadcast=manager.broadcast,
                shared_browser=shared_browser,
                shared_context=shared_context,
                already_in_proactor_loop=(shared_browser is not None),
            )
            await orch.run()
        finally:
            _running.discard(exec_id)

        final = artifact_store.get_execution(exec_id)
        status = final.status.value if final else "failed"
        duration = final.duration_seconds if final else None

        # Extract the most informative error message from the execution logs
        if status == "failed" and final and final.logs:
            for log in reversed(final.logs):
                msg = log.get("message", "") if isinstance(log, dict) else getattr(log, "message", "")
                if "STEP FAILED" in msg or "STOPPED at step" in msg:
                    # Pull just the first line — the step description is most useful
                    error = msg.split("\n")[0].strip().lstrip("✗ ").lstrip("→ ")
                    break

    except Exception as e:
        error = str(e)

    run = _load(bulk_id)
    run["items"][idx].update({
        "status": status,
        "finished_at": _now(),
        "duration_seconds": duration,
        "error": error,
        "execution_id": exec_id,
    })
    run["completed"] += 1
    run["success" if status == "success" else "failed"] += 1
    _save(run)


async def _execute_bulk(bulk_id: str):
    run = _load(bulk_id)
    max_parallel = max(1, run.get("max_parallel", 1))
    n_items = len(run["items"])

    if max_parallel == 1:
        # One Chromium process, sequential contexts — no timeout from concurrency
        import sys
        import threading
        from playwright.async_api import async_playwright

        def sequential_thread():
            import asyncio as _aio
            loop = _aio.ProactorEventLoop() if sys.platform == "win32" else _aio.new_event_loop()
            _aio.set_event_loop(loop)

            async def _run():
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(
                        headless=settings.BROWSER_HEADLESS,
                        args=[
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-blink-features=AutomationControlled",
                            "--disable-web-security",
                            "--allow-running-insecure-content",
                            "--disable-background-timer-throttling",
                            "--disable-renderer-backgrounding",
                            "--no-first-run",
                            "--ignore-certificate-errors",
                        ],
                    )
                    # One shared context — login once, session reused for all runs
                    context = await browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                        ),
                        ignore_https_errors=True,
                    )
                    for i in range(n_items):
                        await _run_one_item(bulk_id, i, shared_browser=browser, shared_context=context)
                    await browser.close()

            loop.run_until_complete(_run())
            loop.close()

        t = threading.Thread(target=sequential_thread, daemon=True)
        t.start()
        while t.is_alive():
            await asyncio.sleep(0.5)
        t.join()

    else:
        # Parallel: each item gets its own browser, staggered to spread the load.
        _STAGGER_SECONDS = 2   # gap between each browser launch
        sem = asyncio.Semaphore(max_parallel)

        async def run_one(idx: int):
            await asyncio.sleep(idx * _STAGGER_SECONDS)
            async with sem:
                await _run_one_item(bulk_id, idx, shared_browser=None)

        await asyncio.gather(*[run_one(i) for i in range(n_items)], return_exceptions=True)

    run = _load(bulk_id)
    run["status"] = "completed"
    run["finished_at"] = _now()
    _save(run)


# ── list / get ────────────────────────────────────────────────────────────────

@router.get("")
async def list_bulk_runs(user: str = Depends(get_current_user)):
    runs = []
    for p in sorted(_BULK_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name == "bulk_env.json":
            continue
        try:
            run = json.loads(p.read_text(encoding="utf-8"))
            runs.append({k: v for k, v in run.items() if k != "items"})
        except Exception:
            continue
    return runs

@router.get("/{bulk_id}")
async def get_bulk_run(bulk_id: str, user: str = Depends(get_current_user)):
    run = _load(bulk_id)
    if not run:
        raise HTTPException(status_code=404, detail="Bulk run not found")
    return run
