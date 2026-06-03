"""
Flow Memory Store — saves LLM insights per flow in local JSON files.

When a flow is uploaded, the LLM analyses it and saves:
  - Extracted steps
  - Key URLs / credentials env var names
  - Common pitfalls observed from past runs
  - Recommended action overrides

Memory files live at:  artifacts/memory/<flow_name_slug>.json
"""
from __future__ import annotations

import json
import re
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """Convert a flow name to a safe filename slug."""
    return re.sub(r"[^a-z0-9_-]", "_", name.lower().strip())[:60]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _memory_path(flow_name: str) -> Path:
    return settings.MEMORY_DIR / f"{_slug(flow_name)}.json"


# ─────────────────────────────────────────────────────────────────────────────
# Read / Write
# ─────────────────────────────────────────────────────────────────────────────

def load_memory(flow_name: str) -> Optional[Dict[str, Any]]:
    """Return the memory dict for a flow, or None if it doesn't exist yet."""
    path = _memory_path(flow_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_memory(flow_name: str, data: Dict[str, Any]) -> None:
    """Persist (merge) new memory data for a flow."""
    path = _memory_path(flow_name)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update(data)
    existing["flow_name"] = flow_name
    existing["updated_at"] = _now()
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def record_failure(flow_name: str, step_description: str, error_msg: str) -> None:
    """Append a failure observation to this flow's memory."""
    mem = load_memory(flow_name) or {}
    failures: List[Dict] = mem.get("observed_failures", [])
    # Keep last 20 failures only
    failures = failures[-19:] + [{
        "step": step_description,
        "error": error_msg[:200],
        "at": _now(),
    }]
    save_memory(flow_name, {"observed_failures": failures})


def list_memories() -> List[Dict[str, Any]]:
    """Return a list of all saved flow memories (summary)."""
    result = []
    for f in sorted(settings.MEMORY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "flow_name":  data.get("flow_name", f.stem),
                "step_count": len(data.get("steps", [])),
                "updated_at": data.get("updated_at"),
                "failures":   len(data.get("observed_failures", [])),
            })
        except Exception:
            pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# LLM-powered flow analysis (called on upload)
# ─────────────────────────────────────────────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = """You are a QA automation expert. Analyse a browser automation flow and extract key insights.

Respond ONLY with valid JSON in this exact structure:
{
  "summary": "One-sentence description of what this flow does",
  "urls": ["list of URLs the flow visits"],
  "credential_env_vars": ["list of env var names that supply credentials, e.g. ADMIN_USER, ADMIN_PASS"],
  "step_count": 10,
  "key_steps": ["brief description of each critical step"],
  "risks": ["potential issues or things that might go wrong"],
  "hints": ["specific tips for making this flow more reliable"]
}"""


async def analyse_and_save(flow_name: str, task_text: str) -> Dict[str, Any]:
    """
    Call LLM to analyse the flow and save insights.
    Falls back to basic extraction if LLM is unavailable.
    """
    from app.agents.llm_client import llm_client

    # Check if we already have a recent analysis (within 24h) — skip re-analysis
    existing = load_memory(flow_name)
    if existing and existing.get("summary") and existing.get("updated_at"):
        try:
            updated = datetime.fromisoformat(existing["updated_at"].replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
            if age_h < 24:
                return existing   # fresh enough
        except Exception:
            pass

    analysis: Dict[str, Any] = {}
    try:
        url = f"{settings.OLLAMA_HOST}/api/generate"
        import httpx
        payload = {
            "model": settings.LLM_MODEL,
            "prompt": (
                f"Analyse this browser automation flow and extract insights:\n\n"
                f"{task_text[:3000]}\n\n"
                "Respond ONLY with the JSON object."
            ),
            "system": ANALYSIS_SYSTEM_PROMPT,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 1000},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")

        # Extract JSON from LLM response
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("```").strip()
        depth, start = 0, None
        for i, ch in enumerate(raw):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        analysis = json.loads(raw[start:i + 1])
                        break
                    except Exception:
                        start = None
    except Exception:
        pass

    # Basic fallback: count lines, extract URLs
    if not analysis.get("summary"):
        lines = [l.strip() for l in task_text.splitlines() if l.strip()]
        urls = re.findall(r"https?://[^\s,\"']+", task_text)
        analysis = {
            "summary": f"Automated flow with {len(lines)} steps",
            "urls": list(set(urls)),
            "credential_env_vars": [],
            "step_count": len(lines),
            "key_steps": lines[:10],
            "risks": [],
            "hints": [],
        }

    save_memory(flow_name, {**analysis, "source": "llm_analysis"})
    return analysis
