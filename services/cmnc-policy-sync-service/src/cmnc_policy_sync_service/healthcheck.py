import asyncio
import sys

from cmnc_policy_sync_service.mikrotik_client import MikroTikClient
from cmnc_policy_sync_service.settings import settings


async def check() -> None:
    client = MikroTikClient(
        base_url=settings.mikrotik_base_url,
        username=settings.mikrotik_username,
        password=settings.mikrotik_password,
        verify_tls=settings.mikrotik_verify_tls,
        timeout_seconds=settings.mikrotik_timeout_seconds,
        managed_comment_prefix=settings.managed_comment_prefix,
    )

    await client.healthcheck(
        address_list_name=settings.address_list_name,
        check_connections=settings.kill_connections_on_block,
        connection_src_ip=settings.healthcheck_connection_src_ip,
        write_probe_enabled=settings.healthcheck_write_probe_enabled,
        healthcheck_address_list_name=settings.healthcheck_address_list_name,
        healthcheck_address=settings.healthcheck_address,
    )


def main() -> None:
    try:
        asyncio.run(check())
    except Exception as exc:
        print(f"unhealthy: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("healthy")


if __name__ == "__main__":
    main()
