"""
Filesystem-based artifact store.
No database required — everything lives in JSON files + screenshot PNGs.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.core.config import settings
from app.models.schemas import FlowResponse, ExecutionResult, ExecutionStatus, ExecutionLog


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# ──────────────────────────────────────────────
# FLOWS
# ──────────────────────────────────────────────

def create_flow(payload: dict) -> FlowResponse:
    flow_id = str(uuid.uuid4())
    now = _now()
    record = {
        "id": flow_id,
        "name": payload["name"],
        "description": payload.get("description", ""),
        "format": payload.get("format", "natural"),
        "task": payload["task"],
        "tags": payload.get("tags", []),
        "env_vars": payload.get("env_vars", {}),
        "created_at": now,
        "updated_at": now,
    }
    _write_json(settings.FLOWS_DIR / f"{flow_id}.json", record)
    return FlowResponse(**record)


def update_flow(flow_id: str, updates: dict) -> Optional[FlowResponse]:
    """Patch any fields on a flow (e.g. env_vars, name, description)."""
    path = settings.FLOWS_DIR / f"{flow_id}.json"
    data = _read_json(path)
    if not data:
        return None
    data.update(updates)
    data["updated_at"] = _now()
    _write_json(path, data)
    return FlowResponse(**data)


def list_flows() -> List[FlowResponse]:
    flows = []
    for f in sorted(settings.FLOWS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _read_json(f)
        if data:
            flows.append(FlowResponse(**data))
    return flows


def get_flow(flow_id: str) -> Optional[FlowResponse]:
    path = settings.FLOWS_DIR / f"{flow_id}.json"
    data = _read_json(path)
    return FlowResponse(**data) if data else None


def delete_flow(flow_id: str) -> bool:
    path = settings.FLOWS_DIR / f"{flow_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ──────────────────────────────────────────────
# EXECUTIONS
# ──────────────────────────────────────────────

def create_execution(flow: FlowResponse) -> ExecutionResult:
    exec_id = str(uuid.uuid4())
    now = _now()
    record = {
        "id": exec_id,
        "flow_id": flow.id,
        "flow_name": flow.name,
        "status": ExecutionStatus.PENDING,
        "started_at": now,
        "finished_at": None,
        "duration_seconds": None,
        "logs": [],
        "screenshots": [],
        "result_summary": None,
        "error": None,
        "steps_completed": 0,
        "steps_total": 0,
    }
    # Create execution dir for screenshots
    exec_dir = settings.SCREENSHOTS_DIR / exec_id
    exec_dir.mkdir(parents=True, exist_ok=True)

    _write_json(settings.EXECUTIONS_DIR / f"{exec_id}.json", record)
    return ExecutionResult(**record)


def update_execution(exec_id: str, updates: dict) -> Optional[ExecutionResult]:
    path = settings.EXECUTIONS_DIR / f"{exec_id}.json"
    data = _read_json(path)
    if not data:
        return None
    data.update(updates)
    _write_json(path, data)
    return ExecutionResult(**data)


def append_log(exec_id: str, log: ExecutionLog) -> None:
    path = settings.EXECUTIONS_DIR / f"{exec_id}.json"
    data = _read_json(path)
    if data:
        data["logs"].append(log.dict())
        _write_json(path, data)


def add_screenshot(exec_id: str, filename: str) -> None:
    path = settings.EXECUTIONS_DIR / f"{exec_id}.json"
    data = _read_json(path)
    if data:
        if filename not in data["screenshots"]:
            data["screenshots"].append(filename)
        _write_json(path, data)


def get_execution(exec_id: str) -> Optional[ExecutionResult]:
    path = settings.EXECUTIONS_DIR / f"{exec_id}.json"
    data = _read_json(path)
    return ExecutionResult(**data) if data else None


def list_executions() -> List[ExecutionResult]:
    executions = []
    for f in sorted(settings.EXECUTIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _read_json(f)
        if data:
            executions.append(ExecutionResult(**data))
    return executions
