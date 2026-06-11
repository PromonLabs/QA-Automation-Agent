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

    # Ollama / LLM
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen2.5:14b")          # text: flow parsing
    VISION_MODEL: str = os.getenv("VISION_MODEL", "qwen2.5vl:latest") # vision: screen agent
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))

    # Browser — headless=true for speed (no visible window)
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
    BROWSER_SLOW_MO: int = int(os.getenv("BROWSER_SLOW_MO", "0"))
    BROWSER_NAVIGATION_TIMEOUT: int = int(os.getenv("BROWSER_NAVIGATION_TIMEOUT", "60000"))

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
    MEMORY_DIR: Path = ARTIFACTS_DIR / "memory"
    # Disk flows folder — lives inside backend/flows/ so it deploys with the code
    # Override with DISK_FLOWS_DIR env var if needed
    DISK_FLOWS_DIR: Path = Path(os.getenv("DISK_FLOWS_DIR", str(Path(__file__).parent.parent.parent / "flows")))

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
                  self.REPORTS_DIR, self.MEMORY_DIR]:
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
