"""
Bulk execution — run a flow for a list of numbers/IDs in parallel.
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

_BULK_DIR = settings.ARTIFACTS_DIR / "bulk"
_BULK_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bulk_path(bulk_id: str) -> Path:
    return _BULK_DIR / f"{bulk_id}.json"


def _save(run: dict):
    _bulk_path(run["id"]).write_text(json.dumps(run, indent=2), encoding="utf-8")


def _load(bulk_id: str) -> Optional[dict]:
    p = _bulk_path(bulk_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class BulkRunRequest(BaseModel):
    flow_id: str
    numbers: List[str]
    variable_names: List[str] = ["MISTIN_ID"]
    max_parallel: int = 3


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
    numbers = [n.strip() for n in req.numbers if n.strip()]

    run = {
        "id": bulk_id,
        "flow_id": req.flow_id,
        "flow_name": flow_name,
        "variable_names": req.variable_names,
        "total": len(numbers),
        "completed": 0,
        "success": 0,
        "failed": 0,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "items": [
            {
                "number": n,
                "execution_id": None,
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "error": None,
            }
            for n in numbers
        ],
    }
    _save(run)
    background_tasks.add_task(_execute_bulk, bulk_id, req)
    return run


async def _execute_bulk(bulk_id: str, req: BulkRunRequest):
    from app.api.routes.disk_flows import _load_disk_flow_content
    from app.agents.orchestrator import Orchestrator
    from app.api.routes.execution import manager, _running

    sem = asyncio.Semaphore(max(1, min(req.max_parallel, 5)))

    async def run_one(idx: int, number: str):
        async with sem:
            run = _load(bulk_id)
            run["items"][idx]["status"] = "running"
            run["items"][idx]["started_at"] = _now()
            _save(run)

            status, duration, error = "failed", None, None
            exec_id = None
            try:
                result = _load_disk_flow_content(req.flow_id)
                if not result:
                    raise Exception("Flow not found")
                name, task_content, fmt = result
                env_vars = {v: number for v in req.variable_names}

                payload = {
                    "name": f"{name} [{number}]",
                    "description": f"Bulk run for {number}",
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
                        headless=True,
                        ws_broadcast=manager.broadcast,
                    )
                    await orch.run()
                finally:
                    _running.discard(exec_id)

                final = artifact_store.get_execution(exec_id)
                status = final.status.value if final else "failed"
                duration = final.duration_seconds if final else None

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
            if status == "success":
                run["success"] += 1
            else:
                run["failed"] += 1
            _save(run)

    run = _load(bulk_id)
    await asyncio.gather(*[run_one(i, item["number"]) for i, item in enumerate(run["items"])])

    run = _load(bulk_id)
    run["status"] = "completed"
    run["finished_at"] = _now()
    _save(run)


@router.get("")
async def list_bulk_runs(user: str = Depends(get_current_user)):
    runs = []
    for p in sorted(_BULK_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
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
