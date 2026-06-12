from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cmnc_inventory_service.db import Base


class ObservedDevice(Base):
    __tablename__ = "observed_devices"

    __table_args__ = (
        UniqueConstraint(
            "router_id",
            "mac_address",
            name="uq_observed_devices_router_mac",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    router_id: Mapped[int] = mapped_column(Integer, nullable=False)

    mac_address: Mapped[str] = mapped_column(String(17), nullable=False)
    active_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)

    dynamic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
