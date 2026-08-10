"""
General-purpose chat endpoint — plain conversational assistant backed by
whichever LLM provider is active (Ollama / Claude / AI Gateway / Gemini).

The caller may override the provider per-request (`provider` field) to pick
Local / Gateway / Gemini for just this chat session, without touching the
platform-wide LLM_PROVIDER used by flow execution.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Literal, Optional

from app.api.deps import get_current_user
from app.core.config import settings
from app.agents.llm_client import _get_gateway_client, _record_gemini_usage

router = APIRouter(prefix="/chat", tags=["chat"])

_SYSTEM_PROMPT = (
    "You are a helpful, concise assistant embedded in a QA automation platform. "
    "Answer the user's questions directly and conversationally."
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    provider: Optional[Literal["ollama", "claude", "gateway", "gemini"]] = None


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: str = Depends(get_current_user)):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    provider = req.provider or settings.LLM_PROVIDER
    history = [{"role": m.role, "content": m.content} for m in req.messages[-20:]]

    try:
        if provider == "claude":
            reply, model = await _chat_claude(history)
        elif provider == "gateway":
            reply, model = await _chat_gateway(history)
        elif provider == "gemini":
            reply, model = await _chat_gemini(history)
        else:
            reply, model = await _chat_ollama(history)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chat model call failed: {exc}")

    return ChatResponse(reply=reply, provider=provider, model=model)


async def _chat_gateway(history: list[dict]) -> tuple[str, str]:
    api_key = settings.GATEWAY_API_KEY
    if not api_key:
        raise RuntimeError("GATEWAY_API_KEY not set in .env")

    payload = {
        "model": settings.GATEWAY_MODEL,
        "messages": [{"role": "system", "content": _SYSTEM_PROMPT}, *history],
        "max_tokens": 1000,
        "temperature": 0.4,
    }
    client = await _get_gateway_client()
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=settings.LLM_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    return reply or "(no response)", settings.GATEWAY_MODEL


async def _chat_claude(history: list[dict]) -> tuple[str, str]:
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": settings.CLAUDE_MODEL,
        "max_tokens": 1000,
        "system": _SYSTEM_PROMPT,
        "messages": history,
        "temperature": 0.4,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages", headers=headers, json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    reply = data.get("content", [{}])[0].get("text", "").strip()
    return reply or "(no response)", settings.CLAUDE_MODEL


async def _chat_gemini(history: list[dict]) -> tuple[str, str]:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")

    role_map = {"assistant": "model", "user": "user"}
    contents = [{"role": role_map[m["role"]], "parts": [{"text": m["content"]}]} for m in history]

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1000},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            params={"key": api_key},
            headers={"content-type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    await _record_gemini_usage(data.get("usageMetadata", {}))
    reply = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    return reply or "(no response)", settings.GEMINI_MODEL


async def _chat_ollama(history: list[dict]) -> tuple[str, str]:
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "system", "content": _SYSTEM_PROMPT}, *history],
        "stream": False,
        "options": {"temperature": 0.4},
    }
    async with httpx.AsyncClient(timeout=float(settings.LLM_TIMEOUT)) as client:
        resp = await client.post(f"{settings.OLLAMA_HOST}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
    reply = data.get("message", {}).get("content", "").strip()
    return reply or "(no response)", settings.LLM_MODEL
