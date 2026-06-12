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
COPY services/cmnc-api-gateway ./services/cmnc-api-gateway

RUN uv sync --package cmnc-api-gateway --no-dev

EXPOSE 8000

CMD ["uvicorn", "cmnc_api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
