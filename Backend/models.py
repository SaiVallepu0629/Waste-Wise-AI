from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(254), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    inventory_items: Mapped[list[InventoryItem]] = relationship(
        back_populates="owner"
    )


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class LoginRateLimit(Base):
    __tablename__ = "login_rate_limits"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_until: Mapped[int | None] = mapped_column(Integer)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stock_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    estimated_daily_demand: Mapped[float | None] = mapped_column(Float)
    inventory_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="in_stock", index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="manual", index=True
    )
    source_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    source_batch_id: Mapped[int | None] = mapped_column(Integer)
    source_product_id: Mapped[int | None] = mapped_column(Integer)
    snapshot_date: Mapped[date | None] = mapped_column(Date)
    source_data: Mapped[dict | None] = mapped_column(JSON)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    owner: Mapped[User | None] = relationship(back_populates="inventory_items")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
