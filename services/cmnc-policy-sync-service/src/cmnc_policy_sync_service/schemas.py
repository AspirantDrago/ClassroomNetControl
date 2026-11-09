from pydantic import BaseModel


class DesiredBlocklistItem(BaseModel):
    device_id: int
    mac_address: str
    ip_address: str
    comment: str


class DesiredBlocklistResponse(BaseModel):
    router_id: int
    policy_generation: int
    device_generations: dict[int, int] | None = None
    address_list_name: str
    blocked: list[DesiredBlocklistItem]
