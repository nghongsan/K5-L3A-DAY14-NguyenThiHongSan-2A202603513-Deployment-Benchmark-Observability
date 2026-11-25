# ============================================================
# Stage 1 — builder: cài dependencies vào virtualenv riêng
# ============================================================
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements trước để Docker cache layer khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt

# ============================================================
# Stage 2 — runtime: chỉ chứa venv + code, không có pip cache / build tools
# ============================================================
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    WORKERS=2

RUN groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app utils ./utils

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=2)"]

# exec để uvicorn là PID 1: nhận SIGTERM từ `docker stop` và tắt êm.
# Lắng nghe theo $PORT (Railway/Render tự cấp), mặc định 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-2}"]
