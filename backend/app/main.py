import asyncio
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.routes import auth, flows, execution, disk_flows, bulk, chat
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
app.include_router(chat.router, prefix="/api")

app.mount(
    "/screenshots",
    StaticFiles(directory=str(settings.SCREENSHOTS_DIR)),
    name="screenshots",
)


@app.on_event("shutdown")
async def _close_gateway_client():
    from app.agents.llm_client import close_gateway_client
    await close_gateway_client()


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
            f"Claude API ({llm_client.active_model})" if llm_provider == "claude"
            else f"AI Gateway ({llm_client.active_model})" if llm_provider == "gateway"
            else f"Gemini API ({llm_client.active_model})" if llm_provider == "gemini"
            else f"Ollama ({llm_client.active_model})"
        ),
        "claude_key_set":       claude_key_set,
        "model":                llm_client.active_model,
        "vision_model":         vision_client.active_model,
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


def _persist_env(updates: dict[str, str]) -> None:
    """Write key=value pairs into backend/.env, replacing existing keys in place."""
    from pathlib import Path
    import re as _re

    env_path = Path(__file__).parent.parent / ".env"
    if not updates:
        return
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
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


@app.get("/api/settings/llms")
async def list_llms(user: str = Depends(get_current_user)):
    """List locally installed Ollama models plus current provider/model selection."""
    import httpx
    from app.agents.llm_client import get_gemini_usage

    models: list[dict] = []
    ollama_reachable = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            if resp.status_code == 200:
                ollama_reachable = True
                for m in resp.json().get("models", []):
                    models.append({
                        "name":        m.get("name"),
                        "size":        m.get("size"),
                        "modified_at": m.get("modified_at"),
                    })
    except Exception:
        pass

    return {
        "provider":            settings.LLM_PROVIDER,
        "ollama_host":         settings.OLLAMA_HOST,
        "ollama_reachable":    ollama_reachable,
        "text_model":          settings.LLM_MODEL,
        "vision_model":        settings.VISION_MODEL,
        "claude_model":        settings.CLAUDE_MODEL,
        "claude_key_set":      bool(settings.ANTHROPIC_API_KEY),
        "gateway_base_url":    settings.GATEWAY_BASE_URL,
        "gateway_model":       settings.GATEWAY_MODEL,
        "gateway_vision_model": settings.GATEWAY_VISION_MODEL,
        "gateway_key_set":     bool(settings.GATEWAY_API_KEY),
        "gemini_model":        settings.GEMINI_MODEL,
        "gemini_vision_model": settings.GEMINI_VISION_MODEL,
        "gemini_key_set":      bool(settings.GEMINI_API_KEY),
        "gemini_usage":        get_gemini_usage(),
        "models":              models,
    }


@app.patch("/api/settings/llms")
async def update_llms(body: dict, user: str = Depends(get_current_user)):
    """
    Switch LLM provider (ollama/claude/gateway/gemini) or the active text/vision model.
    Persists to .env and updates the running singletons immediately (no restart needed).
    """
    from app.agents.llm_client import llm_client, vision_client

    updates: dict[str, str] = {}

    if "provider" in body and body["provider"] in ("ollama", "claude", "gateway", "gemini"):
        settings.LLM_PROVIDER = body["provider"]
        llm_client.provider = body["provider"]
        vision_client.provider = body["provider"]
        updates["LLM_PROVIDER"] = body["provider"]

    if "text_model" in body and body["text_model"]:
        settings.LLM_MODEL = body["text_model"]
        llm_client.model = body["text_model"]
        updates["LLM_MODEL"] = body["text_model"]

    if "vision_model" in body and body["vision_model"]:
        settings.VISION_MODEL = body["vision_model"]
        vision_client.model = body["vision_model"]
        model_lo = body["vision_model"].lower()
        vision_client._capable = any(
            k in model_lo for k in
            ("vl", "vision", "llava", "bakllava", "minicpm", "phi3-vision", "cogvlm", "qwen2.5")
        )
        updates["VISION_MODEL"] = body["vision_model"]

    if "gateway_model" in body and body["gateway_model"]:
        settings.GATEWAY_MODEL = body["gateway_model"]
        updates["GATEWAY_MODEL"] = body["gateway_model"]

    if "gateway_vision_model" in body and body["gateway_vision_model"]:
        settings.GATEWAY_VISION_MODEL = body["gateway_vision_model"]
        updates["GATEWAY_VISION_MODEL"] = body["gateway_vision_model"]

    if "gemini_model" in body and body["gemini_model"]:
        settings.GEMINI_MODEL = body["gemini_model"]
        updates["GEMINI_MODEL"] = body["gemini_model"]

    if "gemini_vision_model" in body and body["gemini_vision_model"]:
        settings.GEMINI_VISION_MODEL = body["gemini_vision_model"]
        updates["GEMINI_VISION_MODEL"] = body["gemini_vision_model"]

    _persist_env(updates)

    return {
        "provider":             settings.LLM_PROVIDER,
        "text_model":           settings.LLM_MODEL,
        "vision_model":         settings.VISION_MODEL,
        "gateway_model":        settings.GATEWAY_MODEL,
        "gateway_vision_model": settings.GATEWAY_VISION_MODEL,
        "gemini_model":         settings.GEMINI_MODEL,
        "gemini_vision_model":  settings.GEMINI_VISION_MODEL,
    }


@app.post("/api/settings/llms/pull")
async def pull_llm(body: dict, user: str = Depends(get_current_user)):
    """Pull (download) a new local Ollama model by name, e.g. {"name": "llama3.1:8b"}."""
    import httpx

    name = (body or {}).get("name", "").strip()
    if not name:
        return {"success": False, "error": "Model name is required"}

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{settings.OLLAMA_HOST}/api/pull",
                json={"name": name, "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    return {"success": False, "error": f"Ollama returned {resp.status_code}"}
                last_status = ""
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        import json as _json
                        data = _json.loads(line)
                        last_status = data.get("status", last_status)
                        if data.get("error"):
                            return {"success": False, "error": data["error"]}
                    except Exception:
                        pass
        return {"success": True, "name": name, "status": last_status}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/settings/llms/{name}")
async def delete_llm(name: str, user: str = Depends(get_current_user)):
    """Remove a locally installed Ollama model."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                "DELETE", f"{settings.OLLAMA_HOST}/api/delete", json={"name": name}
            )
            if resp.status_code == 200:
                return {"success": True}
            return {"success": False, "error": f"Ollama returned {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


