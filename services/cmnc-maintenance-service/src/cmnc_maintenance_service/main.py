import re

import uvicorn
from fastapi import FastAPI, HTTPException

from cmnc_maintenance_service.docker_client import DockerClient
from cmnc_maintenance_service.schemas import (
    ContainerLogsResponse,
    ContainersStatusResponse,
    HealthResponse,
)
from cmnc_maintenance_service.settings import settings

app = FastAPI(title=settings.service_name)


docker_client = DockerClient(
    socket_path=settings.docker_socket_path,
    timeout_seconds=settings.docker_request_timeout_seconds,
    container_name_prefix=settings.container_name_prefix,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@app.get(
    "/internal/maintenance/containers",
    response_model=ContainersStatusResponse,
)
async def get_containers_status() -> ContainersStatusResponse:
    try:
        containers = await docker_client.get_containers_status()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Docker Engine unavailable: {exc}",
        ) from exc

    return ContainersStatusResponse(containers=containers)


@app.get(
    "/internal/maintenance/containers/{container_id}/logs",
    response_model=ContainerLogsResponse,
)
async def get_container_logs(
    container_id: str,
    tail: int = 100,
) -> ContainerLogsResponse:
    if tail not in {100, 1000, 10000}:
        raise HTTPException(status_code=422, detail="tail must be one of: 100, 1000, 10000")

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", container_id):
        raise HTTPException(status_code=422, detail="Invalid container id")

    try:
        container_name, logs = await docker_client.get_container_logs(
            container_id=container_id,
            tail=tail,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Docker Engine unavailable: {exc}",
        ) from exc

    return ContainerLogsResponse(
        container_id=container_id,
        container_name=container_name,
        tail=tail,
        logs=logs,
    )


def run() -> None:
    uvicorn.run(
        "cmnc_maintenance_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    run()
