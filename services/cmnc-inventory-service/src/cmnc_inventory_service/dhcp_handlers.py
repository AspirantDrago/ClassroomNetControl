import logging

from aio_pika import IncomingMessage
from sqlalchemy import select

from cmnc_contracts.events import DhcpLeasesObservedEvent

from cmnc_inventory_service.db import async_session_maker
from cmnc_inventory_service.models import ObservedDevice

logger = logging.getLogger(__name__)


async def handle_dhcp_leases_observed(message: IncomingMessage) -> None:
    async with message.process(requeue=False):
        event = DhcpLeasesObservedEvent.model_validate_json(message.body)

        logger.info(
            "Received DHCP leases observed event: router_id=%s, leases=%s",
            event.router_id,
            len(event.leases),
        )

        seen_macs = {
            lease.mac
            for lease in event.leases
            if lease.mac
        }

        created = 0
        updated = 0
        marked_inactive = 0

        async with async_session_maker() as session:
            for lease in event.leases:
                result = await session.execute(
                    select(ObservedDevice)
                    .where(ObservedDevice.router_id == event.router_id)
                    .where(ObservedDevice.mac_address == lease.mac)
                )
                observed_device = result.scalar_one_or_none()

                if observed_device is None:
                    observed_device = ObservedDevice(
                        router_id=event.router_id,
                        mac_address=lease.mac,
                        active_ip=lease.active_ip,
                        hostname=lease.hostname,
                        dynamic=lease.dynamic,
                        active=lease.active,
                        raw=lease.raw,
                        last_seen_at=event.occurred_at,
                    )
                    session.add(observed_device)
                    created += 1
                    continue

                observed_device.active_ip = lease.active_ip
                observed_device.hostname = lease.hostname
                observed_device.dynamic = lease.dynamic
                observed_device.active = lease.active
                observed_device.raw = lease.raw

                if lease.active:
                    observed_device.last_seen_at = event.occurred_at

                updated += 1

            if seen_macs:
                result = await session.execute(
                    select(ObservedDevice)
                    .where(ObservedDevice.router_id == event.router_id)
                    .where(ObservedDevice.mac_address.not_in(seen_macs))
                    .where(ObservedDevice.active.is_(True))
                )
                missing_devices = list(result.scalars().all())

                for observed_device in missing_devices:
                    observed_device.active = False
                    marked_inactive += 1

            await session.commit()

        logger.info(
            "DHCP leases saved: created=%s, updated=%s, marked_inactive=%s",
            created,
            updated,
            marked_inactive,
        )
