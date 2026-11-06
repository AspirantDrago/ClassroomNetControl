import asyncio
import ipaddress
import re
from typing import Any

import httpx
from fastapi import HTTPException


WOL_PROBE_MAC = "02:00:00:00:00:00"


def usable_addresses(addresses: list[Any]) -> list[dict[str, Any]]:
    return [item for item in addresses if isinstance(item, dict)
            and item.get("disabled") not in (True, "true")
            and item.get("invalid") not in (True, "true")
            and isinstance(item.get("interface"), str) and item["interface"]]


def select_wol_interface(addresses: list[Any], subnet_cidr: str) -> str:
    try:
        subnet = ipaddress.ip_network(subnet_cidr, strict=False)
    except ValueError as exc:
        raise HTTPException(409, "Некорректная подсеть аудитории") from exc
    candidates: list[tuple[int, str]] = []
    for item in usable_addresses(addresses):
        try:
            network = ipaddress.ip_interface(item.get("address", "")).network
        except ValueError:
            continue
        if network.version == subnet.version and subnet.subnet_of(network):
            candidates.append((network.prefixlen, item["interface"]))
    if not candidates:
        raise HTTPException(409, "На MikroTik не найден интерфейс подсети аудитории для WoL")
    best_prefix = max(prefix for prefix, _ in candidates)
    interfaces = {name for prefix, name in candidates if prefix == best_prefix}
    if len(interfaces) != 1:
        raise HTTPException(409, "На MikroTik найдено несколько интерфейсов подсети аудитории для WoL")
    return interfaces.pop()


def wol_response_error(response: httpx.Response) -> str | None:
    if response.status_code in {401, 403}:
        return "Недостаточно прав MikroTik для WoL"
    if not response.is_success:
        return f"MikroTik отклонил запрос WoL (HTTP {response.status_code})"
    try:
        data = response.json()
    except ValueError:
        return "MikroTik вернул некорректный ответ WoL"
    if not isinstance(data, (dict, list)):
        return "MikroTik вернул некорректный ответ WoL"
    if isinstance(data, dict) and data.get("error"):
        return "MikroTik сообщил об ошибке WoL"
    return None


async def read_wol_addresses(client: httpx.AsyncClient, base_url: str) -> list[Any]:
    response = await client.get(f"{base_url}/ip/address")
    if not response.is_success:
        raise HTTPException(502, f"Не удалось прочитать интерфейсы MikroTik (HTTP {response.status_code})")
    try:
        addresses = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Некорректный список интерфейсов MikroTik") from exc
    if not isinstance(addresses, list):
        raise HTTPException(502, "Некорректный список интерфейсов MikroTik")
    return addresses


async def send_wol_packets(
    router: dict[str, Any], base_url: str, subnet_cidr: str, devices: list[dict[str, Any]],
) -> dict[str, Any]:
    if router.get("is_enabled") is False:
        raise HTTPException(409, "Маршрутизатор отключён")
    targets = {str(device.get("mac_address", "")).strip().upper(): device for device in devices}
    if not targets:
        return {"sent_count": 0, "failed_count": 0, "results": []}
    try:
        async with httpx.AsyncClient(
            timeout=10.0, verify=router.get("api_verify_tls", False),
            auth=(router["api_username"], router["api_password"]), follow_redirects=False,
        ) as client:
            addresses = await read_wol_addresses(client, base_url)
            interface = select_wol_interface(addresses, subnet_cidr)
            semaphore = asyncio.Semaphore(4)

            async def send_one(mac: str, device: dict[str, Any]) -> dict[str, Any]:
                error = None
                if (not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac)
                        or mac == "00:00:00:00:00:00" or int(mac[:2], 16) & 1):
                    error = "Некорректный MAC-адрес устройства для WoL"
                else:
                    try:
                        async with asyncio.timeout(30):
                            async with semaphore:
                                response = await client.post(
                                    f"{base_url}/tool/wol", json={"mac": mac, "interface": interface},
                                )
                                error = wol_response_error(response)
                    except (TimeoutError, httpx.TimeoutException):
                        error = "Превышено время ожидания отправки WoL"
                    except httpx.RequestError:
                        error = "MikroTik недоступен для отправки WoL"
                return {"device_id": device["id"], "mac_address": mac, "sent": error is None, "error": error}

            results = await asyncio.gather(*(send_one(mac, device) for mac, device in targets.items()))
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Превышено время ожидания MikroTik") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "MikroTik недоступен для WoL") from exc
    return {
        "sent_count": sum(item["sent"] for item in results),
        "failed_count": sum(not item["sent"] for item in results),
        "interface": interface, "results": results,
    }


async def check_wol_capability(client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
    result = {
        "name": "wake_on_lan", "label": "Wake-on-LAN (WoL)", "method": "POST",
        "path": "/tool/wol", "ok": False, "status_code": None, "error": None,
        "redirect_location": None, "response_preview": None, "item_count": None,
    }
    try:
        addresses = usable_addresses(await read_wol_addresses(client, base_url))
        if not addresses:
            result["error"] = "Нет интерфейса для проверки WoL"
            return result
        response = await client.post(
            f"{base_url}/tool/wol",
            json={"mac": WOL_PROBE_MAC, "interface": addresses[0]["interface"]},
        )
        result["status_code"] = response.status_code
        result["error"] = wol_response_error(response)
        result["ok"] = result["error"] is None
    except HTTPException as exc:
        result["error"] = str(exc.detail)
    except httpx.RequestError:
        result["error"] = "MikroTik недоступен для проверки WoL"
    return result
