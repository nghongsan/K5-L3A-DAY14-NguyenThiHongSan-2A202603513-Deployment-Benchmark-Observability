"""
Lịch sử hội thoại lưu trong Redis (Exercise 5.3 — stateless).

Anti-pattern:  conversation_history = {}        # RAM của từng process/instance
Cách làm đúng: Redis list  history:<user>       # mọi worker/instance đọc chung

Vì state nằm ở Redis nên: nhiều worker/instance dùng chung, restart agent không mất lịch sử,
và request tiếp theo rơi vào instance nào cũng thấy đủ hội thoại.
Đây là tính năng phụ: nếu Redis lỗi thì bỏ qua, không làm hỏng /ask.
"""
import hashlib
import json

import redis

from app import redis_client
from app.config import settings

_TTL_SECONDS = 7 * 24 * 3600


def _key(user_id: str) -> str:
    return "history:" + hashlib.sha256(user_id.encode()).hexdigest()[:16]


def append_turn(user_id: str, question: str, answer: str) -> None:
    if redis_client.r is None:
        return
    key = _key(user_id)
    try:
        pipe = redis_client.r.pipeline()
        pipe.rpush(key, json.dumps({"role": "user", "content": question}, ensure_ascii=False))
        pipe.rpush(key, json.dumps({"role": "assistant", "content": answer}, ensure_ascii=False))
        pipe.ltrim(key, -settings.history_max_messages, -1)  # chỉ giữ N tin nhắn gần nhất
        pipe.expire(key, _TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        pass


def get_history(user_id: str) -> list[dict]:
    if redis_client.r is None:
        return []
    try:
        return [json.loads(m) for m in redis_client.r.lrange(_key(user_id), 0, -1)]
    except redis.RedisError:
        return []
