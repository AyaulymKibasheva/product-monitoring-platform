"""SQLAlchemy schema for the monitoring database."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class OrganizationRow(Base):
    __tablename__ = "organizations"

    organization_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SourceRow(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.organization_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    default_currency: Mapped[str | None] = mapped_column(String(3))
    schedule: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ProductRow(Base):
    __tablename__ = "products"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.organization_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    current_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    review_count: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_links: Mapped[list[ProductSourceLinkRow]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductSourceLinkRow(Base):
    __tablename__ = "product_source_links"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external_product"),
    )

    link_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.product_id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.source_id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    product: Mapped[ProductRow] = relationship(back_populates="source_links")


class PriceHistoryRow(Base):
    __tablename__ = "price_history"

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.product_id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AvailabilityHistoryRow(Base):
    __tablename__ = "availability_history"

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.product_id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), nullable=False)
    availability: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScrapeRunRow(Base):
    __tablename__ = "scrape_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.source_id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    records_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScrapeErrorRow(Base):
    __tablename__ = "scrape_errors"

    error_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.run_id"), nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductMatchEventRow(Base):
    __tablename__ = "product_match_events"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.source_id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.product_id"), nullable=False, index=True
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductChangeEventRow(Base):
    __tablename__ = "product_change_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.run_id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.product_id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.source_id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    absolute_difference: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    percentage_change: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
