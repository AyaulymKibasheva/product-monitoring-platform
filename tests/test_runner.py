from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.application import PipelineRunner
from src.database.models import ScrapeErrorRow, ScrapeRunRow
from src.models import Availability, Organization, Product, SourceDefinition, SourceType
from src.sources import ProductSource, SourceCatalog, SourceRegistry, SourceRunResult, SourceRunStats


class SuccessfulSource(ProductSource):
    organization_id = "org"
    source_id = "good"

    def collect(self, *, max_pages=None):
        item = Product(
            organization_id="org",
            source_id="good",
            external_id="1",
            name="Item",
            category=None,
            price=Decimal("10"),
            currency="USD",
            availability=Availability.IN_STOCK,
            url="https://example.test/1",
            collected_at=datetime.now(timezone.utc),
        )
        return SourceRunResult(
            "org",
            "good",
            [item],
            SourceRunStats(records_found=1, records_processed=1, complete_snapshot=True),
        )


class FailingSource(ProductSource):
    organization_id = "org"
    source_id = "bad"

    def collect(self, *, max_pages=None):
        raise RuntimeError("source unavailable")


def runner_catalog() -> SourceCatalog:
    return SourceCatalog(
        organizations=(Organization("org", "Organization"),),
        sources=(
            SourceDefinition("good", "org", "Good", SourceType.API, "fake"),
            SourceDefinition("bad", "org", "Bad", SourceType.API, "fake"),
        ),
    )


def test_run_all_continues_when_one_source_fails(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    runner = PipelineRunner(
        SourceRegistry([FailingSource(), SuccessfulSource()]),
        runner_catalog(),
        output_directory=tmp_path,
        engine=engine,
    )

    outcomes = runner.run_all()

    assert [(item.source_id, item.status) for item in outcomes] == [
        ("bad", "failed"),
        ("good", "success"),
    ]
    assert (tmp_path / "good.csv").exists()
    with Session(engine) as session:
        failed_run = session.scalar(
            select(ScrapeRunRow).where(ScrapeRunRow.source_id == "bad")
        )
        error = session.scalar(
            select(ScrapeErrorRow).where(ScrapeErrorRow.run_id == failed_run.run_id)
        )
        assert failed_run.status == "failed"
        assert failed_run.duration_seconds is not None
        assert error.error_code == "RuntimeError"
        assert error.message == "source unavailable"


def test_single_success_returns_counts_and_duration(tmp_path) -> None:
    runner = PipelineRunner(
        SourceRegistry([SuccessfulSource()]),
        SourceCatalog(
            organizations=(Organization("org", "Organization"),),
            sources=(
                SourceDefinition("good", "org", "Good", SourceType.API, "fake"),
            ),
        ),
        output_directory=tmp_path,
    )

    outcome = runner.run("good")

    assert outcome.status == "success"
    assert outcome.found == 1
    assert outcome.accepted == 1
    assert outcome.duration_seconds >= 0

