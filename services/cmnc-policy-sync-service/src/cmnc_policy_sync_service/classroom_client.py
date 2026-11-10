import httpx

from cmnc_policy_sync_service.schemas import DesiredBlocklistResponse


class ClassroomServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0, trust_env=False,
                limits=httpx.Limits(max_connections=30, max_keepalive_connections=10))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


    async def get_desired_blocklist(
            self,
            router_id: int,
    ) -> DesiredBlocklistResponse:
        url = f"{self._base_url}/internal/routers/{router_id}/desired-blocklist"

        client = self._http()
        response = await client.get(url)
        response.raise_for_status()

        return DesiredBlocklistResponse.model_validate(response.json())
