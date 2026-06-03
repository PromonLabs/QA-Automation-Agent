import json
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks
from typing import List

from app.api.deps import get_current_user
from app.models.schemas import FlowCreate, FlowResponse, FlowEnvUpdate
from app.storage import artifact_store

router = APIRouter(prefix="/flows", tags=["flows"])


@router.post("/create", response_model=FlowResponse)
async def create_flow(
    payload: FlowCreate,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
):
    flow = artifact_store.create_flow(payload.dict())
    # Trigger LLM memory analysis in background (non-blocking)
    background_tasks.add_task(_analyse_flow_bg, flow.name, payload.task)
    return flow


async def _analyse_flow_bg(flow_name: str, task_text: str) -> None:
    """Background task: ask LLM to analyse the flow and save memory."""
    try:
        from app.agents.memory_store import analyse_and_save
        await analyse_and_save(flow_name, task_text)
    except Exception:
        pass  # Memory save is best-effort; never block the response


@router.post("/upload", response_model=FlowResponse)
async def upload_flow(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    user: str = Depends(get_current_user),
):
    """
    Upload a JSON flow file and create a flow from it.

    Accepted formats:
    - Full flow file:  {"name":..., "description":..., "tags":[...], "task": {"steps":[...]}}
    - Flat steps:      {"steps": ["Navigate to ...", "Click ..."], "name": "..."}
    - Plain step list: ["Navigate to ...", "Click ..."]
    """
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are supported")

    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON — could not parse the file")

    # ── Extract fields from any supported JSON shape ──────────────────────────
    name        = ""
    description = ""
    tags: list  = []
    task_str    = ""

    if isinstance(data, list):
        # Plain list of step strings — minimal metadata
        name     = file.filename.replace(".json", "").replace("-", " ").replace("_", " ").title()
        task_str = json.dumps({"steps": data}, indent=2)

    elif isinstance(data, dict):
        name        = data.get("name", "") or file.filename.replace(".json", "").title()
        description = data.get("description", "")
        tags        = data.get("tags", [])

        # Determine the task payload
        task_inner = data.get("task")
        if isinstance(task_inner, dict) and "steps" in task_inner:
            # Full flow file format: {"task": {"steps": [...]}}
            task_str = json.dumps(task_inner, indent=2)
        elif "steps" in data:
            # Flat format: {"steps": [...]}
            task_str = json.dumps({"steps": data["steps"]}, indent=2)
        elif isinstance(task_inner, str):
            # task is already a plain string
            task_str = task_inner
        else:
            # Fallback: store the whole thing
            task_str = json.dumps(data, indent=2)
    else:
        raise HTTPException(status_code=400, detail="JSON must be an object or an array of steps")

    # Quick sanity check
    if not task_str.strip():
        raise HTTPException(status_code=400, detail="No steps found in uploaded flow file")

    payload = {
        "name":        name or "Uploaded Flow",
        "description": description,
        "format":      "json",
        "task":        task_str,
        "tags":        tags if isinstance(tags, list) else [],
    }
    flow = artifact_store.create_flow(payload)

    # Trigger LLM memory analysis in background (non-blocking)
    if background_tasks:
        background_tasks.add_task(_analyse_flow_bg, flow.name, task_str)

    return flow


@router.get("", response_model=List[FlowResponse])
async def list_flows(user: str = Depends(get_current_user)):
    return artifact_store.list_flows()


@router.get("/{flow_id}", response_model=FlowResponse)
async def get_flow(flow_id: str, user: str = Depends(get_current_user)):
    flow = artifact_store.get_flow(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.patch("/{flow_id}/env", response_model=FlowResponse)
async def update_flow_env(
    flow_id: str,
    body: FlowEnvUpdate,
    user: str = Depends(get_current_user),
):
    """Save environment variables (credentials) linked to a specific flow."""
    flow = artifact_store.update_flow(flow_id, {"env_vars": body.env_vars})
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.delete("/{flow_id}")
async def delete_flow(flow_id: str, user: str = Depends(get_current_user)):
    if not artifact_store.delete_flow(flow_id):
        raise HTTPException(status_code=404, detail="Flow not found")
    return {"message": "Flow deleted"}
