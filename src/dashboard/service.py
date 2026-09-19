"""Database queries and safe mutations used by the dashboard API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, func, or_, select
from sqlalchemy.orm import Session

from src.database.models import (
    AvailabilityHistoryRow,
    OrganizationRow,
    PriceHistoryRow,
    ProductChangeEventRow,
    ProductRow,
    ProductSourceLinkRow,
    ScrapeErrorRow,
    ScrapeRunRow,
    SourceRow,
)


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class DashboardService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def overview(self, organization_id: str | None, source_id: str | None) -> dict[str, Any]:
        with Session(self.engine) as session:
            source_filter = []
            if organization_id:
                source_filter.append(SourceRow.organization_id == organization_id)
            if source_id:
                source_filter.append(SourceRow.source_id == source_id)
            product_filter = []
            event_filter = []
            run_filter = []
            if organization_id:
                product_filter.append(ProductRow.organization_id == organization_id)
                event_filter.append(ProductRow.organization_id == organization_id)
                run_filter.append(SourceRow.organization_id == organization_id)
            if source_id:
                product_filter.append(ProductSourceLinkRow.source_id == source_id)
                event_filter.append(ProductChangeEventRow.source_id == source_id)
                run_filter.append(ScrapeRunRow.source_id == source_id)

            organizations = session.scalar(
                select(func.count()).select_from(OrganizationRow).where(OrganizationRow.active.is_(True))
            )
            sources = session.scalars(select(SourceRow).where(*source_filter)).all()
            product_stmt = (
                select(func.count(func.distinct(ProductRow.product_id)))
                .select_from(ProductRow)
                .join(ProductSourceLinkRow)
                .where(*product_filter)
            )
            event_stmt = (
                select(ProductChangeEventRow.change_type, func.count())
                .join(ProductRow)
                .where(*event_filter)
                .group_by(ProductChangeEventRow.change_type)
            )
            run_stmt = (
                select(func.max(ScrapeRunRow.finished_at))
                .join(SourceRow)
                .where(ScrapeRunRow.status == "success", *run_filter)
            )
            error_stmt = (
                select(func.count())
                .select_from(ScrapeErrorRow)
                .join(ScrapeRunRow)
                .join(SourceRow)
                .where(*run_filter)
            )
            event_counts = dict(session.execute(event_stmt).all())
            broken = 0
            for source in sources:
                latest = session.scalar(
                    select(ScrapeRunRow.status)
                    .where(ScrapeRunRow.source_id == source.source_id)
                    .order_by(ScrapeRunRow.started_at.desc())
                    .limit(1)
                )
                broken += int(latest == "failed")
            return {
                "organizations": organizations,
                "sources": len(sources),
                "active_sources": sum(item.active for item in sources),
                "failing_sources": broken,
                "products": session.scalar(product_stmt) or 0,
                "new_products": event_counts.get("new_product", 0),
                "price_drops": event_counts.get("price_drop", 0),
                "out_of_stock": event_counts.get("out_of_stock", 0),
                "errors": session.scalar(error_stmt) or 0,
                "last_successful_run": json_value(session.scalar(run_stmt)),
            }

    def filters(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            organizations = session.scalars(select(OrganizationRow).order_by(OrganizationRow.name)).all()
            sources = session.scalars(select(SourceRow).order_by(SourceRow.name)).all()
            categories = session.scalars(
                select(ProductRow.category).where(ProductRow.category.is_not(None)).distinct().order_by(ProductRow.category)
            ).all()
            brands = session.scalars(
                select(ProductRow.brand).where(ProductRow.brand.is_not(None)).distinct().order_by(ProductRow.brand)
            ).all()
            return {
                "organizations": [{"id": row.organization_id, "name": row.name} for row in organizations],
                "sources": [
                    {"id": row.source_id, "organization_id": row.organization_id, "name": row.name, "active": row.active}
                    for row in sources
                ],
                "categories": categories,
                "brands": brands,
            }

    def products(self, filters: dict[str, str], *, limit: int = 200) -> list[dict[str, Any]]:
        stmt = (
            select(ProductRow, ProductSourceLinkRow, SourceRow, OrganizationRow)
            .select_from(ProductRow)
            .join(ProductSourceLinkRow, ProductSourceLinkRow.product_id == ProductRow.product_id)
            .join(SourceRow, SourceRow.source_id == ProductSourceLinkRow.source_id)
            .join(OrganizationRow, OrganizationRow.organization_id == ProductRow.organization_id)
            .order_by(ProductRow.last_seen_at.desc())
            .limit(min(limit, 500))
        )
        if filters.get("organization"):
            stmt = stmt.where(ProductRow.organization_id == filters["organization"])
        if filters.get("source"):
            stmt = stmt.where(SourceRow.source_id == filters["source"])
        if filters.get("category"):
            stmt = stmt.where(ProductRow.category == filters["category"])
        if filters.get("brand"):
            stmt = stmt.where(ProductRow.brand == filters["brand"])
        if filters.get("search"):
            term = f"%{filters['search'].strip()}%"
            stmt = stmt.where(or_(ProductRow.name.ilike(term), ProductRow.sku.ilike(term)))
        with Session(self.engine) as session:
            return [
                {
                    "id": product.product_id,
                    "organization": organization.name,
                    "source": source.name,
                    "source_id": source.source_id,
                    "name": product.name,
                    "sku": product.sku,
                    "brand": product.brand,
                    "category": product.category,
                    "price": json_value(product.current_price),
                    "currency": product.currency,
                    "availability": product.availability,
                    "url": link.source_url,
                    "last_seen_at": json_value(link.last_seen_at),
                }
                for product, link, source, organization in session.execute(stmt)
            ]

    def product_history(self, product_id: int) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            product = session.get(ProductRow, product_id)
            if product is None:
                return None
            prices = session.scalars(
                select(PriceHistoryRow).where(PriceHistoryRow.product_id == product_id).order_by(PriceHistoryRow.observed_at)
            ).all()
            availability = session.scalars(
                select(AvailabilityHistoryRow).where(AvailabilityHistoryRow.product_id == product_id).order_by(AvailabilityHistoryRow.observed_at)
            ).all()
            return {
                "product": {"id": product.product_id, "name": product.name},
                "prices": [
                    {"source_id": row.source_id, "price": json_value(row.price), "currency": row.currency, "observed_at": json_value(row.observed_at)}
                    for row in prices
                ],
                "availability": [
                    {"source_id": row.source_id, "status": row.availability, "quantity": row.quantity, "observed_at": json_value(row.observed_at)}
                    for row in availability
                ],
            }

    def runs(self, organization_id: str | None, source_id: str | None) -> list[dict[str, Any]]:
        stmt = select(ScrapeRunRow, SourceRow).join(SourceRow).order_by(ScrapeRunRow.started_at.desc()).limit(100)
        if organization_id:
            stmt = stmt.where(SourceRow.organization_id == organization_id)
        if source_id:
            stmt = stmt.where(SourceRow.source_id == source_id)
        with Session(self.engine) as session:
            return [
                {"id": run.run_id, "source": source.name, "source_id": source.source_id, "status": run.status,
                 "started_at": json_value(run.started_at), "duration_seconds": json_value(run.duration_seconds),
                 "found": run.records_found, "accepted": run.records_accepted, "rejected": run.records_rejected,
                 "errors": run.error_count}
                for run, source in session.execute(stmt)
            ]

    def errors(self, organization_id: str | None, source_id: str | None) -> list[dict[str, Any]]:
        stmt = (
            select(ScrapeErrorRow, SourceRow)
            .select_from(ScrapeErrorRow)
            .join(ScrapeRunRow, ScrapeRunRow.run_id == ScrapeErrorRow.run_id)
            .join(SourceRow, SourceRow.source_id == ScrapeRunRow.source_id)
            .order_by(ScrapeErrorRow.created_at.desc()).limit(100)
        )
        if organization_id:
            stmt = stmt.where(SourceRow.organization_id == organization_id)
        if source_id:
            stmt = stmt.where(SourceRow.source_id == source_id)
        with Session(self.engine) as session:
            return [
                {"id": error.error_id, "source": source.name, "stage": error.stage,
                 "code": error.error_code, "message": error.message, "created_at": json_value(error.created_at)}
                for error, source in session.execute(stmt)
            ]

    def settings(self, organization_id: str | None, source_id: str | None) -> dict[str, Any]:
        with Session(self.engine) as session:
            organization = session.get(OrganizationRow, organization_id) if organization_id else None
            source = session.get(SourceRow, source_id) if source_id else None
            return {
                "organization": organization.monitoring_settings if organization else {},
                "source": source.monitoring_settings if source else {},
            }

    def update_settings(self, scope: str, identifier: str, settings: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        for key in ("minimum_price_change", "minimum_price_change_percent"):
            if key in settings and float(settings[key]) < 0:
                raise ValueError(f"{key} cannot be negative")
        model = OrganizationRow if scope == "organization" else SourceRow
        with Session(self.engine) as session, session.begin():
            row = session.get(model, identifier)
            if row is None:
                return None
            row.monitoring_settings = settings
            return dict(settings)
