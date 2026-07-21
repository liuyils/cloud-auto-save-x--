from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriveAccountLsdirCache(Base):
    __tablename__ = "drive_account_lsdir_cache"
    __table_args__ = (
        UniqueConstraint("account_id", "full_path", name="uq_drive_account_lsdir_cache_account_path"),
        Index("ix_drive_account_lsdir_cache_account_parent", "account_id", "parent_fid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    drive_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_fid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fid: Mapped[str] = mapped_column(String(128), nullable=False)
    full_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    is_dir: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at_remote: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    children_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
