from typing import Any

import httpx
from pydantic import SecretStr

from cmnc_contracts.events import DhcpLeaseObserved

from cmnc_mikrotik_poller_service.normalizers import (
    get_first_present,
    normalize_mac,
    parse_routeros_bool,
)


class MikroTikClient:
    def __init__(
            self,
            base_url: str,
            username: str,
            password: SecretStr,
            verify_tls: bool,
            timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._verify_tls = verify_tls
        self._timeout_seconds = timeout_seconds

    async def get_dhcp_leases_raw(self) -> list[dict[str, Any]]:
        url = f"{self._base_url}/ip/dhcp-server/lease"

        async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                verify=self._verify_tls,
                auth=(self._username, self._password.get_secret_value()),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            raise TypeError("MikroTik DHCP leases response is not a list")

        return data

    async def get_dhcp_leases(self) -> list[DhcpLeaseObserved]:
        raw_leases = await self.get_dhcp_leases_raw()

        leases: list[DhcpLeaseObserved] = []

        for raw in raw_leases:
            lease = self._normalize_dhcp_lease(raw)

            if lease is not None:
                leases.append(lease)

        return leases

    def _normalize_dhcp_lease(
            self,
            raw: dict[str, Any],
    ) -> DhcpLeaseObserved | None:
        mac = normalize_mac(
            get_first_present(
                raw,
                "active-mac-address",
                "mac-address",
            )
        )

        if mac is None:
            return None

        active_ip = get_first_present(
            raw,
            "active-address",
            "address",
        )

        hostname = get_first_present(
            raw,
            "host-name",
            "hostname",
        )

        dynamic = parse_routeros_bool(raw.get("dynamic"))

        disabled = parse_routeros_bool(raw.get("disabled"))
        blocked = parse_routeros_bool(raw.get("blocked"))

        active = bool(raw.get("active-address")) and disabled is not True
        if blocked is True:
            active = False

        return DhcpLeaseObserved(
            mac=mac,
            active_ip=str(active_ip) if active_ip is not None else None,
            hostname=str(hostname) if hostname is not None else None,
            dynamic=dynamic,
            active=active,
            raw=raw,
        )
