from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStep(BaseModel):
    action: str
    description: Optional[str] = None


class FlowFormat(str, Enum):
    NATURAL = "natural"
    JSON = "json"


# Auth
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


# Flows
class FlowCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    format: FlowFormat = FlowFormat.NATURAL
    task: str  # Natural language OR JSON string
    tags: Optional[List[str]] = []
    env_vars: Optional[Dict[str, str]] = {}  # Per-flow credentials (PORTAL_URL, ADMIN_USER, etc.)


class FlowEnvUpdate(BaseModel):
    env_vars: Dict[str, str] = {}


class FlowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    format: FlowFormat
    task: str
    tags: List[str] = []
    env_vars: Dict[str, str] = {}  # Per-flow credentials
    created_at: str
    updated_at: str


# Execution
class ExecutionRequest(BaseModel):
    flow_id: str
    headless: Optional[bool] = None  # Override default
    extra_params: Optional[Dict[str, Any]] = {}


class ExecutionLog(BaseModel):
    timestamp: str
    level: str  # info, warning, error, success
    message: str
    step: Optional[int] = None
    screenshot: Optional[str] = None  # filename


class ExecutionResult(BaseModel):
    id: str
    flow_id: str
    flow_name: str
    status: ExecutionStatus
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    logs: List[ExecutionLog] = []
    screenshots: List[str] = []
    result_summary: Optional[str] = None
    error: Optional[str] = None
    steps_completed: int = 0
    steps_total: int = 0
    report_file: Optional[str] = None   # PDF / TXT report filename


# WebSocket messages
class WSMessage(BaseModel):
    type: str  # log, screenshot, status, complete
    data: Dict[str, Any]
