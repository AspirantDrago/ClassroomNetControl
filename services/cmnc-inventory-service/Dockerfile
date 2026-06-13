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
COPY services/cmnc-inventory-service ./services/cmnc-inventory-service

RUN uv sync --package cmnc-inventory-service --no-dev

EXPOSE 8003

CMD ["sh", "-c", "alembic -c services/cmnc-inventory-service/alembic.ini upgrade head && uvicorn cmnc_inventory_service.main:app --host 0.0.0.0 --port 8003"]
