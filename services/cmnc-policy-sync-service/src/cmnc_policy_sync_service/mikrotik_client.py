import asyncio
import ipaddress
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
    disabled: bool = False
    dynamic: bool = False


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
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds,
                verify=self._verify_tls, trust_env=False,
                auth=(self._username, self._password.get_secret_value()),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_address_list_entries(
            self,
            address_list_name: str,
    ) -> list[AddressListEntry]:
        data = await self._request_json(
            method="GET",
            path="/ip/firewall/address-list",
            params={
                "list": address_list_name,
                ".proplist": ".id,list,address,comment,disabled,dynamic",
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
                    disabled=str(item.get("disabled", "false")).lower() == "true",
                    dynamic=str(item.get("dynamic", "false")).lower() == "true",
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

    async def remove_connections_by_src_ip(self, src_ip: str) -> int:
        return await self.remove_connections_by_src_ips([src_ip])

    async def remove_connections_by_src_ips(self, src_ips: list[str]) -> int:
        from cmnc_policy_sync_service.settings import settings
        targets = sorted({str(ipaddress.IPv4Address(ip)) for ip in src_ips})
        connections: dict[str, dict[str, Any]] = {}
        size = settings.connection_query_batch_size
        for offset in range(0, len(targets), size):
            batch = targets[offset:offset + size]
            query: list[str] = []
            for index, ip in enumerate(batch):
                query.extend([f"src-address={ip}", f">src-address={ip}:", f"<src-address={ip};", "#&", "#|"])
                if index:
                    query.append("#|")
            data = await self._request_json("POST", "/ip/firewall/connection/print",
                json={".proplist": [".id", "src-address"], ".query": query})
            if not isinstance(data, list):
                raise TypeError("MikroTik connections response is not a list")
            for item in data:
                if not isinstance(item, dict) or not item.get(".id"):
                    continue
                source = str(item.get("src-address", ""))
                if any(source == ip or source.startswith(ip + ":") for ip in batch):
                    connections[str(item[".id"])] = item
        pending = asyncio.Queue()
        for identifier in connections:
            pending.put_nowait(identifier)
        interrupted = asyncio.Event()
        async def remove_worker() -> int:
            removed = 0
            while not pending.empty() and not interrupted.is_set():
                try:
                    identifier = pending.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    await self._request("DELETE", f"/ip/firewall/connection/{identifier}")
                    removed += 1
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        interrupted.set()
                    if exc.response.status_code != 404:
                        logger.warning("Connection removal rejected: id=%s status=%s", identifier, exc.response.status_code)
                except httpx.HTTPError:
                    interrupted.set()
                    logger.warning("Connection removal interrupted: id=%s", identifier)
            return removed
        workers = min(settings.connection_delete_concurrency, len(connections))
        return sum(await asyncio.gather(*(remove_worker() for _ in range(workers))))


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


    async def healthcheck(
            self,
            address_list_name: str,
            check_connections: bool,
            connection_src_ip: str,
            write_probe_enabled: bool,
            healthcheck_address_list_name: str,
            healthcheck_address: str,
    ) -> None:
        # Read access to the managed address-list is required for every policy sync.
        await self.get_address_list_entries(address_list_name)

        # Connection cleanup uses /ip/firewall/connection/print. The probe is
        # read-only and does not delete anything.
        if check_connections:
            await self.get_connections_by_src_ip(connection_src_ip)

        # RouterOS REST API has no dry-run mode for write permissions. To verify
        # that policy sync can really change firewall address-list entries, create
        # a disabled probe entry in a dedicated unused list and remove it again.
        if write_probe_enabled:
            await self.verify_address_list_write_access(
                address_list_name=healthcheck_address_list_name,
                address=healthcheck_address,
            )

    async def verify_address_list_write_access(
            self,
            address_list_name: str,
            address: str,
    ) -> None:
        comment = f"{self._managed_comment_prefix}healthcheck=true;"

        await self.delete_healthcheck_entries(
            address_list_name=address_list_name,
            address=address,
            comment=comment,
        )

        try:
            await self.add_healthcheck_address_list_entry(
                address_list_name=address_list_name,
                address=address,
                comment=comment,
            )

            entries = await self.get_address_list_entries(address_list_name)
            exists = any(
                entry.address == address and entry.comment == comment
                for entry in entries
            )

            if not exists:
                raise RuntimeError("MikroTik healthcheck address-list entry was not created")

        finally:
            await self.delete_healthcheck_entries(
                address_list_name=address_list_name,
                address=address,
                comment=comment,
            )

    async def add_healthcheck_address_list_entry(
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
                "disabled": "true",
            },
        )

    async def delete_healthcheck_entries(
            self,
            address_list_name: str,
            address: str,
            comment: str,
    ) -> None:
        entries = await self.get_address_list_entries(address_list_name)

        for entry in entries:
            if entry.address != address or entry.comment != comment:
                continue

            await self.delete_address_list_entry(entry.routeros_id)

    async def apply_desired_blocklist(self, desired: DesiredBlocklistResponse,
                                     kill_connections_on_block: bool) -> PolicyApplyResult:
        current = await self.get_address_list_entries(desired.address_list_name)
        managed: dict[str, list[AddressListEntry]] = {}
        for entry in current:
            if (entry.comment or "").startswith(self._managed_comment_prefix) and not entry.dynamic:
                managed.setdefault(entry.address, []).append(entry)
        wanted = {item.ip_address: item for item in desired.blocked if item.ip_address}
        added = removed = updated = 0
        errors: list[str] = []
        newly_blocked: list[str] = []
        for ip, item in sorted(wanted.items()):
            entries = managed.get(ip, [])
            if not entries:
                try:
                    await self.add_address_list_entry(desired.address_list_name, ip, item.comment)
                except Exception as exc:
                    # A timed-out write may have succeeded. Never mistake a foreign,
                    # dynamic or disabled record for confirmation of our operation.
                    try:
                        observed = await self.get_address_list_entries(desired.address_list_name)
                        confirmed = any(e.address == ip and e.comment == item.comment
                            and not e.disabled and not e.dynamic for e in observed)
                    except Exception:
                        confirmed = False
                    if not confirmed:
                        errors.append(f"failed to add {ip}: {type(exc).__name__}")
                        continue
                added += 1
                newly_blocked.append(ip)
                continue
            entries.sort(key=lambda e: (e.disabled, e.comment != item.comment, e.routeros_id))
            primary, *duplicates = entries
            try:
                if primary.disabled or primary.comment != item.comment:
                    await self._request_json("PATCH", f"/ip/firewall/address-list/{primary.routeros_id}",
                        json={"comment": item.comment, "disabled": "false"})
                    updated += 1
                    if primary.disabled:
                        newly_blocked.append(ip)
            except Exception as exc:
                errors.append(f"failed to enable/update {ip}: {type(exc).__name__}")
                continue
            for duplicate in duplicates:
                try:
                    await self.delete_address_list_entry(duplicate.routeros_id)
                    removed += 1
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        errors.append(f"failed to remove duplicate {ip}: HTTP {exc.response.status_code}")
                except Exception as exc:
                    errors.append(f"failed to remove duplicate {ip}: {type(exc).__name__}")
        for ip in sorted(set(managed) - set(wanted)):
            for entry in managed[ip]:
                try:
                    await self.delete_address_list_entry(entry.routeros_id)
                    removed += 1
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        errors.append(f"failed to remove {ip}: HTTP {exc.response.status_code}")
                except Exception as exc:
                    errors.append(f"failed to remove {ip}: {type(exc).__name__}")
        killed = 0
        if newly_blocked and kill_connections_on_block:
            try:
                killed = await self.remove_connections_by_src_ips(newly_blocked)
            except Exception as exc:
                logger.warning("Connection cleanup incomplete after applying blocklist: %s", type(exc).__name__)
        return PolicyApplyResult(added, removed, updated, killed, errors)

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

        response = await self._http().request(method=method, url=url, params=params, json=json)

        response.raise_for_status()
        return response
