FROM python:3.15.2-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app/services/cmnc-veyon-service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
ENV PATH="/app/services/cmnc-veyon-service/.venv/bin:$PATH"
COPY services/cmnc-veyon-service/pyproject.toml ./pyproject.toml
COPY services/cmnc-veyon-service/src ./src
COPY libs/cmnc-contracts/src /app/contracts
ENV PYTHONPATH=/app/contracts
RUN uv sync --no-dev --no-sources
EXPOSE 8008
CMD ["uvicorn", "cmnc_veyon_service.main:app", "--host", "0.0.0.0", "--port", "8008"]
