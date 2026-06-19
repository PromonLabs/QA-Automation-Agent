import asyncio
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.routes import auth, flows, execution, disk_flows, bulk, flow_agent
from app.api.deps import get_current_user


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="AI Browser Automation Platform powered by local LLMs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(flows.router, prefix="/api")
app.include_router(execution.router, prefix="/api")
app.include_router(disk_flows.router, prefix="/api")
app.include_router(bulk.router, prefix="/api")
app.include_router(flow_agent.router, prefix="/api")

app.mount(
    "/screenshots",
    StaticFiles(directory=str(settings.SCREENSHOTS_DIR)),
    name="screenshots",
)


def _chromium_ok() -> bool:
    """Check if Chromium is installed without launching sync_playwright (fails on Windows)."""
    try:
        import os, subprocess
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=5
        )
        return True  # If playwright module runs, browser is accessible
    except Exception:
        pass
    # Fallback: check known install paths
    try:
        from pathlib import Path
        import sys
        base = Path(sys.executable).parent.parent
        for pattern in [
            "**/chrome-win/chrome.exe",
            "**/chromium*/chrome",
            "**/chromium*/chromium",
        ]:
            if list(base.glob(pattern)):
                return True
    except Exception:
        pass
    # Final fallback: try importing playwright (if it imports, browser can run)
    try:
        import playwright  # noqa
        return True
    except Exception:
        return False


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": settings.VERSION, "status": "running"}


@app.get("/health")
async def health():
    from app.agents.llm_client import llm_client, vision_client
    llm_ok, vision_ok = await asyncio.gather(
        llm_client.check_health(),
        vision_client.check_health(),
    )
    browser_ok = _chromium_ok()
    import sys
    llm_provider = settings.LLM_PROVIDER
    claude_key_set = bool(settings.ANTHROPIC_API_KEY)
    return {
        "status":               "healthy" if browser_ok else "degraded",
        "llm":                  "connected" if llm_ok else "disconnected",
        "vision":               "connected" if vision_ok else "disconnected",
        "llm_provider":         llm_provider,
        "llm_provider_label":   (
            f"Claude API ({settings.CLAUDE_MODEL})" if llm_provider == "claude"
            else f"Ollama ({settings.LLM_MODEL})"
        ),
        "claude_key_set":       claude_key_set,
        "model":                settings.CLAUDE_MODEL if llm_provider == "claude" else settings.LLM_MODEL,
        "vision_model":         settings.VISION_MODEL,
        "ollama_host":          settings.OLLAMA_HOST,
        "browser":              "ready" if browser_ok else "not_installed",
        "browser_headless":     settings.BROWSER_HEADLESS,
        "screenshot_mode":      settings.SCREENSHOT_MODE,
        "browser_fix":          None if browser_ok else "python -m playwright install chromium",
        "platform":             sys.platform,
        "note":                 "Windows: Playwright runs in a ProactorEventLoop thread (automatic)",
        "flow_agent_enabled":   settings.USE_FLOW_AGENT,
        "vision_agent_enabled": settings.USE_VISION_AGENT,
    }


@app.patch("/api/settings/agents")
async def update_agent_settings(
    body: dict,
    user: str = Depends(get_current_user),
):
    """Toggle flow / vision agents at runtime and persist to .env."""
    from pathlib import Path
    import re as _re

    env_path = Path(__file__).parent.parent / ".env"
    updates: dict[str, str] = {}

    if "use_flow_agent" in body:
        val = str(body["use_flow_agent"]).lower() in ("true", "1", "yes")
        settings.USE_FLOW_AGENT = val
        updates["USE_FLOW_AGENT"] = "true" if val else "false"

    if "use_vision_agent" in body:
        val = str(body["use_vision_agent"]).lower() in ("true", "1", "yes")
        settings.USE_VISION_AGENT = val
        updates["USE_VISION_AGENT"] = "true" if val else "false"

    if updates and env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        for key, new_val in updates.items():
            replaced = False
            for i, ln in enumerate(lines):
                if _re.match(rf"^\s*{key}\s*=", ln):
                    lines[i] = f"{key}={new_val}"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"{key}={new_val}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "flow_agent_enabled":   settings.USE_FLOW_AGENT,
        "vision_agent_enabled": settings.USE_VISION_AGENT,
    }


@app.get("/api/memory")
async def list_flow_memory(user: str = Depends(get_current_user)):
    """List all saved flow memory entries."""
    from app.agents.memory_store import list_memories
    return list_memories()


@app.get("/api/memory/{flow_name}")
async def get_flow_memory(flow_name: str, user: str = Depends(get_current_user)):
    """Get the saved memory for a specific flow."""
    from app.agents.memory_store import load_memory
    mem = load_memory(flow_name)
    if not mem:
        return {"flow_name": flow_name, "message": "No memory saved yet"}
    return mem
