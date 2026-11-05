from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UtcDateTime


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512))
    original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    preview_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    upload_state: Mapped[str] = mapped_column(String(32), default="pending")
    files_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    detection_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    regions: Mapped[list["Region"]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Region.position",
    )


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    center_x: Mapped[float] = mapped_column(Float)
    center_y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    angle_deg: Mapped[float] = mapped_column(Float)
    quarter_turns: Mapped[int] = mapped_column(Integer, default=0)
    taken_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    album_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String(32), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(32), default="pending")
    immich_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    immich_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    album_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_crop_signature: Mapped[str | None] = mapped_column(String(512), nullable=True)
    upload_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retouch_upscale: Mapped[bool] = mapped_column(Boolean, default=False)
    retouch_faces: Mapped[bool] = mapped_column(Boolean, default=False)
    retouch_colorize: Mapped[bool] = mapped_column(Boolean, default=False)
    retouch_scratches: Mapped[bool] = mapped_column(Boolean, default=False)
    upload_source: Mapped[str] = mapped_column(String(16), default="crop")
    retouch_status: Mapped[str] = mapped_column(String(16), default="none")
    retouch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retouch_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retouch_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    crop_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="regions")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    scan_id: Mapped[str | None] = mapped_column(
        ForeignKey("scans.id", ondelete="SET NULL"),
        nullable=True,
    )
    region_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
