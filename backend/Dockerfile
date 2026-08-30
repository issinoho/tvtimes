# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /bin/uv

# Dependency layer (cached until pyproject changes)
COPY pyproject.toml ./
RUN uv pip install --system --no-deps . 2>/dev/null || true \
    && uv pip install --system \
        "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9" "pydantic-settings>=2.6" \
        "sqlalchemy[asyncio]>=2.0.36" "alembic>=1.14" "asyncpg>=0.30" "aiosqlite>=0.20" \
        "greenlet>=3.1" "structlog>=24.4" "httpx>=0.28" "python-multipart>=0.0.12" \
        "email-validator>=2.2" "webauthn>=2.2" "argon2-cffi>=23.1" "pyotp>=2.9" \
        "pyjwt[crypto]>=2.10" "cryptography>=44" "arq>=0.26" "redis>=5.2"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
