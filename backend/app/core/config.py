import os
from pathlib import Path
from typing import Optional

# Load .env file if present
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except Exception:
    pass


class Settings:
    APP_NAME: str = "AI Browser Automation Platform"
    VERSION: str = "2.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Admin credentials (platform login — NOT flow credentials)
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    # LLM Provider — "ollama" (local), "claude" (Anthropic API), "gateway", or "gemini"
    # (Promon AI Gateway — LiteLLM proxy, OpenAI-compatible, see litellm_benchmarking)
    # Set LLM_PROVIDER=claude + ANTHROPIC_API_KEY to use the Claude API
    # instead of a local Ollama model (recommended for laptops without a GPU)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").lower()   # "ollama" | "claude" | "gateway" | "gemini"
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    # Claude model to use when LLM_PROVIDER=claude
    # claude-haiku-4-5-20251001 = fastest/cheapest; claude-sonnet-4-6 = smarter
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Google Gemini API — used when LLM_PROVIDER=gemini. Natively multimodal, so
    # the same model can serve both flow planning (text) and vision element-finding.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_VISION_MODEL: str = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")

    # Ollama / LLM
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen2.5:14b")          # text: flow parsing (Ollama)
    VISION_MODEL: str = os.getenv("VISION_MODEL", "qwen2.5vl:latest") # vision: screen agent
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))

    # AI Gateway (LiteLLM proxy) — used when LLM_PROVIDER=gateway.
    # Get a scoped/budget-capped virtual key from whoever holds vault_litellm_master_key
    # (see litellm_benchmarking step 3) — never use the master key here.
    GATEWAY_BASE_URL: str = os.getenv("GATEWAY_BASE_URL", "https://ai-gateway.promon.co.in")
    GATEWAY_API_KEY: str = os.getenv("GATEWAY_API_KEY", "")
    GATEWAY_MODEL: str = os.getenv("GATEWAY_MODEL", "local-qwen25")           # text: flow parsing
    GATEWAY_VISION_MODEL: str = os.getenv("GATEWAY_VISION_MODEL", "local-moondream")  # vision: screen agent
    # Path to the self-signed CA cert (fetched-certs/ai-gateway.promon.co.in.crt).
    # Leave blank to use default system trust (will fail against the self-signed cert).
    GATEWAY_CACERT: str = os.getenv("GATEWAY_CACERT", "")

    # Agent toggles — set in .env to control which agents are active
    # USE_FLOW_AGENT=false  → steps execute directly, no LLM planning (fast, offline)
    # USE_FLOW_AGENT=true   → LLM plans steps before execution (Ollama or Claude API)
    # USE_VISION_AGENT=true → vision model used as fallback element finder
    USE_FLOW_AGENT: bool = os.getenv("USE_FLOW_AGENT", "false").lower() in ("true", "1", "yes")
    USE_VISION_AGENT: bool = os.getenv("USE_VISION_AGENT", "true").lower() in ("true", "1", "yes")

    # Browser — headless=true for speed (no visible window)
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
    BROWSER_SLOW_MO: int = int(os.getenv("BROWSER_SLOW_MO", "0"))
    BROWSER_NAVIGATION_TIMEOUT: int = int(os.getenv("BROWSER_NAVIGATION_TIMEOUT", "180000"))

    # Screenshot mode: "fail_only" (only on failure) | "final" (one at end) | "all" (every step)
    # Default: "fail_only" — fastest, captures failures for debugging
    SCREENSHOT_MODE: str = os.getenv("SCREENSHOT_MODE", "fail_only")

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    ARTIFACTS_DIR: Path = BASE_DIR / "artifacts"
    EXECUTIONS_DIR: Path = ARTIFACTS_DIR / "executions"
    SCREENSHOTS_DIR: Path = ARTIFACTS_DIR / "screenshots"
    FLOWS_DIR: Path = ARTIFACTS_DIR / "flows"
    REPORTS_DIR: Path = ARTIFACTS_DIR / "reports"
    # Disk flows folder — lives in <project-root>/flows/ so VS Code edits are picked up directly.
    # config.py is at backend/app/core/config.py, so .parent×4 = project root.
    # Override with DISK_FLOWS_DIR env var if needed.
    DISK_FLOWS_DIR: Path = Path(os.getenv("DISK_FLOWS_DIR", str(Path(__file__).parent.parent.parent.parent / "flows")))

    # CORS — comma-separated origins via ALLOWED_ORIGINS env var
    ALLOWED_ORIGINS: list = [
        o.strip()
        for o in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000"
        ).split(",")
        if o.strip()
    ]

    def __init__(self):
        for p in [self.EXECUTIONS_DIR, self.SCREENSHOTS_DIR, self.FLOWS_DIR,
                  self.REPORTS_DIR]:
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
