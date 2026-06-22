import asyncio
import sys

from cmnc_mikrotik_poller_service.mikrotik_client import MikroTikClient
from cmnc_mikrotik_poller_service.settings import settings


async def check() -> None:
    client = MikroTikClient(
        base_url=settings.mikrotik_base_url,
        username=settings.mikrotik_username,
        password=settings.mikrotik_password,
        verify_tls=settings.mikrotik_verify_tls,
        timeout_seconds=settings.mikrotik_timeout_seconds,
    )

    await client.get_dhcp_leases_raw()


def main() -> None:
    try:
        asyncio.run(check())
    except Exception as exc:
        print(f"unhealthy: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("healthy")


if __name__ == "__main__":
    main()
