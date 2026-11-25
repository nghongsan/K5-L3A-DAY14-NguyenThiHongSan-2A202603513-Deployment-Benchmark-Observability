"""
Production AI Agent — Part 6 Final Project

Chạy: uvicorn app.main:app --workers 2
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import redis_client
from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            # Chỉ ghi loại lỗi, không đưa stack trace ra client; chi tiết nằm trong log nội bộ
            entry["exc"] = self.formatException(record.exc_info).replace("\n", " | ")
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("agent")
    log.handlers[:] = [handler]
    log.setLevel(settings.log_level)
    log.propagate = False
    return log


logger = _setup_logging()
_state = {"shutting_down": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis không bị ping lúc khởi động: app vẫn lên được khi Redis chưa sẵn sàng.
    logger.info("startup", extra={"fields": {"environment": settings.environment, "port": settings.port}})
    yield
    # Graceful shutdown: uvicorn nhận SIGTERM → ngừng nhận kết nối mới, chờ request đang chạy xong,
    # rồi mới chạy phần dưới. /ready trả 503 để load balancer ngừng gửi request tới instance này.
    _state["shutting_down"] = True
    logger.info("shutdown", extra={"fields": {"reason": "SIGTERM"}})
    redis_client.close()


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        logger.info("request", extra={"fields": {
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "ms": round((time.perf_counter() - start) * 1000, 1),
        }})


# ── Xử lý lỗi: trả JSON rõ ràng, không lộ stack trace ──
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc, extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 200 khi nhận được request, 503 khi Redis mất kết nối hoặc đang tắt."""
    if _state["shutting_down"] or not redis_client.redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False})
    return {"ready": True}


def _tokens(text: str) -> int:
    # Ước lượng thô: ~1.3 token / từ (mock LLM không trả số token thật)
    return max(1, int(len(text.split()) * 1.3))


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    cost = record_cost(_tokens(body.question), _tokens(answer))
    logger.info("ask", extra={"fields": {"user_id": body.user_id, "cost_usd": round(cost, 8)}})
    return {"question": body.question, "answer": answer}
