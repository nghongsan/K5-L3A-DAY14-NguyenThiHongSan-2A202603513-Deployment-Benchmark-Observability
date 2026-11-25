"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày, theo tháng và theo TỪNG USER
  • Tổng chi phí vượt DAILY_BUDGET_USD / MONTHLY_BUDGET_USD (toàn hệ thống) hoặc
    USER_MONTHLY_BUDGET_USD (mỗi user) → HTTP 402
"""
import hashlib
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app import redis_client
from app.config import settings

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_DAY_TTL = 2 * 24 * 3600
_MONTH_TTL = 35 * 24 * 3600


def _keys(user_id: str | None = None) -> tuple[str, str, str | None]:
    now = datetime.now(timezone.utc)
    user_key = None
    if user_id:
        # Băm user_id để độ dài key cố định và không chứa ký tự lạ do client gửi
        uid = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        user_key = f"cost:user:{uid}:{now:%Y-%m}"
    return f"cost:day:{now:%Y-%m-%d}", f"cost:month:{now:%Y-%m}", user_key


def check_budget(user_id: str | None = None) -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    if redis_client.r is None:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    day_key, month_key, user_key = _keys(user_id)
    try:
        day_spent, month_spent, user_spent = redis_client.r.mget(day_key, month_key, user_key or day_key)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    if float(day_spent or 0) >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exhausted")
    if float(month_spent or 0) >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail="Monthly budget exhausted")
    # Budget riêng từng user: một user đốt hết phần của mình không làm chết user khác
    if user_key and float(user_spent or 0) >= settings.user_monthly_budget_usd:
        raise HTTPException(status_code=402, detail="User monthly budget exhausted")


def record_cost(input_tokens: int, output_tokens: int, user_id: str | None = None) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    if redis_client.r is None:
        return cost
    day_key, month_key, user_key = _keys(user_id)
    try:
        pipe = redis_client.r.pipeline()
        pipe.incrbyfloat(day_key, cost)
        pipe.expire(day_key, _DAY_TTL)
        pipe.incrbyfloat(month_key, cost)
        pipe.expire(month_key, _MONTH_TTL)
        if user_key:
            pipe.incrbyfloat(user_key, cost)
            pipe.expire(user_key, _MONTH_TTL)
        pipe.execute()
    except redis.RedisError:
        pass  # request đã được phục vụ; mất một lần ghi chi phí tốt hơn là trả lỗi cho người dùng
    return cost
