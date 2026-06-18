import httpx


class ServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def get_json(self, path: str) -> dict | list:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}{path}")
            response.raise_for_status()
            return response.json()

    async def post_json(self, path: str, json: dict | None = None) -> dict | list:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{self._base_url}{path}", json=json)
            response.raise_for_status()
            return response.json()

    async def patch_json(self, path: str, json: dict | None = None) -> dict | list:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(f"{self._base_url}{path}", json=json)
            response.raise_for_status()
            return response.json()

    async def get_bytes(self, path: str) -> tuple[bytes, str | None, str | None]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{self._base_url}{path}")
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

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{self._base_url}{path}", files=files)
            response.raise_for_status()
            return response.json()
