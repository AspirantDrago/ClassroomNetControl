import httpx

from cmnc_policy_sync_service.schemas import DesiredBlocklistResponse


class ClassroomServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def get_desired_blocklist(
            self,
            router_id: int,
    ) -> DesiredBlocklistResponse:
        url = f"{self._base_url}/internal/routers/{router_id}/desired-blocklist"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        return DesiredBlocklistResponse.model_validate(response.json())
