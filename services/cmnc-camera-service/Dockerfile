FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app/services/cmnc-camera-service

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/services/cmnc-camera-service/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY services/cmnc-camera-service/pyproject.toml ./pyproject.toml
COPY services/cmnc-camera-service/src ./src

RUN uv sync --no-dev

EXPOSE 8005

CMD ["uvicorn", "cmnc_camera_service.main:app", "--host", "0.0.0.0", "--port", "8005"]
