"""Transactional persistence for source runs and product snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.matching import MatchCandidate, ProductMatcher
from src.models import Product
from src.monitoring import ChangeEvent, ChangePolicy, ChangeType, ProductSnapshot, detect_changes
from src.sources import SourceCatalog, SourceRunResult
from src.validation import ProductValidationResult

from .models import (
    AvailabilityHistoryRow,
    OrganizationRow,
    PriceHistoryRow,
    ProductChangeEventRow,
    ProductMatchEventRow,
    ProductRow,
    ProductSourceLinkRow,
    NotificationChannelRow,
    NotificationRuleRow,
    ScrapeErrorRow,
    ScrapeRunRow,
    SourceRow,
)


class ProductRepository:
    def __init__(self, engine: Engine, matcher: ProductMatcher | None = None) -> None:
        self.engine = engine
        self.matcher = matcher or ProductMatcher()
        self._catalog: SourceCatalog | None = None

    def sync_catalog(self, catalog: SourceCatalog) -> None:
        self._catalog = catalog
        with Session(self.engine) as session, session.begin():
            for organization in catalog.organizations:
                organization_row = session.get(OrganizationRow, organization.organization_id)
                if organization_row is None:
                    organization_row = OrganizationRow(organization_id=organization.organization_id)
                    session.add(organization_row)
                organization_row.name = organization.name
                organization_row.active = organization.active
                organization_row.monitoring_settings = organization.monitoring_settings
                self._sync_notification_configuration(session, organization)

            for source_definition in catalog.sources:
                source_row = session.get(SourceRow, source_definition.source_id)
                if source_row is None:
                    source_row = SourceRow(
                        source_id=source_definition.source_id,
                        organization_id=source_definition.organization_id,
                        last_success_at=source_definition.last_success_at,
                    )
                    session.add(source_row)
                source_row.organization_id = source_definition.organization_id
                source_row.name = source_definition.name
                source_row.source_type = source_definition.source_type.value
                source_row.adapter = source_definition.adapter
                source_row.base_url = source_definition.base_url
                source_row.default_currency = source_definition.default_currency
                source_row.schedule = source_definition.schedule
                source_row.timeout_seconds = Decimal(str(source_definition.timeout_seconds))
                source_row.max_retries = source_definition.max_retries
                source_row.backoff_factor = Decimal(str(source_definition.backoff_factor))
                source_row.delay_seconds = Decimal(str(source_definition.delay_seconds))
                source_row.requests_per_second = (
                    Decimal(str(source_definition.requests_per_second))
                    if source_definition.requests_per_second is not None
                    else None
                )
                source_row.active = source_definition.active
                if source_definition.last_success_at is not None:
                    source_row.last_success_at = source_definition.last_success_at
                source_row.settings = source_definition.settings
                source_row.monitoring_settings = source_definition.monitoring_settings

    @staticmethod
    def _sync_notification_configuration(session: Session, organization) -> None:
        for item in organization.notification_channels:
            channel_id = str(item["id"])
            channel_row = session.get(NotificationChannelRow, channel_id)
            if channel_row is None:
                channel_row = NotificationChannelRow(channel_id=channel_id, organization_id=organization.organization_id)
                session.add(channel_row)
            channel_row.organization_id = organization.organization_id
            channel_row.name = str(item.get("name", channel_id))
            channel_row.channel_type = str(item["type"]).casefold()
            channel_row.recipient = item.get("recipient")
            channel_row.settings = dict(item.get("settings", {}))
            channel_row.active = bool(item.get("active", True))
        for item in organization.notification_rules:
            rule_id = str(item["id"])
            rule_row = session.get(NotificationRuleRow, rule_id)
            if rule_row is None:
                rule_row = NotificationRuleRow(rule_id=rule_id, organization_id=organization.organization_id)
                session.add(rule_row)
            rule_row.organization_id = organization.organization_id
            rule_row.name = str(item.get("name", rule_id))
            rule_row.event_types = [str(value).casefold() for value in item.get("events", [])]
            rule_row.source_ids = list(item.get("source_ids", []))
            rule_row.categories = list(item.get("categories", []))
            rule_row.brands = list(item.get("brands", []))
            rule_row.channel_ids = list(item.get("channel_ids", []))
            rule_row.minimum_price_change_percent = Decimal(str(item.get("minimum_price_change_percent", 0)))
            rule_row.frequency = str(item.get("frequency", "immediate")).casefold()
            rule_row.active = bool(item.get("active", True))

    def save_run(
        self,
        source_result: SourceRunResult,
        validation: ProductValidationResult,
        *,
        started_at: datetime,
    ) -> int:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            run = ScrapeRunRow(
                source_id=source_result.source_id,
                status="success" if not source_result.stats.errors else "partial",
                started_at=started_at,
                finished_at=now,
                duration_seconds=Decimal(str((now - started_at).total_seconds())),
                records_found=source_result.stats.records_found,
                records_accepted=validation.accepted_count,
                records_rejected=validation.rejected_count,
                error_count=len(source_result.stats.errors) + validation.rejected_count,
            )
            session.add(run)
            session.flush()

            current_product_ids: set[int] = set()
            for product in validation.valid_products:
                current_product_ids.add(self._save_product(session, product, run.run_id))
            if source_result.stats.complete_snapshot:
                self._record_missing_products(
                    session,
                    run.run_id,
                    source_result.source_id,
                    {item.external_id for item in validation.valid_products},
                    current_product_ids,
                    now,
                )
            for message in source_result.stats.errors:
                session.add(
                    ScrapeErrorRow(
                        run_id=run.run_id,
                        stage="source",
                        message=message,
                        created_at=now,
                    )
                )
            for rejected in validation.rejected_products:
                for issue in rejected.issues:
                    session.add(
                        ScrapeErrorRow(
                            run_id=run.run_id,
                            external_id=rejected.external_id,
                            stage="validation",
                            error_code=issue.code,
                            message=issue.message,
                            created_at=now,
                        )
                    )

            source = session.get(SourceRow, source_result.source_id)
            if source is not None and run.status == "success":
                source.last_success_at = now
            run_id = run.run_id
        return run_id

    def save_failed_run(
        self,
        source_id: str,
        *,
        started_at: datetime,
        error: Exception,
    ) -> int:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            run = ScrapeRunRow(
                source_id=source_id,
                status="failed",
                started_at=started_at,
                finished_at=now,
                duration_seconds=Decimal(str((now - started_at).total_seconds())),
                records_found=0,
                records_accepted=0,
                records_rejected=0,
                error_count=1,
            )
            session.add(run)
            session.flush()
            session.add(
                ScrapeErrorRow(
                    run_id=run.run_id,
                    stage="source",
                    error_code=type(error).__name__,
                    message=str(error),
                    created_at=now,
                )
            )
            run_id = run.run_id
        return run_id

    def _save_product(self, session: Session, item: Product, run_id: int) -> int:
        link = session.scalar(
            select(ProductSourceLinkRow).where(
                ProductSourceLinkRow.source_id == item.source_id,
                ProductSourceLinkRow.external_id == item.external_id,
            )
        )
        is_new_product = False
        if link is None:
            candidates = session.scalars(
                select(ProductRow).where(
                    ProductRow.organization_id == item.organization_id
                )
            ).all()
            decision = self.matcher.best_match(
                item,
                [
                    MatchCandidate(
                        product_id=row.product_id,
                        organization_id=row.organization_id,
                        name=row.name,
                        sku=row.sku,
                        brand=row.brand,
                        url=row.url,
                        attributes=row.attributes,
                    )
                    for row in candidates
                ],
            )
            if decision.auto_merge and decision.candidate_product_id is not None:
                product = session.get(ProductRow, decision.candidate_product_id)
                assert product is not None
                match_decision = "auto_linked"
            else:
                product = ProductRow(
                    organization_id=item.organization_id,
                    name=item.name,
                    current_price=item.price,
                    currency=item.currency or "",
                    availability=item.availability.value,
                    url=item.url,
                    first_seen_at=item.collected_at,
                    last_seen_at=item.collected_at,
                )
                session.add(product)
                session.flush()
                match_decision = "review_required"
                is_new_product = True

            if decision.candidate_product_id is not None and decision.score > 0:
                session.add(
                    ProductMatchEventRow(
                        source_id=item.source_id,
                        external_id=item.external_id,
                        candidate_product_id=decision.candidate_product_id,
                        score=decision.score,
                        reason=decision.reason,
                        decision=match_decision,
                        created_at=item.collected_at,
                    )
                )
            prior_source_link = session.scalar(
                select(ProductSourceLinkRow)
                .where(
                    ProductSourceLinkRow.product_id == product.product_id,
                    ProductSourceLinkRow.source_id == item.source_id,
                )
                .order_by(ProductSourceLinkRow.link_id.desc())
            )
            link = ProductSourceLinkRow(
                product_id=product.product_id,
                source_id=item.source_id,
                external_id=item.external_id,
                source_url=item.url,
                first_seen_at=item.collected_at,
                last_seen_at=item.collected_at,
            )
            session.add(link)
            if is_new_product:
                self._add_change(
                    session,
                    run_id,
                    product.product_id,
                    item,
                    ChangeEvent(ChangeType.NEW_PRODUCT, "product", None, item.name),
                )
            elif prior_source_link is not None:
                self._add_change(
                    session,
                    run_id,
                    product.product_id,
                    item,
                    ChangeEvent(
                        ChangeType.EXTERNAL_ID_CHANGED,
                        "external_id",
                        prior_source_link.external_id,
                        item.external_id,
                    ),
                )
            else:
                self._add_change(
                    session,
                    run_id,
                    product.product_id,
                    item,
                    ChangeEvent(
                        ChangeType.NEW_SOURCE_LISTING,
                        "source_id",
                        None,
                        item.source_id,
                    ),
                )
        else:
            product = link.product
            previous = self._previous_snapshot(session, product, item.source_id)
            if previous is not None:
                for event in detect_changes(
                    previous, item, self._change_policy(item.source_id)
                ):
                    self._add_change(
                        session, run_id, product.product_id, item, event
                    )
            if self._latest_visibility_event(
                session, item.source_id, item.external_id
            ) == ChangeType.PRODUCT_MISSING.value:
                self._add_change(
                    session,
                    run_id,
                    product.product_id,
                    item,
                    ChangeEvent(
                        ChangeType.PRODUCT_REAPPEARED,
                        "presence",
                        "missing",
                        "present",
                    ),
                )
            link.source_url = item.url
            link.last_seen_at = item.collected_at

        product.name = item.name
        product.sku = item.sku
        product.brand = item.brand
        product.category = item.category
        product.description = item.description
        product.current_price = item.price
        product.currency = item.currency or ""
        product.availability = item.availability.value
        product.quantity = item.quantity
        product.rating = Decimal(str(item.rating)) if item.rating is not None else None
        product.review_count = item.review_count
        product.url = item.url
        product.image_url = item.image_url
        product.attributes = item.attributes
        product.last_seen_at = item.collected_at

        session.add(
            PriceHistoryRow(
                product_id=product.product_id,
                source_id=item.source_id,
                price=item.price,
                currency=item.currency or "",
                observed_at=item.collected_at,
            )
        )
        session.add(
            AvailabilityHistoryRow(
                product_id=product.product_id,
                source_id=item.source_id,
                availability=item.availability.value,
                quantity=item.quantity,
                observed_at=item.collected_at,
            )
        )
        return product.product_id

    @staticmethod
    def _previous_snapshot(
        session: Session, product: ProductRow, source_id: str
    ) -> ProductSnapshot | None:
        price = session.scalar(
            select(PriceHistoryRow)
            .where(
                PriceHistoryRow.product_id == product.product_id,
                PriceHistoryRow.source_id == source_id,
            )
            .order_by(PriceHistoryRow.history_id.desc())
        )
        availability = session.scalar(
            select(AvailabilityHistoryRow)
            .where(
                AvailabilityHistoryRow.product_id == product.product_id,
                AvailabilityHistoryRow.source_id == source_id,
            )
            .order_by(AvailabilityHistoryRow.history_id.desc())
        )
        if price is None or availability is None:
            return None
        from src.models import Availability

        return ProductSnapshot(
            name=product.name,
            category=product.category,
            brand=product.brand,
            price=price.price,
            currency=price.currency,
            availability=Availability(availability.availability),
            attributes=product.attributes,
        )

    def _add_change(
        self,
        session: Session,
        run_id: int,
        product_id: int,
        item: Product,
        event: ChangeEvent,
    ) -> None:
        if not self._change_policy(item.source_id).allows(event):
            return
        session.add(
            ProductChangeEventRow(
                run_id=run_id,
                product_id=product_id,
                source_id=item.source_id,
                external_id=item.external_id,
                change_type=event.change_type.value,
                field=event.field,
                old_value=event.old_value,
                new_value=event.new_value,
                absolute_difference=event.absolute_difference,
                percentage_change=event.percentage_change,
                observed_at=item.collected_at,
            )
        )

    def _change_policy(self, source_id: str) -> ChangePolicy:
        return (
            self._catalog.change_policy(source_id)
            if self._catalog is not None
            else ChangePolicy()
        )

    @staticmethod
    def _latest_visibility_event(
        session: Session, source_id: str, external_id: str
    ) -> str | None:
        return session.scalar(
            select(ProductChangeEventRow.change_type)
            .where(
                ProductChangeEventRow.source_id == source_id,
                ProductChangeEventRow.external_id == external_id,
                ProductChangeEventRow.change_type.in_(
                    [
                        ChangeType.PRODUCT_MISSING.value,
                        ChangeType.PRODUCT_REAPPEARED.value,
                    ]
                ),
            )
            .order_by(ProductChangeEventRow.event_id.desc())
        )

    def _record_missing_products(
        self,
        session: Session,
        run_id: int,
        source_id: str,
        current_external_ids: set[str],
        current_product_ids: set[int],
        observed_at: datetime,
    ) -> None:
        links = session.scalars(
            select(ProductSourceLinkRow).where(
                ProductSourceLinkRow.source_id == source_id
            )
        ).all()
        for link in links:
            if (
                link.external_id in current_external_ids
                or link.product_id in current_product_ids
                or self._latest_visibility_event(session, source_id, link.external_id)
                == ChangeType.PRODUCT_MISSING.value
            ):
                continue
            event = ChangeEvent(
                ChangeType.PRODUCT_MISSING,
                "presence",
                "present",
                "missing",
            )
            if not self._change_policy(source_id).allows(event):
                continue
            session.add(
                ProductChangeEventRow(
                    run_id=run_id,
                    product_id=link.product_id,
                    source_id=source_id,
                    external_id=link.external_id,
                    change_type=event.change_type.value,
                    field=event.field,
                    old_value=event.old_value,
                    new_value=event.new_value,
                    observed_at=observed_at,
                )
            )
