FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock* ./

COPY libs/cmnc-contracts ./libs/cmnc-contracts
COPY services/cmnc-classroom-service ./services/cmnc-classroom-service

RUN uv sync --package cmnc-classroom-service --no-dev

EXPOSE 8002

CMD ["sh", "-c", "alembic -c services/cmnc-classroom-service/alembic.ini upgrade head && uvicorn cmnc_classroom_service.main:app --host 0.0.0.0 --port 8002"]
