"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

redis.from_url() không mở kết nối ngay, nên app vẫn khởi động được khi Redis chưa sẵn sàng.
Timeout ngắn để /ready và /ask không treo khi Redis mất kết nối.
"""
import redis

from app.config import settings

r = (
    redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    if settings.redis_url
    else None
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: Redis không kết nối được → False."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False


def close() -> None:
    if r is not None:
        try:
            r.close()
        except redis.RedisError:
            pass
