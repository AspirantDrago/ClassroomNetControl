import logging
from datetime import timezone

from aio_pika import IncomingMessage
from sqlalchemy import select

from cmnc_contracts.events import DhcpLeasesObservedEvent
from cmnc_inventory_service.db import async_session_maker
from cmnc_inventory_service.models import ObservedDevice, Router

logger = logging.getLogger(__name__)

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

async def handle_dhcp_leases_observed(message: IncomingMessage) -> None:
    async with message.process(requeue=False):
        event = DhcpLeasesObservedEvent.model_validate_json(message.body)
        async with async_session_maker() as session:
            # Serialize snapshots of the same router, including empty snapshots.
            result = await session.execute(select(Router).where(Router.id == event.router_id).with_for_update())
            router = result.scalar_one_or_none()
            if router is None:
                logger.warning("Ignoring DHCP snapshot for removed router_id=%s", event.router_id)
                return
            observed_at = utc(event.occurred_at)
            if router.dhcp_snapshot_at is not None and observed_at <= utc(router.dhcp_snapshot_at):
                logger.info("Ignoring stale DHCP snapshot router_id=%s", event.router_id)
                return
            result = await session.execute(select(ObservedDevice).where(ObservedDevice.router_id == event.router_id))
            existing = {device.mac_address: device for device in result.scalars().all()}
            # Bootstrap protection for pre-migration records; future comparisons use
            # the explicit watermark even when all devices are absent/inactive.
            if router.dhcp_snapshot_at is None:
                previous = [utc(device.last_seen_at) for device in existing.values() if device.last_seen_at is not None]
                if previous and observed_at < max(previous):
                    logger.info("Ignoring pre-watermark stale DHCP snapshot router_id=%s", event.router_id)
                    return
            leases = {lease.mac: lease for lease in event.leases if lease.mac}
            created = updated = inactive = 0
            for mac, lease in leases.items():
                device = existing.get(mac)
                if device is None:
                    device = ObservedDevice(router_id=event.router_id, mac_address=mac,
                        first_seen_at=observed_at, last_seen_at=observed_at)
                    session.add(device)
                    created += 1
                else:
                    updated += 1
                device.active_ip = lease.active_ip
                device.hostname = lease.hostname
                device.dynamic = lease.dynamic
                device.active = lease.active
                device.raw = lease.raw
                if lease.active:
                    device.last_seen_at = observed_at
            for mac, device in existing.items():
                if mac not in leases and device.active:
                    device.active = False
                    inactive += 1
            router.dhcp_snapshot_at = observed_at
            await session.commit()
        logger.info("DHCP snapshot saved router_id=%s created=%s updated=%s inactive=%s", event.router_id, created, updated, inactive)
