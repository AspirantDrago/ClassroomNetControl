FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app/services/cmnc-maintenance-service

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/services/cmnc-maintenance-service/.venv/bin:$PATH"

COPY services/cmnc-maintenance-service/pyproject.toml ./pyproject.toml
COPY services/cmnc-maintenance-service/src ./src

RUN uv sync --no-dev

EXPOSE 8004

CMD ["uvicorn", "cmnc_maintenance_service.main:app", "--host", "0.0.0.0", "--port", "8004"]
