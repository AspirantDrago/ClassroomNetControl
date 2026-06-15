import logging
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from cmnc_policy_sync_service.schemas import DesiredBlocklistResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddressListEntry:
    routeros_id: str
    list_name: str
    address: str
    comment: str | None


@dataclass(frozen=True)
class PolicyApplyResult:
    added: int
    removed: int
    updated: int
    connections_killed: int
    errors: list[str]


class MikroTikClient:
    def __init__(
            self,
            base_url: str,
            username: str,
            password: SecretStr,
            verify_tls: bool,
            timeout_seconds: float,
            managed_comment_prefix: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._verify_tls = verify_tls
        self._timeout_seconds = timeout_seconds
        self._managed_comment_prefix = managed_comment_prefix

    async def get_address_list_entries(
            self,
            address_list_name: str,
    ) -> list[AddressListEntry]:
        data = await self._request_json(
            method="GET",
            path="/ip/firewall/address-list",
            params={
                "list": address_list_name,
            },
        )

        if not isinstance(data, list):
            raise TypeError("MikroTik address-list response is not a list")

        entries: list[AddressListEntry] = []

        for item in data:
            if not isinstance(item, dict):
                continue

            routeros_id = item.get(".id")
            list_name = item.get("list")
            address = item.get("address")
            comment = item.get("comment")

            if not routeros_id or not list_name or not address:
                continue

            entries.append(
                AddressListEntry(
                    routeros_id=str(routeros_id),
                    list_name=str(list_name),
                    address=str(address),
                    comment=str(comment) if comment is not None else None,
                )
            )

        return entries

    async def add_address_list_entry(
            self,
            address_list_name: str,
            address: str,
            comment: str,
    ) -> None:
        await self._request_json(
            method="PUT",
            path="/ip/firewall/address-list",
            json={
                "list": address_list_name,
                "address": address,
                "comment": comment,
                "disabled": "false",
            },
        )

    async def address_list_entry_exists(
            self,
            address_list_name: str,
            address: str,
    ) -> bool:
        entries = await self.get_address_list_entries(address_list_name)

        return any(
            entry.address == address
            for entry in entries
        )

    async def update_address_list_comment(
            self,
            routeros_id: str,
            comment: str,
    ) -> None:
        await self._request_json(
            method="PATCH",
            path=f"/ip/firewall/address-list/{routeros_id}",
            json={
                "comment": comment,
            },
        )

    async def delete_address_list_entry(
            self,
            routeros_id: str,
    ) -> None:
        await self._request(
            method="DELETE",
            path=f"/ip/firewall/address-list/{routeros_id}",
        )

    async def remove_connections_by_src_ip(
            self,
            src_ip: str,
    ) -> int:
        connections = await self.get_connections_by_src_ip(src_ip)
        removed = 0

        for connection in connections:
            routeros_id = connection.get(".id")

            if not routeros_id:
                continue

            try:
                await self._request(
                    method="DELETE",
                    path=f"/ip/firewall/connection/{routeros_id}",
                )
                removed += 1
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Failed to delete connection %s for %s: %s",
                    routeros_id,
                    src_ip,
                    exc,
                )

        return removed

    async def get_connections_by_src_ip(
            self,
            src_ip: str,
    ) -> list[dict[str, Any]]:
        # RouterOS stores connection src-address as either the plain IP or as
        # IP:port, for example 192.168.119.105:54231. REST GET query parameters
        # only do exact matching, so use the print command with a query stack:
        # src-address == ip OR (src-address > "ip:" AND src-address < "ip;").
        # The ";" upper bound works because it is the next ASCII character
        # after ":", so it matches all strings that start with "ip:".
        data = await self._request_json(
            method="POST",
            path="/ip/firewall/connection/print",
            json={
                ".proplist": [".id", "src-address"],
                ".query": [
                    f"src-address={src_ip}",
                    f">src-address={src_ip}:",
                    f"<src-address={src_ip};",
                    "#&",
                    "#|",
                ],
            },
        )

        if not isinstance(data, list):
            raise TypeError("MikroTik connections response is not a list")

        connections: list[dict[str, Any]] = []

        for item in data:
            if not isinstance(item, dict):
                continue

            routeros_id = item.get(".id")
            src_address = item.get("src-address")

            if not routeros_id or not src_address:
                continue

            src_address_str = str(src_address)

            # Keep a local guard because this query relies on RouterOS string
            # range comparison. The guard prevents deleting a wrong connection
            # if a RouterOS version behaves differently.
            if src_address_str == src_ip or src_address_str.startswith(f"{src_ip}:"):
                connections.append(item)

        return connections

    async def apply_desired_blocklist(
            self,
            desired: DesiredBlocklistResponse,
            kill_connections_on_block: bool,
    ) -> PolicyApplyResult:
        current_entries = await self.get_address_list_entries(
            desired.address_list_name,
        )

        managed_entries = [
            entry
            for entry in current_entries
            if (entry.comment or "").startswith(self._managed_comment_prefix)
        ]

        desired_by_ip = {
            item.ip_address: item
            for item in desired.blocked
            if item.ip_address
        }

        managed_by_ip = {
            entry.address: entry
            for entry in managed_entries
        }

        desired_ips = set(desired_by_ip)
        current_ips = set(managed_by_ip)

        ips_to_add = sorted(desired_ips - current_ips)
        ips_to_remove = sorted(current_ips - desired_ips)
        ips_to_keep = sorted(desired_ips & current_ips)

        added = 0
        removed = 0
        updated = 0
        connections_killed = 0
        errors: list[str] = []

        for ip in ips_to_add:
            item = desired_by_ip[ip]

            entry_added = False

            try:
                await self.add_address_list_entry(
                    address_list_name=desired.address_list_name,
                    address=ip,
                    comment=item.comment,
                )
                entry_added = True
                added += 1

            except Exception as exc:
                if await self.address_list_entry_exists(
                    address_list_name=desired.address_list_name,
                    address=ip,
                ):
                    entry_added = True
                    added += 1
                    logger.warning(
                        "MikroTik add request for %s failed after the entry was applied: %r",
                        ip,
                        exc,
                    )
                else:
                    error = f"failed to add {ip}: {exc}"
                    logger.exception(error)
                    errors.append(error)

            if entry_added and kill_connections_on_block:
                try:
                    connections_killed += await self.remove_connections_by_src_ip(ip)
                except Exception as exc:
                    logger.warning(
                        "Failed to remove active connections for %s after blocking. "
                        "The address-list entry is already applied, so policy sync is not failed: %s",
                        ip,
                        exc.__class__.__name__,
                    )
                    logger.debug(
                        "Connection cleanup traceback for %s",
                        ip,
                        exc_info=True,
                    )

        for ip in ips_to_keep:
            item = desired_by_ip[ip]
            entry = managed_by_ip[ip]

            if entry.comment != item.comment:
                try:
                    await self.update_address_list_comment(
                        routeros_id=entry.routeros_id,
                        comment=item.comment,
                    )
                    updated += 1
                except Exception as exc:
                    error = f"failed to update comment for {ip}: {exc}"
                    logger.exception(error)
                    errors.append(error)

        for ip in ips_to_remove:
            entry = managed_by_ip[ip]

            try:
                await self.delete_address_list_entry(entry.routeros_id)
                removed += 1
            except Exception as exc:
                error = f"failed to remove {ip}: {exc}"
                logger.exception(error)
                errors.append(error)

        return PolicyApplyResult(
            added=added,
            removed=removed,
            updated=updated,
            connections_killed=connections_killed,
            errors=errors,
        )

    async def _request_json(
            self,
            method: str,
            path: str,
            params: dict[str, Any] | None = None,
            json: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._request(
            method=method,
            path=path,
            params=params,
            json=json,
        )

        if response.content:
            return response.json()

        return None

    async def _request(
            self,
            method: str,
            path: str,
            params: dict[str, Any] | None = None,
            json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"

        async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                verify=self._verify_tls,
                auth=(self._username, self._password.get_secret_value()),
        ) as client:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )

        response.raise_for_status()
        return response
