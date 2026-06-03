import asyncio
import shutil
from typing import List, Dict, Set
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.models.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.storage import artifact_store
from app.agents.orchestrator import Orchestrator, cancel_execution
from app.core.config import settings

router = APIRouter(prefix="/execution", tags=["execution"])


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, exec_id: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(exec_id, set()).add(ws)

    def disconnect(self, exec_id: str, ws: WebSocket):
        if exec_id in self._connections:
            self._connections[exec_id].discard(ws)

    async def broadcast(self, exec_id: str, message: dict):
        dead = set()
        for ws in list(self._connections.get(exec_id, set())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections[exec_id].discard(ws)


manager = ConnectionManager()
_running: Set[str] = set()   # guard against duplicate background tasks


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.post("", response_model=ExecutionResult)
async def start_execution(
    req: ExecutionRequest,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
):
    flow = artifact_store.get_flow(req.flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    exec_record = artifact_store.create_execution(flow)

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


@router.get("", response_model=List[ExecutionResult])
async def list_executions(user: str = Depends(get_current_user)):
    return artifact_store.list_executions()


@router.get("/reports", response_model=List[dict])
async def list_reports(user: str = Depends(get_current_user)):
    """List all saved reports by scanning executions that have a report_file."""
    reports = []
    for result in artifact_store.list_executions():
        if not result.report_file:
            continue
        report_path = settings.REPORTS_DIR / result.report_file
        if not report_path.exists():
            continue
        reports.append({
            "exec_id": result.id,
            "flow_name": result.flow_name,
            "status": result.status,
            "started_at": result.started_at,
            "filename": result.report_file,
            "ext": report_path.suffix.lstrip("."),
        })
    # newest first
    reports.sort(key=lambda r: r["started_at"] or "", reverse=True)
    return reports


@router.get("/{exec_id}", response_model=ExecutionResult)
async def get_execution(exec_id: str, user: str = Depends(get_current_user)):
    result = artifact_store.get_execution(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")
    return result


@router.post("/{exec_id}/cancel")
async def cancel_exec(exec_id: str, user: str = Depends(get_current_user)):
    cancel_execution(exec_id)
    artifact_store.update_execution(exec_id, {"status": ExecutionStatus.CANCELLED})
    return {"message": "Cancellation requested"}


@router.get("/logs/{exec_id}")
async def get_logs(exec_id: str, user: str = Depends(get_current_user)):
    result = artifact_store.get_execution(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")
    return {"exec_id": exec_id, "logs": result.logs}


@router.get("/screenshots/{exec_id}")
async def get_screenshots(exec_id: str, user: str = Depends(get_current_user)):
    result = artifact_store.get_execution(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")
    return {"exec_id": exec_id, "screenshots": result.screenshots}


@router.get("/screenshot/{exec_id}/{filename}")
async def serve_screenshot(exec_id: str, filename: str):
    path = settings.SCREENSHOTS_DIR / exec_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


@router.get("/report/{exec_id}")
async def download_report(exec_id: str, user: str = Depends(get_current_user)):
    """Serve the PDF report for an execution."""
    result = artifact_store.get_execution(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")

    # Use the stored report_file name if available
    if result.report_file:
        path = settings.REPORTS_DIR / result.report_file
        if path.exists():
            mime = "application/pdf" if path.suffix == ".pdf" else "text/plain"
            return FileResponse(path, media_type=mime,
                                headers={"Content-Disposition": "inline"})

    # Generate on-demand if missing
    from app.agents.pdf_reporter import generate_pdf
    import re
    safe = re.sub(r"[^\w\-]", "_", result.flow_name.strip()).strip("_")
    report_path = settings.REPORTS_DIR / f"{safe}_{exec_id[:8]}.pdf"
    if generate_pdf(result, report_path):
        artifact_store.update_execution(exec_id, {"report_file": report_path.name})
        return FileResponse(report_path, media_type="application/pdf",
                            headers={"Content-Disposition": "inline"})

    raise HTTPException(status_code=404, detail="Report not available")


@router.delete("/report/{exec_id}")
async def delete_report(exec_id: str, user: str = Depends(get_current_user)):
    """Delete the PDF report file for a specific execution."""
    result = artifact_store.get_execution(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")
    if result.report_file:
        path = settings.REPORTS_DIR / result.report_file
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
        artifact_store.update_execution(exec_id, {"report_file": None})
    return {"ok": True, "exec_id": exec_id}


@router.delete("/cleanup")
async def cleanup_artifacts(user: str = Depends(get_current_user)):
    """
    Remove ALL execution artifacts (executions, screenshots, reports).
    Flows and memory are preserved.
    """
    removed = {"executions": 0, "screenshot_dirs": 0, "reports": 0}

    # Remove execution JSON files
    for f in settings.EXECUTIONS_DIR.glob("*.json"):
        try:
            f.unlink()
            removed["executions"] += 1
        except Exception:
            pass

    # Remove screenshot directories
    for d in settings.SCREENSHOTS_DIR.iterdir():
        if d.is_dir():
            try:
                shutil.rmtree(d)
                removed["screenshot_dirs"] += 1
            except Exception:
                pass

    # Remove report files
    for f in settings.REPORTS_DIR.glob("*"):
        try:
            f.unlink()
            removed["reports"] += 1
        except Exception:
            pass

    return {
        "message": "Artifacts cleaned",
        "removed": removed,
    }


# ── WebSocket: REAL-TIME ONLY — no log replay (frontend loads initial via REST) ──

@router.websocket("/ws/{exec_id}")
async def websocket_endpoint(websocket: WebSocket, exec_id: str):
    await manager.connect(exec_id, websocket)
    try:
        # Send ONLY the current status on connect (not the full log history)
        # Frontend already loaded logs via GET /execution/{id}
        result = artifact_store.get_execution(exec_id)
        if result:
            await websocket.send_json({
                "type": "status",
                "data": {"status": result.status, "exec_id": exec_id},
            })

        # Keep-alive loop — receive pings, relay real-time events via broadcast()
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(exec_id, websocket)
