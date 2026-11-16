"""Recipient-visible demonstration endpoint, configured per MikroTik."""
import ipaddress
import re

from pydantic import BaseModel, Field, field_validator


def normalize_demo_host(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        try:
            name = value.encode('idna').decode('ascii').lower().rstrip('.')
        except UnicodeError as exc:
            raise ValueError('Некорректное имя сервера демонстрации') from exc
        if (not name or len(name) > 253 or name == 'localhost' or name.endswith('.localhost')
                or re.fullmatch(r'[0-9.]+', name)
                or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in name.split('.'))):
            raise ValueError('Укажите IP или DNS сервера без протокола, пути и порта')
        return name
    if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_link_local:
        raise ValueError('Укажите адрес сервера, доступный с ПК аудитории')
    return str(address)


class DemoEndpoint(BaseModel):
    relay_host: str = Field(min_length=1, max_length=253)
    relay_port: int = Field(ge=1, le=65535, strict=True)

    @field_validator('relay_host')
    @classmethod
    def valid_host(cls, value):
        host = normalize_demo_host(value)
        if not host:
            raise ValueError('Укажите адрес сервера демонстрации')
        return host
