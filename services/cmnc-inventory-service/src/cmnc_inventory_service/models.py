from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cmnc_inventory_service.db import Base


class Router(Base):
    __tablename__ = "routers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_host: Mapped[str] = mapped_column(String(255), nullable=False)
    api_port: Mapped[int] = mapped_column(Integer, nullable=False, default=8728)
    api_use_ssl: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    api_verify_tls: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    api_username: Mapped[str] = mapped_column(String(255), nullable=False)
    api_password: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
    )
    poll_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
    )
    sync_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
    )
    poll_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("10"),
        default=10,
    )
    created_at: Mapped[datetime] = mapped_column(
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


class RouterServiceStatus(Base):
    __tablename__ = "router_service_status"

    __table_args__ = (
        UniqueConstraint(
            "router_id",
            "service_name",
            name="uq_router_service_status_router_service",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    router_id: Mapped[int] = mapped_column(Integer, nullable=False)
    service_name: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="starting",
        default="starting",
    )
    is_running: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0,
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


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
