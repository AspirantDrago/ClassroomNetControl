from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from cmnc_classroom_service.db import Base


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    router_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        default=1,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subnet_cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_service: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
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

    devices: Mapped[list["Device"]] = relationship(
        back_populates="classroom",
        cascade="all, delete-orphan",
    )
    cameras: Mapped[list["ClassroomCamera"]] = relationship(
        back_populates="classroom",
        cascade="all, delete-orphan",
    )


class ClassroomCamera(Base):
    __tablename__ = "classroom_cameras"

    __table_args__ = (
        UniqueConstraint(
            "classroom_id",
            "sort_order",
            name="uq_classroom_cameras_classroom_sort_order",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
    )
    rtsp_main_stream: Mapped[str | None] = mapped_column(Text, nullable=True)
    rtsp_sub_stream: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_quality: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="sub",
        default="sub",
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

    classroom: Mapped[Classroom] = relationship(back_populates="cameras")


class Device(Base):
    __tablename__ = "devices"

    __table_args__ = (
        UniqueConstraint("mac_address", name="uq_devices_mac_address"),
        UniqueConstraint(
            "classroom_id",
            "row_index",
            "column_index",
            name="uq_devices_classroom_position",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"),
        nullable=False,
    )

    mac_address: Mapped[str] = mapped_column(String(17), nullable=False)
    inventory_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)

    static_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_pinned: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    wan_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    wan_protected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )

    policy_generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    sync_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

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

    classroom: Mapped[Classroom] = relationship(back_populates="devices")
