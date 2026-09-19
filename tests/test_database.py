from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.database import ProductRepository, create_schema
from src.database.models import (
    AvailabilityHistoryRow,
    PriceHistoryRow,
    ProductMatchEventRow,
    ProductChangeEventRow,
    ProductRow,
    ProductSourceLinkRow,
    ScrapeRunRow,
    ScrapeErrorRow,
    SourceRow,
)
from src.models import Availability, Organization, Product, SourceDefinition, SourceType
from src.sources import SourceCatalog, SourceRunResult, SourceRunStats
from src.validation import ProductValidator


def catalog() -> SourceCatalog:
    return SourceCatalog(
        organizations=(Organization("org", "Company"),),
        sources=(
            SourceDefinition(
                source_id="source",
                organization_id="org",
                name="Source",
                source_type=SourceType.API,
                adapter="fake",
            ),
        ),
    )


def monitored_catalog(*, minimum_price_change: int) -> SourceCatalog:
    return SourceCatalog(
        organizations=(Organization("org", "Company"),),
        sources=(
            SourceDefinition(
                source_id="source",
                organization_id="org",
                name="Source",
                source_type=SourceType.API,
                adapter="fake",
                timeout_seconds=7,
                max_retries=4,
                backoff_factor=1.5,
                monitoring_settings={"minimum_price_change": minimum_price_change},
            ),
        ),
    )


def product(
    price: str = "10.00",
    *,
    source_id: str = "source",
    external_id: str = "item-1",
    sku: str | None = None,
    name: str = "Item",
) -> Product:
    return Product(
        organization_id="org",
        source_id=source_id,
        external_id=external_id,
        name=name,
        category="Category",
        price=Decimal(price),
        currency="USD",
        availability=Availability.IN_STOCK,
        url="https://example.test/item-1",
        collected_at=datetime.now(timezone.utc),
        sku=sku,
    )


def test_persists_catalog_products_history_and_run() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())

    item = product()
    source_result = SourceRunResult("org", "source", [item], SourceRunStats(records_found=1, records_processed=1))
    validation = ProductValidator().validate_batch([item])
    run_id = repository.save_run(
        source_result,
        validation,
        started_at=datetime.now(timezone.utc),
    )

    with Session(engine) as session:
        assert session.get(ScrapeRunRow, run_id).status == "success"
        assert session.get(ScrapeRunRow, run_id).duration_seconds is not None
        assert session.get(SourceRow, "source").last_success_at is not None
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProductSourceLinkRow)) == 1
        assert session.scalar(select(func.count()).select_from(PriceHistoryRow)) == 1
        assert session.scalar(select(func.count()).select_from(AvailabilityHistoryRow)) == 1


def test_second_snapshot_updates_product_without_duplicate() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())

    for price in ("10.00", "8.50"):
        item = product(price)
        result = SourceRunResult("org", "source", [item], SourceRunStats(records_found=1, records_processed=1))
        repository.save_run(
            result,
            ProductValidator().validate_batch([item]),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        stored = session.scalar(select(ProductRow))
        assert stored.current_price == Decimal("8.5000")
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 1
        assert session.scalar(select(func.count()).select_from(PriceHistoryRow)) == 2


def test_catalog_sync_preserves_runtime_last_success() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())
    item = product()
    result = SourceRunResult("org", "source", [item], SourceRunStats(records_found=1, records_processed=1))
    repository.save_run(
        result,
        ProductValidator().validate_batch([item]),
        started_at=datetime.now(timezone.utc),
    )

    repository.sync_catalog(catalog())

    with Session(engine) as session:
        assert session.get(SourceRow, "source").last_success_at is not None


def test_catalog_sync_persists_runtime_and_monitoring_settings() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(monitored_catalog(minimum_price_change=5))

    with Session(engine) as session:
        source = session.get(SourceRow, "source")
        assert source.timeout_seconds == Decimal("7.000")
        assert source.max_retries == 4
        assert source.backoff_factor == Decimal("1.500")
        assert source.monitoring_settings == {"minimum_price_change": 5}


def test_repository_ignores_price_change_below_source_threshold() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(monitored_catalog(minimum_price_change=2))

    for price in ("10.00", "9.00"):
        item = product(price)
        result = SourceRunResult(
            "org", "source", [item], SourceRunStats(records_found=1, records_processed=1)
        )
        repository.save_run(
            result,
            ProductValidator().validate_batch([item]),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        price_events = session.scalar(
            select(func.count()).select_from(ProductChangeEventRow).where(
                ProductChangeEventRow.change_type.in_(["price_drop", "price_increase"])
            )
        )
        assert price_events == 0


def test_cross_source_same_sku_links_to_one_product() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    multi_source_catalog = SourceCatalog(
        organizations=(Organization("org", "Company"),),
        sources=(
            SourceDefinition("source", "org", "Source A", SourceType.API, "fake"),
            SourceDefinition("source-b", "org", "Source B", SourceType.HTML, "fake"),
        ),
    )
    repository.sync_catalog(multi_source_catalog)

    for item in (
        product(source_id="source", external_id="a-1", sku="SKU-42"),
        product(source_id="source-b", external_id="b-9", sku="SKU-42"),
    ):
        source_result = SourceRunResult(
            "org", item.source_id, [item], SourceRunStats(records_found=1, records_processed=1)
        )
        repository.save_run(
            source_result,
            ProductValidator().validate_batch([item]),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProductSourceLinkRow)) == 2
        event = session.scalar(select(ProductMatchEventRow))
        assert event.decision == "auto_linked"
        assert event.reason == "sku"


def test_same_name_with_different_sku_remains_separate() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    multi_source_catalog = SourceCatalog(
        organizations=(Organization("org", "Company"),),
        sources=(
            SourceDefinition("source", "org", "Source A", SourceType.API, "fake"),
            SourceDefinition("source-b", "org", "Source B", SourceType.HTML, "fake"),
        ),
    )
    repository.sync_catalog(multi_source_catalog)

    for item in (
        product(source_id="source", external_id="a", sku="SIZE-S", name="T-shirt"),
        product(source_id="source-b", external_id="b", sku="SIZE-L", name="T-shirt"),
    ):
        source_result = SourceRunResult(
            "org", item.source_id, [item], SourceRunStats(records_found=1, records_processed=1)
        )
        repository.save_run(
            source_result,
            ProductValidator().validate_batch([item]),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 2


def test_changed_external_id_relinks_by_stable_sku() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())

    for external_id in ("old-id", "new-id"):
        item = product(external_id=external_id, sku="STABLE-SKU")
        result = SourceRunResult(
            "org", "source", [item], SourceRunStats(records_found=1, records_processed=1)
        )
        repository.save_run(
            result,
            ProductValidator().validate_batch([item]),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProductSourceLinkRow)) == 2


def test_price_change_is_persisted_with_difference_and_percentage() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())

    for price in ("10.00", "8.50"):
        item = product(price)
        result = SourceRunResult(
            "org", "source", [item], SourceRunStats(records_found=1, records_processed=1)
        )
        repository.save_run(
            result,
            ProductValidator().validate_batch([item]),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        event = session.scalar(
            select(ProductChangeEventRow).where(
                ProductChangeEventRow.change_type == "price_drop"
            )
        )
        assert event.absolute_difference == Decimal("-1.5000")
        assert event.percentage_change == Decimal("-15.0000")


def test_complete_snapshots_detect_missing_and_reappeared_product() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())
    item = product()

    snapshots = ([item], [], [item])
    for products in snapshots:
        stats = SourceRunStats(
            records_found=len(products),
            records_processed=len(products),
            complete_snapshot=True,
        )
        result = SourceRunResult("org", "source", products, stats)
        repository.save_run(
            result,
            ProductValidator().validate_batch(products),
            started_at=datetime.now(timezone.utc),
        )

    with Session(engine) as session:
        event_types = session.scalars(
            select(ProductChangeEventRow.change_type).order_by(
                ProductChangeEventRow.event_id
            )
        ).all()
        assert event_types == ["new_product", "product_missing", "product_reappeared"]


def test_partial_snapshot_does_not_mark_unseen_products_missing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())
    item = product()
    complete = SourceRunResult(
        "org",
        "source",
        [item],
        SourceRunStats(records_found=1, records_processed=1, complete_snapshot=True),
    )
    repository.save_run(
        complete,
        ProductValidator().validate_batch([item]),
        started_at=datetime.now(timezone.utc),
    )
    partial = SourceRunResult("org", "source", [], SourceRunStats())
    repository.save_run(
        partial,
        ProductValidator().validate_batch([]),
        started_at=datetime.now(timezone.utc),
    )

    with Session(engine) as session:
        missing = session.scalar(
            select(func.count()).select_from(ProductChangeEventRow).where(
                ProductChangeEventRow.change_type == "product_missing"
            )
        )
        assert missing == 0


def test_source_and_validation_errors_are_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(catalog())
    good = product("10")
    bad = Product(
        organization_id="org",
        source_id="source",
        external_id="bad",
        name="",
        category=None,
        price=Decimal("5"),
        currency="USD",
        availability=Availability.UNKNOWN,
        url="https://example.test/bad",
        collected_at=datetime.now(timezone.utc),
    )
    stats = SourceRunStats(
        records_found=3,
        records_processed=2,
        records_skipped=1,
        errors=["detail request failed"],
    )
    source_result = SourceRunResult("org", "source", [good, bad], stats)
    validation = ProductValidator().validate_batch([good, bad])

    run_id = repository.save_run(
        source_result,
        validation,
        started_at=datetime.now(timezone.utc),
    )

    with Session(engine) as session:
        run = session.get(ScrapeRunRow, run_id)
        errors = session.scalars(
            select(ScrapeErrorRow).order_by(ScrapeErrorRow.error_id)
        ).all()
        assert run.status == "partial"
        assert run.records_accepted == 1
        assert run.records_rejected == 1
        assert [error.stage for error in errors] == ["source", "validation"]
        assert errors[1].external_id == "bad"
