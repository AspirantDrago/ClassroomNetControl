from typing import Any


def parse_routeros_bool(value: Any) -> bool | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        value_lower = value.strip().lower()

        if value_lower in {"true", "yes", "1"}:
            return True

        if value_lower in {"false", "no", "0"}:
            return False

    return None


def normalize_mac(value: str | None) -> str | None:
    if value is None:
        return None

    mac = value.strip().upper()

    if not mac:
        return None

    return mac


def get_first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)

        if value not in (None, ""):
            return value

    return None
