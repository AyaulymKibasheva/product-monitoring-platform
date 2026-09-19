"""Database-backed datasets shared by Excel and Google Sheets reports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.database.models import (
    OrganizationRow,
    ProductChangeEventRow,
    ProductRow,
    ProductSourceLinkRow,
    ScrapeErrorRow,
    ScrapeRunRow,
    SourceRow,
)


@dataclass(frozen=True, slots=True)
class ReportFilters:
    organization_id: str | None = None
    source_id: str | None = None
    category: str | None = None
    brand: str | None = None
    currency: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReportData:
    generated_at: datetime
    filters: ReportFilters
    products: list[dict[str, Any]]
    price_changes: list[dict[str, Any]]
    new_products: list[dict[str, Any]]
    back_in_stock: list[dict[str, Any]]
    out_of_stock: list[dict[str, Any]]
    missing_products: list[dict[str, Any]]
    scrape_history: list[dict[str, Any]]
    data_quality: list[dict[str, Any]]
    errors: list[dict[str, Any]]


def build_report(engine: Engine, filters: ReportFilters | None = None) -> ReportData:
    filters = filters or ReportFilters()
    with Session(engine) as session:
        products = _products(session, filters)
        events = _events(session, filters)
        runs = _runs(session, filters)
        errors = _errors(session, filters)
    return ReportData(
        generated_at=datetime.now().astimezone(),
        filters=filters,
        products=products,
        price_changes=_select_events(events, "price_drop", "price_increase"),
        new_products=_select_events(events, "new_product", "new_source_listing"),
        back_in_stock=_select_events(events, "back_in_stock", "product_reappeared"),
        out_of_stock=_select_events(events, "out_of_stock"),
        missing_products=_select_events(events, "product_missing"),
        scrape_history=runs,
        data_quality=[row for row in errors if row["stage"] == "validation"],
        errors=errors,
    )


def write_report_json(report: ReportData, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(asdict(report), default=_json_default, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination


def _products(session: Session, filters: ReportFilters) -> list[dict[str, Any]]:
    stmt = (
        select(ProductRow, ProductSourceLinkRow, SourceRow, OrganizationRow)
        .join(ProductSourceLinkRow, ProductSourceLinkRow.product_id == ProductRow.product_id)
        .join(SourceRow, SourceRow.source_id == ProductSourceLinkRow.source_id)
        .join(OrganizationRow, OrganizationRow.organization_id == ProductRow.organization_id)
        .order_by(OrganizationRow.name, SourceRow.name, ProductRow.name)
    )
    stmt = _apply_product_filters(stmt, filters, ProductRow.last_seen_at)
    return [
        {
            "organization": org.name,
            "organization_id": org.organization_id,
            "source": source.name,
            "source_id": source.source_id,
            "product_id": product.product_id,
            "external_id": link.external_id,
            "sku": product.sku,
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
            "price": product.current_price,
            "currency": product.currency,
            "availability": product.availability,
            "quantity": product.quantity,
            "rating": product.rating,
            "review_count": product.review_count,
            "url": link.source_url,
            "first_seen_at": link.first_seen_at,
            "last_seen_at": link.last_seen_at,
        }
        for product, link, source, org in session.execute(stmt)
    ]


def _events(session: Session, filters: ReportFilters) -> list[dict[str, Any]]:
    stmt = (
        select(ProductChangeEventRow, ProductRow, SourceRow, OrganizationRow)
        .join(ProductRow, ProductRow.product_id == ProductChangeEventRow.product_id)
        .join(SourceRow, SourceRow.source_id == ProductChangeEventRow.source_id)
        .join(OrganizationRow, OrganizationRow.organization_id == ProductRow.organization_id)
        .order_by(ProductChangeEventRow.observed_at.desc())
    )
    stmt = _apply_product_filters(stmt, filters, ProductChangeEventRow.observed_at)
    return [
        {
            "observed_at": event.observed_at,
            "organization": org.name,
            "organization_id": org.organization_id,
            "source": source.name,
            "source_id": source.source_id,
            "product_id": product.product_id,
            "external_id": event.external_id,
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
            "currency": product.currency,
            "change_type": event.change_type,
            "field": event.field,
            "old_value": event.old_value,
            "new_value": event.new_value,
            "absolute_difference": event.absolute_difference,
            "percentage_change": event.percentage_change,
            "url": product.url,
        }
        for event, product, source, org in session.execute(stmt)
    ]


def _runs(session: Session, filters: ReportFilters) -> list[dict[str, Any]]:
    stmt = (
        select(ScrapeRunRow, SourceRow, OrganizationRow)
        .join(SourceRow, SourceRow.source_id == ScrapeRunRow.source_id)
        .join(OrganizationRow, OrganizationRow.organization_id == SourceRow.organization_id)
        .order_by(ScrapeRunRow.started_at.desc())
    )
    stmt = _apply_common_filters(stmt, filters, ScrapeRunRow.started_at)
    return [
        {
            "run_id": run.run_id,
            "organization": org.name,
            "organization_id": org.organization_id,
            "source": source.name,
            "source_id": source.source_id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_seconds": run.duration_seconds,
            "records_found": run.records_found,
            "records_accepted": run.records_accepted,
            "records_rejected": run.records_rejected,
            "error_count": run.error_count,
        }
        for run, source, org in session.execute(stmt)
    ]


def _errors(session: Session, filters: ReportFilters) -> list[dict[str, Any]]:
    stmt = (
        select(ScrapeErrorRow, ScrapeRunRow, SourceRow, OrganizationRow)
        .join(ScrapeRunRow, ScrapeRunRow.run_id == ScrapeErrorRow.run_id)
        .join(SourceRow, SourceRow.source_id == ScrapeRunRow.source_id)
        .join(OrganizationRow, OrganizationRow.organization_id == SourceRow.organization_id)
        .order_by(ScrapeErrorRow.created_at.desc())
    )
    stmt = _apply_common_filters(stmt, filters, ScrapeErrorRow.created_at)
    return [
        {
            "created_at": error.created_at,
            "run_id": run.run_id,
            "organization": org.name,
            "organization_id": org.organization_id,
            "source": source.name,
            "source_id": source.source_id,
            "external_id": error.external_id,
            "stage": error.stage,
            "error_code": error.error_code,
            "message": error.message,
        }
        for error, run, source, org in session.execute(stmt)
    ]


def _apply_common_filters(stmt: Any, filters: ReportFilters, timestamp: Any) -> Any:
    if filters.organization_id:
        stmt = stmt.where(OrganizationRow.organization_id == filters.organization_id)
    if filters.source_id:
        stmt = stmt.where(SourceRow.source_id == filters.source_id)
    if filters.date_from:
        stmt = stmt.where(timestamp >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(timestamp <= filters.date_to)
    return stmt


def _apply_product_filters(stmt: Any, filters: ReportFilters, timestamp: Any) -> Any:
    stmt = _apply_common_filters(stmt, filters, timestamp)
    if filters.category:
        stmt = stmt.where(ProductRow.category == filters.category)
    if filters.brand:
        stmt = stmt.where(ProductRow.brand == filters.brand)
    if filters.currency:
        stmt = stmt.where(ProductRow.currency == filters.currency.upper())
    return stmt


def _select_events(events: list[dict[str, Any]], *types: str) -> list[dict[str, Any]]:
    return [row for row in events if row["change_type"] in types]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, Decimal)):
        return value.isoformat() if isinstance(value, datetime) else float(value)
    raise TypeError(f"Unsupported report value: {type(value).__name__}")
