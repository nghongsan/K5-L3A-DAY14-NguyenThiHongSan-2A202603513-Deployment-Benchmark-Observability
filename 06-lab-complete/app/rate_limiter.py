"""
Rate limiting (tiêu chí 7) — sliding window 60 giây cho mỗi API key.

State nằm trong Redis (sorted set) nên mọi worker / instance dùng chung và vẫn còn
sau khi restart agent. Việc kiểm tra + ghi chạy trong một Lua script để atomic,
tránh hai worker cùng đọc "còn chỗ" rồi cùng vượt giới hạn.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app import redis_client
from app.config import settings

WINDOW_SECONDS = 60

# KEYS[1]=zset; ARGV: now_ms, window_ms, limit, member
# trả {allowed(0/1), retry_after_ms}
_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return {0, math.max(tonumber(oldest[2]) + window - now, 1)}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


def check_rate_limit(key: str) -> None:
    if redis_client.r is None:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
    # Băm key để không ghi API key thật vào Redis
    redis_key = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    now_ms = int(time.time() * 1000)
    try:
        allowed, retry_ms = redis_client.r.eval(
            _LUA, 1, redis_key,
            now_ms, WINDOW_SECONDS * 1000, settings.rate_limit_per_minute,
            f"{now_ms}-{uuid.uuid4().hex}",
        )
    except redis.RedisError:
        # Không có Redis thì không đếm được → từ chối (fail closed) thay vì bỏ qua giới hạn
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
    if not allowed:
        retry_after = max(1, -(-int(retry_ms) // 1000))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} requests/minute",
            headers={"Retry-After": str(retry_after)},
        )
