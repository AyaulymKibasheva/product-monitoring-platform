from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import (
    Base,
    OrganizationRow,
    ProductChangeEventRow,
    ProductRow,
    ProductSourceLinkRow,
    ScrapeErrorRow,
    ScrapeRunRow,
    SourceRow,
)
from src.reports import ReportFilters, build_report, write_report_json


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        session.add(OrganizationRow(organization_id="acme", name="Acme", active=True))
        session.add(SourceRow(source_id="shop", organization_id="acme", name="Shop", source_type="api", adapter="demo", active=True, settings={}))
        product = ProductRow(organization_id="acme", name="Widget", brand="A", category="Tools", current_price=Decimal("10"), currency="USD", availability="in_stock", url="https://example.test/1", first_seen_at=now, last_seen_at=now)
        session.add(product)
        session.flush()
        session.add(ProductSourceLinkRow(product_id=product.product_id, source_id="shop", external_id="w1", source_url=product.url, first_seen_at=now, last_seen_at=now))
        run = ScrapeRunRow(source_id="shop", status="partial", started_at=now, finished_at=now, duration_seconds=Decimal("1.2"), records_found=1, records_accepted=1, records_rejected=1, error_count=1)
        session.add(run)
        session.flush()
        session.add(ProductChangeEventRow(run_id=run.run_id, product_id=product.product_id, source_id="shop", external_id="w1", change_type="price_drop", field="price", old_value="12", new_value="10", absolute_difference=Decimal("-2"), percentage_change=Decimal("-16.67"), observed_at=now))
        session.add(ScrapeErrorRow(run_id=run.run_id, external_id="bad", stage="validation", error_code="price", message="invalid", created_at=now))
    return engine


def test_build_report_segments_and_filters():
    report = build_report(_engine(), ReportFilters(organization_id="acme", currency="USD"))
    assert len(report.products) == 1
    assert len(report.price_changes) == 1
    assert len(report.scrape_history) == 1
    assert report.data_quality == report.errors
    assert not report.new_products
    assert not build_report(_engine(), ReportFilters(brand="Other")).products


def test_write_report_json(tmp_path):
    destination = write_report_json(build_report(_engine()), tmp_path / "report.json")
    text = destination.read_text(encoding="utf-8")
    assert '"products"' in text
    assert '"price_changes"' in text
    assert "Widget" in text
