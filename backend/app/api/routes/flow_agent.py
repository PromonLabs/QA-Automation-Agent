"""
Flow-Agent chat endpoint.
Converts rough natural-language flow descriptions into clean JSON flows
using the local Ollama model via HTTP, with regex-parser fallback.
"""
import json
import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user
from app.core.config import settings
from app.agents.llm_client import _steps_from_task, _extract_json

router = APIRouter(prefix="/flow-agent", tags=["flow-agent"])

_SYSTEM_PROMPT = """You are a QA automation expert. Convert rough descriptions into clean JSON automation flows.

Output ONLY valid JSON in this exact format:
{
  "name": "Flow Name",
  "steps": [
    "Navigate to ${URL}",
    "Click the - Button Label - button",
    "Enter Username in input box ${ADMIN_USER}",
    "Enter Password in input box ${ADMIN_PASS}",
    "Click the - Log in - button",
    "Wait 2000ms",
    "In Search box enter the ${ACCOUNT_NUMBER}",
    "Click on the customer ${ACCOUNT_NUMBER}",
    "Note the old balance on this page",
    "Take the screenshot of that page and save it as - page.png -",
    "SS",
    "Verify the balance is updated"
  ]
}

Step writing rules:
- Use ${VARIABLE_NAME} for any value that changes per run
- Common variables: ${COS_URL}, ${PORTAL_URL}, ${ADMIN_USER}, ${ADMIN_PASS}, ${ACCOUNT_NUMBER}, ${MISTIN_ID}
- Button text format: "Click the - Label - button" (with dashes around label)
- One action per step — never combine two actions in one step
- Add "Wait Nms" after slow page loads or form submissions
- Add screenshot steps for important states: "Take the screenshot ... save it as - name.png -"
- Add "SS" as a separate step after screenshot steps for live preview
- For login flows always include: escape, click login-with-password, enter username, enter password, click login
- Output ONLY the JSON object — no markdown, no explanation.

Reference example (Tusass TopUp Talk flow):
{
  "name": "Tusass TopUp Talk",
  "steps": [
    "Navigate to ${COS_URL}",
    "Click escape button to show the - Login with password - button",
    "Click the - Login with password - button",
    "Enter Username in input box ${ADMIN_USER}",
    "Enter Password in input box ${ADMIN_PASS}",
    "Click the - Log in - button",
    "In Search box enter the ${MISTIN_ID}",
    "Click on the customer ${MISTIN_ID}",
    "Note the old balance on this page",
    "Take the screenshot of that page and save it as - search-result.png -",
    "SS",
    "Navigate to ${PORTAL_URL}",
    "Click the TopUp talk button",
    "Enter phone number in input box ${PHONE_NUMBER}",
    "Click the Continue button",
    "Select amount ${TOPUP_AMOUNT}",
    "Click the continue button",
    "In Card number field, enter ${CARD_NUMBER}",
    "In MM field, enter ${CARD_MONTH}",
    "In YY field, enter ${CARD_YEAR}",
    "In CVV/CVD field, enter ${CARD_CVV}",
    "Click the Pay button",
    "Take the screenshot of that page and save it as - receipt.png -",
    "SS",
    "Navigate to ${COS_URL}",
    "Note the new balance on this page after topup",
    "Verify the balance is updated by comparing the current balance with previous balance and topup amount - ${TOPUP_AMOUNT} -",
    "Give the report - Flow completed successfully"
  ]
}"""


class ChatRequest(BaseModel):
    message: str
    flow_name: Optional[str] = ""


class ChatResponse(BaseModel):
    flow: dict
    flow_json: str
    used_llm: bool


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: str = Depends(get_current_user)):
    """Convert a rough flow description to a clean JSON flow."""
    name = req.flow_name.strip() if req.flow_name else "Untitled Flow"
    prompt = f'Flow name: "{name}"\n\nConvert this description to a JSON flow:\n\n{req.message}'

    llm_flow: dict | None = None
    used_llm = False

    try:
        payload = {
            "model": settings.LLM_MODEL,
            "prompt": prompt,
            "system": _SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 2000,
                "num_ctx": 4096,
            },
        }
        async with httpx.AsyncClient(timeout=float(settings.LLM_TIMEOUT)) as client:
            resp = await client.post(
                f"{settings.OLLAMA_HOST}/api/generate", json=payload
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")

        parsed = _extract_json(raw)
        if parsed and isinstance(parsed.get("steps"), list) and parsed["steps"]:
            llm_flow = parsed
            used_llm = True
    except Exception:
        pass

    if not llm_flow:
        # Regex-parser fallback: always gives a usable result
        steps_data = _steps_from_task(req.message)
        step_strings = [
            s.get("description") or s.get("target") or ""
            for s in steps_data
            if s.get("action") != "skip"
        ]
        llm_flow = {"name": name, "steps": step_strings}

    if "name" not in llm_flow or not llm_flow["name"]:
        llm_flow["name"] = name

    return ChatResponse(
        flow=llm_flow,
        flow_json=json.dumps(llm_flow, indent=2, ensure_ascii=False),
        used_llm=used_llm,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest, user: str = Depends(get_current_user)):
    """Stream LLM tokens as Server-Sent Events."""
    name = req.flow_name.strip() if req.flow_name else "Untitled Flow"
    prompt = f'Flow name: "{name}"\n\nConvert this description to a JSON flow:\n\n{req.message}'

    async def generate():
        try:
            payload = {
                "model": settings.LLM_MODEL,
                "prompt": prompt,
                "system": _SYSTEM_PROMPT,
                "stream": True,
                "options": {"temperature": 0.1, "num_predict": 2000, "num_ctx": 4096},
            }
            async with httpx.AsyncClient(timeout=float(settings.LLM_TIMEOUT)) as client:
                async with client.stream(
                    "POST", f"{settings.OLLAMA_HOST}/api/generate", json=payload
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                yield f"data: {json.dumps({'token': token})}\n\n"
                            if data.get("done"):
                                yield f"data: {json.dumps({'done': True})}\n\n"
                        except Exception:
                            pass
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
