"""
Disk-flows API — serves flows directly from the QA-App/flows/ folder.
Flows live as .json (json-flow/) or .txt (normal-flow/) files on disk.
"""
import json
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.storage import artifact_store
from app.models.schemas import ExecutionResult

router = APIRouter(prefix="/disk-flows", tags=["disk-flows"])


class DiskFlow(BaseModel):
    id: str          # unique slug: "json-flow/Tusass-TopUp-Talk"
    name: str
    flow_type: str   # "json" or "normal"
    filename: str
    preview: str     # first 200 chars of content


class RunDiskFlowRequest(BaseModel):
    flow_id: str            # e.g. "json-flow/Tusass-TopUp-Talk"
    headless: Optional[bool] = None
    env_vars: Optional[dict] = {}


def _read_disk_flows() -> List[DiskFlow]:
    """Scan DISK_FLOWS_DIR for .json and .txt flow files."""
    base = settings.DISK_FLOWS_DIR
    results: List[DiskFlow] = []

    if not base.exists():
        return results

    for subdir, flow_type in [("json-flow", "json"), ("normal-flow", "normal")]:
        folder = base / subdir
        if not folder.exists():
            continue
        # collect .json for json-flow, .txt for normal-flow
        ext = ".json" if flow_type == "json" else ".txt"
        for filepath in sorted(folder.glob(f"*{ext}")):
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception:
                continue

            stem = filepath.stem
            flow_id = f"{subdir}/{stem}"
            # Build a friendly name from the filename
            name = stem.replace("-", " ").replace("_", " ")

            results.append(DiskFlow(
                id=flow_id,
                name=name,
                flow_type=flow_type,
                filename=filepath.name,
                preview=content[:200],
            ))

    return results


def _load_disk_flow_content(flow_id: str) -> Optional[tuple[str, str, str]]:
    """
    Return (name, task_content, flow_format) for a disk flow id.
    flow_id format: "json-flow/StemName" or "normal-flow/StemName"
    """
    parts = flow_id.split("/", 1)
    if len(parts) != 2:
        return None
    subdir, stem = parts
    base = settings.DISK_FLOWS_DIR / subdir

    if subdir == "json-flow":
        filepath = base / f"{stem}.json"
        fmt = "json"
    else:
        filepath = base / f"{stem}.txt"
        fmt = "natural"

    if not filepath.exists():
        return None

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    name = stem.replace("-", " ").replace("_", " ")
    return name, content, fmt


class CreateDiskFlowRequest(BaseModel):
    name: str
    content: str
    flow_type: str = "json"   # "json" or "normal"


class DiskFlowContent(BaseModel):
    flow_id: str
    content: str


class EnvVar(BaseModel):
    key: str
    value: str


class EnvPayload(BaseModel):
    vars: List[EnvVar]


# Path to .env file
_ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"

# Per-flow env files live under DISK_FLOWS_DIR/env/
_FLOW_ENV_DIR = settings.DISK_FLOWS_DIR / "env"


def _flow_id_to_stem(flow_id: str) -> str:
    """'json-flow/Tusass-TopUp-Talk' → 'Tusass-TopUp-Talk'"""
    parts = flow_id.split("/", 1)
    return parts[1] if len(parts) == 2 else flow_id


class FlowEnvPayload(BaseModel):
    flow_id: str
    vars: List[EnvVar]


@router.get("", response_model=List[DiskFlow])
async def list_disk_flows(user: str = Depends(get_current_user)):
    """List all available flows from the QA-App/flows/ directory."""
    return _read_disk_flows()


@router.post("/create", response_model=DiskFlow)
async def create_disk_flow(req: CreateDiskFlowRequest, user: str = Depends(get_current_user)):
    """Save a new flow as a file on disk and return it as a DiskFlow."""
    import re
    # Build a safe filename from the name
    stem = re.sub(r"[^\w\s-]", "", req.name.strip()).strip()
    stem = re.sub(r"[\s]+", "-", stem) or "Untitled-Flow"

    subdir   = "json-flow" if req.flow_type == "json" else "normal-flow"
    ext      = ".json"     if req.flow_type == "json" else ".txt"
    folder   = settings.DISK_FLOWS_DIR / subdir
    folder.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting — append a number if the file already exists
    filepath = folder / f"{stem}{ext}"
    counter  = 1
    while filepath.exists():
        filepath = folder / f"{stem}-{counter}{ext}"
        counter += 1

    try:
        filepath.write_text(req.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {e}")

    flow_id = f"{subdir}/{filepath.stem}"
    return DiskFlow(
        id=flow_id,
        name=req.name.strip(),
        flow_type=req.flow_type,
        filename=filepath.name,
        preview=req.content[:200],
    )


@router.post("/run", response_model=ExecutionResult)
async def run_disk_flow(
    req: RunDiskFlowRequest,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
):
    """
    Load a flow from disk, create it in the artifact store (or reuse existing),
    and start execution.
    """
    result = _load_disk_flow_content(req.flow_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Disk flow not found: {req.flow_id}")

    name, task_content, fmt = result

    # Create a transient flow record in the artifact store
    payload = {
        "name": name,
        "description": f"Loaded from disk: {req.flow_id}",
        "format": fmt,
        "task": task_content,
        "tags": ["disk-flow"],
        "env_vars": req.env_vars or {},
    }
    flow = artifact_store.create_flow(payload)
    exec_record = artifact_store.create_execution(flow)

    from app.agents.orchestrator import Orchestrator
    from app.api.routes.execution import manager, _running

    async def run_bg():
        eid = exec_record.id
        if eid in _running:
            return
        _running.add(eid)
        try:
            orch = Orchestrator(
                flow=flow,
                exec_id=eid,
                headless=req.headless,
                ws_broadcast=manager.broadcast,
            )
            await orch.run()
        finally:
            _running.discard(eid)

    background_tasks.add_task(run_bg)
    return exec_record


# ── Delete a disk flow ───────────────────────────────────────────────────────

@router.delete("/delete")
async def delete_disk_flow(flow_id: str, user: str = Depends(get_current_user)):
    """Delete a flow file from disk."""
    parts = flow_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid flow_id format")
    subdir, stem = parts
    ext = ".json" if subdir == "json-flow" else ".txt"
    filepath = settings.DISK_FLOWS_DIR / subdir / f"{stem}{ext}"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Flow file not found")
    try:
        filepath.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
    return {"ok": True, "flow_id": flow_id}


# ── Disk file read/write ───────────────────────────────────────────────────────

@router.get("/content", response_model=DiskFlowContent)
async def get_flow_content(flow_id: str, user: str = Depends(get_current_user)):
    """Return the raw file content of a disk flow."""
    result = _load_disk_flow_content(flow_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Disk flow not found: {flow_id}")
    _, content, _ = result
    return DiskFlowContent(flow_id=flow_id, content=content)


@router.put("/content")
async def save_flow_content(body: DiskFlowContent, user: str = Depends(get_current_user)):
    """Overwrite a disk flow file with new content."""
    parts = body.flow_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid flow_id format")
    subdir, stem = parts
    ext = ".json" if subdir == "json-flow" else ".txt"
    filepath = settings.DISK_FLOWS_DIR / subdir / f"{stem}{ext}"
    if not filepath.parent.exists():
        raise HTTPException(status_code=404, detail="Flow directory not found")
    try:
        filepath.write_text(body.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save: {e}")
    return {"ok": True, "flow_id": body.flow_id}


# ── .env read/write ───────────────────────────────────────────────────────────

@router.get("/env", response_model=List[EnvVar])
async def get_env(user: str = Depends(get_current_user)):
    """Return the .env file as a list of {key, value} pairs."""
    if not _ENV_FILE.exists():
        return []
    vars_list = []
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            vars_list.append(EnvVar(key=k.strip(), value=v.strip()))
    return vars_list


_ENV_SECTIONS = [
    ("Platform Settings",             ["SCREENSHOT_MODE","SKIP_LLM","BROWSER_HEADLESS","BROWSER_SLOW_MO","BROWSER_NAVIGATION_TIMEOUT","LLM_PROVIDER","LLM_MODEL","VISION_MODEL","CLAUDE_MODEL","ANTHROPIC_API_KEY"]),
    ("Shared Admin Credentials",       ["ADMIN_USER","ADMIN_PASS","ADMIN_EMAIL","ADMIN_PASSWORD","OPERATIONS_USER","OPERATIONS_PASS"]),
    ("Flow 1 : New Account Creation",  ["ICC_URL","CSR_USER","CSR_PASSWORD","ACCOUNT_NUMBER","MSITCOS_URL"]),
    ("Flow 2 : Tusass TopUp Talk",     ["COS_URL","PORTAL_URL","MISTIN_ID","PHONE_NUMBER","MOBILE_NUMBER","TOPUP_AMOUNT"]),
    ("Flow 3 : Tusass Extra Data Add", ["COS_OPERATION_URL","DATA_AMOUNT"]),
    ("Payment Card Details",           ["CARD_NUMBER","CARD_MONTH","CARD_YEAR","CARD_CVV","CARD_EXPIRY","CARD_CVC"]),
]

@router.put("/env")
async def save_env(body: EnvPayload, user: str = Depends(get_current_user)):
    """Overwrite the .env file with updated key=value pairs, preserving section headers."""
    var_map = {v.key.strip().upper(): v for v in body.vars if v.key.strip()}

    lines: list[str] = []
    used: set[str] = set()

    for section_title, keys in _ENV_SECTIONS:
        section_vars = [var_map[k.upper()] for k in keys if k.upper() in var_map]
        if not section_vars:
            continue
        lines.append(f"# ── {section_title} {'─' * max(0, 60 - len(section_title))}")
        for v in section_vars:
            lines.append(f"{v.key}={v.value}")
            used.add(v.key.strip().upper())
        lines.append("")

    # Any vars not belonging to a known section go at the end
    extras = [v for v in body.vars if v.key.strip() and v.key.strip().upper() not in used]
    if extras:
        lines.append("# ── Other ───────────────────────────────────────────────────────────────")
        for v in extras:
            lines.append(f"{v.key}={v.value}")
        lines.append("")

    content = "\n".join(lines)
    try:
        _ENV_FILE.write_text(content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save .env: {e}")
    return {"ok": True, "count": len(used) + len(extras)}


# ── Per-flow .env read/write ───────────────────────────────────────────────────

@router.get("/flow-env", response_model=List[EnvVar])
async def get_flow_env(flow_id: str, user: str = Depends(get_current_user)):
    """Return the per-flow .env file as a list of {key, value} pairs."""
    stem = _flow_id_to_stem(flow_id)
    env_file = _FLOW_ENV_DIR / f"{stem}.env"
    if not env_file.exists():
        return []
    vars_list = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            vars_list.append(EnvVar(key=k.strip(), value=v.strip()))
    return vars_list


@router.put("/flow-env")
async def save_flow_env(body: FlowEnvPayload, user: str = Depends(get_current_user)):
    """Save per-flow env vars to DISK_FLOWS_DIR/env/<stem>.env"""
    stem = _flow_id_to_stem(body.flow_id)
    _FLOW_ENV_DIR.mkdir(parents=True, exist_ok=True)
    env_file = _FLOW_ENV_DIR / f"{stem}.env"
    lines = [f"# Per-flow env for {body.flow_id}", ""]
    for v in body.vars:
        if v.key.strip():
            lines.append(f"{v.key.strip()}={v.value}")
    lines.append("")
    try:
        env_file.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save flow env: {e}")
    return {"ok": True, "flow_id": body.flow_id, "file": env_file.name, "count": len(body.vars)}
