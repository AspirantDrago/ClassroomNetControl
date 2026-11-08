from contextlib import asynccontextmanager

import httpx


class ServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def start(self):
        self._client = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(max_connections=100, max_keepalive_connections=30))

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def connection(self, timeout):
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                yield client

    async def get_json(self, path: str, timeout_seconds: float = 10.0) -> dict | list:
        async with self.connection(timeout_seconds) as client:
            response = await client.get(f"{self._base_url}{path}", timeout=timeout_seconds)
            response.raise_for_status()
            return response.json()

    async def post_json(self, path: str, json: dict | None = None) -> dict | list:
        async with self.connection(10.0) as client:
            response = await client.post(f"{self._base_url}{path}", json=json)
            response.raise_for_status()
            return response.json()

    async def patch_json(self, path: str, json: dict | None = None) -> dict | list:
        async with self.connection(10.0) as client:
            response = await client.patch(f"{self._base_url}{path}", json=json)
            response.raise_for_status()
            return response.json()

    async def get_bytes(self, path: str) -> tuple[bytes, str | None, str | None]:
        async with self.connection(120.0) as client:
            response = await client.get(f"{self._base_url}{path}", timeout=120.0)
            response.raise_for_status()
            return (
                response.content,
                response.headers.get("content-type"),
                response.headers.get("content-disposition"),
            )

    async def post_file(
        self,
        path: str,
        field_name: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict | list:
        files = {
            field_name: (filename, content, content_type),
        }

        async with self.connection(300.0) as client:
            response = await client.post(f"{self._base_url}{path}", files=files, timeout=300.0)
            response.raise_for_status()
            return response.json()
