"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không có secret nào được hard-code ở đây. AGENT_API_KEY mặc định rỗng và khi rỗng
thì /ask từ chối mọi request (an toàn khi quên cấu hình).
"""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    port: int = _int("PORT", 8000)
    environment: str = os.getenv("ENVIRONMENT", "development")
    agent_api_key: str = os.getenv("AGENT_API_KEY", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    rate_limit_per_minute: int = _int("RATE_LIMIT_PER_MINUTE", 10)
    daily_budget_usd: float = _float("DAILY_BUDGET_USD", 1.0)
    monthly_budget_usd: float = _float("MONTHLY_BUDGET_USD", 10.0)
    user_monthly_budget_usd: float = _float("USER_MONTHLY_BUDGET_USD", 10.0)
    history_max_messages: int = _int("HISTORY_MAX_MESSAGES", 20)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()
