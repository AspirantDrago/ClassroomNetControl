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
